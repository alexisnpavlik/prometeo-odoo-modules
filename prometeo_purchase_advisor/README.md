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
| 4 | Clasificación ABC/XYZ, exclusiones, filtros | hecha |
| 5 | Explicabilidad, advertencias, crons | hecha |
| 6 | Validación de extensibilidad con un estimador en módulo satélite | pendiente |

El circuito completo funciona. Falta solamente la fase 6, que no agrega
funcionalidad: implementa un segundo estimador en un módulo satélite para
verificar que se puede extender sin tocar el core.

## Cómo se usa

1. *Recomendador → Sugerencias de compra*, crear una, elegir el almacén.
2. **Calcular**. Cada línea explica en castellano por qué sugiere esa cantidad;
   el botón de expandir la fila muestra el detalle completo.
3. Editar cantidades, agregar o quitar productos. Un recálculo posterior
   respeta lo que se editó a mano.
4. **Confirmar** y **Crear órdenes de compra**: quedan en borrador, agrupadas
   por proveedor.

La pestaña *Calidad del cálculo* muestra la tasa de edición: si supera el 50%,
el modelo está mal calibrado para el negocio y conviene revisar los días de
cobertura y el nivel de servicio.

## Automatización

Tres crons, configurables en *Ajustes técnicos*:

- **Clasificar ABC/XYZ** (semanal, activo): valor de consumo de los últimos 180
  días y variabilidad de la demanda.
- **Medir proveedores** (semanal, activo): plazo real y nivel de cumplimiento
  del último año.
- **Generar sugerencias** (semanal, **inactivo** por defecto): crea y calcula
  una sugerencia por cada almacén con *Sugerencia automática* tildada, y le
  deja una actividad al responsable.

El spec completo está en
`docs/superpowers/specs/2026-09-08-prometeo-purchase-advisor-design.md`.

## Grupos

- **Operador de compras** — crea y edita sugerencias, genera las órdenes.
- **Manager de compras** — además configura modelos de demanda y reglas.
