# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CcaCommon(TransactionCase):
    """Fixtures compartidos por los tests del módulo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        # main_company puede estar archivada en bases compartidas; se reactiva dentro
        # de la transacción del test (se revierte sola).
        cls.company.sudo().active = True
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.groups_id = [(4, cls.env.ref("customer_checking_account.group_cca_user").id)]
        cls.partner = cls.env["res.partner"].create({
            "name": "Cliente CCA Test",
            "vat": "30111222",
            "company_id": False,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Producto CCA Test",
            "type": "consu",
            "is_storable": True,
            "list_price": 100.0,
        })
        # is_storable puede venir True en servicios según la base: se fuerza False.
        cls.service = cls.env["product.product"].create({
            "name": "Servicio CCA Test",
            "type": "service",
            "is_storable": False,
            "list_price": 50.0,
        })
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
