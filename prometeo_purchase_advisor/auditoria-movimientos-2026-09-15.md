# Revisión de entradas, salidas y demanda — 15 de septiembre de 2026

Se leyó `prod` en Docker, que es una **copia histórica**, sin modificar sus ventas,
recepciones, transferencias, contactos ni inventario. El historial contiene
245.718 movimientos terminados, entre el 05/02 y el 05/09/2026. La mayoría de las
sucursales termina sus ventas el 19/08; Barranqueras el 26/06. No se interpreta el
período posterior como evidencia de que la base real dejó de registrar ventas.

## Resultado

**La lectura de cantidades necesitaba una corrección y la propuesta de compra
sigue requiriendo revisión humana.** Las cantidades entregadas se pueden conciliar;
la clasificación del destino, la disponibilidad y la precisión de la predicción
son problemas distintos.

### Correcciones de código

- Se leía `stock_move.product_qty`, cantidad solicitada en unidad de stock, incluso
  en movimientos terminados. Ahora se suman `stock_move_line.quantity_product_uom`,
  las cantidades realizadas expresadas en la unidad del producto.
- Hay 21 movimientos con diferencias: 21 unidades en salidas a clientes, 1 en una
  recepción desde proveedor y 23 en recepciones desde tránsito. Ejemplo:
  `IM/OUT/00005`, movimiento 28258, producto 11082: solicitado 17, realizado 14.
  `GY/IN/00017`, movimiento 207613: solicitado 7, realizado 2.
- La clasificación ABC/XYZ también usaba cantidades solicitadas, no restaba
  devoluciones y podía incluir despachos a contactos de compañías. Se alineó con
  ventas netas realizadas. Para ABC, un saldo neto de devoluciones no puede
  reducir el valor total de consumo de los demás productos: se acota a cero.
- Se mantiene cantidad **prevista** para compromisos pendientes: lo aún no
  recibido no debe convertirse en cero por no tener cantidad realizada.

Las pruebas anteriores creaban movimientos terminados sin líneas realizadas.
Se corrigieron esas fixtures y se añadieron regresiones de entrega parcial,
recepción parcial y devoluciones para evitar que ese supuesto oculte el error.

## Conciliación de ventas

Una consulta independiente basada en las ubicaciones de las líneas de movimiento
coincidió con el lector corregido en **121.919 combinaciones producto/día de 14
almacenes**, con cero diferencias. Se utilizó la misma zona horaria (UTC en esta
conciliación técnica). Esto valida cantidades y agrupación; no prueba que el
contacto del movimiento esté bien clasificado como cliente o sucursal.

Además se compararon **132.428 combinaciones ticket/producto almacenable** del POS
con sus entregas terminadas vinculadas. Las 136 diferencias, neto de 144 unidades,
corresponden todas a productos `pack_ok`: el ticket vende el combo y el inventario
mueve componentes. Los productos sin pack coinciden. No se afirma aquí que la
composición histórica de cada combo esté conciliada: eso necesita comparar sus
componentes, considerando posibles cambios en las recetas.

## Entradas y salidas observadas

Cantidades sumadas en la unidad de stock de cada producto. Estas sumas sirven
para auditar flujos; **no son un total físico homogéneo ni un importe de compra**.
La distinción externa/interna usa el contacto exacto de la compañía y tránsito;
los contactos duplicados de la sección siguiente todavía afectan esa etiqueta.

| Almacén | Salidas a cliente | Devoluciones | Recepciones externas | Entradas por traslado | Salidas por traslado |
|---|---:|---:|---:|---:|---:|
| Impacto | 30.994 | 516 | 30.407,01 | 2.909 | 44 |
| Central | 28.526 | 3 | 16.269 | 9.520 | 248.842 |
| Corrientes 2 | 33.470 | 558 | 0 | 51.298 | 230 |
| Goya | 22.227 | 502 | 0 | 20.107 | 135 |
| Corrientes Mayorista | 51.256 | 886 | 0 | 67.294 | 8.061 |

Los datos permiten compras externas y abastecimiento desde el central; no
justifican imponer una modalidad única a todas las sucursales.

## Datos que aún impiden confiar ciegamente en la sugerencia

1. **Contactos de sucursales sin vínculo a su compañía.** Los contactos 57, 58,
   60 y 61 se llaman como Corrientes 2, Mayorista, Villa Angela y Reconquista,
   pero las compañías usan los contactos 68, 79, 80 y 77. Hay 1.191 movimientos /
   25.389 unidades del central hacia esos primeros contactos que hoy parecen
   ventas externas. Son candidatos claros a revisar, no una equivalencia
   confirmada por el nombre. Solución: verificar albaranes y vincular esos aliases
   explícitamente al destino; aplicar la misma relación a demanda, recepciones y
   detección de sucursales. No fusionar contactos automáticamente por nombre.
2. **Stock que no se reconstruye con el historial disponible.** Hay 17.443
   posiciones producto/ubicación interna negativas, y 9.015 cuyo saldo de quants
   difiere del neto de movimientos presentes; 7.899 de estas últimas están en el
   central. Puede haber saldos iniciales importados o historia incompleta: la
   diferencia por sí sola no demuestra que el inventario físico sea incorrecto.
   Solución: contrastar apertura/importación y conteo físico, sin generar ajustes
   automáticos para forzar una igualdad.
3. **Artículo de ajuste usado como producto almacenable/comprable.** El producto
   29152, `AJUSTE POR VENTA MINORISTA (056473)`, tiene una salida de ajuste de
   27.752.829,23 unidades (movimiento 183626, 26/07). No debe tratarse como demanda
   de mercadería. El motor ya evita convertir un stock negativo en compra extra;
   además conviene excluir formalmente este artículo del recomendador.
4. **Recepciones pendientes antiguas.** Hay 1.893 movimientos de entrada
   pendientes con 35.435 unidades previstas; 30.630 ya tenían más de 30 días al
   cierre del 05/09. El motor los descuenta como suministro. Solución: verificar
   si siguen en viaje, falta validar recepción o deben cancelarse; después usar
   una fecha de disponibilidad para que una entrada lejana no cubra una necesidad
   inmediata. No se cancelaron ni validaron durante esta auditoría.

## Predicción: prueba temporal adicional

Se eligieron los 100 productos comprables/almacenables con mayor volumen previo
al 06/08 en cada uno de cinco almacenes. Entrenamiento: 08/05–05/08; evaluación:
06/08–19/08. Selección sin mirar ventas futuras. Se ejecutó el estimador ponderado
configurado contra ventas realizadas futuras, y promedios de 14 y 30 días como
referencias. Es una muestra de 500 pares producto/almacén y un corte temporal,
no una validación general de todos los productos ni de ventas que se perdieron
por falta de stock. La reconstrucción histórica usa los quants de la copia y
se marca como no fiable cuando corresponde; no es una instantánea archivada del
inventario al corte. No se incluyeron presupuestos, mínimos ni stock de seguridad
para no confundir predicción de demanda con cantidad a comprar.

| Almacén | Ventas futuras | Predicción ponderada | Error absoluto ponderado (WAPE) |
|---|---:|---:|---:|
| Impacto | 179 | 268,40 | 148,5 % |
| Corrientes 1 | 754 | 665,89 | 78,6 % |
| Corrientes 2 | 1.341 | 1.172,60 | 52,3 % |
| Reconquista | 467 | 575,69 | 96,0 % |
| Villa Angela | 372 | 662,92 | 172,4 % |

Total: 3.113 realizadas frente a 3.345,50 previstas (+7,47 %). Ese total oculta
errores por producto: **WAPE 85,10 %**, frente a 91,23 % del promedio de 14 días y
92,07 % del de 30. WAPE es suma de errores absolutos / ventas reales; puede superar
100 % y no es un porcentaje de productos acertados.

El ponderado mejora a ambas referencias en tres de cinco almacenes, pero no en
Impacto ni Villa Angela. **No hay evidencia suficiente para sustituirlo por un
único algoritmo universal.** Antes: corregir clasificación de flujos y entradas
pendientes; después comparar varios cortes completos por sucursal y demanda
intermitente. El stock reconstruido fue no fiable en 406 de los 500 casos, lo que
limita cualquier corrección por quiebres. No se recomienda ejecutar compras
masivas basándose solo en la predicción.

## Verificación y evidencia

- Suite integrada: 176 pruebas sin fallos. Tras el último ajuste de ABC: 17
  pruebas de clasificación sin fallos.
- SQL y Odoo shell contra `prod` en lectura; las pruebas que crean movimientos
  se ejecutaron en `advisor_review_20260909`.
- Detalle por almacén, movimientos parciales y métricas: `auditoria-movimientos-2026-09-15.json`.
- Scripts de esta ejecución: `/tmp/advisor-stock-audit/` (temporales); se adjunta
  una copia reproducible en `tools/stock_audit_20260915/` del módulo.
