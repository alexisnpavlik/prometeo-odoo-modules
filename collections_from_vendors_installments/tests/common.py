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
        cls.customer = cls.env["cvi.customer"].create({
            "name": "Cliente CVI Test",
            "dni": "20111111",
            "company_id": cls.company.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Ropero 3 puertas",
            "type": "consu",
            "is_storable": True,
            # Precio de contado, informativo: el módulo no lo usa para nada. Los planes
            # de cuotas llevan su propio importe, con el interés ya incluido.
            "list_price": 95000.0,
        })
        cls.plan_12 = cls.env["cvi.product.plan"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "name": "12 cuotas",
            "installment_count": 12,
            "installment_amount": 10000.0,
            "frequency": "monthly",
        })
        cls.plan_3 = cls.env["cvi.product.plan"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "name": "3 cuotas",
            "installment_count": 3,
            "installment_amount": 10000.0,
            "frequency": "monthly",
        })
        cls.plan_weekly = cls.env["cvi.product.plan"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "name": "4 semanas",
            "installment_count": 4,
            "installment_amount": 5000.0,
            "frequency": "weekly",
        })
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.vendor_user = cls.env["res.users"].create({
            "name": "Vendedor Test",
            "login": "cvi_vendor_test",
            "email": "vendor@test.local",
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
            "email": "collector@test.local",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                cls.env.ref("base.group_user").id,
            ])],
        })
        cls.vendor_location = cls.vendor_user._cvi_get_location()
        cls.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": cls.product.id,
            "location_id": cls.vendor_location.id,
            "inventory_quantity": 500,
        }).action_apply_inventory()
