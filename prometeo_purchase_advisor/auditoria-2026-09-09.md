# Auditoría del recomendador de compras — 9 de septiembre de 2026

## Qué muestran los movimientos reales

Se consultó `prod` en modo lectura y se probó sobre una copia separada,
`advisor_prod_review_20260909`. La base contiene 245.718 movimientos terminados,
14 almacenes y compañías distintas para las sucursales. El último movimiento
terminado registrado es del 5 de septiembre de 2026; no representa ventas en vivo
hasta el día de esta auditoría.

Los contactos de destino y las contrapartes de `stock_intercompany` identifican
**12 sucursales abastecidas desde el depósito central**: Impacto, Barranqueras,
Corrientes 1 y 2, Fontana, Goya, Reconquista, Resistencia, Corrientes Mayorista,
Villa Angela, Santo Tome y Mega futbol.

El origen técnico «proveedor» no basta para identificar compras externas:
`stock_intercompany` también lo usa para recibir transferencias. Separando por
contacto de la compañía, el historial tiene estas recepciones terminadas:

| Almacén | Movimientos de recepción externa | Movimientos de recepción entre compañías |
|---|---:|---:|
| Impacto modas | 3.062 | 632 |
| Depósito central | 177 | 395 |
| Mega futbol | 24 | 64 |
| Villa Angela | 2 | 171 |

En las demás sucursales no se encontraron recepciones externas terminadas con ese
criterio. Esto no demuestra que nunca compren directamente: puede haber compras
sin recepción registrada o con un contacto incorrecto. Por eso se mantienen
ambas modalidades y la detección no impone una política permanente de compras.

## Fallas corregidas

| Falla | Efecto | Cambio |
|---|---|---|
| Solo se analizaba el almacén receptor | Comprar desde el central ignoraba ventas de sucursales | Modo centralizado con selección/detección de destinos, demanda por sucursal y consolidación de faltantes |
| Traslados a otra compañía con destino de tipo cliente | Se contaban 181 movimientos / 5.589 unidades como ventas del central en el historial | Se excluyen movimientos cuyo contacto es una compañía |
| Despachos preparados sin recepción contraparte | Se sumaba el compromiso del central sin descontarlo del faltante de la sucursal | Crédito de entrada al destino, sin duplicarlo cuando existe contraparte o movimiento encadenado |
| Plazo configurado tomado del primer producto del proveedor | Un producto con plazo de 20 días usaba 2 días | Medición por compañía/almacén comprador y respaldo individual por producto |
| Precio de compra usado como precio por unidad de stock | Un precio de 120 por docena inflaba el total | Normalización de unidad y moneda; conversión inversa al generar la orden y compatibilidad con registros antiguos |
| Recálculo retenía productos excluidos | Podían comprarse con cantidades obsoletas | Se retiran líneas automáticas que dejaron de participar; decisiones manuales se conservan con aviso |
| Reglas de demanda de otras compañías | El modelo dependía de compañías activas ajenas al cálculo | Resolución en la compañía del almacén de demanda, manteniendo el proveedor de la compañía compradora |
| Métricas consolidadas visibles solo con permiso del central | Exposición de stock y demanda de sucursales | Reglas exigen acceso al alcance seleccionado y al de las métricas persistidas |
| Dependencia incompleta de `purchase` | Instalación limpia podía carecer de integración con recepciones | Dependencia explícita de `purchase_stock` |

Los mínimos del proveedor se aplican al total consolidado. No se usa el exceso de
una sucursal para cubrir otra sin una transferencia planificada. Las órdenes
generadas se reciben en la compañía y el almacén receptor elegidos, en borrador.

## Prueba sobre copia de datos reales

Cobertura objetivo: 30 días. Modelos de demanda existentes. Distribución: 0 días,
que es una suposición para la comparación, no un plazo real medido.

| Caso | Antes | Después |
|---|---|---|
| Compra directa al central | 9 líneas; 317,34 unidades | 8 líneas; 260,94 unidades; 2,64 s |
| Compra directa en Impacto | 48 líneas; 272,80 unidades | 48 líneas; 275,44 unidades; 2,52 s |
| Central para 12 sucursales | No existía | 448 líneas; 8.728,31 unidades; 28,01 s |

**Estas cantidades son resultados de prueba, no órdenes recomendadas para ejecutar
sin revisión.** De las 448 líneas centralizadas, 445 tienen baja confianza. La
estimación está limitada por proveedores faltantes, stock inconsistente,
quiebres reconstruidos y movimientos desactualizados.

La pantalla detectó **5.693 productos con ventas externas en los últimos 90 días
sin proveedor cargado**. Además, hay **17.443 registros de stock negativo en
ubicaciones internas**. Contando todas las ubicaciones, incluso virtuales, son
70.938; esa cifra total no debe interpretarse como faltantes físicos.

Hay 1.756 movimientos pendientes desde ubicaciones de proveedor o tránsito con
fecha de más de 30 días: suman 32.160 unidades. Son registros que se deben revisar;
el recomendador no puede decidir si siguen en camino o si falta validar su recepción.

## Validación

- Suite Odoo del módulo y su extensión EWMA: 122 pruebas de negocio ejecutadas,
  incluidas compra directa, centralizada, mínimos, excedentes, entradas pendientes,
  distribución, recálculo, unidades, permisos y resolución de modelos por compañía.
- Reproducción antes de corregir: una transferencia preparada de 60 elevaba la
  compra de 223 a 283. Con la corrección sigue en 223.
- Actualización real desde la versión anterior en una tercera base: una sugerencia
  confirmada de 24 unidades con precio 120/docena genera una orden de 2 docenas a
  120/docena. No se multiplica el precio de una sugerencia antigua por 12.
- La instalación/actualización carga las vistas y reglas de Odoo. Las pruebas con
  datos de producción no confirmaron compras ni validaron transferencias.

## Pendientes y cómo resolverlos

1. **Completar proveedores y regularizar recepciones.** El código no puede inferir
   a quién comprar 5.693 productos sin un vínculo fiable. Importar/corregir esas
   fichas y revisar los pendientes antiguos por sucursal antes de usar la propuesta.
2. **ABC/XYZ por compañía o almacén.** Los campos existentes se guardan globalmente
   en el producto: el cron de una compañía puede pisar la clase de otra. Migrarlos
   a métricas por producto/almacén. El modo centralizado ya evita que ese filtro
   global oculte faltantes; el modo directo conserva el comportamiento anterior.
3. **Entradas por fecha y compras repetidas.** Hoy se descuentan todas las entradas
   confirmadas, incluso fuera del horizonte, y los borradores no reservan suministro.
   Incorporar un calendario de disponibilidad y asignaciones entre sugerencias para
   evitar superposición entre compras centralizadas y directas.
4. **Reglas con historia mínima.** El resolutor acepta historia por producto, pero
   el pipeline aún no se la proporciona; esas reglas no se activan. Materializar
   la antigüedad por almacén antes de resolverlas, y validar con datos conocidos.

La versión preparada es `18.0.1.1.0`. No se actualizó ni reinició el servicio que
atiende `prod`; el código y las bases de revisión están separados.
