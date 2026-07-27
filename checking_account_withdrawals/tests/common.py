# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CawCommon(TransactionCase):
    """Fixtures compartidos por todos los tests del módulo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.env.user.company_ids = [(4, cls.company.id)]
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
