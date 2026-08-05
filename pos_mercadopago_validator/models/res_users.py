from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    mp_visible_account_ids = fields.Json(
        string="Cuentas de Mercado Pago visibles",
        compute="_compute_mp_visible_account_ids",
        compute_sudo=True,
        help="Ids de las cuentas de las cajas a las que este usuario tiene "
             "acceso. La regla de registro de la bandeja se apoya en esto.",
    )

    def _compute_mp_visible_account_ids(self):
        """Cuentas de Mercado Pago de las cajas a las que llega este usuario.

        Existe para la `ir.rule` de `mercadopago.payment`: el cajero tiene
        `perm_read` sobre la bandeja porque el diálogo del POS la consulta, y
        sin regla de registro un `search_read` directo le devuelve los
        movimientos de dinero de todas las cajas y todas las cuentas. No puede
        imputar nada ajeno -eso lo cierra `_find_inbox_line()`- pero verlo ya
        es de más.

        "Sus cajas" son las `pos.config` que el usuario puede leer: ahí ya
        actúan la regla multiempresa y los grupos de acceso del POS, así que
        heredamos ese criterio en vez de inventar uno paralelo que después
        divergiría. De esas configs se toman los métodos de pago de este
        módulo, y de ahí las cuentas.

        Se resuelve con `with_user()` a propósito: la pregunta es qué ve *ese*
        usuario, no qué ve quien está computando.

        **Es una lista de ids (Json), no un Many2many**, y no es un detalle: la
        lectura de un campo relacional x2many filtra los registros archivados,
        y `mercadopago.account` nace con `active = False` hasta que se validan
        las credenciales. Con un Many2many, una cuenta archivada desaparecía de
        la lista y la regla escondía sus pagos incluso para las cajas que la
        usan -y sus pagos huérfanos son justamente los que hay que poder ver-.
        Una lista de ids no tiene esa semántica: dice exactamente lo que se le
        puso.
        """
        Config = self.env["pos.config"]
        for user in self:
            config_ids = Config.with_user(user).search([]).ids
            methods = Config.sudo().browse(config_ids).payment_method_ids
            mp_methods = methods.filtered(
                lambda m: m.use_payment_terminal == "mercadopago_validator"
            )
            user.mp_visible_account_ids = mp_methods.mp_account_id.ids
