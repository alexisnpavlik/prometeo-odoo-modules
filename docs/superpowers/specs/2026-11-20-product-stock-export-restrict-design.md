# product_stock_export_restrict — diseño

## Intención

Que los usuarios no tengan a mano la exportación de productos ni de stock a archivo.
El resto de las exportaciones (clientes, ventas, facturas) no se tocan.

## Objetivos

- Ocultar "Exportar" (menú de acciones) y "Exportar todo" en listas de los modelos cubiertos.
- Ocultar "Descargar xlsx" del pivote en esos modelos.
- Ocultar el botón Excel del dashboard de `inventory_dashboard_metrics`.
- Usuarios del grupo nuevo "Puede exportar productos/stock" ven todo como siempre.

## No objetivos

- Bloqueo en servidor (`/web/export`, `export_data`, rutas xlsx del dashboard): quien llame la URL a mano igual exporta. Decisión explícita de Alexis (opción B).
- Copiar/pegar, impresión de reportes, capturas.
- Exportaciones de otros modelos.

## Approaches considerados

- **A. Servidor + UI**: override de `export_data` + checks en rutas xlsx + ocultar botones. Seguro de verdad, ~3–4 h.
- **B. Solo UI** (elegida): patches OWL que ocultan botones. ~1 h. Barrera de conveniencia, no de seguridad.
- **Grupo nativo `base.group_allow_export`**: descartado, es todo-o-nada para todos los modelos.

## Diseño

- **Grupo** `product_stock_export_restrict.group_product_stock_export`, implicado por `base.group_system`.
- **Modelos cubiertos** (lista en JS): `product.template`, `product.product`, `stock.quant`,
  `stock.move`, `stock.move.line`, `product.supplierinfo`.
- **Patch `ListController`**: si `resModel` está en la lista y el usuario no tiene el grupo → `isExportEnable = false`.
- **Patch pivote**: ocultar el botón de descarga xlsx con la misma condición.
- **Dashboard de inventario**: `inventory_dashboard_metrics` oculta su botón Excel si el usuario no tiene el grupo.
  Chequeo por xmlid para no forzar dependencia dura (si el módulo de restricción no está instalado, el botón se ve).

## Para el builder

- Nombre exacto de los hooks OWL en Odoo 18 (`isExportEnable`, botón del pivote).
- Prueba manual en la base `pruebas` con un usuario sin el grupo y otro con el grupo.
