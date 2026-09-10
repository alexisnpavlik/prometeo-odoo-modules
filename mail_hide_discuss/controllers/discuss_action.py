# -*- coding: utf-8 -*-

from odoo import _, http
from odoo.addons.web.controllers.action import Action
from odoo.exceptions import AccessError
from odoo.http import request


def is_discuss_action(action_id, discuss_action_id):
    """Indica si el identificador corresponde a la acción Conversaciones."""
    return str(action_id) in {
        "discuss",
        "mail.action_discuss",
        str(discuss_action_id),
    }


class DiscussBlockedAction(Action):
    """Bloquea la carga directa de la acción cliente Conversaciones."""

    @http.route()
    def load(self, action_id, context=None):
        """Rechaza Conversaciones y delega las demás acciones al controlador base."""
        discuss_action = request.env.ref(
            "mail.action_discuss", raise_if_not_found=False
        )
        if discuss_action and is_discuss_action(action_id, discuss_action.id):
            raise AccessError(_("El acceso a Conversaciones está deshabilitado."))
        return super().load(action_id, context=context)
