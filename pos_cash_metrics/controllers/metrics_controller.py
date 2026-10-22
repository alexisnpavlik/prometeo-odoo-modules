# -*- coding: utf-8 -*-
import io
import json
import logging
import re
import unicodedata
from datetime import datetime

import pytz
import xlsxwriter

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'America/Argentina/Buenos_Aires'
MAX_TABLE_ROWS = 20000
# Diferencias de menos de $1 son redondeo, no faltante ni sobrante
DIFF_TOLERANCE = 1.0
ORDER_STATES = ('paid', 'done', 'invoiced')   # 'paid' = venta de una caja todavía abierta
STATUS_LABELS = {
    "abierta_hoy": "Abierta hoy",
    "abierta_vieja": "Abierta hace días",
    "cerro_justo": "Cerró justo",
    "faltante": "Cerró con faltante",
    "sobrante": "Cerró con sobrante",
}
# Grupo de cada método de pago por su nombre: los nombres reales están cargados a mano y se repiten
# con variantes ("Tarjeta Debito", "Debito", "Tarjeta de debito"). Se evalúan en orden.
METHOD_GROUP_RULES = (
    ("Mercado Pago", ("mercado",)),
    ("Transferencia", ("transf", "tranf")),   # "Tranferencia" está así en la base
    ("Débito", ("debito",)),
    ("Crédito / cuotas", ("cred", "cuota", "visa", "master", "naranja", "tuya", "cabal", "consumax", "amex")),
    ("Contra reembolso", ("reembolso",)),
    ("Tarjeta", ("tarjeta",)),
)
GROUP_ORDER = ("Efectivo", "Débito", "Crédito / cuotas", "Tarjeta", "Mercado Pago", "Transferencia",
               "Cuenta corriente", "Contra reembolso", "Otros")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _to_list(value):
    """Filtro multi-selección: lista, JSON de lista o valor suelto. Vacío o 'all' = sin filtro."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, (str, int)):
        value = [value]
    return [v for v in (value or []) if v not in (None, '', 'all')]


def _to_ids(value):
    """Lista de ids enteros desde un filtro multi-selección; lo que no es número se descarta."""
    ids = []
    for v in _to_list(value):
        try:
            ids.append(int(v))
        except (TypeError, ValueError):
            continue
    return tuple(ids)


def _plain(text):
    """minúsculas y sin acentos, para clasificar nombres cargados a mano."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _method_group(name, kind):
    """Grupo de un método de pago: por tipo (efectivo, cuenta corriente) y si no por palabras del nombre."""
    if kind == 'cash':
        return "Efectivo"
    if kind == 'pay_later':
        return "Cuenta corriente"
    plain = _plain(name)
    for group, words in METHOD_GROUP_RULES:
        if any(w in plain for w in words):
            return group
    return "Otros"


def _money(value):
    return round(float(value or 0.0), 2)


class CashMetricsController(http.Controller):

    def _check_access(self):
        """Corta cualquier endpoint si el usuario no está en el grupo del módulo."""
        if not request.env.user.has_group('pos_cash_metrics.group_pos_cash_metrics_user'):
            raise AccessError("No tienes permisos para acceder a Métricas de Caja.")

    def _get_lang(self):
        return request.env.context.get('lang') or 'es_AR'

    def _get_tz(self):
        return request.env.user.tz or DEFAULT_TZ

    def _today(self):
        """Fecha de hoy en la zona del usuario: la misma que usa el SQL para cortar el día."""
        return datetime.now(pytz.timezone(self._get_tz())).date()

    def _resolve_companies(self, company):
        """Empresas a consultar: las elegidas (que el usuario pueda ver) o todas las permitidas."""
        allowed = tuple(request.env.companies.ids)
        names = _to_list(company)
        if names and allowed:
            request.env.cr.execute(
                "SELECT id FROM res_company WHERE name IN %s AND id IN %s ORDER BY id",
                (tuple(names), allowed))
            ids = tuple(r[0] for r in request.env.cr.fetchall())
            if ids:
                return ids
        return allowed

    def _valid_date(self, value):
        """YYYY-MM-DD que además existe: '2026-13-99' pasa el regex pero rompe el cast del SQL."""
        if not isinstance(value, str) or not DATE_RE.match(value):
            return False
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return False
        return True

    def _resolve_range(self, start_date, end_date):
        """Rango de fechas locales validado; sin fechas válidas, hoy. Hasta nunca queda antes que desde."""
        today = self._today().isoformat()
        start = start_date if self._valid_date(start_date) else today
        end = end_date if self._valid_date(end_date) else today
        if end < start:
            start, end = end, start
        return start, end

    @http.route('/pos_cash_metrics/filters', type='json', auth='user')
    def get_filters(self, **kwargs):
        """Empresas, cajas (con su empresa) y cajeros: quien abrió una caja o vendió alguna vez."""
        self._check_access()
        allowed = tuple(request.env.companies.ids)
        if not allowed:
            return {"companies": [], "configs": [], "cashiers": []}
        cr = request.env.cr
        cr.execute("SELECT name FROM res_company WHERE id IN %s ORDER BY name", (allowed,))
        companies = [r[0] for r in cr.fetchall() if r[0]]
        cr.execute("""
            SELECT pc.id, pc.name, rc.name AS company
            FROM pos_config pc JOIN res_company rc ON rc.id = pc.company_id
            WHERE pc.company_id IN %s ORDER BY pc.name
        """, (allowed,))
        configs = cr.dictfetchall()
        cr.execute("""
            SELECT ru.id, rp.name
            FROM res_users ru JOIN res_partner rp ON rp.id = ru.partner_id
            WHERE ru.id IN (
                SELECT ps.user_id FROM pos_session ps JOIN pos_config pc ON pc.id = ps.config_id
                WHERE pc.company_id IN %(c)s
                UNION
                SELECT po.user_id FROM pos_order po WHERE po.company_id IN %(c)s
            )
            ORDER BY rp.name
        """, {"c": allowed})
        return {"companies": companies, "configs": configs, "cashiers": cr.dictfetchall()}

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def _params(self, company, pos, start, end):
        companies = self._resolve_companies(company)
        return {
            "companies": companies or (0,),
            "configs": _to_ids(pos),
            "tz": self._get_tz(),
            "start": f"{start} 00:00:00",
            "end": f"{end} 23:59:59",
            "lang": self._get_lang(),
        }

    def _order_where(self, p, cashiers):
        """WHERE de las ventas del período. Las fechas locales se pasan a UTC con la zona del usuario."""
        where = """po.state IN %(states)s AND po.company_id IN %(companies)s
            AND po.date_order >= (%(start)s::timestamp AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')
            AND po.date_order <= (%(end)s::timestamp AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')"""
        if p["configs"]:
            where += " AND ps.config_id IN %(configs)s"
        if cashiers:
            where += " AND po.user_id IN %(cashiers)s"
        return where

    def _fetch_sellers(self, p, cashiers):
        """Ventas por vendedor (el usuario de cada orden, no el que abrió la caja)."""
        cr = request.env.cr
        cr.execute(f"""
            SELECT po.user_id, rp.name,
                   SUM(po.amount_total) AS sold,
                   COUNT(*) FILTER (WHERE po.amount_total >= 0) AS tickets,
                   COUNT(*) FILTER (WHERE po.amount_total < 0) AS refunds,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total < 0), 0) AS refunds_amount
            FROM pos_order po
            JOIN pos_session ps ON ps.id = po.session_id
            JOIN res_users ru ON ru.id = po.user_id
            JOIN res_partner rp ON rp.id = ru.partner_id
            WHERE {self._order_where(p, cashiers)}
            GROUP BY po.user_id, rp.name
        """, dict(p, states=ORDER_STATES, cashiers=cashiers))
        return cr.dictfetchall()

    def _fetch_payments(self, p, cashiers):
        """Cobrado por vendedor, caja y método. El vuelto es un pago negativo: la suma ya es neta."""
        cr = request.env.cr
        cr.execute(f"""
            SELECT po.user_id, pc.name AS caja, pm.id AS method_id,
                   COALESCE(pm.name->>%(lang)s, pm.name->>'en_US') AS method,
                   CASE WHEN pm.is_cash_count THEN 'cash'
                        WHEN pm.journal_id IS NULL THEN 'pay_later' ELSE 'bank' END AS kind,
                   SUM(pp.amount) AS amount
            FROM pos_payment pp
            JOIN pos_order po ON po.id = pp.pos_order_id
            JOIN pos_session ps ON ps.id = po.session_id
            JOIN pos_config pc ON pc.id = ps.config_id
            JOIN pos_payment_method pm ON pm.id = pp.payment_method_id
            WHERE {self._order_where(p, cashiers)}
            GROUP BY 1, 2, 3, 4, 5
        """, dict(p, states=ORDER_STATES, cashiers=cashiers))
        return cr.dictfetchall()

    def _fetch_sessions(self, p, cashiers):
        """Sesiones del período (abiertas, cerradas o con ventas en el rango) más todas las abiertas ahora.

        Efectivo esperado = apertura + cobros en efectivo + ingresos - retiros. Los movimientos de caja se
        asientan como '<sesión>-<tipo>-<motivo>' con el tipo traducido ('en'/'out'), por eso se reconocen
        por el prefijo y no por la palabra. La línea '<sesión>' sola es la venta en efectivo al cerrar y la
        de 'Diferencia ...' es el ajuste del conteo: ninguna de las dos entra.
        """
        cr = request.env.cr
        where = """pc.company_id IN %(companies)s AND ps.state <> 'opening_control'
            AND (ps.state IN ('opened', 'closing_control')
                 OR (ps.start_at <= (%(end)s::timestamp AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')
                     AND ps.stop_at >= (%(start)s::timestamp AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')))"""
        if p["configs"]:
            where += " AND ps.config_id IN %(configs)s"
        if cashiers:
            where += " AND ps.user_id IN %(cashiers)s"
        cr.execute(f"""
            SELECT ps.id, ps.name, ps.state, ps.user_id, rp.name AS opener,
                   pc.name AS caja, rc.name AS empresa,
                   ps.start_at AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s AS start_local,
                   ps.stop_at AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s AS stop_local,
                   ps.cash_journal_id IS NOT NULL AS has_cash,
                   COALESCE(ps.cash_register_balance_start, 0) AS cash_start,
                   ps.cash_register_balance_end_real AS counted,
                   COALESCE(cash.amount, 0) AS cash_sales,
                   COALESCE(sales.amount, 0) AS sold,
                   COALESCE(sales.tickets, 0) AS tickets,
                   COALESCE(mv.deposits, 0) AS deposits,
                   COALESCE(mv.withdrawals, 0) AS withdrawals,
                   COALESCE(mv.withdrawals_count, 0) AS withdrawals_count
            FROM pos_session ps
            JOIN pos_config pc ON pc.id = ps.config_id
            JOIN res_company rc ON rc.id = pc.company_id
            JOIN res_users ru ON ru.id = ps.user_id
            JOIN res_partner rp ON rp.id = ru.partner_id
            LEFT JOIN LATERAL (
                SELECT SUM(pp.amount) AS amount
                FROM pos_payment pp
                JOIN pos_order po ON po.id = pp.pos_order_id
                JOIN pos_payment_method pm ON pm.id = pp.payment_method_id
                WHERE po.session_id = ps.id AND pm.is_cash_count AND po.state IN %(states)s
            ) cash ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(po.amount_total) AS amount, COUNT(*) FILTER (WHERE po.amount_total >= 0) AS tickets
                FROM pos_order po WHERE po.session_id = ps.id AND po.state IN %(states)s
            ) sales ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(l.amount) FILTER (WHERE l.amount > 0) AS deposits,
                       -SUM(l.amount) FILTER (WHERE l.amount < 0) AS withdrawals,
                       COUNT(*) FILTER (WHERE l.amount < 0) AS withdrawals_count
                FROM account_bank_statement_line l
                WHERE l.pos_session_id = ps.id AND l.payment_ref LIKE ps.name || '-%%'
            ) mv ON TRUE
            WHERE {where}
            ORDER BY ps.start_at DESC
        """, dict(p, states=ORDER_STATES, cashiers=cashiers))
        return cr.dictfetchall()

    def _fetch_moves(self, p, cashiers):
        """Retiros e ingresos de efectivo hechos en el período, con quién los registró y el motivo."""
        cr = request.env.cr
        where = """pc.company_id IN %(companies)s AND l.payment_ref LIKE ps.name || '-%%'
            AND l.create_date >= (%(start)s::timestamp AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')
            AND l.create_date <= (%(end)s::timestamp AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')"""
        if p["configs"]:
            where += " AND ps.config_id IN %(configs)s"
        if cashiers:
            where += " AND l.create_uid IN %(cashiers)s"
        cr.execute(f"""
            SELECT l.id, l.amount, l.create_uid AS user_id, rp.name AS user_name,
                   l.create_date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s AS date_local,
                   ps.name AS session, pc.name AS caja,
                   -- '<sesión>-out-RETIRO' -> 'RETIRO'
                   substr(l.payment_ref, length(ps.name) + 2) AS rest
            FROM account_bank_statement_line l
            JOIN pos_session ps ON ps.id = l.pos_session_id
            JOIN pos_config pc ON pc.id = ps.config_id
            JOIN res_users ru ON ru.id = l.create_uid
            JOIN res_partner rp ON rp.id = ru.partner_id
            WHERE {where}
            ORDER BY l.create_date DESC
        """, dict(p, cashiers=cashiers))
        return cr.dictfetchall()

    # ------------------------------------------------------------------
    # Armado
    # ------------------------------------------------------------------
    def _session_rows(self, sessions, today):
        rows = []
        for s in sessions:
            expected = None
            if s["has_cash"]:
                expected = float(s["cash_start"]) + float(s["cash_sales"]) + float(s["deposits"]) - float(s["withdrawals"])
            is_open = s["state"] in ('opened', 'closing_control')
            counted = float(s["counted"]) if not is_open and s["counted"] is not None and s["has_cash"] else None
            difference = counted - expected if counted is not None and expected is not None else None
            start_local = s["start_local"]
            if is_open:
                status = "abierta_hoy" if start_local and start_local.date() == today else "abierta_vieja"
            elif difference is None or abs(difference) < DIFF_TOLERANCE:
                status = "cerro_justo"
            else:
                status = "faltante" if difference < 0 else "sobrante"
            rows.append({
                "id": s["id"],
                "session": s["name"],
                "caja": s["caja"],
                "empresa": s["empresa"],
                "user_id": s["user_id"],
                "opener": s["opener"],
                "start": start_local.strftime("%d/%m/%Y %H:%M") if start_local else None,
                "stop": s["stop_local"].strftime("%d/%m/%Y %H:%M") if s["stop_local"] else None,
                "stop_date": s["stop_local"].date().isoformat() if s["stop_local"] else None,
                "days_open": (today - start_local.date()).days if is_open and start_local else 0,
                "is_open": is_open,
                "cash_start": _money(s["cash_start"]),
                "cash_sales": _money(s["cash_sales"]),
                "deposits": _money(s["deposits"]),
                "withdrawals": _money(s["withdrawals"]),
                "withdrawals_count": int(s["withdrawals_count"]),
                "expected": _money(expected) if expected is not None else None,
                "counted": _money(counted) if counted is not None else None,
                "difference": _money(difference) if difference is not None else None,
                "sold": _money(s["sold"]),
                "tickets": int(s["tickets"]),
                "status": status,
            })
        return rows

    def _move_rows(self, moves):
        rows = []
        for m in moves:
            kind, _sep, reason = (m["rest"] or "").partition("-")
            amount = float(m["amount"])
            rows.append({
                "id": m["id"],
                "date": m["date_local"].strftime("%d/%m/%Y %H:%M"),
                "session": m["session"],
                "caja": m["caja"],
                "user_id": m["user_id"],
                "user_name": m["user_name"],
                "kind": "retiro" if amount < 0 else "ingreso",
                "reason": reason.strip() or kind,
                "amount": _money(abs(amount)),
            })
        return rows

    def _method_tables(self, payments):
        """Cobrado por grupo (con el detalle por nombre real) y la matriz caja x grupo."""
        groups, by_pos = {}, {}
        for pay in payments:
            group = _method_group(pay["method"], pay["kind"])
            amount = float(pay["amount"] or 0.0)
            g = groups.setdefault(group, {"group": group, "amount": 0.0, "details": {}})
            g["amount"] += amount
            g["details"][pay["method"]] = g["details"].get(pay["method"], 0.0) + amount
            row = by_pos.setdefault(pay["caja"], {"caja": pay["caja"], "values": {}, "total": 0.0})
            row["values"][group] = row["values"].get(group, 0.0) + amount
            row["total"] += amount
        total = sum(g["amount"] for g in groups.values()) or 0.0
        methods = []
        for name in GROUP_ORDER:
            g = groups.get(name)
            if not g or abs(g["amount"]) < 0.005:
                continue
            methods.append({
                "group": name,
                "amount": _money(g["amount"]),
                "pct": round(g["amount"] / total * 100, 1) if total else 0.0,
                "details": sorted(({"name": k, "amount": _money(v)} for k, v in g["details"].items()),
                                  key=lambda d: -d["amount"]),
            })
        present = [m["group"] for m in methods]
        pos_rows = sorted(({"caja": r["caja"], "total": _money(r["total"]),
                            "values": {k: _money(v) for k, v in r["values"].items()}}
                           for r in by_pos.values()), key=lambda r: -r["total"])
        return methods, {"groups": present, "rows": pos_rows}

    def _cashier_rows(self, sellers, payments, sessions, moves):
        """Una fila por persona con sus dos miradas: como vendedor y como responsable de caja."""
        people = {}

        def person(uid, name):
            return people.setdefault(uid, {
                "user_id": uid, "name": name, "sold": 0.0, "tickets": 0, "avg_ticket": 0.0,
                "refunds": 0, "refunds_amount": 0.0, "cash": 0.0, "other": 0.0,
                "sessions": 0, "closed": 0, "difference": 0.0, "shortage": 0.0, "shortages": 0,
                "withdrawals": 0.0, "withdrawals_count": 0,
            })

        for s in sellers:
            p = person(s["user_id"], s["name"])
            p["sold"] = _money(s["sold"])
            p["tickets"] = int(s["tickets"])
            p["refunds"] = int(s["refunds"])
            p["refunds_amount"] = _money(-float(s["refunds_amount"]))
            p["avg_ticket"] = _money(float(s["sold"]) / s["tickets"]) if s["tickets"] else 0.0
        for pay in payments:
            p = people.get(pay["user_id"])
            if p:
                key = "cash" if pay["kind"] == 'cash' else "other"
                p[key] = _money(p[key] + float(pay["amount"] or 0.0))
        for s in sessions:
            p = person(s["user_id"], s["opener"])
            p["sessions"] += 1
            if not s["is_open"]:
                p["closed"] += 1
            if s["difference"] is not None and abs(s["difference"]) >= DIFF_TOLERANCE:
                p["difference"] = _money(p["difference"] + s["difference"])
                if s["difference"] < 0:
                    p["shortage"] = _money(p["shortage"] - s["difference"])
                    p["shortages"] += 1
        for m in moves:
            if m["kind"] == "retiro":
                p = person(m["user_id"], m["user_name"])
                p["withdrawals"] = _money(p["withdrawals"] + m["amount"])
                p["withdrawals_count"] += 1
        return sorted(people.values(), key=lambda r: -r["sold"])

    def _build(self, company, pos, cashier, start_date, end_date):
        """Todo el dashboard con una sola regla de filtros: lo usan la pantalla y el Excel."""
        start, end = self._resolve_range(start_date, end_date)
        p = self._params(company, pos, start, end)
        cashiers = _to_ids(cashier)
        today = self._today()

        sellers = self._fetch_sellers(p, cashiers)
        payments = self._fetch_payments(p, cashiers)
        sessions = self._session_rows(self._fetch_sessions(p, cashiers), today)
        moves = self._move_rows(self._fetch_moves(p, cashiers))
        methods, methods_by_pos = self._method_tables(payments)
        cashier_rows = self._cashier_rows(sellers, payments, sessions, moves)

        sold = sum(float(s["sold"]) for s in sellers)
        tickets = sum(int(s["tickets"]) for s in sellers)
        open_today = [s for s in sessions if s["status"] == "abierta_hoy"]
        open_old = [s for s in sessions if s["status"] == "abierta_vieja"]
        closed_in_range = [s for s in sessions if not s["is_open"] and s["stop_date"] and start <= s["stop_date"] <= end]
        with_diff = [s for s in closed_in_range if s["status"] in ("faltante", "sobrante")]
        withdrawals = [m for m in moves if m["kind"] == "retiro"]

        kpis = {
            "sold": _money(sold),
            "tickets": tickets,
            "avg_ticket": _money(sold / tickets) if tickets else 0.0,
            "refunds": sum(int(s["refunds"]) for s in sellers),
            "cash_now": _money(sum(s["expected"] or 0.0 for s in open_today)),
            "open_today": len(open_today),
            "cash_old": _money(sum(s["expected"] or 0.0 for s in open_old)),
            "open_old": len(open_old),
            "withdrawals": _money(sum(m["amount"] for m in withdrawals)),
            "withdrawals_count": len(withdrawals),
            "deposits": _money(sum(m["amount"] for m in moves if m["kind"] == "ingreso")),
            "deposits_count": len(moves) - len(withdrawals),
            "difference": _money(sum(s["difference"] or 0.0 for s in with_diff)),
            "shortage": _money(-sum(s["difference"] for s in with_diff if s["difference"] < 0)),
            "closed": len(closed_in_range),
            "closed_with_diff": len(with_diff),
        }
        return {
            "range": {"start": start, "end": end, "today": today.isoformat()},
            "kpis": kpis,
            "cashiers": cashier_rows[:MAX_TABLE_ROWS],
            "sessions": sessions[:MAX_TABLE_ROWS],
            "moves": moves[:MAX_TABLE_ROWS],
            "methods": methods,
            "methods_by_pos": methods_by_pos,
        }

    @http.route('/pos_cash_metrics/data', type='json', auth='user')
    def get_data(self, company='all', pos='all', cashier='all', start_date=None, end_date=None, **kwargs):
        """Datos de las cinco pestañas. Sólo el estado de la caja se filtra en el cliente."""
        self._check_access()
        return self._build(company, pos, cashier, start_date, end_date)

    # ------------------------------------------------------------------
    # Excel
    # ------------------------------------------------------------------
    def _export_table(self, data, table, status):
        """Título, encabezados, claves y filas de la pestaña pedida, con los mismos filtros que la pantalla."""
        if table == 'sessions':
            rows = [r for r in data["sessions"] if not status or r["status"] in status]
            return ("Cajas y cierres",
                    ["Caja", "Empresa", "Sesión", "Abrió", "Apertura", "Cierre", "Vendido", "Tickets",
                     "Efectivo inicial", "Cobrado en efectivo", "Ingresos", "Retiros", "Efectivo esperado",
                     "Contado", "Diferencia", "Estado"],
                    ["caja", "empresa", "session", "opener", "start", "stop", "sold", "tickets",
                     "cash_start", "cash_sales", "deposits", "withdrawals", "expected",
                     "counted", "difference", "status"], rows)
        if table == 'moves':
            return ("Retiros e ingresos",
                    ["Fecha", "Caja", "Sesión", "Hecho por", "Tipo", "Motivo", "Monto"],
                    ["date", "caja", "session", "user_name", "kind", "reason", "amount"], data["moves"])
        if table == 'methods':
            rows = [{"group": m["group"], "name": d["name"], "amount": d["amount"]}
                    for m in data["methods"] for d in m["details"]]
            return ("Medios de pago", ["Grupo", "Método", "Cobrado"], ["group", "name", "amount"], rows)
        return ("Cajeros",
                ["Cajero", "Vendido", "Tickets", "Ticket promedio", "Devoluciones", "Monto devuelto",
                 "Cobrado en efectivo", "Cobrado otros medios", "Cajas abiertas", "Cajas cerradas",
                 "Diferencia acumulada", "Faltante", "Cierres con faltante", "Retiros", "Cantidad de retiros"],
                ["name", "sold", "tickets", "avg_ticket", "refunds", "refunds_amount", "cash", "other",
                 "sessions", "closed", "difference", "shortage", "shortages", "withdrawals", "withdrawals_count"],
                data["cashiers"])

    @http.route('/pos_cash_metrics/export', type='http', auth='user')
    def export_xlsx(self, table='cashiers', company='all', pos='all', cashier='all', status='all',
                    start_date=None, end_date=None, **kwargs):
        """Exporta a Excel la pestaña activa con los mismos filtros que ve el usuario."""
        try:
            self._check_access()
            data = self._build(company, pos, cashier, start_date, end_date)
            title, headers, keys, rows = self._export_table(data, table, _to_list(status))
            money_keys = {"sold", "avg_ticket", "refunds_amount", "cash", "other", "difference", "shortage",
                          "withdrawals", "cash_start", "cash_sales", "deposits", "expected", "counted", "amount"}

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            fmt_title = workbook.add_format({'bold': True, 'font_size': 12})
            fmt_header = workbook.add_format({
                'bold': True, 'bg_color': '#1e293b', 'font_color': '#ffffff',
                'border': 1, 'align': 'center', 'valign': 'vcenter'})
            fmt_text = workbook.add_format({'border': 1})
            fmt_money = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
            fmt_num = workbook.add_format({'border': 1, 'num_format': '#,##0'})

            sheet = workbook.add_worksheet(title[:31])
            sheet.set_column(0, 0, 32)
            sheet.set_column(1, len(headers) - 1, 16)
            company_label = ', '.join(_to_list(company)) or 'Todas las empresas'
            rng = data["range"]
            sheet.write(0, 0, f"Métricas de Caja · {title}", fmt_title)
            sheet.write(1, 0, f"{company_label} · del {rng['start']} al {rng['end']}")
            for col, header in enumerate(headers):
                sheet.write(3, col, header, fmt_header)
            for idx, row in enumerate(rows):
                for col, key in enumerate(keys):
                    value = row.get(key)
                    if key == "status":
                        sheet.write_string(4 + idx, col, STATUS_LABELS.get(value, ''), fmt_text)
                    elif key == "kind":
                        sheet.write_string(4 + idx, col, "Retiro" if value == "retiro" else "Ingreso", fmt_text)
                    elif isinstance(value, bool) or value is None:
                        sheet.write_string(4 + idx, col, '', fmt_text)
                    elif isinstance(value, (int, float)):
                        sheet.write_number(4 + idx, col, value, fmt_money if key in money_keys else fmt_num)
                    else:
                        sheet.write_string(4 + idx, col, str(value), fmt_text)
            sheet.freeze_panes(4, 1)
            workbook.close()
            xlsx_data = output.getvalue()
            output.close()

            filename = f"caja_{table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            return request.make_response(xlsx_data, headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
                ('Content-Length', str(len(xlsx_data))),
            ])
        except Exception as e:
            _logger.exception("Error exportando Métricas de Caja")
            return request.make_response(str(e), status=500)
