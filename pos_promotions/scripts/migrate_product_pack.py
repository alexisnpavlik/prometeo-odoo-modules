# -*- coding: utf-8 -*-
"""Convierte los packs OCA (product_pack / pos_product_pack) en promociones de pos_promotions.

Se corre con odoo shell contra una base que tenga los dos módulos instalados:

    DRY_RUN=1 odoo shell -d <base> --no-http < pos_promotions/scripts/migrate_product_pack.py
    DRY_RUN=0 odoo shell -d <base> --no-http < pos_promotions/scripts/migrate_product_pack.py

Cada pack conserva su producto (nombre, código, código de barras, historial) y pasa a ser
una promoción de precio fijo = su precio de venta, automática, en su empresa (o en todas
las sucursales si no tiene). El tipo de inventario del producto no se toca: con
promociones se venden los componentes, no el pack.
Después de migrar se pueden desinstalar pos_product_pack y product_pack.

- Packs sin productos o con precio 1 o menos: no se migran (se listan).
- Packs activos con los mismos productos: queda activo el más nuevo, los otros se archivan.
- Packs con precio propio en alguna lista de sucursal: se migran con el precio de la ficha
  y se listan, porque la promoción tiene un solo precio fijo.
"""
import os

from odoo import Command
from odoo.exceptions import ValidationError

DRY_RUN = os.getenv("DRY_RUN", "1") != "0"


def migrate_product_packs(env):
    """Migra todos los packs OCA a promociones y devuelve un resumen."""
    Template = env["product.template"].with_context(active_test=False)
    companies = env["res.company"].search([])
    packs = Template.search([("pack_ok", "=", True)], order="active desc, create_date desc, id desc")
    summary = {"migrados": [], "archivados_por_duplicado": [], "sin_productos": [], "precio_invalido": [],
               "precio_por_sucursal": [], "errores": []}
    print(f"Packs OCA: {len(packs)} (DRY_RUN={DRY_RUN})")
    for template in packs:
        variant = template.product_variant_ids[:1]
        pack_lines = variant.pack_line_ids
        label = f"[{template.id}] {template.name}"
        if not pack_lines:
            summary["sin_productos"].append(label)
            continue
        if template.list_price <= 1:
            summary["precio_invalido"].append(label)
            continue
        branch_prices = env["product.pricelist.item"].search_count([
            "|", ("product_tmpl_id", "=", template.id), ("product_id", "=", variant.id),
            ("fixed_price", "!=", template.list_price),
        ])
        if branch_prices:
            summary["precio_por_sucursal"].append(label)
        quantities = {}
        for line in pack_lines:
            quantities[line.product_id.id] = quantities.get(line.product_id.id, 0) + int(round(line.quantity))
        vals = {
            "is_promotion_pack": True,
            "available_in_pos": True,
            "promotion_price_mode": "fixed",
            "promotion_company_ids": [Command.set((template.company_id or companies).ids)],
            "promotion_pack_line_ids": [Command.clear()] + [
                Command.create({"product_id": product_id, "quantity": qty}) for product_id, qty in quantities.items()
            ],
        }
        try:
            with env.cr.savepoint():
                template.write(vals)
                env.flush_all()
            summary["migrados"].append(label)
        except ValidationError as error:
            if template.active and "Ya existe" in str(error):
                try:
                    with env.cr.savepoint():
                        template.write(dict(vals, active=False))
                        env.flush_all()
                    summary["migrados"].append(label)
                    summary["archivados_por_duplicado"].append(f"{label} -> {str(error).splitlines()[0]}")
                    continue
                except Exception as retry_error:  # noqa: BLE001
                    error = retry_error
            summary["errores"].append(f"{label}: {str(error).splitlines()[0]}")
        except Exception as error:  # noqa: BLE001
            summary["errores"].append(f"{label}: {type(error).__name__}: {str(error).splitlines()[0]}")
    return summary


def main():
    """Corre la migración, imprime el resumen y confirma o descarta según DRY_RUN."""
    summary = migrate_product_packs(env)  # noqa: F821 (env lo pone odoo shell)
    for key, items in summary.items():
        print(f"{key}: {len(items)}")
        for item in items[:15] if key == "migrados" else items:
            print(f"   {item}")
    if DRY_RUN:
        env.cr.rollback()  # noqa: F821
        print("DRY_RUN: no se guardó nada")
    else:
        env.cr.commit()  # noqa: F821
        print("Migración guardada")


main()
