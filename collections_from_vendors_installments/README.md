# Cobranza a vendedores y cuotas

Módulo de Odoo 18 para el circuito de **venta domiciliaria financiada** de una
fábrica de muebles: el vendedor retira mercadería de fábrica, la vende en cuotas
en la casa del cliente, cobra la entrega como comisión, y después un cobrador se
hace cargo de las cuotas restantes casa por casa.

No genera asientos contables ni comprobantes fiscales. Usa modelos propios con
prefijo `cvi.` y se apoya en el inventario nativo de Odoo para la mercadería.

---

## Índice

1. [Vocabulario](#1-vocabulario)
2. [El circuito de punta a punta](#2-el-circuito-de-punta-a-punta)
3. [Roles: quién hace qué](#3-roles-quién-hace-qué)
4. [Catálogo: muebles y planes de cuotas](#4-catálogo-muebles-y-planes-de-cuotas)
5. [Clientes](#5-clientes)
6. [Mercadería y ubicaciones](#6-mercadería-y-ubicaciones)
7. [La venta, paso a paso](#7-la-venta-paso-a-paso)
8. [Calendario de cuotas](#8-calendario-de-cuotas)
9. [Enrutamiento y aceptación](#9-enrutamiento-y-aceptación)
10. [Cobranza](#10-cobranza)
11. [Rendiciones de caja](#11-rendiciones-de-caja)
12. [Mora, retiro y recuperación](#12-mora-retiro-y-recuperación)
13. [Supervisión](#13-supervisión)
14. [Tablero de indicadores](#14-tablero-de-indicadores)
15. [Configuración](#15-configuración)
16. [Los cuatro estados](#16-los-cuatro-estados)
17. [Numeración](#17-numeración)
18. [Automatismos](#18-automatismos)
19. [Qué te va a rechazar el sistema y por qué](#19-qué-te-va-a-rechazar-el-sistema-y-por-qué)
20. [Preguntas frecuentes](#20-preguntas-frecuentes)
21. [Para desarrolladores](#21-para-desarrolladores)

---

## 1. Vocabulario

| Término | Qué es |
|---|---|
| **Tarjeta** (`cvi.card`) | La venta. Es el equivalente a la tarjeta de papel: un cliente, uno o varios muebles, un plan y un calendario de cuotas. Se numera `TARJ/000001`. |
| **Cuota** (`cvi.installment`) | Cada vencimiento de una tarjeta. La cuota 1 es siempre la **entrega/comisión** del vendedor. |
| **Plan de cuotas** (`cvi.product.plan`) | Combinación cerrada de cantidad de cuotas + importe + frecuencia, definida en la ficha de cada mueble. |
| **Cobro** (`cvi.payment`) | Plata que se recibió. Se numera `COB/000001`. Se imputa solo sobre las cuotas. |
| **Imputación** (`cvi.allocation`) | El vínculo entre un cobro y la cuota que salda. Un cobro puede tener varias. |
| **Cartera** | El conjunto de tarjetas de las que un cobrador es responsable. |
| **Rendición** (`cvi.settlement`) | La entrega de caja del cobrador a la empresa. Se numera `REND/000001`. |
| **Visita** (`cvi.supervision.visit`) | Auditoría de un supervisor sobre la cartera de un cobrador. Se numera `SUP/000001`. |
| **Ubicación del vendedor** | Ubicación de inventario propia de cada vendedor, donde vive la mercadería que tiene en la calle. |

---

## 2. El circuito de punta a punta

```
  FÁBRICA                VENDEDOR              CLIENTE            COBRADOR
     │                      │                     │                  │
 (1) │ produce              │                     │                  │
     ├─── entrega ─────────►│                     │                  │
 (2) │   WH/Stock →         │                     │                  │
     │   Vendedores/X       │                     │                  │
     │                      ├─── vende ──────────►│                  │
 (3) │                      │  Vendedores/X →     │                  │
     │                      │  Clientes           │                  │
     │                      │◄── cuota 1 ─────────┤                  │
 (4) │                      │   (comisión)        │                  │
     │                      ├─── enruta ──────────┼─────────────────►│
 (5) │                      │                     │                  │
     │                      │                     │◄── acepta ───────┤
 (6) │                      │                     │                  │
     │                      │                     │◄── cobra ────────┤
 (7) │                      │                     │   cuotas 2..N    │
     │◄─────────────────────┼─────────────────────┼─── rinde caja ───┤
 (8) │                      │                     │                  │
```

1. **Ingreso de producción** — Inventario nativo. Un albarán de entrada o un
   ajuste suma cantidad por modelo en `WH/Stock`. Los muebles **no** llevan lote
   ni serie: no se identifican por unidad.
2. **Entrega al vendedor** — *Depósito → Entregar / recibir mercadería*,
   dirección "Entrega al vendedor". Genera un albarán interno
   `WH/Stock → Vendedores/<nombre>`. La ubicación del vendedor se crea sola la
   primera vez que se le entrega algo.
3. **Venta** — *Vendedor → Nueva venta*. Se identifica al cliente por DNI, se
   elige mueble y plan. Al confirmar se descuenta el mueble del stock del
   vendedor hacia Clientes y se genera el calendario de cuotas.
4. **Cobro de la entrega** — El vendedor registra la cuota 1 (su comisión) desde
   la tarjeta. **No es automático**: puede cobrarla otro día, o en partes.
5. **Enrutamiento** — La tarjeta se manda a un cobrador, que queda "Enrutada".
6. **Aceptación** — El cobrador la acepta y recién ahí entra a su cartera.
   También puede rechazarla con un motivo, y vuelve al vendedor.
7. **Cobranza** — El cobrador trabaja con la *Agenda de cobro* y registra los
   cobros de las cuotas 2..N.
8. **Rendición** — El cobrador entrega la caja; el administrador la revisa y la
   aprueba, con diferencia o sin ella.

Cuando el saldo llega a cero, la tarjeta pasa sola a **Finalizada**.

---

## 3. Roles: quién hace qué

Los cuatro grupos están en *Ajustes → Usuarios*, categoría **Venta en cuotas**
(el supervisor tiene su propia categoría).

| Rol | Ve | Puede |
|---|---|---|
| **Vendedor** | Solo sus propias ventas | Dar de alta clientes, cargar y confirmar ventas, cobrar la entrega, enrutar tarjetas, ver su mercadería en la calle |
| **Cobrador** | Solo las tarjetas donde figura como cobrador | Aceptar o rechazar tarjetas, registrar cobros, ver su agenda, armar y entregar sus rendiciones |
| **Supervisor** | La cartera de los cobradores que tiene asignados, en **solo lectura** | Cargar visitas de auditoría con observaciones |
| **Administrador de cobranzas** | Todo | Todo lo anterior más: configurar, definir planes y ciudades, transferir carteras, anular cobros, aprobar rendiciones, marcar clientes problemáticos, marcar y registrar retiros |

### Menús por rol

| Menú | Quién lo ve |
|---|---|
| **Dashboard** | Administrador |
| **Vendedor** → Mis ventas, Nueva venta, Clientes, Mi mercadería, Sin cobrador | Vendedor |
| **Cobrador** → Agenda de cobro, Pendientes de aceptar, Mi cartera, Cobros, Mis rendiciones | Cobrador |
| **Depósito** → Entregar / recibir mercadería, Mercadería en la calle, Muebles retirados | Usuarios de Inventario |
| **Supervisión** → Visitas, Asignaciones | Supervisor y Administrador (Asignaciones solo Administrador) |
| **Administración** → Todas las tarjetas, Transferir cartera, Entregas a vendedores, Rendiciones, Diferencias por cobrador, Clientes en mora, Clientes problemáticos | Administrador |
| **Muebles** | Administrador |
| **Configuración** → Ajustes, Ciudades | Administrador |

### Cómo está construida la separación

- **Reglas de registro** (`ir.rule`) por modelo: el vendedor ve las tarjetas
  donde es `vendor_id`, el cobrador donde es `collector_id`, el supervisor las
  de los cobradores que tiene asignados **hoy**, el administrador todas.
- Todos los modelos llevan además una **regla multi-empresa**.
- Las operaciones que técnicamente necesitan permisos de Inventario (crear y
  validar albaranes) corren con `sudo()` **solo para esa parte**: el vendedor no
  recibe el grupo de Inventario. Los chequeos de disponibilidad corren con el
  usuario real.

---

## 4. Catálogo: muebles y planes de cuotas

Los muebles son productos almacenables comunes. Se cargan desde
*Venta en cuotas → Muebles* (o desde Inventario).

Cada mueble lleva **sus propios planes** en la pestaña *Planes de cuotas*. Un
plan es: nombre, cantidad de cuotas, importe de cuota y frecuencia.

| Plan | Cuotas | Importe | Total |
|---|---|---|---|
| 6 cuotas | 6 | 22.000 | 132.000 |
| 12 cuotas | 12 | 13.500 | 162.000 |
| 20 semanas | 20 | 7.000 | 140.000 |

- El total se calcula solo: **cuotas × importe**.
- El importe **ya incluye el interés**. Por eso el total no es una división del
  precio de contado.
- **El precio de lista del producto no se usa para nada.** Cada plan es una
  opción cerrada cargada a mano: no hay coeficientes ni tasas que mantener.
- Mensuales y semanales conviven; elegir el plan es lo que define la modalidad.
- Un plan archivado deja de ofrecerse en ventas nuevas, pero las tarjetas ya
  vendidas con él no se tocan.
- Un plan no puede tener menos de 1 cuota ni importe cero.

Definir planes requiere ser administrador. Vendedores, cobradores y supervisores
solo los leen.

---

## 5. Clientes

### La identidad es el DNI

El cliente **no** es un `res.partner`: es un modelo propio (`cvi.customer`) cuya
identidad es el documento. El DNI se guarda normalizado —sin puntos, espacios ni
guiones— y es único por empresa.

> `30.111.222`, `30 111 222` y `30111222` son **la misma persona**. Sin
> normalizar entrarían como tres clientes distintos y el historial de
> antecedentes no serviría para nada.

Buscar por nombre nunca da de alta: el circuito de venta arranca **siempre** por
DNI, y eso es lo que evita que la misma persona entre dos veces escrita distinto.

### Datos de la ficha

- Nombre y apellido, DNI
- **Celular** (un solo número; el teléfono fijo se eliminó)
- Dirección, **Ciudad** (de una lista, ver abajo), Código postal
- **Foto del DNI: frente y dorso**
- Marca de cliente problemático con motivo, fecha y autor

Cuáles de esos datos son **obligatorios** se configura por empresa (ver
[Configuración](#15-configuración)).

### Ciudades

La ciudad **no es texto libre**: se elige de una lista que mantiene el
administrador en *Configuración → Ciudades*. Cada ciudad cuelga de una
**provincia** de las que ya trae Odoo, y se muestra como `Sáenz Peña (Chaco)`.

El vendedor la elige, no la puede crear. Es lo que evita que la misma localidad
entre escrita de cinco formas y rompa los filtros y el mapa.

La provincia del cliente sale sola de la ciudad elegida: no se carga a mano y no
se puede contradecir.

### Fotos del DNI

Frente y dorso, en la ficha del cliente (no en la venta: el documento es de la
persona, no de cada compra, así que no se vuelve a fotografiar en la segunda
venta). Se redimensionan a 1600 px al guardar, para que cada foto de celular no
entre al filestore con varios megas.

Hay un filtro **"Sin foto de DNI"** en el buscador de clientes para reclamar la
documentación que falta. Se enciende recién con **las dos caras** cargadas: un
frente solo no alcanza.

### Notas e historial

La ficha **no tiene un campo de observaciones**. Las notas se registran en el
**historial** (el chatter de abajo, botón *Registrar nota*), donde cada una queda
con autor y fecha. Un campo libre que se pisa no deja rastro de quién escribió
qué ni cuándo.

Ese historial recibe además, automáticamente, los hechos de sus compras:

- Marca de retiro de una tarjeta, con el motivo
- Levantada de esa marca
- Retiro efectivo del mueble, con cuánto había pagado

### Antecedentes y clientes problemáticos

Cuando se empieza una venta, el sistema busca por DNI y, si el cliente ya
existe, **avisa** al vendedor:

- si está marcado como problemático, con motivo, fecha y quién lo marcó;
- si se le retiró algún mueble;
- si tiene cuotas vencidas en otras tarjetas.

**Avisa, no bloquea.** La decisión de venderle es del vendedor.

La ficha además *sugiere* la marca de problemático sola —se enciende si tuvo un
mueble retirado o tiene tarjetas en mora— pero **no marca nada**: marcar es
decisión del administrador.

Para marcarlo, el botón **Marcar problemático** abre un recuadro que pide el
motivo. No hay forma de marcar sin explicación.

---

## 6. Mercadería y ubicaciones

El módulo no inventa un stock paralelo: usa ubicaciones internas de Odoo.

| Ubicación | Para qué |
|---|---|
| `WH/Stock` | Fábrica. Stock vendible. |
| `Vendedores/<nombre>` | Lo que cada vendedor tiene en la calle. Se crea sola la primera vez que se le entrega. |
| `Recuperados` | Muebles retirados a clientes que dejaron de pagar. **No es stock vendible.** |
| `Clientes` (virtual, nativa) | Adonde sale el mueble cuando se vende. |

### Entregar y devolver

*Depósito → Entregar / recibir mercadería*. Un solo asistente con dos
direcciones:

- **Entrega al vendedor**: `WH/Stock → Vendedores/X`
- **Devolución a fábrica**: `Vendedores/X → WH/Stock`

Se cargan modelo y cantidad, y al confirmar se crea y valida el albarán, con una
notificación que lleva al albarán generado.

### Stock negativo

Con el ajuste **Permitir entregar sin stock** (activo por defecto) la entrega al
vendedor **no se traba** por falta de existencias: la fábrica suele terminar el
mueble después de que el vendedor se lo llevó. El faltante queda como **stock
negativo real** en `WH/Stock` y se regulariza cuando cierra la producción.

Dos cosas que **sí se siguen chequeando siempre**, aunque el ajuste esté activo:

- **La devolución del vendedor a fábrica**: aceptar más unidades de las que
  tiene a cargo inventaría stock que nunca estuvo en la calle.
- **La confirmación de una venta**: el vendedor no puede vender un mueble que no
  tiene a cargo.

> **Ojo al leer el stock:** `_get_available_quantity()` de Odoo **recorta los
> negativos a cero**. El `-3` está en el quant y se ve en Inventario, pero
> cualquier reporte que pregunte "cuánto hay disponible" va a leer `0`.

### Anular una entrega

Un albarán de entrega se puede revertir, pero **solo si la mercadería sigue en
destino**. Si el vendedor ya la vendió, la anulación se rechaza: revertirla
inventaría stock que ya no existe. En ese caso hay que corregir desde la tarjeta,
no desde la entrega.

---

## 7. La venta, paso a paso

### 7.1 Arranque por DNI

*Vendedor → Nueva venta* abre un asistente que pide **el documento**. Al buscar:

- Si el cliente existe: lo muestra y avisa de sus antecedentes.
- Si no existe: pide los datos para darlo de alta ahí mismo.

Después continúa al formulario de la venta con el cliente ya puesto.

> *Mis ventas* está primero en el menú a propósito. Al entrar a una aplicación
> Odoo abre sola la primera opción con acción permitida; con *Nueva venta*
> arriba, entrar al módulo disparaba el diálogo del DNI sin que nadie lo pidiera.
> Cargar una venta tiene que ser una decisión, no la pantalla de bienvenida.

### 7.2 Cargar la venta

- **Cliente** (ya viene del asistente)
- **Muebles**: una o varias líneas, cada una con su modelo, su plan y cantidad
- **Fecha de venta**
- **Día de cobro**: día del mes (1–31) si el plan es mensual, o día de la semana
  si es semanal
- **Cobrador** (opcional acá; se puede enrutar después)
- **Evidencia opcional**: ubicación GPS tomada en el domicilio y foto de la
  vivienda

Una venta con varios muebles puede combinar planes distintos **de la misma
frecuencia** (no se mezcla mensual con semanal en una tarjeta). Cada línea aporta
su importe a las cuotas 1..N de *su* plan: cuando un plan corto se termina, la
cuota baja. Por eso las cuotas no son todas iguales cuando hay planes distintos.

### 7.3 Confirmar

Al confirmar la venta, en una sola transacción:

1. Se chequea que el vendedor tenga la mercadería a cargo.
2. Se descuenta el mueble de `Vendedores/X` hacia `Clientes` con un albarán.
3. Se genera el calendario completo de cuotas.
4. La tarjeta pasa a **Enrutada** si ya tiene cobrador, o a **Vendida** si no.

**No se cobra la primera cuota automáticamente.**

### 7.4 Cobrar la entrega (comisión del vendedor)

La cuota 1 es del vendedor y vence el día de la venta. Se registra a mano desde
la tarjeta, porque puede cobrarse otro día o en partes:

- Sin monto: cobra todo lo que falta de la entrega.
- Con monto: cobra eso y el resto queda pendiente en la misma cuota.
- Se puede fechar distinto del día de la venta.

Queda como un cobro **a nombre del vendedor**, marcado como comisión.

**La comisión está separada del resto**: un cobro normal nunca la toca, el
cobrador no la ve como pendiente en su agenda, y **no entra en sus rendiciones**
(esa plata nunca pasó por la caja de la empresa).

### 7.5 Qué queda congelado

Al confirmar, **la mercadería de la tarjeta no se puede cambiar**. Precio,
cantidad de cuotas e importe quedan fijados por el plan. Solo un administrador
puede vender con valores distintos al plan, y lo hace antes de confirmar.

---

## 8. Calendario de cuotas

- **Cuota 1** vence **el día de la venta**. Es la entrega/comisión del vendedor.
- **Mensual**: la cuota 2 vence el día de cobro elegido, del **mes siguiente** al
  de la venta. Si el mes no llega a ese día (31 en febrero), vence el **último
  día del mes**.
- **Semanal**: la cuota 2 vence en la **próxima ocurrencia estricta** del día de
  la semana elegido (nunca el mismo día de la venta).
- El resto sigue de mes en mes o de semana en semana.
- Todas las cuotas valen lo que fija el plan.

Una cuota puntual se puede **postergar** a pedido del cliente sin tocar el resto
del calendario. Queda registrado en el historial de la tarjeta.

---

## 9. Enrutamiento y aceptación

**Enrutar** es mandarle la tarjeta a un cobrador. Dos caminos:

- Eligiendo el cobrador al cargar la venta.
- Desde *Vendedor → Sin cobrador*: se seleccionan varias tarjetas y se usa la
  acción *Enviar al cobrador*, todas al mismo.

La tarjeta queda **Enrutada**: el cobrador figura como destinatario, pero
**todavía no es responsable**.

**Aceptar** es lo que la hace entrar a la cartera. *Cobrador → Pendientes de
aceptar*, se pueden aceptar varias juntas. La tarjeta pasa a **En cobranza**.

**Rechazar** exige un motivo, en un recuadro. La tarjeta vuelve al vendedor y el
motivo queda visible en la ficha.

**Transferir cartera** (solo administrador) mueve tarjetas de un cobrador a
otro, por ejemplo cuando alguien se va o se reparte una zona.

---

## 10. Cobranza

### Agenda de cobro

*Cobrador → Agenda de cobro*. Lista las cuotas **de su cartera** que vencen hoy o
quedaron atrasadas. Trae por cada una:

- Cliente, dirección y **celular** (en el teléfono es un link que llama)
- Número de cuota, vencimiento, importe a cobrar y saldo total de la tarjeta
- Botón de **mapa**: usa el GPS tomado en la venta y, si no hay, la dirección del
  cliente como respaldo. Un campo indica cuál de las dos se está usando, para
  que el cobrador no confunda un respaldo con una ubicación tomada en el lugar.

La agenda solo muestra cuotas de tarjetas **En cobranza**, y nunca la comisión.

### Registrar un cobro

Desde la agenda, desde la tarjeta o desde *Cobros*. Se carga el monto, la fecha y
una observación opcional.

### Cómo se imputa

Un cobro se reparte **automáticamente** sobre las cuotas impagas de la tarjeta,
**en orden de vencimiento (FIFO)**:

- Soporta **pago parcial**: la cuota queda en estado *Parcial*.
- Soporta **pagar varias cuotas de una vez**: se van saldando en orden.
- Un cobro que **supere el saldo** de la tarjeta se **rechaza** (no queda plata
  sin imputar).
- Un cobro de comisión solo toca la cuota de comisión; un cobro normal solo toca
  las de cobranza.

### Anular

Un cobro registrado **no se puede borrar**: solo **anular**, y queda el registro
con quién y cuándo. Al anular se liberan sus imputaciones y la tarjeta vuelve a
mostrar el saldo.

Un cobro **ya rendido** no se puede anular: está respaldado por plata entregada
en caja. Primero hay que reabrir la rendición.

---

## 11. Rendiciones de caja

La rendición es la entrega de la plata cobrada. Cada una cubre un período que
sale de la **frecuencia configurada** (diaria, semanal o mensual).

### El flujo

| Paso | Quién | Qué pasa |
|---|---|---|
| **Borrador** | Cobrador | Se crea la rendición y con *Reunir cobros* se enganchan todos sus cobros pendientes |
| **Entregada** | Cobrador | Declara cuánto entrega. El sistema calcula la diferencia contra lo esperado |
| **Aprobada** | Administrador | Cierra la rendición. Queda quién la revisó y cuándo |
| **Con diferencia** | Administrador | Aprueba dejando la diferencia registrada **y explicada** (exige observación) |

Una rendición se puede **volver a borrador**, lo que libera sus cobros para que
entren en otra.

### Detalles que importan

- **No tiene límite inferior de fecha a propósito**: un cobro cargado tarde, con
  fecha de un período ya rendido, entra en la próxima rendición abierta en vez de
  quedar huérfano. Lo que define si un cobro ya se rindió es estar enganchado a
  una rendición, no su fecha.
- **Las comisiones quedan afuera.** La primera cuota es del vendedor: nunca entra
  a la caja de la empresa, así que reclamársela sería pedirle plata propia. Esto
  importa cuando alguien es vendedor **y** cobrador a la vez.
- Se cuentan aparte los **cobros cargados tarde** (con fecha anterior al período).
- *Administración → Diferencias por cobrador* junta las rendiciones que no
  cuadraron.

---

## 12. Mora, retiro y recuperación

### Mora

Una cuota pasa a **Vencida** cuando su vencimiento quedó atrás por más de los
**días de tolerancia** configurados. Un **cron diario** recalcula las vencidas y
la antigüedad de la deuda de cada tarjeta.

Por tarjeta se guarda:

- **Días de mora**: los de la cuota impaga más vieja.
- **Monto vencido**: la suma de los residuales vencidos, **sin contar la
  comisión** (esa no es deuda del cliente).

*Administración → Clientes en mora* lista las tarjetas con cuotas vencidas.

### El retiro son DOS pasos

Esto es lo que más confunde:

**Paso 1 — Marcar para retiro.** Botón *Marcar para retiro* en la tarjeta. Abre
un recuadro que **pide el motivo**. Es una **marca, no un estado**: la tarjeta
sigue en cobranza y **la mercadería no se mueve**. Si el cliente aparece y paga
antes de que vayas a buscarlo, se levanta la marca y no hay nada que deshacer.

**Paso 2 — Registrar retiro.** Botón azul que aparece recién después de marcar.
**Este es el que mueve el mueble.** Pide confirmación y entonces:

1. Genera un albarán `Clientes → Recuperados`.
2. Las cuotas que quedaban sin cobrar pasan a **Cancelada**.
3. La tarjeta queda con **saldo cero** y pasa a **Retirada**.
4. Se guarda **cuánto había pagado el cliente** hasta ese momento.
5. Queda asentado en el historial de la tarjeta **y en el del cliente**.

> Si marcaste y el mueble no aparece en *Muebles retirados*, es porque falta el
> paso 2.

### Qué pasa con la plata

**No se devuelve nada.** La deuda se da por perdida junto con el mueble:

- Las cuotas pendientes quedan **Canceladas** y no se reclaman más.
- La tarjeta muestra **saldo 0** — no es deuda viva.
- Lo cobrado queda en **Cobrado al retirar**.
- **La pérdida es**: `total de la tarjeta − cobrado al retirar`. Cuota por cuota,
  es el residual de cada cancelada.
- Una cuota **ya pagada** queda *Pagada*, no cancelada.
- Intentar cobrar una tarjeta retirada da un error explícito: *"sus cuotas se
  cancelaron y no se cobran más"*.

### El stock de retirados

El mueble entra a la ubicación **`Recuperados`**, que **no es stock vendible**:
uno usado no es el mismo producto que uno nuevo, y mezclarlos falsearía la
disponibilidad de fábrica.

Se ve en *Depósito → Muebles retirados*, agrupado por modelo. Para saber de qué
venta salió cada uno, el filtro *Retiradas* en *Todas las tarjetas*.

---

## 13. Supervisión

Un supervisor audita la cobranza de otros.

**Asignaciones** (*Supervisión → Asignaciones*, solo administrador): qué
cobradores audita cada supervisor y **entre qué fechas**. La asignación es
temporal: el supervisor ve la cartera de sus cobradores **mientras la asignación
esté vigente hoy**, siempre en solo lectura. Nadie puede auditarse a sí mismo.

**Visitas** (*Supervisión → Visitas*): el supervisor arma una visita eligiendo
cobrador y período. Con *Cargar tarjetas* trae la cartera de ese cobrador en ese
período, y marca cada una como **verificada** y, si corresponde, **con
observación** (que exige escribir qué pasó).

Al **cerrar** la visita queda el resultado —conforme o con observaciones— con el
recuento de tarjetas revisadas y de observaciones. Una visita cerrada se puede
reabrir para corregirla.

---

## 14. Tablero de indicadores

*Venta en cuotas → Dashboard*, solo para administradores. Filtra por rango de
fechas y por empresa.

**Indicadores**: vendido, cantidad de tarjetas, saldo por cobrar, cobrado,
cantidad de cobros, monto vencido, cuotas vencidas, **tasa de mora**, muebles
retirados y tarjetas marcadas para retiro.

**Gráficos**:

- Ventas por vendedor y por mes
- Cartera por cobrador (asignado vs. cobrado)
- Mora por antigüedad (*aging*)
- Rendiciones con diferencia
- Mercadería en poder de vendedores

**Mapa** con los domicilios, **listados** paginados de ventas y cuotas, y
**exportación a CSV**.

### Validaciones

El tablero solo permite elegir empresas a las que el usuario tiene acceso. Los
listados aceptan únicamente las pestañas publicadas (ventas o cuotas); la página
debe ser un entero ≥ 1 y la cantidad por página un entero entre 1 y 200. Los
valores inválidos se rechazan con un error funcional, sin corregir la consulta
por atrás.

---

## 15. Configuración

*Venta en cuotas → Configuración → Ajustes*. Todo es **por empresa**.

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| **Cuotas por defecto** | 12 | Se propone al cargar una venta nueva |
| **Días de tolerancia de mora** | 0 | Atraso tolerado antes de marcar una cuota como vencida |
| **Frecuencia de rendición** | Diaria | Diaria, semanal o mensual: define el período que cubre cada rendición |
| **Frecuencias permitidas** | Ambas | Mensual, semanal o ambas para los planes |
| **Exigir celular** | Sí | Obliga a cargar el celular del cliente |
| **Exigir dirección** | Sí | Obliga a cargar la dirección |
| **Exigir ciudad** | Sí | Obliga a elegir ciudad |
| **Exigir código postal** | Sí | Obliga a cargar el CP |
| **Exigir fotos del DNI** | No | Obliga a cargar frente y dorso |
| **Permitir entregar sin stock** | Sí | La entrega al vendedor no se traba por falta de stock; el faltante queda negativo en fábrica |

Además, *Configuración → Ciudades*: el padrón de ciudades con su provincia.

---

## 16. Los cuatro estados

### Tarjeta (`cvi.card`)

```
Borrador ──confirmar──► Vendida ──enrutar──► Enrutada ──aceptar──► En cobranza
    │                      │                     │                      │
    │                      │                  rechazar                  │
    │                      │◄────────────────────┘             saldo 0  │
  anular                                                          ┌─────┴─────┐
    │                                                             ▼           ▼
    ▼                                                        Finalizada   Retirada
  Anulada                                                                (registrar
                                                                          retiro)
```

Si al confirmar ya tiene cobrador, salta directo a **Enrutada**.
Una tarjeta Finalizada vuelve a **En cobranza** si se anula un cobro y reaparece
saldo. Anular solo se puede desde Borrador o Vendida.

### Cuota (`cvi.installment`)

| Estado | Cuándo |
|---|---|
| **Pendiente** | Sin cobrar y sin vencer |
| **Parcial** | Cobrada en parte |
| **Pagada** | Residual en cero |
| **Vencida** | Pasó el vencimiento más la tolerancia, y falta cobrar |
| **Cancelada** | El mueble se retiró y esta cuota había quedado sin cobrar |

El estado es **calculado**: sale de los montos y la fecha, no se toca a mano.

### Cobro (`cvi.payment`)

`Borrador → Registrado → Anulado`. Al registrar se imputa; al anular se liberan
las imputaciones. No se borra nunca.

### Rendición (`cvi.settlement`)

`Borrador → Entregada → Aprobada` (o **Con diferencia**). Se puede volver a
Borrador, lo que libera sus cobros.

---

## 17. Numeración

| Documento | Prefijo | Ejemplo |
|---|---|---|
| Tarjeta | `TARJ/` | `TARJ/000001` |
| Cobro | `COB/` | `COB/000001` |
| Rendición | `REND/` | `REND/000001` |
| Visita de supervisión | `SUP/` | `SUP/000001` |

Los albaranes usan la numeración nativa de Odoo (`WH/INT/`, `WH/OUT/`, `WH/IN/`).

---

## 18. Automatismos

**Cron diario "Venta en cuotas: marcar cuotas vencidas"**. Recalcula el estado de
las cuotas vencidas abiertas y la antigüedad de la mora de sus tarjetas.

Existe porque el estado de la cuota depende de **la fecha de hoy**, que no es un
campo: sin el cron, una cuota marcada vencida ayer no envejecería sola. Solo
recorre cuotas impagas de tarjetas abiertas (no toca pagadas, retiradas ni
finalizadas).

---

## 19. Qué te va a rechazar el sistema y por qué

| Te rechaza | Por qué |
|---|---|
| Vender sin cargar el DNI del cliente | El DNI es la identidad; sin él el historial de antecedentes no sirve |
| Confirmar una venta sin mercadería a cargo del vendedor | No se puede vender lo que no se tiene; primero registrá la entrega |
| Cambiar los muebles de una tarjeta confirmada | La venta ya está cerrada y el calendario generado |
| Un cobro mayor al saldo de la tarjeta | Quedaría plata sin imputar |
| Borrar un cobro registrado | Solo se anula, y queda constancia |
| Anular un cobro ya rendido | Está respaldado por plata entregada; reabrí la rendición primero |
| Marcar para retiro sin motivo | Una marca sin explicación no sirve para nada |
| Marcar para retiro una tarjeta que no está en cobranza | No se retira mercadería de una venta que todavía no salió a cobrar |
| Registrar un retiro sin haber marcado antes | El retiro es la segunda mitad de una decisión que se toma primero |
| Cobrar una tarjeta retirada | Sus cuotas se cancelaron |
| Devolver a fábrica más de lo que el vendedor tiene a cargo | Inventaría stock que nunca estuvo en la calle |
| Anular una entrega cuya mercadería ya se vendió | Inventaría stock que ya no existe |
| Aprobar una rendición con diferencia sin explicarla | La diferencia sin motivo no es auditable |
| Un supervisor auditándose a sí mismo | No es auditoría |
| Crear una ciudad siendo vendedor | El padrón lo mantiene administración, para que no entre cinco veces escrita distinto |

---

## 20. Preguntas frecuentes

**Marqué el mueble para retiro y no aparece en *Muebles retirados*.**
Falta el segundo paso: el botón **Registrar retiro**. Marcar es solo el aviso de
que hay que ir a buscarlo.

**El cliente pagó y la tarjeta sigue mostrando saldo.**
Fijate si el cobro quedó en *Borrador*: se imputa recién al registrarlo.

**El cobrador no ve una tarjeta que le enruté.**
Tiene que **aceptarla** desde *Pendientes de aceptar*. Enrutada todavía no es
suya.

**La comisión del vendedor no aparece en la agenda del cobrador.**
Correcto: la primera cuota es del vendedor y está separada a propósito. Tampoco
entra en sus rendiciones.

**Entregué mercadería que el depósito no tenía y no se quejó.**
Es el ajuste *Permitir entregar sin stock*. El faltante quedó como negativo en
`WH/Stock`.

**Inventario me muestra 0 pero yo entregué de más.**
El negativo está en el quant, pero la "cantidad disponible" que reporta Odoo
recorta los negativos a cero. Miralo en la ubicación, no en el disponible.

**Cargué el mismo cliente dos veces.**
No deberías haber podido: el DNI es único por empresa. Si pasó, es que se cargó
con documentos distintos.

**Anulé un cobro y la tarjeta volvió a En cobranza.**
Es correcto: reapareció saldo, así que deja de estar finalizada.

---

## 21. Para desarrolladores

### Estructura

```
collections_from_vendors_installments/
  models/          un archivo por modelo (cvi_card.py, cvi_installment.py, ...)
  wizards/         asistentes (venta, cobro, enrutar, transferir, retiro, ...)
  controllers/     endpoints JSON del tablero
  views/           vistas y menús
  security/        grupos, reglas de registro y ACL
  data/            secuencias, cron, ubicaciones
  migrations/      scripts por versión
  static/src/      OWL del tablero
  tests/           ~493 pruebas
```

### Correr las pruebas

```bash
docker exec odoo-odoo-1 odoo -d <base> -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http
```

### Actualizar

```bash
docker exec odoo-odoo-1 odoo -d <base> -u collections_from_vendors_installments \
  --stop-after-init --no-http
docker restart odoo-odoo-1   # el proceso vivo mantiene el Python que importó al arrancar
```

Hacer **respaldo antes**: varias migraciones mueven datos y Odoo 18 **borra la
columna** de un campo eliminado al terminar la actualización.

### Concurrencia de cobros

Una prueba con dos cursores PostgreSQL reales verifica la garantía bajo el
aislamiento `REPEATABLE READ` de Odoo: dos cobros concurrentes no pueden imputar
más que el saldo de una misma cuota. Uno se confirma y el otro recibe un
conflicto de serialización; al reintentar ve el saldo actualizado y se rechaza si
excede la deuda. **No se agregó un bloqueo de aplicación adicional** porque la
prueba demostró que no hace falta.

### Decisiones de diseño que conviene no revertir sin leer

- **El cliente no es `res.partner`.** Es un modelo propio con el DNI como
  identidad, porque el circuito necesita unicidad por documento y antecedentes
  propios.
- **El estado de la cuota es calculado y almacenado**, y depende de la fecha de
  hoy: de ahí el cron.
- **`amount_residual` de la cuota no depende del estado de la tarjeta.** Se
  intentó y rompía el borrado: es un campo `Monetary` y necesita `currency_id`
  para escribirse, así que al borrar una tarjeta el flush moría con
  `MissingError` sobre cuotas ya eliminadas. El saldo cero de una tarjeta
  retirada se resuelve en el cálculo de **la tarjeta**.
- **Los computes de las líneas van separados, uno por campo.** La protección de
  Odoo contra pisar valores explícitos es a nivel de método: con uno solo,
  pasar `installment_amount` en el create saltearía también el cálculo de los
  otros dos.
- **`sudo()` solo para la parte privilegiada.** El vendedor no recibe el grupo de
  Inventario; los chequeos corren con el usuario real y solo el alta y la
  validación del albarán van con sudo.
