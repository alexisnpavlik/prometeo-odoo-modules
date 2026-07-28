# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CawCommon(TransactionCase):
    """Fixtures compartidos por todos los tests del módulo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.env.user.company_ids = [(4, cls.company.id)]
        # Los tests ejercitan por defecto acciones Manager-only (cancelar, reabrir, anular
        # pagos). `has_group` no bypassea aunque el env corra con el usuario del sistema,
        # así que se lo suma explícitamente; los tests del hallazgo 8 usan un usuario aparte
        # (solo group_cc_user) para probar el bloqueo.
        cls.env.user.groups_id = [
            (4, cls.env.ref("checking_account_withdrawals.group_cc_manager").id)
        ]
        cls.partner = cls.env["res.partner"].create({
            "name": "Fiado Test",
            "company_id": False,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Producto CC Test",
            "type": "consu",
            "is_storable": True,
            "list_price": 100.0,
        })
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
