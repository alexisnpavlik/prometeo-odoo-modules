# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

import pytz

from odoo.tests.common import TransactionCase


class PurchaseAdvisorCommon(TransactionCase):
    """Fixtures compartidas: un almacén, dos proveedores y productos comprables."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.supplier_a = cls.env["res.partner"].create({"name": "Proveedor A"})
        cls.supplier_b = cls.env["res.partner"].create({"name": "Proveedor B"})
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")

        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")

        cls.product_a = cls._make_product("Producto A", cls.supplier_a, price=100.0)
        cls.product_b = cls._make_product("Producto B", cls.supplier_a, price=250.0)
        cls.product_c = cls._make_product("Producto C", cls.supplier_b, price=80.0)
        # Sin supplierinfo: el motor no lo toca, así que sirve para probar los
        # controles sobre líneas que el usuario carga a mano.
        cls.product_no_seller = cls.env["product.product"].create({
            "name": "Producto sin proveedor",
            "type": "consu", "is_storable": True, "purchase_ok": True,
        })

    @classmethod
    def _make_product(cls, name, supplier, price=100.0, uom_po=None):
        product = cls.env["product.product"].create({
            "name": name,
            "type": "consu",
            "is_storable": True,
            "purchase_ok": True,
            "uom_id": cls.uom_unit.id,
            "uom_po_id": (uom_po or cls.uom_unit).id,
            "standard_price": price * 0.7,
            "list_price": price,
        })
        cls.env["product.supplierinfo"].create({
            "partner_id": supplier.id,
            "product_tmpl_id": product.product_tmpl_id.id,
            "price": price,
            "delay": 10,
        })
        return product

    def _make_suggestion(self, lines=None, **kwargs):
        """Crea una sugerencia con líneas manuales listas para confirmar."""
        vals = {
            "warehouse_id": self.warehouse.id,
            "coverage_days": 30,
        }
        vals.update(kwargs)
        suggestion = self.env["prometeo.purchase.suggestion"].create(vals)
        for line_vals in lines or []:
            self.env["prometeo.purchase.suggestion.line"].create(
                dict(line_vals, suggestion_id=suggestion.id))
        return suggestion

    # ------------------------------------------------------------------
    # Datos sintéticos de movimientos
    # ------------------------------------------------------------------
    def _timezone(self):
        return self.env["prometeo.demand.series.builder"]._timezone()

    def _today(self):
        return self.env["prometeo.demand.series.builder"]._today(self._timezone())

    def _local_dt(self, day, hour=12):
        """Timestamp UTC del mediodía local de ese día.

        Al mediodía para que ninguna conversión de zona horaria lo corra de día
        y el test mida lo que dice medir.
        """
        tz = pytz.timezone(self._timezone())
        local = tz.localize(datetime.combine(day, time(hour, 0)))
        return local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _make_move(self, product, qty, day, outgoing=True, warehouse=None):
        """Movimiento ya hecho en una fecha concreta.

        Se escribe `state` y `date` a mano en vez de pasar por el flujo de
        albaranes: al motor solo le importa lo que quedó en la tabla, y armar
        90 días de pickings reales haría los tests inusables.
        """
        warehouse = warehouse or self.warehouse
        stock = warehouse.lot_stock_id
        if outgoing:
            src, dest = stock, self.customer_location
        else:
            src, dest = self.supplier_location, stock
        move = self.env["stock.move"].create({
            "name": product.name,
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "location_id": src.id,
            "location_dest_id": dest.id,
            "company_id": warehouse.company_id.id,
        })
        move.write({"state": "done", "date": self._local_dt(day)})
        return move

    def _make_return(self, product, qty, day):
        """Devolución de cliente: entra al almacén desde la ubicación de cliente."""
        move = self.env["stock.move"].create({
            "name": "Devolución %s" % product.name,
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "location_id": self.customer_location.id,
            "location_dest_id": self.warehouse.lot_stock_id.id,
            "company_id": self.company.id,
        })
        move.write({"state": "done", "date": self._local_dt(day)})
        return move

    def _sell_daily(self, product, qty, days_back_from, days_back_to):
        """Vende `qty` por día en el rango [days_back_from, days_back_to).

        Los índices son días hacia atrás desde hoy: 1 es ayer.
        """
        today = self._today()
        for offset in range(days_back_to, days_back_from):
            self._make_move(product, qty, today - timedelta(days=offset))

    def _build_series(self, model, products, lookback=None):
        """Serie de demanda cruda, sin pasar por una sugerencia."""
        builder = self.env["prometeo.demand.series.builder"]
        date_to = self._today()
        date_from = date_to - timedelta(days=lookback or model.lookback_days)
        return builder.build(self.warehouse, products.ids, date_from, date_to)

    def _make_model(self, **kwargs):
        vals = {
            "name": "Modelo de prueba",
            "method": "weighted_ma",
            "lookback_days": 90,
            "weight_config": "14:0.5,30:0.3,90:0.2",
            "outlier_percentile": 0.95,
            "min_history_days": 21,
        }
        vals.update(kwargs)
        return self.env["prometeo.demand.model"].create(vals)

    def _set_stock(self, product, qty, location=None):
        """Deja stock real en el almacén.

        Los movimientos sintéticos no crean quants, así que `qty_available`
        sigue en cero por más movimientos que se carguen.
        """
        location = location or self.warehouse.lot_stock_id
        self.env["stock.quant"]._update_available_quantity(product, location, qty)
        return product.with_context(warehouse_id=self.warehouse.id).qty_available
