# Prometeo - Recomendador de compra

Sugerencias de compra a partir de la demanda real observada.

## Qué hace

Lee los movimientos de stock hacia ubicaciones de cliente (`stock.move` en estado
`done`), estima la demanda diaria promedio de cada producto por almacén, y sugiere
cuánto comprar contemplando lead time medido del proveedor, stock actual,
mercadería en tránsito y variabilidad de la demanda.

La sugerencia nunca se ejecuta sola: el usuario la revisa, edita cantidades,
agrega o quita productos, y recién entonces genera órdenes de compra **en
borrador** agrupadas por proveedor.

## Por qué lee de `stock.move` y no de las líneas de venta

Es el único lugar donde queda registrada la salida física de mercadería sin
importar el canal. Una sola query cubre POS, ventas normales y entregas manuales,
y da la dimensión de almacén de forma natural.

## Estado de la implementación

| Fase | Alcance | Estado |
|---|---|---|
| 1 | Modelos, vistas, seguridad, generación de órdenes por proveedor | hecha |
| 2 | Motor de demanda: `DemandSeries` en SQL, corrección por quiebres, `weighted_ma` | hecha |
| 3 | Lead time medido, stock de seguridad, cantidad, packaging y `min_qty` | hecha |
| 4 | Clasificación ABC/XYZ, exclusiones, filtros | pendiente |
| 5 | Explicabilidad, advertencias, crons | pendiente |
| 6 | Validación de extensibilidad con un estimador en módulo satélite | pendiente |

`action_compute()` ya produce sugerencias reales. Falta la clasificación ABC/XYZ
que decide qué productos entran (hoy entran todos los que tengan proveedor) y
los crons que disparan la corrida sola.

El spec completo está en
`docs/superpowers/specs/2026-09-08-prometeo-purchase-advisor-design.md`.

## Grupos

- **Operador de compras** — crea y edita sugerencias, genera las órdenes.
- **Manager de compras** — además configura modelos de demanda y reglas.
