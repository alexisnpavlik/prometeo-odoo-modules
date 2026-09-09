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
| 6 | Validación de extensibilidad con un estimador en módulo satélite | hecha |

Las seis fases están implementadas. El módulo satélite
[`prometeo_purchase_advisor_ewma`](../prometeo_purchase_advisor_ewma/README.md)
agrega un segundo método de estimación sin modificar una línea de este módulo:
el core no menciona `ewma` en ningún lado.

## Cómo se usa

1. *Recomendador → Sugerencias de compra*, crear una y elegir el **almacén receptor**.
   Para comprar directamente en una sucursal, usar **Compra directa al almacén**.
   Para comprar en el central, usar **Compra centralizada para sucursales** y
   **Detectar sucursales por movimientos**. La detección considera despachos
   hechos en los últimos 180 días, dentro de las compañías habilitadas; revisar
   la selección según lo que abastecerá esta compra.
2. **Calcular**. Cada línea explica en castellano por qué sugiere esa cantidad;
   el botón de expandir la fila muestra el detalle completo.
3. Editar cantidades, agregar o quitar productos. Un recálculo posterior
   respeta lo que se editó a mano.
4. **Confirmar** y **Crear órdenes de compra**: quedan en borrador, agrupadas
   por proveedor.

### Cómo calcula una compra centralizada

Cada sucursal usa su propia demanda, disponibilidad histórica, stock y entradas
confirmadas. Se suman sus faltantes positivos; el exceso de una sucursal no se
supone disponible para otra. El central cubre esos faltantes con su disponibilidad
libre y se compra la diferencia. Los mínimos y bultos se aplican una sola vez.

Los traslados entre compañías no cuentan como ventas a clientes, incluso cuando
su destino técnico es una ubicación de cliente. Las recepciones pendientes de
las sucursales descuentan necesidades tanto si provienen de una compra directa
como del central. Los despachos preparados sin recepción contraparte se acreditan
al destino identificado, evitando duplicar compras antes de validar el traslado.

**Días de distribución** agrega el plazo del central a las sucursales. Cero
supone distribución inmediata. No se mide automáticamente: los pendientes viejos
y las recepciones registradas tarde no permiten inferirlo con suficiente confianza.
La generación de órdenes no crea ni valida transferencias entre compañías.

Las cantidades y los precios nuevos de la sugerencia se expresan por unidad de
stock, en la moneda de la compañía compradora. La orden convierte ambos a la unidad
de compra. La actualización conserva el significado de los precios ya guardados.

Para consultar una sugerencia centralizada hacen falta permisos sobre todas las
compañías seleccionadas y sobre aquellas cuyas métricas siguen guardadas en las
líneas. La explicación conserva el desglose por almacén.

### Límites que hay que revisar antes de comprar

- Los productos sin proveedor quedan fuera del motor; la pantalla avisa cuántos
  tuvieron ventas en los últimos 90 días.
- El stock negativo se trata como cero y se advierte en la línea. No se corrige
  el inventario automáticamente.
- Las entradas confirmadas pendientes descuentan stock aunque estén atrasadas.
  Revisar recepciones antiguas antes de confiar en la propuesta.
- Las órdenes en borrador no reservan abastecimiento. Confirmar o cancelar las
  anteriores antes de repetir una compra para las mismas sucursales.
- La compra centralizada no aplica el filtro ABC global para ocultar faltantes:
  las clases actuales todavía se guardan por producto, no por almacén/compañía.

La auditoría con datos reales y las limitaciones restantes están en
[auditoria-2026-09-09.md](auditoria-2026-09-09.md).

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

## Validación con datos reales

La [evaluación de predicciones del 9 de septiembre de 2026](validacion-predicciones-2026-09-09.md)
documenta el error observado, la comparación de algoritmos y sus límites.
Cuando la reconstrucción de inventario produce saldos negativos, el estimador
usa días calendario, avisa al operador y limita la confianza a 0,2. Ese indicador
describe calidad de datos; no expresa una probabilidad de acertar.
