import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Campos magicos / tecnicos que nunca se registran en el historial.
_MAGIC_FIELDS = {
    "id",
    "create_uid",
    "create_date",
    "write_uid",
    "write_date",
    "display_name",
    "__last_update",
}

# Tipos de campo que el tracking nativo (_mail_track) sabe representar.
# Otros (html, binary, json, ...) lanzan NotImplementedError, por eso se saltean.
_TRACKABLE_TYPES = {
    "integer",
    "float",
    "monetary",
    "char",
    "text",
    "date",
    "datetime",
    "boolean",
    "selection",
    "many2one",
    "many2many",
    "one2many",
}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _pch_candidate_fields(self, vals):
        """Campos de `vals` a registrar en el historial.

        Se descartan los campos magicos, los computados puros (compute sin
        inverse) y los que ya tienen tracking nativo (Odoo los registra solo,
        para no duplicar la nota en el chatter).
        """
        candidates = []
        for fname in vals:
            field = self._fields.get(fname)
            if field is None or fname in _MAGIC_FIELDS:
                continue
            if field.compute and not field.inverse:
                continue
            if getattr(field, "tracking", False):
                continue
            if field.type not in _TRACKABLE_TYPES:
                continue
            candidates.append(fname)
        return candidates

    def write(self, vals):
        """Registra en el chatter (formato nativo) todo campo editado.

        Captura los valores previos, delega al super y usa el mecanismo nativo
        `_message_track` para postear los `mail.tracking.value` con el mismo
        formato que el tracking de Odoo.
        """
        candidates = self._pch_candidate_fields(vals)
        initial_values = {}
        if candidates:
            for record in self:
                initial_values[record.id] = {
                    fname: record[fname] for fname in candidates
                }

        res = super().write(vals)

        if candidates:
            self._message_track(candidates, initial_values)

        return res
