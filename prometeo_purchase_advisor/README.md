# Prometeo - Recomendador de compra

Guía de uso para comprar directamente en una sucursal o recibir mercadería en
el depósito central y distribuirla después. Versión del módulo: `18.0.1.1.1`.

**Inicio rápido:** **Recomendador → Sugerencias de compra → Nuevo**.
Elegí el almacén receptor y seguí **Calcular → revisar → Confirmar → Crear órdenes de compra**.

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

## Preparación inicial

1. Asigná al comprador el grupo **Operador de compras**; quien configure modelos
   necesita **Manager de compras**. Verificá también los permisos habituales de
   Compras y las compañías habilitadas en Odoo.
2. Revisá en los productos sus proveedores, precios, unidades de compra y plazos
   de entrega. Los productos sin proveedor también se calculan y se muestran con
   una advertencia; completá proveedor y precio antes de generar la orden.
3. Revisá existencias y recepciones pendientes. Una recepción vieja que sigue
   abierta puede reducir la cantidad sugerida.
4. En **Ajustes → Recomendador de compra**, elegí el modelo por defecto y los
   **Días de cobertura objetivo** de la compañía. El modelo inicial es
   **Promedio ponderado 14/30/90**.

Los días de cobertura son adicionales al plazo del proveedor. Por ejemplo,
30 días de cobertura y 7 días de entrega implican cubrir un horizonte de 37 días,
al que se agrega el stock de seguridad y se le descuenta la disponibilidad.

## Elegir la modalidad

| Situación | Almacén | Modalidad |
|---|---|---|
| El proveedor entrega directamente en una sucursal | Esa sucursal | Compra directa al almacén |
| El proveedor entrega en central para abastecer sucursales | Depósito central | Compra centralizada para sucursales |
| Central compra únicamente para su propia demanda | Depósito central | Compra directa al almacén |

### Compra directa en una sucursal

1. Abrí **Recomendador → Sugerencias de compra → Nuevo**.
2. Elegí la sucursal en **Almacén** y **Compra directa al almacén** en **Modalidad**.
   La compañía compradora se toma del almacén.
3. Indicá **Días de cobertura** y **Responsable**. Dejá **Modelo de demanda** vacío
   para usar las asignaciones configuradas; seleccionarlo fuerza ese modelo para
   toda la sugerencia.
4. Guardá y pulsá **Calcular**. Revisá las líneas siguiendo la sección siguiente.

### Compra centralizada para sucursales

1. Creá una sugerencia con el depósito central en **Almacén** y
   **Compra centralizada para sucursales** en **Modalidad**.
2. Pulsá **Detectar sucursales por movimientos**. Revisa despachos completados
   de los últimos 180 días entre las compañías habilitadas.
3. Revisá **Sucursales a abastecer**: agregá o quitá destinos según esta compra.
   La detección propone destinos históricos; no define una lista fija ni garantiza
   identificar todos los casos. No incluyas otra vez el depósito receptor.
4. Completá **Días de cobertura** y **Días de distribución**. Este último es el
   plazo desde central hasta las sucursales; cero supone distribución inmediata.
5. Guardá y pulsá **Calcular**. Abrí las líneas para revisar el desglose por almacén.

Si una sucursal no aparece, verificá las compañías activadas y tus permisos.
También podés seleccionarla manualmente si tenés acceso. Si ya calculaste y
necesitás cambiar almacén, modalidad o destinos, usá **Volver a borrador** y
recalculá antes de confirmar.

## Revisar y generar la compra

1. Leé los avisos generales y abrí las líneas con advertencias mediante el botón
   de abrir formulario de la fila. Ahí están **Por qué esta cantidad** y el detalle
   de stock, demanda y plazo.
2. Revisá **Cantidad**, **Proveedor** y **Precio unitario**. Podés modificarlos o
   agregar productos manualmente. Para no comprar una línea, dejá **Cantidad = 0**.
3. Si cambiaste cobertura o modelo, pulsá **Calcular** otra vez. Se actualizan las
   métricas y se conservan cantidades, proveedores y precios editados a mano.
   Revisá esos valores conservados: recalcular no los reemplaza por el nuevo sugerido.
4. Pulsá **Confirmar** y después **Crear órdenes de compra**. Se crean borradores
   agrupados por proveedor para recibir en el almacén elegido. Solo pasan las líneas
   con cantidad positiva; todas ellas necesitan proveedor.
5. Abrí **Órdenes**, revisá condiciones, impuestos, precios y cantidades, y confirmá
   cada compra desde el flujo habitual de Odoo. Un precio cero no bloquea la creación:
   corregilo antes de confirmar la orden.

**Confirmar la sugerencia no confirma las órdenes ni registra recepciones.**
En modalidad centralizada, la distribución se realiza después mediante el flujo
habitual de transferencias. El módulo no crea ni valida esos traslados.

Antes de generar órdenes podés usar **Volver a borrador** para cambiar el alcance.
Una sugerencia que ya generó órdenes no se reutiliza desde este flujo: gestioná
las órdenes existentes desde **Órdenes** y evitá crear compras duplicadas.

### Qué significa cada columna

| Campo | Cómo interpretarlo |
|---|---|
| Venta/día | Estimación diaria; no es una venta futura garantizada. |
| Stock | Existencias consideradas por el cálculo. |
| Tránsito | Entradas pendientes consideradas; no necesariamente mercadería ya en viaje ni con llegada a tiempo. |
| Cobertura | Días que cubre el stock al ritmo estimado; no es el objetivo configurado. |
| Sugerido / Cantidad | Resultado automático / cantidad final que pasará a la compra. |
| Plazo de entrega | Días del proveedor usados para anticipar la reposición. |
| Stock de seguridad | Reserva calculada por variabilidad y nivel de servicio. |
| Confianza | Calidad de datos entre 0 y 1; no es probabilidad de acierto. Por debajo de 0,5, revisá la línea. |

En una sugerencia centralizada, las columnas resumen varios almacenes.
La explicación por almacén permite distinguir dónde falta mercadería.
Podés mostrar columnas opcionales, como confianza, método y advertencias,
desde el selector de columnas de la lista.

### Cómo calcula una compra centralizada

Cada sucursal usa su propia demanda, disponibilidad histórica, stock y entradas
confirmadas. Se suman sus faltantes positivos; el exceso de una sucursal no se
supone disponible para otra. El central cubre esos faltantes con su disponibilidad
libre y se compra la diferencia. Los mínimos y bultos se aplican una sola vez.

**Ejemplo:** después de calcular necesidades y descontar stock y entradas, a la
sucursal A le faltan 30 unidades y a B le faltan 20. Central tiene 15 unidades
libres, luego de cubrir sus propios compromisos y demanda. La compra neta es
`30 + 20 − 15 = 35`. Si el bulto aplicable es de 12 unidades y no hay otro mínimo,
la sugerencia final se redondea a **36 unidades**.

### Cuando se combinan compra directa y abastecimiento desde central

Podés incluir una sucursal que también compra directamente. Sus entradas
confirmadas ya reducen lo que necesita recibir desde central.

**Ejemplo:** una sucursal necesita 40 unidades antes de entradas pendientes y tiene
una compra directa confirmada por 25 todavía sin recibir. Esa entrada deja una
necesidad neta de **15 unidades**, antes de consolidar con la disponibilidad del
central y aplicar mínimos. Si las 25 unidades siguen en una orden en borrador,
todavía no se descuentan como abastecimiento confirmado.

Revisá que cada necesidad tenga una única compra o transferencia que la cubra.
Crear dos sugerencias superpuestas no bloquea ni reserva esas cantidades.

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

- Los productos sin proveedor participan del cálculo con las mismas reglas de
  reposición. La pantalla avisa cuántos tuvieron ventas en los últimos 90 días
  y marca sus líneas; proveedor y precio quedan pendientes de completar.
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

La pestaña **Calidad del cálculo** muestra cuántas líneas se editaron y cuánto se
apartaron del sugerido. Una tasa de edición alta es una señal para revisar datos,
cobertura y modelo; también puede responder a decisiones comerciales. No mide
aciertos contra ventas futuras ni demuestra por sí sola mala calibración.

## Configurar el modelo de demanda

En **Recomendador → Configuración → Modelos de demanda**, abrí
**Promedio ponderado 14/30/90**. Como punto de partida, conservá sus valores:

| Parámetro | Valor inicial | Efecto |
|---|---|---|
| Ventana de historia | 90 días | Cuánto pasado se analiza. |
| Pesos por ventana | `14:0.5,30:0.3,90:0.2` | Da más peso al ritmo reciente; los pesos suman 1. |
| Historia mínima | 21 días | Reduce la confianza y exige una muestra de días con stock por ventana, limitada por su duración y la historia disponible. |
| Ignorar días sin stock | Activado | Descuenta faltantes cuando la reconstrucción de inventario es consistente. |
| Percentil de recorte | `0.95` | Reduce el efecto de picos; `0` desactiva el recorte. |
| Nivel de servicio | `0.95` | Objetivo usado para calcular stock de seguridad; no garantiza 95% de acierto. |

El promedio ponderado descarta ventanas con pocos días con stock y redistribuye
sus pesos. Si ninguna alcanza la muestra mínima, usa toda la historia disponible.
Si tampoco esa historia reúne suficientes días con stock, usa el promedio por
día calendario y advierte que requiere revisión. Así, una salida de 34 unidades
en el único día con stock de una ventana no se extrapola como 34 ventas diarias.
La explicación distingue la demanda estimada de las ventas netas registradas.

Si **Modelo de demanda** está vacío en la sugerencia, el orden de asignación es
**producto → categoría → primera regla coincidente → modelo de la compañía**.
Configurá excepciones en la pestaña **Compra** del producto, en su categoría o
en **Configuración → Reglas de asignación**. Las reglas se evalúan por secuencia.
En centralizado, cada almacén resuelve sus reglas en su propia compañía.

La condición **Historia mínima** de las reglas tiene una limitación pendiente:
el flujo actual no entrega esa historia al resolutor y esas reglas no coinciden.
Para una asignación explícita usá producto o categoría. Esto es distinto del
umbral de historia mínima del modelo, que sí reduce la confianza de la estimación.

El complemento [`prometeo_purchase_advisor_ewma`](../prometeo_purchase_advisor_ewma/README.md)
agrega suavizado exponencial. No hace falta instalarlo para usar el recomendador.
La evaluación disponible no justifica cambiar todas las sucursales a ese método.

## Resolver situaciones frecuentes

| Situación | Qué revisar |
|---|---|
| No aparece el menú Recomendador | Grupo Operador de compras y módulo instalado en esa base. |
| No aparece un producto | Posibilidad de compra, producto activo y casilla de exclusión en su pestaña Compra. También puede no tener necesidad de reposición o quedar fuera por el filtro C. La falta de proveedor no lo excluye. |
| La cantidad es menor de lo esperado | Stock y entradas pendientes; en centralizado, revisá el desglose y las compras directas de cada sucursal. |
| El stock reconstruido es inconsistente | Revisá inventario y movimientos. El motor usa días calendario y confianza como máximo 0,2; no corrige existencias. |
| El recálculo mantiene mi cantidad | Es intencional: conserva ediciones manuales. Compará Cantidad con Sugerido y ajustá si corresponde. |
| No puedo generar órdenes | La sugerencia debe estar confirmada, tener cantidades positivas y proveedor en esas líneas. |

**Al probar sobre una copia histórica:** el aviso de última venta antigua puede
corresponder al corte de la copia. No demuestra una falla de actualización en la
base real. El botón **Calcular** usa la fecha actual; no tiene selector de fecha
histórica. Para evaluar predicciones dentro de la copia usá el procedimiento de
[validación histórica](tools/forecast_validation/README.md).

## Automatización

Tres crons, configurables en *Ajustes técnicos*:

- **Clasificar ABC/XYZ** (semanal, activo): valor de consumo de los últimos 180
  días y variabilidad de la demanda.
- **Medir proveedores** (semanal, activo): plazo real y nivel de cumplimiento
  del último año.
- **Generar sugerencias** (semanal, **inactivo** por defecto): crea y calcula
  una sugerencia por cada almacén con *Sugerencia automática* tildada, y le
  deja una actividad al responsable.

Para habilitar sugerencias automáticas:

1. Como manager, abrí **Inventario → Configuración → Almacenes** y activá
   **Sugerencia automática**, indicando su responsable.
2. Con permisos de administración y modo desarrollador, abrí las acciones
   planificadas de Ajustes técnicos y activá la generación de sugerencias.
3. Revisá las sugerencias generadas antes de crear órdenes.

La generación automática usa **compra directa** por almacén. No detecta ni
selecciona sucursales para armar una compra centralizada; preparala manualmente.
Estos procesos no confirman compras ni validan transferencias.

## Grupos

- **Operador de compras** — crea y edita sugerencias, genera las órdenes.
- **Manager de compras** — además configura modelos de demanda y reglas.

## Validación con datos reales

La [evaluación de predicciones del 9 de septiembre de 2026](validacion-predicciones-2026-09-09.md)
documenta el error observado, la comparación de algoritmos y sus límites.
Cuando la reconstrucción de inventario produce saldos negativos, el estimador
usa días calendario, avisa al operador y limita la confianza a 0,2. Ese indicador
describe calidad de datos; no expresa una probabilidad de acertar.
