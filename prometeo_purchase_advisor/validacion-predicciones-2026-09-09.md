# Validación de predicciones — 9 de septiembre de 2026

**Decisión:** corregir el tratamiento del inventario inconsistente y mantener el promedio ponderado como opción inicial. Esta muestra no justifica reemplazarlo por EWMA, Croston/SBA o TSB en todas las sucursales. Tampoco permite declarar que las cantidades recomendadas sean compras óptimas.

## Resultado principal

5.204 pares producto–almacén con proveedor actualmente cargado; ventas posteriores de 28 días; depósito central excluido de esta tabla.

| Método | Error absoluto ponderado (WAPE) | Sesgo agregado | RMSE, unidades por producto/almacén |
|---|---:|---:|---:|
| Ponderado anterior | 113,76% | +34,13% | 9,40 |
| **Ponderado corregido en Odoo** | **88,31%** | **+3,36%** | **7,95** |
| EWMA calendario, p95, α=0,3 | 103,25% | +6,41% | 10,99 |
| Croston/SBA, α=0,2, inicialización con entrenamiento | 104,04% | +41,08% | 12,01 |
| TSB, α=0,1/β=0,1, inicialización con entrenamiento | 96,25% | +23,24% | 9,84 |

El WAPE suma los errores absolutos por par producto–almacén y los divide por las ventas totales. **88,31% de error no significa 88,31% de aciertos.** El sesgo compara cantidades totales: un +3,36% puede esconder exceso en unos artículos y falta en otros. RMSE penaliza más los errores grandes. Todas las cantidades son unidades de stock; sumar unidades de productos heterogéneos no mide impacto económico.

El ponderado sin ninguna corrección por faltantes obtuvo WAPE 84,28%, sesgo −0,69% y RMSE 7,48. Es una referencia útil de ventas registradas, pero no demuestra que ignorar todos los faltantes estime mejor la demanda perdida. Se conserva la corrección cuando el saldo reconstruido es consistente; esta elección es defensiva, no una optimización probada de costos de inventario.

## Falla corregida

Antes, el reconstructor acotaba a cero los saldos negativos y el estimador seguía descontando los supuestos días sin stock. Con inventario imposible, eso concentraba ventas esporádicas en unos pocos días y multiplicaba la demanda diaria.

Caso reproducido en Odoo: 10 unidades vendidas durante una ventana de 30 días y stock actual −100. Antes: **10 unidades/día**. Ahora: **0,333 unidades/día**, confianza heurística como máximo 0,2 y advertencia para revisar inventario. La protección también cubre stock actual positivo con saldos históricos negativos.

Core y EWMA ahora incluyen todos los días calendario cuando la reconstrucción es inconsistente. Esto estima ventas registradas; no inventa ventas perdidas. Si la disponibilidad reconstruida es consistente, permanece la corrección existente por faltantes. El parámetro α queda registrado en la instantánea del modelo y la ayuda de “Confianza” aclara que no es una probabilidad de acertar.

## Datos y procedimiento

Se trabajó con `advisor_prod_review_20260909`, clon de la base Docker llamada `prod`, usando cron y correo deshabilitados. Alexis confirmó que esa base `prod` ya es una copia de la base real: no es producción en vivo. La instancia Docker original conserva el código anterior. Las consultas de evaluación no crean compras, movimientos ni registros de negocio.

La consulta de configuración en la copia `prod` confirmó un único modelo: ponderado de 90 días, ventanas 14/30/90 con pesos 0,5/0,3/0,2, corrección por faltantes activada y percentil 95. Son los parámetros utilizados para el baseline del ensayo.

Se extrajeron 26.315 casos: 9.751 de validación y 16.564 del período final, incluyendo central. Cada caso contiene hasta 90 días anteriores al corte, al menos 28 días desde el primer movimiento conocido y venta neta positiva en entrenamiento. Se incluyeron productos archivados. La elegibilidad no usa ventas futuras. La serie representa movimientos completados hacia clientes, menos devoluciones, excluyendo contrapartes de las propias empresas.

Los últimos movimientos de clientes de la mayoría de sucursales son del **19 de agosto**, y los de Mayorista del **5 de septiembre**. La ausencia de datos hasta hoy se explica por trabajar con una copia; no es evidencia de fallas de carga en la base real. No se conoce la fecha exacta de extracción ni se deduce que todas las sucursales tengan el mismo último día de actividad. El día final se excluyó por potencialmente incompleto. No se completó agosto–septiembre con ceros hasta la fecha actual: el ensayo reserva períodos históricos dentro de la copia.

Para la mayoría de sucursales, los cortes fueron 24 de junio, 8 de julio y 22 de julio. Las dos validaciones abarcan 14 días cada una; el período final abarca **22 de julio–18 de agosto**, 28 días. Mayorista usa cortes 11 de julio, 25 de julio y 8 de agosto, con período final **8 de agosto–4 de septiembre**. Central termina un día antes que las sucursales. No todos los almacenes califican en los primeros cortes.

Se comparó una grilla inicial de medias de 14/28/56/90 días, ponderado con y sin recorte, EWMA α=0,05/0,1/0,2/0,3, SBA α=0,1/0,2 y TSB (α,β)=(0,1;0,05)/(0,1;0,1)/(0,2;0,1). Un control predice cero. La grilla inicial seleccionó el ponderado calendario por RMSE de validación. **Los horizontes de validación y prueba son distintos**, por lo que esta selección no sustituye una validación mensual repetida.

Después del análisis inicial se añadieron el guard de inventario, EWMA calendario con p95 y una sensibilidad a la inicialización de SBA/TSB. Estas adiciones son exploratorias; no se presentan como hipótesis elegidas antes de toda evaluación. La inicialización alternativa utiliza exclusivamente el tamaño medio positivo y la frecuencia del entrenamiento; evita atribuir el mal resultado de Croston a una única inicialización. No constituye una búsqueda exhaustiva de parámetros.

Una prueba previa de 14 días reservados produjo 45.801 casos y mostró el mismo problema de sobreestimación. No se combina esa muestra con la mensual: comparten productos y fechas.

## Límites que impiden afirmar “predicciones correctas”

1. **Ventas observadas no equivalen a demanda.** Un día sin venta puede indicar falta de stock, falta de clientes o falta de datos. No existe etiqueta de ventas perdidas. Los errores positivos y negativos no son costos, fill rate ni quiebres reales.
2. **El stock es una reconstrucción retrospectiva.** Parte de los quants actuales y revierte movimientos; no hay instantáneas archivadas al corte. Incluso con ventas de entrenamiento anteriores al corte, no es una reproducción estricta de la información disponible históricamente. Se usa para diagnosticar el motor, no para prometer rendimiento futuro.
3. **Las cohortes tienen límites.** “Con proveedor” usa la ficha actual, sin probar que existiera o fuera elegible en la fecha del corte. Saldos diarios iniciales/finales compatibles con disponibilidad no garantizan disponibilidad intradía. Las salidas a cliente son una aproximación a ventas, especialmente débil en central.
4. **La exactitud individual sigue siendo baja.** En todos los 15.324 casos de sucursales del período final, el corregido da WAPE 99,41%, sesgo +13,40% y RMSE 10,39. El control cero da WAPE 100% y RMSE 9,52: demuestra lo escasa que es la señal, no que convenga dejar de comprar. En los 2.183 casos con saldos diarios compatibles con disponibilidad, el WAPE corregido sigue en 122,06%.
5. **La muestra no cubre el ciclo de compra completo.** No valida plazos reales de entrega, stock de seguridad, costos de faltantes, reservas históricas ni compras óptimas. Las sucursales tienen poca historia para evaluar estacionalidad anual. No se estimaron intervalos de incertidumbre estadística ni significancia de las diferencias.

Central registra grandes salidas manuales a clientes y ventas posteriores muy pequeñas: su error porcentual excede 7.000% incluso después del guard. No corresponde mezclar esos registros con retail ni tratarlos como demanda recurrente sin validar su naturaleza. En compra centralizada, la necesidad debe provenir de las sucursales abastecidas y descontar existencias/entradas una sola vez, tal como contempla el cambio de red de abastecimiento anterior. Este ensayo evalúa demanda local, no reconstruye la red histórica de cada compra.

## Algoritmo recomendado y siguiente iteración

Mantener el ponderado corregido, con revisión de líneas de confianza baja. **No hay evidencia en esta muestra para migrar universalmente a otro algoritmo.** EWMA calendario con p95 fue mejor en la validación retail (RMSE 7,33), pero empeoró en el período final (13,91 frente a 10,39 del corregido). Los candidatos SBA y TSB ensayados tampoco mejoran el resultado principal; esto no descarta toda la familia de modelos intermitentes.

La siguiente mejora de mayor valor es revisar los saldos inconsistentes de la copia y ampliar la evaluación con cortes históricos de **28 días** contenidos en ella, separados por sucursal y frecuencia de venta. Para una validación prospectiva, registrar predicciones y saldos diarios antes de conocer el resultado. La antigüedad de la copia no exige corregir la carga de datos de la base real. Comparar demanda y política de compra por separado, incorporando proveedor/plazo/costo. Solo cambiar de método por segmento cuando mejore en períodos posteriores y bajo un costo de inventario explícito.

## Evidencia reproducible

Los agregados están en [forecast-validation-2026-09-09.json](forecast-validation-2026-09-09.json); scripts e instrucciones en [tools/forecast_validation](tools/forecast_validation/README.md). Las series de productos permanecen fuera de Git. Se verificaron **26.315 estimaciones ejecutando el motor real de Odoo por almacén y corte**: cero diferencias contra el cálculo legado cuando se desactiva el nuevo guard, y coincidencia exacta con el fallback correspondiente. Esto valida implementación, no exactitud futura.

Referencias metodológicas: evaluación por [origen móvil](https://otexts.com/fpp3/tscv.html), [errores fuera de muestra](https://otexts.com/fpp3/accuracy.html), [demanda intermitente y Croston](https://otexts.com/fpp3/counts.html) y [artículo original de TSB](https://pure.rug.nl/ws/portalfiles/portal/145394864/Intermittent_demand_Linking_forecasting_to_inventory_obsolescence.pdf).

Verificación de código: **125 pruebas Odoo aprobadas, cero fallos y cero errores**, incluyendo compras directas/centralizadas, seguridad, UoM, stock válido, saldo actual negativo, saldo histórico imposible y EWMA. Antes del arreglo, la regresión de 10 unidades/30 días falló con 10,0 frente a 0,3333 esperado. La revisión independiente no encontró un defecto funcional bloqueante; sus observaciones metodológicas se incorporaron a este documento.
