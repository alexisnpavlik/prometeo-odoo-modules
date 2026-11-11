import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .params import get_param

SEVERITIES = [("low", "Baja"), ("medium", "Media"), ("high", "Alta")]


class PrometeoAiAlert(models.Model):
    _name = "prometeo.ai.alert"
    _description = "Alerta del agente IA"
    _inherit = ["mail.thread"]
    _order = "state_sequence, severity_sequence, last_seen desc, id desc"

    name = fields.Char("Título", required=True)
    summary = fields.Text("Resumen")
    severity = fields.Selection(SEVERITIES, "Gravedad", required=True, default="medium")
    severity_sequence = fields.Integer(compute="_compute_sequences", store=True)
    kind = fields.Selection([("routine", "Rutina"), ("system", "Sistema")], "Tipo", required=True, default="routine")
    routine_id = fields.Many2one("prometeo.ai.routine", "Rutina", ondelete="cascade", index=True)
    recipient_ids = fields.Many2many("res.users", "prometeo_ai_alert_recipient_rel", "alert_id", "user_id",
                                     "Destinatarios")
    res_model = fields.Char("Modelo de los registros")
    res_ids = fields.Json("Ids de los registros")
    res_domain = fields.Char("Dominio de los registros")
    record_count = fields.Integer("Registros", compute="_compute_record_count")
    dedup_key = fields.Char("Clave", required=True, index=True)
    state = fields.Selection([("new", "Abierta"), ("resolved", "Resuelta"), ("dismissed", "Descartada")],
                             "Estado", required=True, default="new", index=True)
    state_sequence = fields.Integer(compute="_compute_sequences", store=True)
    first_seen = fields.Datetime("Detectada", default=fields.Datetime.now, required=True)
    last_seen = fields.Datetime("Última detección", default=fields.Datetime.now, required=True)
    seen_by_ids = fields.Many2many("res.users", "prometeo_ai_alert_seen_rel", "alert_id", "user_id", "Vista por")
    silenced_until = fields.Datetime("Silenciada hasta")
    resolved_note = fields.Text("Motivo de cierre")

    @api.depends("severity", "state")
    def _compute_sequences(self):
        """Orden de la bandeja: abiertas primero, alta gravedad primero."""
        for rec in self:
            rec.severity_sequence = {"high": 0, "medium": 1, "low": 2}.get(rec.severity, 3)
            rec.state_sequence = 0 if rec.state == "new" else 1

    def _compute_record_count(self):
        """Cantidad de registros citados (ids) o 0 si se respalda por dominio."""
        for rec in self:
            rec.record_count = len(rec.res_ids or [])

    # ------------------------------------------------------------------ creación

    @api.model
    def _upsert(self, routine, recipients, vals):
        """Crea o actualiza la alerta abierta (rutina, clave). Respeta el silencio de las descartadas."""
        Alert = self.sudo()
        now = fields.Datetime.now()
        key = vals["dedup_key"]
        routine_id = routine.id if routine else False
        alert = Alert.search([("routine_id", "=", routine_id), ("dedup_key", "=", key), ("state", "=", "new")],
                             limit=1)
        if alert:
            was_high = alert.severity == "high"
            alert.write(dict(vals, last_seen=now))
            if alert.severity == "high" and not was_high:
                alert._notify_high()
            return alert, "updated"
        silenced = Alert.search([("routine_id", "=", routine_id), ("dedup_key", "=", key),
                                 ("state", "=", "dismissed"), ("silenced_until", ">", now)], limit=1)
        if silenced:
            return silenced, "silenced"
        alert = Alert.create(dict(vals, routine_id=routine_id, recipient_ids=[(6, 0, recipients.ids)],
                                  kind="routine" if routine else "system", first_seen=now, last_seen=now))
        if alert.severity == "high":
            alert._notify_high()
        return alert, "created"

    @api.model
    def _create_system_alert(self, key, title, summary, severity="medium"):
        """Alerta de sistema para los administradores del agente, deduplicada por clave."""
        admins = self.env.ref("prometeo_ai_agent.group_admin").sudo().users.filtered(lambda u: not u.share)
        alert, _status = self._upsert(self.env["prometeo.ai.routine"], admins, {
            "dedup_key": key, "name": title, "summary": summary, "severity": severity})
        return alert

    def _notify_high(self):
        """Notificación de Odoo a los destinatarios (bandeja de Conversaciones o correo según su preferencia)."""
        for alert in self.sudo():
            partners = alert.recipient_ids.partner_id
            if partners:
                alert.message_notify(
                    partner_ids=partners.ids,
                    subject=_("Alerta: %s", alert.name),
                    body=alert.summary or alert.name,
                )

    # ------------------------------------------------------------------ acciones

    def _check_recipient(self):
        """Solo un destinatario o un administrador del agente opera sobre la alerta."""
        user = self.env.user
        if user.has_group("prometeo_ai_agent.group_admin"):
            return
        for alert in self.sudo():
            if user not in alert.recipient_ids:
                raise AccessError(_("No sos destinatario de la alerta %s.", alert.name))

    def action_mark_seen(self):
        """Marca la alerta como vista por el usuario actual."""
        self._check_recipient()
        self.sudo().write({"seen_by_ids": [(4, self.env.uid)]})
        return True

    def action_resolve(self):
        """Cierra la alerta. Si el problema reaparece, la rutina crea una nueva."""
        self._check_recipient()
        self.sudo().write({"state": "resolved"})
        return True

    def action_dismiss(self):
        """Descarta la alerta y silencia su clave por los días configurados."""
        self._check_recipient()
        days = get_param(self.env, "dismiss_silence_days")
        self.sudo().write({"state": "dismissed",
                           "silenced_until": fields.Datetime.now() + timedelta(days=days)})
        return True

    def action_reopen(self):
        """Vuelve a abrir una alerta resuelta o descartada."""
        self._check_recipient()
        self.sudo().write({"state": "new", "silenced_until": False})
        return True

    def action_view_records(self):
        """Abre los registros que respaldan la alerta."""
        self.ensure_one()
        self._check_recipient()
        alert = self.sudo()
        if not alert.res_model or alert.res_model not in self.env:
            raise UserError(_("Esta alerta no tiene registros asociados."))
        if alert.res_ids:
            domain = [("id", "in", alert.res_ids)]
        elif alert.res_domain:
            domain = json.loads(alert.res_domain)
        else:
            raise UserError(_("Esta alerta no tiene registros asociados."))
        return {"type": "ir.actions.act_window", "name": alert.name, "res_model": alert.res_model,
                "domain": domain, "view_mode": "list,form", "views": [(False, "list"), (False, "form")],
                "target": "current"}

    def web_read(self, specification):
        """Abrir una alerta en el formulario la marca como vista."""
        if len(self) == 1 and self.state == "new" and self.env.uid not in self.seen_by_ids.ids:
            try:
                self.action_mark_seen()
            except AccessError:
                pass
        return super().web_read(specification)

    @api.model
    def systray_count(self):
        """Alertas abiertas del usuario que todavía no vio."""
        return self.search_count([("state", "=", "new"), ("recipient_ids", "in", self.env.uid),
                                  ("seen_by_ids", "not in", self.env.uid)])
