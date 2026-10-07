# -*- coding: utf-8 -*-

from odoo import _, http
from odoo.addons.web.controllers.action import Action
from odoo.exceptions import AccessError
from odoo.http import request

from ..models.simplify_options import is_option_active


def is_discuss_action(action_id, discuss_action_id):
    """Indica si el identificador corresponde a la acción Conversaciones."""
    return str(action_id) in {
        "discuss",
        "mail.action_discuss",
        str(discuss_action_id),
    }


class DiscussBlockedAction(Action):
    """Bloquea abrir Conversaciones por URL cuando la opción está activada."""

    @http.route()
    def load(self, action_id, context=None):
        """Rechaza Conversaciones (salvo admin en debug) y delega el resto al controlador base."""
        discuss_action = request.env.ref("mail.action_discuss", raise_if_not_found=False)
        if (
            discuss_action
            and is_discuss_action(action_id, discuss_action.id)
            and is_option_active(request.env, "hide_discuss")
            and not (request.session.debug and request.env.user.has_group("base.group_system"))
        ):
            raise AccessError(_("El acceso a Conversaciones está deshabilitado."))
        return super().load(action_id, context=context)
