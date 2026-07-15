import logging

from odoo import _, models

_logger = logging.getLogger(__name__)

# Campos de imagen (binary) a registrar. El tracking nativo no soporta binary,
# asi que en vez de "viejo -> nuevo" se postea una nota de actualizada/eliminada.
_IMAGE_FIELDS = {"image_1920"}

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
        image_fields = [f for f in vals if f in _IMAGE_FIELDS]
        initial_values = {}
        old_images = {}
        if candidates:
            for record in self:
                initial_values[record.id] = {
                    fname: record[fname] for fname in candidates
                }
        if image_fields:
            for record in self:
                old_images[record.id] = {f: record[f] for f in image_fields}

        res = super().write(vals)

        if candidates:
            try:
                self._message_track(candidates, initial_values)
            except Exception as e:
                # El historial nunca debe abortar el guardado del producto.
                _logger.warning(
                    "product_change_history: fallo al registrar cambios en %s: %s",
                    self, e,
                )

        if image_fields:
            self._pch_log_image_changes(image_fields, old_images)

        return res

    def _pch_log_image_changes(self, image_fields, old_images):
        """Postea una nota cuando cambia una imagen (campo binary sin tracking)."""
        for record in self:
            olds = old_images.get(record.id, {})
            for fname in image_fields:
                try:
                    new_val = record[fname]
                    if new_val == olds.get(fname):
                        continue
                    body = (
                        _("Imagen del producto actualizada")
                        if new_val
                        else _("Imagen del producto eliminada")
                    )
                    record.message_post(body=body)
                except Exception as e:
                    _logger.warning(
                        "product_change_history: fallo al registrar imagen de %s: %s",
                        record, e,
                    )
