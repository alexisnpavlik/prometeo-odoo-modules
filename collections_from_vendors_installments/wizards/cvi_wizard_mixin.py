# -*- coding: utf-8 -*-
from odoo import models


class CviWizardMixin(models.AbstractModel):
    _name = "cvi.wizard.mixin"
    _description = "Utilidades compartidas por los asistentes del módulo"

    def _cvi_group_domain(self, group_name):
        """Dominio que restringe un campo de usuarios a los de un grupo del módulo.

        Si el xmlid del grupo no resuelve (base a medio actualizar), devuelve un dominio
        vacío en vez de romper el formulario con un ValueError.
        """
        group = self.env.ref(
            "collections_from_vendors_installments.%s" % group_name,
            raise_if_not_found=False,
        )
        return [("groups_id", "in", group.id)] if group else []
