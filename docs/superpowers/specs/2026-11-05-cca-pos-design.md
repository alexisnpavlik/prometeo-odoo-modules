# Cuenta corriente desde el POS — diseño

Fecha: 2026-11-05 · Módulo base: `customer_checking_account` (prefijo `cca.`) · Base de uso: `kiosco`

## Por qué

En el kiosco se fía todos los días. Hoy un retiro a cuenta corriente se carga desde el backend,
producto por producto en el formulario de `cca.withdrawal`, y es lento comparado con el POS, donde
se escanea o se busca en la grilla. Además, cuando un cliente viene a pagar una cuota, la plata
entra a la caja física pero el pago se registra fuera del POS: al cerrar la sesión la caja no cuadra.

Se agregan dos cosas al POS:

1. **Vender a cuenta corriente**: armar el pedido en el POS y, en la pantalla de pago, mandar
   todo o parte del total a la cuenta corriente del cliente con su financiación (recargo, cuotas,
   primera fecha, frecuencia).
2. **Cobrar cuotas**: registrar en el POS el pago de un cliente con un producto
   "Pago Cuenta Corriente", cobrado con cualquier medio de pago, para que la sesión cuadre y el
   pago se impute por FIFO en la cuenta corriente.

## Objetivos

- Un pedido del POS validado con el medio de pago de cuenta corriente genera un `cca.withdrawal`
  **confirmado**, con sus cuotas, visible en la cuenta del cliente como cualquier retiro.
- Recargo %, cantidad de cuotas, fecha de la primera cuota y frecuencia se eligen en el POS en
  el momento de cobrar, precargados con valores por defecto configurables.
- Un pedido con el producto "Pago Cuenta Corriente" genera un `cca.payment` imputado por FIFO
  (el mismo `_cca_allocate_fifo` que usa el backend).
- La caja del POS cuadra: todo lo que entra físicamente pasa por un pedido del POS.
- El stock baja **una sola vez**, por el albarán propio del pedido del POS.

## No-objetivos

- Coherencia contable entre POS y cuenta corriente. El módulo base no genera asientos y eso no
  cambia. El POS seguirá generando sus asientos al cerrar sesión (cuenta a cobrar del medio diferido,
  ingreso del producto de pago); nadie los concilia contra `cca.`.
- Editar retiros o cuotas desde el POS. La edición sigue en el backend.
- Uso offline del POS para estas dos funciones. Requieren conexión (límite de crédito, saldo).
- Facturación electrónica AFIP de estos pedidos. `l10n_ar_pos_afipws_fe` no está instalado en
  `kiosco`; si algún día lo está, se revisa aparte.

## Anti-objetivos (sería un fracaso aunque funcione)

- Que el stock baje dos veces (albarán del POS + albarán o `sale.order` del retiro).
- Que los cobros de cuotas inflen las ventas en `pos_management_metrics` / `pos_cash_metrics`.
- Que un pedido pagado a cuenta corriente quede en el POS pero sin retiro (o al revés) por un
  error a mitad de camino: retiro y pedido se crean en la misma transacción, o falla todo.
- Que el cajero tenga que salir del POS para cualquiera de las dos operaciones.

## Decisiones tomadas

### Con Alexis

- **Financiación configurable en el POS**: popup con recargo %, cuotas, primera fecha y frecuencia,
  precargado con valores por defecto, editable en cada venta.
- **Cobro de cuotas por producto**: producto de servicio "Pago Cuenta Corriente"; el precio lo
  carga el cajero; se cobra con cualquier medio de pago del POS.

### Llamadas mías (corregibles)

- **Módulo puente nuevo `customer_checking_account_pos`** que depende de
  `customer_checking_account` y `point_of_sale`, con `auto_install: True`. El módulo base no pasa a
  depender del POS (hay bases sin POS). Layout y convenciones según el skill `odoo-prometeo-modules`.
- **Valores por defecto por empresa** (no por punto de venta), en `res.company` y expuestos en la
  app propia de Ajustes del módulo base, sección nueva "Punto de venta" (ver memoria "Ajustes en app
  propia"): `cca_pos_surcharge_percent`, `cca_pos_installment_count`, `cca_pos_first_due_days`
  (días desde hoy para la primera cuota) y `cca_pos_frequency`.
- **Medio de pago**: un booleano nuevo `cca_is_checking_account` en `pos.payment.method`. Solo es
  válido en métodos de pago diferido (sin `journal_id`, `split_transactions` = True), que ya exigen
  cliente. En `kiosco` se marca el existente "Cuenta de cliente" (id 4). Más de un método marcado
  por POS no tiene sentido; se valida.
- **Producto de pago**: `product_cca_pos_payment` en `data/`, tipo servicio, `available_in_pos`,
  sin impuestos, precio 0, con `noupdate`. Se referencia por xmlid.
- **Pago mixto**: si el total del pedido se paga parte con otros medios y parte con cuenta
  corriente, el retiro lleva todas las líneas del pedido y la parte pagada con otros medios entra
  como **entrega inicial** (`down_payment`). El recargo se aplica solo sobre lo financiado, como ya
  calcula `_compute_amounts`. Medio de la entrega (`down_payment_method`): se mapea desde el medio
  del POS (efectivo si `is_cash_count`, si no `other`; ver mapeo abajo).
- **Precio de las líneas del retiro**: `price_subtotal_incl / qty` de la línea del POS, o sea, lo que
  vio el cliente con IVA y descuentos/promos incluidos. Así la deuda coincide con el ticket.
- **Límite de crédito**: se reutiliza `_cca_check_limit`. En modo `block` el POS muestra el error y
  no valida; en modo `warn` muestra el aviso y deja seguir.
- **Saldo en el POS**: al elegir un cliente que tiene cuenta, el POS muestra saldo y monto vencido
  (en el popup de financiación y al agregar el producto de pago). Se piden por RPC, no se cargan en
  los datos iniciales del POS.
- **Recibos**: no se imprime el reporte QWeb del módulo base desde el POS. El ticket del POS agrega
  una línea con el número de retiro o de pago `cca.` y, para pagos, el saldo que queda.

## Comportamiento

### Parte 1: venta a cuenta corriente

1. El cajero arma el pedido como siempre y elige el cliente.
2. En la pantalla de pago agrega el medio de cuenta corriente con el monto a financiar (puede ser
   todo o el resto después de un pago en efectivo).
3. Al agregar ese medio (o al validar, lo que el builder vea más simple en OWL) se abre el popup de
   financiación: recargo %, cuotas, primera fecha, frecuencia, con los valores por defecto. Muestra
   en vivo el recargo, el total financiado, el monto de cada cuota, y el saldo actual del cliente.
4. Los valores elegidos viajan con el pedido al backend (campos nuevos en `pos.order` o un JSON;
   elección del builder).
5. Al sincronizar el pedido (`sync_from_ui` / `_process_order` de Odoo 18), en el servidor, dentro
   de la misma transacción:
   - se obtiene la cuenta con `cca.account._get_or_create(partner, company)`;
   - se crea el `cca.withdrawal` con las líneas, la financiación, `down_payment` y un vínculo
     `pos_order_id`;
   - se confirma con un camino que **no** llama a `_cca_create_sale_order` ni crea albarán
     (por ejemplo, una bandera de contexto o un método `_cca_confirm_from_pos`); el resto de la
     confirmación (`_cca_check_limit`, `_cca_regenerate_installments`, `_cca_register_down_payment`,
     `_cca_after_confirm`) corre igual;
   - el `picking_id` del retiro apunta al albarán del pedido del POS cuando exista (si se crea al
     cerrar sesión, queda vacío; es informativo).
6. El `pos.order` guarda `cca_withdrawal_id` y el retiro `pos_order_id`; ambos visibles con un link
   en sus formularios.

### Parte 2: cobro de cuotas

1. El cajero elige el cliente y agrega el producto "Pago Cuenta Corriente" con el monto recibido
   como precio (el POS muestra saldo y vencido del cliente al agregarlo).
2. Cobra con cualquier medio (efectivo, tarjeta, transferencia, Mercado Pago).
3. Al sincronizar el pedido se crea un `cca.payment` por el subtotal de esas líneas, con
   `ref` = nombre del pedido del POS, `pos_order_id` y el medio mapeado, y se imputa por FIFO
   (el `create` normal ya lo hace salvo con `cca_no_auto_allocate`).
4. Si el pago supera la deuda, el sobrante queda como saldo a favor (comportamiento actual).

Mapeo de medio POS → `payment_method` de `cca.`: `is_cash_count` → `cash`; resto → `other`, salvo
que el builder encuentre una forma confiable (sin depender del nombre) de distinguir tarjeta y
transferencia. Si un pedido tiene varios medios, el `cca.payment` usa el del monto mayor.

### Validaciones en el POS (antes de enviar) y en el servidor (siempre)

- Medio de cuenta corriente o producto de pago sin cliente → bloquea.
- Cliente sin DNI/CUIT (`vat` vacío) → bloquea. Es la misma regla que el backend.
- Medio de cuenta corriente **y** producto de pago en el mismo pedido → bloquea.
- Producto de pago con monto ≤ 0 → bloquea.
- Límite de crédito en modo `block` → bloquea con el mensaje de `_cca_check_limit`.

El servidor repite todas las validaciones; el POS las anticipa para no perder el pedido en la cola
de sincronización.

### Reembolsos y anulaciones (decidido con Alexis)

- **La única forma de anular una venta a cuenta corriente es el reembolso en el POS.**
- El reembolso tiene que **replicar los medios del pedido original**: la parte financiada vuelve
  por el medio de cuenta corriente (monto negativo) y la entrega por el medio con que se pagó.
  El POS lo valida en la pantalla de pago del reembolso; el servidor lo repite.
- Un pedido de reembolso (líneas con `refunded_orderline_id`) pagado con el medio de cuenta
  corriente **no crea un retiro**: cancela el retiro del pedido original (`action_cancel` sin
  devolución de stock propia; la devolución del POS ya mueve el stock). Si el retiro tiene pagos
  imputados, `action_cancel` lo impide y el reembolso falla con ese mensaje.
- Reembolso de un pedido con producto de pago → `action_cancel` del `cca.payment`.
- Reembolsos parciales: no se soportan; si el reembolso no cubre todas las líneas, bloquea con un
  mensaje que mande a resolverlo en el backend.

### Retiros del POS en el backend (decidido con Alexis)

Un retiro con `pos_order_id` en el backend solo permite editar **financiación, vencimientos y
mora**. Quedan bloqueados (botones ocultos y `UserError` en el servidor):

- `action_edit` en su variante "vuelve a borrador" (la que devuelve stock y regenera todo);
  la variante "solo vencimientos" sigue disponible.
- `action_draft` y la reconfirmación.
- `action_cancel` directo: el mensaje manda a hacer el reembolso en el POS.
- Cambios de líneas o de cliente.

Ninguno de estos caminos puede crear `sale.order`, albarán ni devolución para un retiro del POS.

### Métricas

`pos_management_metrics` y `pos_cash_metrics` excluyen las líneas del producto de pago de las
ventas, igual que hoy excluyen `surcharge_product_id` / `discount_product_id` (subconsulta
condicionada a que exista el xmlid/tabla, porque no todas las bases tienen el módulo puente).
Las ventas a cuenta corriente **sí** cuentan como ventas.

## Restricciones

- Odoo 18, POS en OWL; patches con `@web/core/utils/patch`; assets en `point_of_sale._assets_pos`.
- Usuarios del POS no necesariamente están en `group_cca_user`: las escrituras en `cca.` desde la
  sincronización del pedido van con `sudo()` acotado, siguiendo el patrón del módulo base.
- `kiosco` tiene `pos_block_zero_price`: el producto de pago con precio 0 por defecto no debe quedar
  bloqueado de forma que el cajero no pueda cargar el monto; verificar la interacción.
- `kiosco` tiene `pos_promotions` y `pos_restaurant`: probar que las líneas de promo y los pedidos
  de restaurante no rompen la creación del retiro.
- Tests en la base scratch `cca_test` (necesita `point_of_sale` instalado) o una nueva; nunca en
  `prod`. Verificación visual en `kiosco`.

## Verificado en código y en `kiosco` (revisión del diseño)

- `_process_saved_order` loguea y traga excepciones de `action_pos_order_paid`: el enganche va donde
  los errores se propaguen. Un `UserError` del servidor vuelve el pedido a borrador en el POS y
  muestra el error, así que "falla todo junto" es viable.
- `cca.withdrawal.line` rechaza precios negativos. En `kiosco` no hay `pos_global_discount_button`
  ni `pos_global_surcharge_button`, y `pos_promotions` aplica descuento % por línea. Igual: si un
  pedido trae una línea negativa, se bloquea con mensaje claro.
- Las compañías de `kiosco` usan stock `real`: el albarán del POS se crea al validar el pedido.
- "Cuenta de cliente" (id 4) solo está en el POS "Mueblería". Hay que agregarlo al POS que use el
  kiosco. Tiene un pedido histórico; no se migra.
- `checking_account_withdrawals` (`caw.`) también está instalado en `kiosco`, pero no toca el POS.

## Queda en manos del builder

- Dónde exactamente se engancha el servidor (`_process_order`, `_process_saved_order`, override de
  `sync_from_ui`) y cómo guarda los datos de financiación en el pedido.
- Diseño del popup OWL y en qué momento se abre.
- Cómo se marca el camino "confirmar sin venta ni albarán" en el módulo base sin romper sus 78
  tests.
- Seguridad fina: qué accesos necesita el usuario POS para los RPC de saldo.
