# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CviCommon(TransactionCase):
    """Fixtures compartidos por todos los tests del módulo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        # En DBs compartidas (p.ej. `calidad`) main_company puede estar archivada por
        # datos ajenos al módulo. Si está inactiva, el company_ids de un res.users nuevo
        # no la reconoce como empresa permitida y rompe la creación de usuarios de test.
        # Se reactiva dentro de la transacción; el rollback lo revierte.
        cls.company.sudo().active = True
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.groups_id = [
            (4, cls.env.ref("collections_from_vendors_installments.group_cvi_manager").id)
        ]
        cls.partner = cls.env["res.partner"].create({
            "name": "Cliente CVI Test",
            "vat": "20111111112",
            "company_id": False,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Ropero 3 puertas",
            "type": "consu",
            "is_storable": True,
            # Precio de contado, informativo: el módulo no lo usa para nada. Los planes
            # de cuotas llevan su propio importe, con el interés ya incluido.
            "list_price": 95000.0,
        })
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.vendor_user = cls.env["res.users"].create({
            "name": "Vendedor Test",
            "login": "cvi_vendor_test",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                cls.env.ref("base.group_user").id,
            ])],
        })
        cls.collector_user = cls.env["res.users"].create({
            "name": "Cobrador Test",
            "login": "cvi_collector_test",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                cls.env.ref("base.group_user").id,
            ])],
        })
