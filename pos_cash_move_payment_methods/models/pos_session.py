from odoo import _, fields, models
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = "pos.session"

    def try_cash_in_out(self, _type, amount, reason, extras):
        """Si extras trae un método no efectivo, registra el movimiento en su diario."""
        method_id = extras.get("payment_method_id")
        method = self.env["pos.payment.method"].browse(method_id) if method_id else None
        if not method or method.type == "cash":
            return super().try_cash_in_out(_type, amount, reason, extras)
        if not method.allow_cash_in_out or not method.journal_id:
            raise UserError(_("El método %s no permite ingresos/retiros.", method.name))
        sign = 1 if _type == "in" else -1
        self.env["account.bank.statement.line"].sudo().create([{
            "pos_move_session_id": session.id,
            "pos_move_payment_method_id": method.id,
            "journal_id": method.journal_id.id,
            "amount": sign * amount,
            "date": fields.Date.context_today(self),
            "payment_ref": "-".join([session.name, method.name, extras["translatedType"], reason]),
        } for session in self])

    def get_closing_control_data(self):
        """Suma los ingresos/retiros de cada método no efectivo a su esperado y los lista."""
        data = super().get_closing_control_data()
        lines = self.env["account.bank.statement.line"].sudo().search(
            [("pos_move_session_id", "=", self.id)], order="create_date"
        )
        for pm in data["non_cash_payment_methods"]:
            pm_lines = lines.filtered(lambda line: line.pos_move_payment_method_id.id == pm["id"])
            pm["amount"] += sum(pm_lines.mapped("amount"))
            pm["moves_total"] = sum(pm_lines.mapped("amount"))
            pm["moves"] = [
                {"id": line.id, "name": line.payment_ref, "amount": line.amount} for line in pm_lines
            ]
            # El popup solo muestra Contado/Diferencia si number != 0: contar también los movimientos.
            pm["number"] += len(pm_lines)
        return data
