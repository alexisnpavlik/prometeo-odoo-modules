# Cambios de Precio para Góndola — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Módulo Odoo 18 `product_price_change_metrics` que registra cada cambio de precio (global y de lista) y muestra a cada sucursal una lista de trabajo para actualizar las etiquetas de góndola, con checklist pendiente/actualizado.

**Architecture:** Un modelo de log `product.price.log` se puebla vía override de `write()`/`create()` en `product.template` (precio global) y `product.pricelist.item` (precios de lista). Un cambio global genera una fila por empresa (fan-out); un cambio de lista genera una fila para la empresa dueña de la lista. Un dashboard OWL (controller JSON + componente) lista los cambios filtrados por empresa/estado/ventana y permite marcarlos como actualizados en góndola (endpoint con sudo). Sin gráficos.

**Tech Stack:** Odoo 18.0, Python (ORM overrides), OWL (`@odoo/owl`, `@web/core/network/rpc`), `http.Controller` JSON.

## Global Constraints

- Odoo target: **18.0**; versión del módulo **18.0.1.0.0**.
- `depends`: **["product", "web"]**. `license`: **LGPL-3**. `author`: **"Alexis Medina"**. `website`: **"alexis.medn@gmail.com"**.
- Estructura del repo: `__init__.py` + `__manifest__.py` + `models/` (un archivo por modelo) + `controllers/` + `security/` + `views/` + `static/`.
- snake_case en todo. Función-orientado; clases solo para modelos Odoo / componentes OWL. Docstring (en español) en cada método.
- Traducciones nuevo estilo: `_("texto %s", arg)` (coma, no `%`).
- El logging de cambios **nunca** debe abortar el guardado del producto/item: envolver en `try/except Exception as e` con `_logger.warning(...)` y llamar siempre a `super()`.
- `data` en el manifest: `security/*` antes que `views/`.
- Multi-compañía: scoping vía `request.env.companies` en el controller y record rule `[('company_id', 'in', company_ids)]` en el modelo.
- Verificación (no hay pytest en este repo): validación de sintaxis local + `sudo docker exec odoo-odoo-1 odoo -u product_price_change_metrics -d prod --stop-after-init` (confirmar nombre de DB si difiere; módulo montado en el addons-path del contenedor).

---

### Task 1: Scaffold del módulo (instala vacío)

**Files:**
- Create: `product_price_change_metrics/__init__.py`
- Create: `product_price_change_metrics/__manifest__.py`
- Create: `product_price_change_metrics/models/__init__.py`
- Create: `product_price_change_metrics/controllers/__init__.py`

**Interfaces:**
- Produces: paquete instalable `product_price_change_metrics` con `models` y `controllers` importables (vacíos por ahora).

- [ ] **Step 1: Crear `__init__.py` raíz**

```python
# -*- coding: utf-8 -*-
from . import models
from . import controllers
```

- [ ] **Step 2: Crear `models/__init__.py` (vacío por ahora)**

```python
# -*- coding: utf-8 -*-
```

- [ ] **Step 3: Crear `controllers/__init__.py` (vacío por ahora)**

```python
# -*- coding: utf-8 -*-
```

- [ ] **Step 4: Crear `__manifest__.py`**

```python
# -*- coding: utf-8 -*-
{
    "name": "Cambios de Precio para Góndola",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Lista operativa de productos con precio cambiado recientemente para actualizar etiquetas en góndola",
    "description": """
        Registra cada cambio de precio de venta (global) y de listas de precios,
        y muestra a cada sucursal una lista de trabajo con los productos que
        cambiaron de precio recientemente, para actualizar las etiquetas en la
        góndola. Cada fila se marca como pendiente/actualizado por sucursal.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "product_price_change_metrics/static/src/css/dashboard.css",
            "product_price_change_metrics/static/src/js/dashboard.js",
            "product_price_change_metrics/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
```

> Nota: el manifest ya referencia archivos `data`/`assets` que se crean en tasks siguientes. El módulo **no instala** hasta la Task 6. La validación de esta task es solo de sintaxis del manifest.

- [ ] **Step 5: Validar sintaxis del manifest**

Run: `python3 -c "import ast; ast.parse(open('product_price_change_metrics/__manifest__.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add product_price_change_metrics/__init__.py product_price_change_metrics/__manifest__.py product_price_change_metrics/models/__init__.py product_price_change_metrics/controllers/__init__.py
git commit -m "feat(price-change): scaffold product_price_change_metrics module"
```

---

### Task 2: Modelo `product.price.log` + seguridad

**Files:**
- Create: `product_price_change_metrics/models/product_price_log.py`
- Modify: `product_price_change_metrics/models/__init__.py`
- Create: `product_price_change_metrics/security/security.xml`
- Create: `product_price_change_metrics/security/ir.model.access.csv`
- Create: `product_price_change_metrics/views/menu_views.xml` (placeholder mínimo para que el manifest cargue)

**Interfaces:**
- Produces:
  - Modelo `product.price.log` con campos: `product_tmpl_id` (m2o product.template), `product_id` (m2o product.product), `source` (selection global/pricelist), `pricelist_id` (m2o), `company_id` (m2o res.company, required), `price_type` (selection fixed/percent), `old_price`/`new_price`/`diff_amount` (float), `change_date` (datetime), `user_id` (m2o res.users), `state` (selection pending/done), `done_user_id`, `done_date`.
  - Método `@api.model _log_change(self, vals, companies)` → crea una fila por empresa (sudo) y devuelve el recordset creado. `vals` NO incluye `company_id`.
  - Grupo `product_price_change_metrics.group_price_change_metrics_user`.
  - Record rule global `[('company_id', 'in', company_ids)]` sobre `product.price.log`.

- [ ] **Step 1: Crear `models/product_price_log.py`**

```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ProductPriceLog(models.Model):
    _name = "product.price.log"
    _description = "Cambio de precio para actualización de góndola"
    _order = "change_date desc, id desc"

    product_tmpl_id = fields.Many2one(
        "product.template", string="Producto", required=True,
        ondelete="cascade", index=True,
    )
    product_id = fields.Many2one(
        "product.product", string="Variante", ondelete="cascade", index=True,
    )
    source = fields.Selection(
        [("global", "Precio global"), ("pricelist", "Lista de precios")],
        string="Origen", required=True,
    )
    pricelist_id = fields.Many2one("product.pricelist", string="Lista de precios")
    company_id = fields.Many2one(
        "res.company", string="Empresa", required=True, index=True,
    )
    price_type = fields.Selection(
        [("fixed", "Fijo"), ("percent", "Porcentaje")], string="Tipo de precio",
    )
    old_price = fields.Float(string="Precio anterior")
    new_price = fields.Float(string="Precio nuevo")
    diff_amount = fields.Float(
        string="Diferencia", compute="_compute_diff_amount", store=True,
    )
    change_date = fields.Datetime(
        string="Fecha de cambio", default=fields.Datetime.now, index=True,
    )
    user_id = fields.Many2one(
        "res.users", string="Modificado por", default=lambda self: self.env.user,
    )
    state = fields.Selection(
        [("pending", "Pendiente"), ("done", "Actualizado")],
        string="Estado góndola", default="pending", required=True, index=True,
    )
    done_user_id = fields.Many2one("res.users", string="Actualizado por")
    done_date = fields.Datetime(string="Fecha actualización")

    @api.depends("old_price", "new_price")
    def _compute_diff_amount(self):
        """Diferencia absoluta entre precio nuevo y anterior."""
        for rec in self:
            rec.diff_amount = (rec.new_price or 0.0) - (rec.old_price or 0.0)

    @api.model
    def _log_change(self, vals, companies):
        """Crea una fila de log por cada empresa (fan-out). `vals` sin company_id."""
        logs = self.browse()
        for company in companies:
            logs |= self.sudo().create(dict(vals, company_id=company.id))
        return logs
```

- [ ] **Step 2: Registrar el modelo en `models/__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import product_price_log
```

- [ ] **Step 3: Crear `security/security.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="group_price_change_metrics_user" model="res.groups">
        <field name="name">Acceso a Cambios de Precio (Góndola)</field>
        <field name="category_id" ref="base.module_category_usability"/>
        <field name="comment">Permite ver la lista de productos con precio cambiado recientemente y marcarlos como actualizados en góndola.</field>
    </record>

    <record id="rule_price_log_company" model="ir.rule">
        <field name="name">product.price.log multi-company</field>
        <field name="model_id" ref="model_product_price_log"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>
</odoo>
```

- [ ] **Step 4: Crear `security/ir.model.access.csv` (solo lectura para el grupo)**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_product_price_log_user,product.price.log usuario,model_product_price_log,group_price_change_metrics_user,1,0,0,0
```

- [ ] **Step 5: Crear `views/menu_views.xml` (placeholder para que el manifest cargue; se completa en Task 6)**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
</odoo>
```

- [ ] **Step 6: Validar sintaxis de XML y CSV**

Run:
```bash
python3 -c "import xml.dom.minidom as m; m.parse('product_price_change_metrics/security/security.xml'); m.parse('product_price_change_metrics/views/menu_views.xml'); print('XML OK')"
python3 -c "import csv; rows=list(csv.reader(open('product_price_change_metrics/security/ir.model.access.csv'))); print('CSV cols', {len(r) for r in rows})"
```
Expected: `XML OK` y `CSV cols {8}`

- [ ] **Step 7: Instalar el módulo en el contenedor**

Run: `sudo docker exec odoo-odoo-1 odoo -i product_price_change_metrics -d prod --stop-after-init`
Expected: termina sin traceback; en el log aparece `Loading module product_price_change_metrics` y `Modules loaded.` (confirmar nombre de DB si `prod` no aplica).

- [ ] **Step 8: Commit**

```bash
git add product_price_change_metrics/models/ product_price_change_metrics/security/ product_price_change_metrics/views/menu_views.xml
git commit -m "feat(price-change): add product.price.log model, group and access rules"
```

---

### Task 3: Captura de cambio de precio global (`product.template`)

**Files:**
- Create: `product_price_change_metrics/models/product_template.py`
- Modify: `product_price_change_metrics/models/__init__.py`

**Interfaces:**
- Consumes: `product.price.log._log_change(vals, companies)` (Task 2).
- Produces: al cambiar `list_price` de una plantilla, se crea una fila `source="global"`, `price_type="fixed"` por cada empresa activa.

- [ ] **Step 1: Crear `models/product_template.py`**

```python
# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def write(self, vals):
        """Registra un cambio de precio global (list_price) para cada empresa."""
        track_price = "list_price" in vals
        old_prices = {}
        if track_price and not self.env.context.get("install_mode"):
            for record in self:
                old_prices[record.id] = record.list_price
        res = super().write(vals)
        if old_prices:
            try:
                self._ppcm_log_global_change(old_prices)
            except Exception as e:
                _logger.warning(
                    "product_price_change_metrics: fallo al registrar cambio global en %s: %s",
                    self, e,
                )
        return res

    def _ppcm_log_global_change(self, old_prices):
        """Crea una fila de log global (fan-out a todas las empresas) por producto cambiado."""
        companies = self.env["res.company"].sudo().search([])
        Log = self.env["product.price.log"].sudo()
        for record in self:
            old = old_prices.get(record.id)
            new = record.list_price
            if old is None or old == new:
                continue
            Log._log_change({
                "product_tmpl_id": record.id,
                "source": "global",
                "price_type": "fixed",
                "old_price": old,
                "new_price": new,
                "user_id": self.env.uid,
            }, companies)
```

- [ ] **Step 2: Registrar en `models/__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import product_price_log
from . import product_template
```

- [ ] **Step 3: Validar sintaxis Python**

Run: `python3 -c "import ast; ast.parse(open('product_price_change_metrics/models/product_template.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Actualizar el módulo**

Run: `sudo docker exec odoo-odoo-1 odoo -u product_price_change_metrics -d prod --stop-after-init`
Expected: sin traceback.

- [ ] **Step 5: Verificar comportamiento con odoo shell**

Run:
```bash
sudo docker exec -i odoo-odoo-1 odoo shell -d prod --stop-after-init <<'PY'
n_companies = env["res.company"].search_count([])
tmpl = env["product.template"].search([("sale_ok", "=", True)], limit=1)
before = env["product.price.log"].search_count([])
tmpl.write({"list_price": tmpl.list_price + 5})
after = env["product.price.log"].search_count([])
print("companies:", n_companies, "logs creados:", after - before)
env.cr.rollback()
PY
```
Expected: `logs creados:` == número de empresas activas (fan-out).

- [ ] **Step 6: Commit**

```bash
git add product_price_change_metrics/models/product_template.py product_price_change_metrics/models/__init__.py
git commit -m "feat(price-change): log global list_price changes with per-company fan-out"
```

---

### Task 4: Captura de cambio en listas de precio (`product.pricelist.item`)

**Files:**
- Create: `product_price_change_metrics/models/product_pricelist_item.py`
- Modify: `product_price_change_metrics/models/__init__.py`

**Interfaces:**
- Consumes: `product.price.log._log_change(vals, companies)` (Task 2).
- Produces: al crear/modificar un item de lista con precio `fixed`/`percentage` a nivel producto/variante, se crea una fila `source="pricelist"` para la empresa de la lista (o fan-out si la lista no tiene empresa).

- [ ] **Step 1: Crear `models/product_pricelist_item.py`**

```python
# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

_PRICE_FIELDS = ("fixed_price", "percent_price", "compute_price")


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    def _ppcm_price_snapshot(self):
        """Devuelve (price_type, precio) comparable del item, o None si no aplica."""
        self.ensure_one()
        if self.applied_on not in ("1_product", "0_product_variant"):
            return None
        if self.compute_price == "fixed":
            return ("fixed", self.fixed_price or 0.0)
        if self.compute_price == "percentage":
            return ("percent", self.percent_price or 0.0)
        return None  # formula u otros: no comparable

    def write(self, vals):
        """Registra un cambio de precio de item de lista para la empresa dueña."""
        track = any(f in vals for f in _PRICE_FIELDS) and not self.env.context.get("install_mode")
        old_state = {}
        if track:
            for item in self:
                old_state[item.id] = item._ppcm_price_snapshot()
        res = super().write(vals)
        if track:
            try:
                self._ppcm_log_item_change(old_state)
            except Exception as e:
                _logger.warning(
                    "product_price_change_metrics: fallo al registrar cambio de lista en %s: %s",
                    self, e,
                )
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Registra el alta de un item de lista con precio concreto."""
        items = super().create(vals_list)
        if not self.env.context.get("install_mode"):
            try:
                items._ppcm_log_item_change({})
            except Exception as e:
                _logger.warning(
                    "product_price_change_metrics: fallo al registrar alta de lista: %s", e,
                )
        return items

    def _ppcm_log_item_change(self, old_state):
        """Crea la fila de log del item cambiado, para la empresa de su lista (o fan-out)."""
        Log = self.env["product.price.log"].sudo()
        all_companies = None
        for item in self:
            snap = item._ppcm_price_snapshot()
            if snap is None:
                continue
            old = old_state.get(item.id)
            if old is not None and old == snap:
                continue
            tmpl = item.product_tmpl_id or item.product_id.product_tmpl_id
            if not tmpl:
                continue
            price_type, new_price = snap
            old_price = old[1] if old else 0.0
            company = item.pricelist_id.company_id
            if company:
                companies = company
            else:
                if all_companies is None:
                    all_companies = self.env["res.company"].sudo().search([])
                companies = all_companies
            Log._log_change({
                "product_tmpl_id": tmpl.id,
                "product_id": item.product_id.id if item.product_id else False,
                "source": "pricelist",
                "pricelist_id": item.pricelist_id.id,
                "price_type": price_type,
                "old_price": old_price,
                "new_price": new_price,
                "user_id": self.env.uid,
            }, companies)
```

- [ ] **Step 2: Registrar en `models/__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import product_price_log
from . import product_template
from . import product_pricelist_item
```

- [ ] **Step 3: Validar sintaxis Python**

Run: `python3 -c "import ast; ast.parse(open('product_price_change_metrics/models/product_pricelist_item.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Actualizar el módulo**

Run: `sudo docker exec odoo-odoo-1 odoo -u product_price_change_metrics -d prod --stop-after-init`
Expected: sin traceback.

- [ ] **Step 5: Verificar comportamiento con odoo shell**

Run:
```bash
sudo docker exec -i odoo-odoo-1 odoo shell -d prod --stop-after-init <<'PY'
pl = env["product.pricelist"].search([("company_id", "!=", False)], limit=1) or env["product.pricelist"].search([], limit=1)
tmpl = env["product.template"].search([("sale_ok", "=", True)], limit=1)
before = env["product.price.log"].search_count([("source", "=", "pricelist")])
item = env["product.pricelist.item"].create({
    "pricelist_id": pl.id, "applied_on": "1_product",
    "product_tmpl_id": tmpl.id, "compute_price": "fixed", "fixed_price": 123.45,
})
mid = env["product.price.log"].search_count([("source", "=", "pricelist")])
item.write({"fixed_price": 200.0})
after = env["product.price.log"].search_count([("source", "=", "pricelist")])
print("alta creo:", mid - before, "| write creo:", after - mid)
env.cr.rollback()
PY
```
Expected: `alta creo:` >= 1 y `write creo:` >= 1.

- [ ] **Step 6: Commit**

```bash
git add product_price_change_metrics/models/product_pricelist_item.py product_price_change_metrics/models/__init__.py
git commit -m "feat(price-change): log pricelist item price changes per company"
```

---

### Task 5: Controller JSON (filtros, lista, marcar hecho)

**Files:**
- Create: `product_price_change_metrics/controllers/price_change_controller.py`
- Modify: `product_price_change_metrics/controllers/__init__.py`

**Interfaces:**
- Consumes: modelo `product.price.log` (Task 2), grupo `group_price_change_metrics_user`.
- Produces (rutas JSON `auth="user"`):
  - `/product_price_change_metrics/filters` → `{companies:[{id,name}], current_company:int, categories:[{id,name}]}`
  - `/product_price_change_metrics/changes(company, state, window, category, search, page, per_page)` → `{rows:[...], page, pages, total, pending}`. Cada row: `{id, product_tmpl_id, product, category, source, old_price, new_price, diff_amount, date, state, done_by}`.
  - `/product_price_change_metrics/mark_done(ids, done)` → `{updated:int}`.

- [ ] **Step 1: Crear `controllers/price_change_controller.py`**

```python
# -*- coding: utf-8 -*-
import logging

from odoo import fields, http
from odoo.http import request
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class PriceChangeMetricsController(http.Controller):

    def _check_access(self):
        """Bloquea el acceso si el usuario no está en el grupo del módulo."""
        if not request.env.user.has_group(
            "product_price_change_metrics.group_price_change_metrics_user"
        ):
            raise AccessError("No tienes permisos para ver los cambios de precio.")

    def _window_domain(self, window):
        """Dominio por ventana temporal (días) sobre change_date; [] si 'all'."""
        if not window or window == "all":
            return []
        try:
            days = int(window)
        except (TypeError, ValueError):
            days = 30
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        return [("change_date", ">=", limit_date)]

    def _base_domain(self, company, window, category, search):
        """Construye el dominio común (sin filtro de estado)."""
        domain = self._window_domain(window)
        if company == "current":
            domain.append(("company_id", "=", request.env.company.id))
        elif company and company != "all":
            domain.append(("company_id", "=", int(company)))
        if category and category != "all":
            domain.append(("product_tmpl_id.categ_id", "=", int(category)))
        if search:
            domain.append(("product_tmpl_id.name", "ilike", search))
        return domain

    @http.route("/product_price_change_metrics/filters", type="json", auth="user")
    def get_filters(self, **kwargs):
        """Datos para poblar los filtros del dashboard."""
        self._check_access()
        companies = request.env.companies
        categories = request.env["product.category"].search([])
        return {
            "companies": [{"id": c.id, "name": c.name} for c in companies],
            "current_company": request.env.company.id,
            "categories": [{"id": c.id, "name": c.display_name} for c in categories],
        }

    @http.route("/product_price_change_metrics/changes", type="json", auth="user")
    def get_changes(self, company="current", state="pending", window="30",
                    category="all", search=None, page=1, per_page=20, **kwargs):
        """Lista paginada de cambios de precio filtrados + contador de pendientes."""
        self._check_access()
        base_domain = self._base_domain(company, window, category, search)
        domain = list(base_domain)
        if state and state != "all":
            domain.append(("state", "=", state))

        Log = request.env["product.price.log"]
        per_page = int(per_page or 20)
        page = max(1, int(page or 1))
        total = Log.search_count(domain)
        pages = max(1, (total + per_page - 1) // per_page)
        records = Log.search(
            domain, limit=per_page, offset=(page - 1) * per_page,
            order="change_date desc, id desc",
        )
        rows = []
        for r in records:
            rows.append({
                "id": r.id,
                "product_tmpl_id": r.product_tmpl_id.id,
                "product": r.product_tmpl_id.display_name,
                "category": r.product_tmpl_id.categ_id.display_name or "—",
                "source": "Global" if r.source == "global" else (r.pricelist_id.display_name or "Lista"),
                "old_price": round(r.old_price, 2),
                "new_price": round(r.new_price, 2),
                "diff_amount": round(r.diff_amount, 2),
                "date": fields.Datetime.to_string(r.change_date),
                "state": r.state,
                "done_by": r.done_user_id.name or "",
            })
        pending = Log.search_count(base_domain + [("state", "=", "pending")])
        return {"rows": rows, "page": page, "pages": pages, "total": total, "pending": pending}

    @http.route("/product_price_change_metrics/mark_done", type="json", auth="user")
    def mark_done(self, ids=None, done=True, **kwargs):
        """Marca filas como actualizadas/pendientes en góndola (solo de sus empresas)."""
        self._check_access()
        ids = [int(i) for i in (ids or [])]
        if not ids:
            return {"updated": 0}
        records = request.env["product.price.log"].search([
            ("id", "in", ids),
            ("company_id", "in", request.env.companies.ids),
        ])
        if done:
            vals = {
                "state": "done",
                "done_user_id": request.env.uid,
                "done_date": fields.Datetime.now(),
            }
        else:
            vals = {"state": "pending", "done_user_id": False, "done_date": False}
        records.sudo().write(vals)
        return {"updated": len(records)}
```

- [ ] **Step 2: Registrar en `controllers/__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import price_change_controller
```

- [ ] **Step 3: Validar sintaxis Python**

Run: `python3 -c "import ast; ast.parse(open('product_price_change_metrics/controllers/price_change_controller.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Actualizar el módulo**

Run: `sudo docker exec odoo-odoo-1 odoo -u product_price_change_metrics -d prod --stop-after-init`
Expected: sin traceback (las rutas se registran al levantar el server; la verificación funcional real es en Task 6 con el dashboard).

- [ ] **Step 5: Commit**

```bash
git add product_price_change_metrics/controllers/
git commit -m "feat(price-change): add JSON controller for filters, changes list and mark_done"
```

---

### Task 6: Dashboard OWL + menú (deliverable end-to-end)

**Files:**
- Create: `product_price_change_metrics/static/src/js/dashboard.js`
- Create: `product_price_change_metrics/static/src/xml/dashboard.xml`
- Create: `product_price_change_metrics/static/src/css/dashboard.css`
- Modify: `product_price_change_metrics/views/menu_views.xml`

**Interfaces:**
- Consumes: rutas JSON de Task 5; acción cliente registrada como `product_price_change_metrics.dashboard`.
- Produces: menú de aplicación "Cambios de Precio" que abre el dashboard; componente OWL `PriceChangeDashboard` (template `product_price_change_metrics.Dashboard`).

- [ ] **Step 1: Crear `static/src/js/dashboard.js`**

```javascript
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

class PriceChangeDashboard extends Component {
    static template = "product_price_change_metrics.Dashboard";

    setup() {
        this.action = useService("action");
        this.state = useState({
            company: "current",
            stateFilter: "pending",
            window: "30",
            category: "all",
            search: "",
            page: 1,
            perPage: 20,
            loading: false,
        });
        this.filters = useState({ companies: [], categories: [], current_company: null });
        this.data = useState({ rows: [], page: 1, pages: 1, total: 0, pending: 0 });
        this.selection = useState({ ids: [] });

        onWillStart(async () => {
            await this.loadFilters();
            await this.refresh();
        });
    }

    async loadFilters() {
        const res = await rpc("/product_price_change_metrics/filters", {});
        this.filters.companies = res.companies;
        this.filters.categories = res.categories;
        this.filters.current_company = res.current_company;
    }

    async refresh() {
        this.state.loading = true;
        try {
            const res = await rpc("/product_price_change_metrics/changes", {
                company: this.state.company,
                state: this.state.stateFilter,
                window: this.state.window,
                category: this.state.category,
                search: this.state.search,
                page: this.state.page,
                per_page: this.state.perPage,
            });
            this.data.rows = res.rows;
            this.data.page = res.page;
            this.data.pages = res.pages;
            this.data.total = res.total;
            this.data.pending = res.pending;
            this.selection.ids = [];
        } finally {
            this.state.loading = false;
        }
    }

    onFilterChange() {
        this.state.page = 1;
        this.refresh();
    }

    goToPage(p) {
        if (p < 1 || p > this.data.pages) {
            return;
        }
        this.state.page = p;
        this.refresh();
    }

    toggleRow(id) {
        const idx = this.selection.ids.indexOf(id);
        if (idx >= 0) {
            this.selection.ids.splice(idx, 1);
        } else {
            this.selection.ids.push(id);
        }
    }

    isSelected(id) {
        return this.selection.ids.includes(id);
    }

    async markDone(done) {
        if (!this.selection.ids.length) {
            return;
        }
        await rpc("/product_price_change_metrics/mark_done", {
            ids: this.selection.ids,
            done: done,
        });
        await this.refresh();
    }

    openProduct(tmplId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.template",
            res_id: tmplId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("product_price_change_metrics.dashboard", PriceChangeDashboard);
```

- [ ] **Step 2: Crear `static/src/xml/dashboard.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<templates xml:space="preserve">
    <t t-name="product_price_change_metrics.Dashboard">
        <div class="ppcm-wrap">
            <div class="ppcm-header">
                <h2>Cambios de Precio — Góndola</h2>
                <div class="ppcm-pending">
                    <span t-esc="data.pending"/> pendientes de actualizar
                </div>
            </div>

            <div class="ppcm-filters">
                <select t-model="state.company" t-on-change="onFilterChange">
                    <option value="current">Mi empresa</option>
                    <option value="all">Todas las empresas</option>
                    <t t-foreach="filters.companies" t-as="c" t-key="c.id">
                        <option t-att-value="c.id"><t t-esc="c.name"/></option>
                    </t>
                </select>
                <select t-model="state.stateFilter" t-on-change="onFilterChange">
                    <option value="pending">Pendientes</option>
                    <option value="done">Actualizados</option>
                    <option value="all">Todos</option>
                </select>
                <select t-model="state.window" t-on-change="onFilterChange">
                    <option value="7">Últimos 7 días</option>
                    <option value="30">Últimos 30 días</option>
                    <option value="90">Últimos 90 días</option>
                    <option value="all">Todo</option>
                </select>
                <select t-model="state.category" t-on-change="onFilterChange">
                    <option value="all">Todas las categorías</option>
                    <t t-foreach="filters.categories" t-as="cat" t-key="cat.id">
                        <option t-att-value="cat.id"><t t-esc="cat.name"/></option>
                    </t>
                </select>
                <input type="text" placeholder="Buscar producto..."
                       t-model="state.search" t-on-keyup="onFilterChange"/>
            </div>

            <div class="ppcm-actions">
                <button class="btn btn-primary" t-on-click="() => this.markDone(true)">
                    Marcar seleccionados como actualizados
                </button>
                <button class="btn btn-secondary" t-on-click="() => this.markDone(false)">
                    Volver a pendiente
                </button>
            </div>

            <table class="ppcm-table">
                <thead>
                    <tr>
                        <th></th>
                        <th>Producto</th>
                        <th>Categoría</th>
                        <th>Origen</th>
                        <th>Anterior</th>
                        <th>Nuevo</th>
                        <th>Δ</th>
                        <th>Fecha</th>
                        <th>Estado</th>
                    </tr>
                </thead>
                <tbody>
                    <tr t-if="data.rows.length === 0">
                        <td colspan="9" class="ppcm-empty">Sin cambios para los filtros seleccionados.</td>
                    </tr>
                    <tr t-foreach="data.rows" t-as="row" t-key="row.id"
                        t-att-class="row.state === 'done' ? 'ppcm-done' : ''">
                        <td>
                            <input type="checkbox" t-att-checked="isSelected(row.id)"
                                   t-on-change="() => this.toggleRow(row.id)"/>
                        </td>
                        <td>
                            <a href="#" t-on-click.prevent="() => this.openProduct(row.product_tmpl_id)">
                                <t t-esc="row.product"/>
                            </a>
                        </td>
                        <td><t t-esc="row.category"/></td>
                        <td><t t-esc="row.source"/></td>
                        <td class="ppcm-num"><t t-esc="row.old_price"/></td>
                        <td class="ppcm-num"><t t-esc="row.new_price"/></td>
                        <td t-att-class="'ppcm-num ' + (row.diff_amount >= 0 ? 'ppcm-up' : 'ppcm-down')">
                            <t t-esc="row.diff_amount"/>
                        </td>
                        <td><t t-esc="row.date"/></td>
                        <td>
                            <t t-if="row.state === 'done'">Actualizado</t>
                            <t t-else="">Pendiente</t>
                        </td>
                    </tr>
                </tbody>
            </table>

            <div class="ppcm-pager">
                <button t-on-click="() => this.goToPage(data.page - 1)" t-att-disabled="data.page &lt;= 1">◀</button>
                <span><t t-esc="data.page"/> / <t t-esc="data.pages"/> (<t t-esc="data.total"/>)</span>
                <button t-on-click="() => this.goToPage(data.page + 1)" t-att-disabled="data.page >= data.pages">▶</button>
            </div>
        </div>
    </t>
</templates>
```

- [ ] **Step 3: Crear `static/src/css/dashboard.css`**

```css
.ppcm-wrap { padding: 16px; font-size: 14px; }
.ppcm-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.ppcm-header h2 { margin: 0; }
.ppcm-pending { font-weight: 600; background: #fff3cd; color: #664d03; padding: 6px 12px; border-radius: 6px; }
.ppcm-filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.ppcm-filters select, .ppcm-filters input { padding: 6px 8px; border: 1px solid #ced4da; border-radius: 4px; }
.ppcm-actions { margin-bottom: 12px; display: flex; gap: 8px; }
.ppcm-table { width: 100%; border-collapse: collapse; }
.ppcm-table th, .ppcm-table td { padding: 8px 10px; border-bottom: 1px solid #e9ecef; text-align: left; }
.ppcm-table th { background: #f8f9fa; }
.ppcm-num { text-align: right; font-variant-numeric: tabular-nums; }
.ppcm-up { color: #198754; }
.ppcm-down { color: #dc3545; }
.ppcm-done { opacity: 0.55; }
.ppcm-empty { text-align: center; color: #6c757d; padding: 24px; }
.ppcm-pager { margin-top: 12px; display: flex; gap: 12px; align-items: center; }
.ppcm-pager button { padding: 4px 10px; }
```

- [ ] **Step 4: Completar `views/menu_views.xml` (acción cliente + menú)**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_price_change_dashboard" model="ir.actions.client">
        <field name="name">Cambios de Precio</field>
        <field name="tag">product_price_change_metrics.dashboard</field>
    </record>

    <menuitem id="menu_price_change_root"
              name="Cambios de Precio"
              action="action_price_change_dashboard"
              groups="product_price_change_metrics.group_price_change_metrics_user"
              web_icon="product_price_change_metrics,static/description/icon.png"
              sequence="52"/>
</odoo>
```

- [ ] **Step 5: Validar sintaxis XML**

Run: `python3 -c "import xml.dom.minidom as m; m.parse('product_price_change_metrics/static/src/xml/dashboard.xml'); m.parse('product_price_change_metrics/views/menu_views.xml'); print('XML OK')"`
Expected: `XML OK`

- [ ] **Step 6: Actualizar el módulo**

Run: `sudo docker exec odoo-odoo-1 odoo -u product_price_change_metrics -d prod --stop-after-init`
Expected: sin traceback.

- [ ] **Step 7: Verificación manual en el navegador**

1. Agregar el usuario propio al grupo "Acceso a Cambios de Precio (Góndola)" (Ajustes → Usuarios).
2. Recargar Odoo; abrir el menú **Cambios de Precio**.
3. Cambiar el `list_price` de un producto (Inventario → producto → guardar) y verificar que aparece una fila en el dashboard (filtro "Mi empresa" / "Pendientes").
4. Click en el nombre del producto → abre el formulario del producto.
5. Seleccionar la fila y "Marcar seleccionados como actualizados" → la fila pasa a Actualizado (o desaparece del filtro Pendientes).

Expected: los 5 pasos funcionan sin errores en consola.

- [ ] **Step 8: Commit**

```bash
git add product_price_change_metrics/static/ product_price_change_metrics/views/menu_views.xml
git commit -m "feat(price-change): add OWL dashboard, shelf checklist and app menu"
```

---

### Task 7: Icono del módulo (Cyber-Glassmorphic)

**Files:**
- Create: `product_price_change_metrics/static/description/icon.png`
- Create (temporal): `/tmp/ppcm_icon.svg`

**Interfaces:**
- Consumes: plantilla `~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg`.
- Produces: `icon.png` 512×512 usado por el `web_icon` del menú.

- [ ] **Step 1: Copiar la plantilla y re-skinear el glifo**

```bash
cp ~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg /tmp/ppcm_icon.svg
```
Editar `/tmp/ppcm_icon.svg`: cambiar el `<text>` GLYPH a la inicial del módulo (ej. `$` o `P`). Mantener los acentos cian `#22e6ff` / magenta `#ff3df0` (o ajustarlos).

- [ ] **Step 2: Renderizar a PNG con headless Chrome**

```bash
mkdir -p product_price_change_metrics/static/description
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="$PWD/product_price_change_metrics/static/description/icon.png" \
  "file:///tmp/ppcm_icon.svg"
```
Expected: se crea `icon.png`. Verificar: `python3 -c "from pathlib import Path; print(Path('product_price_change_metrics/static/description/icon.png').stat().st_size, 'bytes')"` → > 0.

> No usar ImageMagick (`convert`/`magick`): descarta `<text>` y gradientes radiales.

- [ ] **Step 3: Recargar el módulo para tomar el icono**

Run: `sudo docker exec odoo-odoo-1 odoo -u product_price_change_metrics -d prod --stop-after-init`
Expected: sin traceback; el menú muestra el icono en la lista de apps.

- [ ] **Step 4: Commit**

```bash
git add product_price_change_metrics/static/description/icon.png
git commit -m "feat(price-change): add module icon"
```

---

## Self-Review — cobertura del spec

- **Objetivo (lista operativa de góndola):** Tasks 5–6 (controller + dashboard con checklist). ✓
- **Trackea precio global (`list_price`):** Task 3. ✓
- **Trackea precios de lista (`product.pricelist.item`):** Task 4. ✓
- **Fan-out por empresa (global) / empresa dueña (lista):** Task 2 (`_log_change`) + Tasks 3–4. ✓
- **Modelo `product.price.log` con campos y estado de góndola:** Task 2. ✓
- **Checklist pendiente/actualizado con usuario+fecha por sucursal:** Task 2 (campos) + Task 5 (`mark_done`) + Task 6 (UI). ✓
- **Click en producto → formulario (Inventario):** Task 6 (`openProduct` / `doAction`). ✓
- **Cambios crudos (sin cruce de precio efectivo):** Tasks 3–4 no cruzan orígenes. ✓
- **Seguridad: grupo + record rule multi-compañía + acceso solo lectura + sudo en mark_done:** Task 2 (grupo/rule/csv) + Task 5 (sudo). ✓
- **Sin gráficos / contador de pendientes:** Task 6 (`ppcm-pending`, sin Chart.js). ✓
- **Robustez (no abortar guardado):** Tasks 3–4 (`try/except` + `super()` siempre). ✓
- **Guard de instalación (evitar ruido en cargas masivas):** Tasks 3–4 (`context.get("install_mode")`). ✓
- **Icono:** Task 7. ✓

Sin placeholders TBD/TODO; los nombres de método (`_log_change`, `_ppcm_log_global_change`, `_ppcm_log_item_change`, `_ppcm_price_snapshot`, `get_changes`, `mark_done`, `openProduct`) son consistentes entre tasks.
