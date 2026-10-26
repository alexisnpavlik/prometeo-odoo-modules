from odoo.tests.common import TransactionCase, new_test_user


class BranchTransferCommon(TransactionCase):
    """Fixtures compartidos: tres sucursales, un producto global y usuarios por rol."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env["res.company"]
        cls.company_a = Company.create({"name": "SBT Sucursal A"})
        cls.company_b = Company.create({"name": "SBT Sucursal B"})
        cls.company_c = Company.create({"name": "SBT Sucursal C"})
        cls.product = cls.env["product.product"].create({
            "name": "Producto SBT",
            "type": "consu",
            "is_storable": True,
            "company_id": False,
        })
        cls.product2 = cls.env["product.product"].create({
            "name": "Producto SBT 2",
            "type": "consu",
            "is_storable": True,
            "company_id": False,
        })
        cls.user_a = cls._make_user("sbt_user_a", cls.company_a)
        cls.user_b = cls._make_user("sbt_user_b", cls.company_b)
        cls.user_c = cls._make_user("sbt_user_c", cls.company_c)
        cls.manager = cls._make_user(
            "sbt_manager",
            cls.company_a,
            cls.company_a | cls.company_b | cls.company_c,
            "base.group_user,stock_branch_transfer.group_branch_transfer_manager",
        )
        cls.transit = cls.env.ref("stock_branch_transfer.location_branch_transit")

    @classmethod
    def _make_user(cls, login, company, companies=None, groups="base.group_user"):
        """Crea un usuario interno con acceso a las empresas indicadas."""
        return new_test_user(
            cls.env,
            login=login,
            groups=groups,
            company_id=company.id,
            company_ids=[(6, 0, (companies or company).ids)],
        )

    def stock_location(self, company):
        """Ubicación de stock del almacén de la empresa."""
        return self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1
        ).lot_stock_id

    def qty(self, product, company):
        """Cantidad del producto en el stock de la empresa."""
        return self._qty_at(product, self.stock_location(company))

    def transit_qty(self, product):
        """Cantidad del producto en la ubicación de tránsito."""
        return self._qty_at(product, self.transit)

    def _qty_at(self, product, location):
        quants = self.env["stock.quant"].sudo().search(
            [("product_id", "=", product.id), ("location_id", "=", location.id)]
        )
        return sum(quants.mapped("quantity"))

    def set_stock(self, product, company, qty):
        """Fija stock inicial en la empresa."""
        self.env["stock.quant"].sudo()._update_available_quantity(
            product, self.stock_location(company), qty
        )

    def make_transfer(self, user, qty=10.0, dest=None, product=None):
        """Crea un traslado en borrador desde la empresa del usuario."""
        Transfer = self.env["stock.branch.transfer"].with_user(user).with_company(user.company_id)
        return Transfer.create({
            "dest_company_id": (dest or self.company_b).id,
            "line_ids": [(0, 0, {
                "product_id": (product or self.product).id,
                "qty_sent": qty,
            })],
        })
