# pos_deletion_reason_log — Diseño

**Fecha:** 2026-07-22
**Odoo:** 18.0
**Repo:** prometeo-odoo-modules

## Objetivo

Trazabilidad de operaciones sensibles del cajero en el POS: eliminación de
orden completa, eliminación de línea/producto, reducción de cantidad,
descuento por encima de un umbral, y reducción de precio de línea. En cada
caso se pide un **motivo** (justificación) y queda un **registro** en el
backend con el motivo, el cajero, el producto y el momento — aunque la orden
nunca llegue a sincronizarse al servidor.

> **Nota de evolución:** el módulo nació como "solo eliminaciones"
> (`pos.deletion.log` / `deletion_type`) y se generalizó a trazabilidad
> completa. El modelo de registro se renombró a **`pos.control.log`**
> (campo `event_type`); el modelo de motivos configurable se mantuvo como
> `pos.deletion.reason` (nombre ya usado en producción, sigue siendo
> genérico). El nombre del módulo/carpeta (`pos_deletion_reason_log`) y del
> maestro de motivos quedaron así por continuidad, aunque el alcance ya no es
> solo eliminaciones.

Convive con `pos_special_approval_omax` (que ya pide aprobación de manager al
eliminar) pero **no depende de él**: el módulo es standalone.

## Alcance

Eventos que piden motivo y quedan registrados (cada uno con toggle propio):

1. **Eliminar orden completa** — `PosStore.deleteOrders(orders, serverIds)`. Es
   el choke point real (no `onDeleteOrder`, que internamente lo llama con un
   array de 1 elemento): también lo usa el popup de cierre de caja cuando
   queda una orden sin finalizar y el cajero elige "Cancelar órdenes"
   (`ClosingPopup.handleClosingError`, rama `cancel`). Un solo motivo cubre
   todo el lote si hay más de una orden. La llamada de sync en background
   (`syncAllOrders` → `deleteOrders([], orderIdsToDelete)`, orders vacío) no
   pide motivo — no es una decisión nueva del cajero, es una baja ya resuelta
   sincronizándose con el servidor.
2. **Eliminar línea/producto** — `OrderSummary._setValue` con `remove`.
3. **Reducir cantidad de una línea** — capturado en `PosStore.selectOrderLine`
   (baseline al seleccionar, comparación al deseleccionar).
4. **Descuento alto** — línea cuyo descuento supera `high_discount_threshold`
   (config, default 30%; hasta 30 inclusive no pide) durante la edición.
   Mismo mecanismo de baseline/
   comparación que cantidad, sobre `line.get_discount()`.
5. **Reducción de precio** — línea cuyo precio baja respecto al que tenía al
   seleccionarla (`line.get_unit_price()`). Mismo mecanismo.

Los eventos 3, 4 y 5 comparten el mismo choke point (`selectOrderLine`) porque
el numpad de Odoo 18 dispara valores intermedios tecla por tecla; pedir el
motivo ahí interrumpiría al cajero a mitad de tipeo. Por eso estos tres son
"ask-after" (se pide el motivo al deseleccionar la línea, comparando contra
el estado capturado al seleccionarla) y no "ask-before" como los eventos 1 y 2.
Si el cajero cancela el motivo, el cambio puntual se revierte (cantidad,
descuento o precio, cada uno independiente).

Fuera de alcance (v1): registrar qué manager aprobó (se descartó para no acoplar
al módulo de aprobación).

## Arquitectura

Módulo independiente. `depends: ['point_of_sale']`. Frontend: patches
motivo-primero sobre los mismos puntos que parchea el módulo de aprobación.
Si el módulo de aprobación está instalado, ambos patches se apilan
(motivo → aprobación → eliminación); si no, el nuestro funciona igual solo.

### Flujo por evento (ej. eliminar orden)

1. Si el toggle del evento está activo → tomar *snapshot* de la orden
   (ref/uid, productos, cantidades, total) **antes** de tocar nada.
2. Mostrar **popup de motivo** (dropdown configurable + textarea opcional).
   Si el usuario cancela → abortar, no se elimina ni se registra.
3. `await super(...)` → corre la lógica base (y la aprobación de manager si el
   otro módulo está instalado) y elimina.
4. Verificar que la orden/línea **realmente** se eliminó (ya no está en
   `pos.orders` / la línea ya no existe). Si sí → RPC al backend con el registro.

### Excepción: reducción de cantidad (no es motivo-primero)

Descubierto durante la implementación (Task 6, revisión final de branch): el
numpad del POS de Odoo 18 dispara `OrderSummary._setValue` **en cada tecla**
tecleada, no al confirmar el valor final. Interceptarlo ahí para pedir motivo
hacía que el popup apareciera con el primer dígito (ej. escribir "12" sobre
una línea con cantidad 50 disparaba el popup al ver "1", interpretándolo como
una reducción de 49 unidades, antes de que el cajero terminara de escribir).

Por eso, **solo para este evento**, el flujo es ask-after-en-vez-de-antes:
1. Al seleccionar una línea (`PosStore.selectOrderLine`, el único choke point
   por el que pasan tanto el click manual como el auto-select al agregar/
   mergear productos) se guarda su cantidad de partida.
2. Al deseleccionarla (se elige otra línea, o se agrega/mergea otro producto)
   se compara la cantidad final contra la guardada.
3. Si bajó → se pide motivo. Si confirma, se registra. Si cancela, se
   **revierte** la cantidad (a diferencia de los otros 2 eventos, acá el
   cambio ya se aplicó en vivo mientras el cajero tecleaba).
4. Corre en background (no bloquea el cambio de línea), porque el código base
   de Odoo llama a `selectOrderLine` sin `await` en varios lugares y espera
   que la selección ya haya cambiado sincrónicamente justo después.

   Si no (rechazado/cancelado) → no registrar.

**Cierre del bypass "editar y cobrar directo"** (era limitación v1): si el cajero
editaba la última línea tocada y ese cambio se cobraba sin volver a seleccionar
otra línea, nunca se disparaba la verificación. `PosStore.pay()` ahora hace
`await this._resolvePendingLineChanges(...)` antes de seguir, así que el cobro
queda bloqueado hasta resolver el motivo. Acá sí se espera la resolución (a
diferencia de `selectOrderLine`, que corre en background a propósito).

**Descuento global** (`pos_discount`): no pasa por el control por línea, porque
en vez de tocar `line.discount` agrega una línea con el producto de descuento y
precio negativo — `get_discount()` nunca lo ve. Se controla aparte en
`static/src/js/control_buttons.js`, patch de `ControlButtons.apply_discount(pc)`:
el porcentaje llega explícito, así que es **ask-before** (si el cajero cancela,
el descuento simplemente no se aplica, sin revert). Se registra como
`high_discount` con `discount_percent = pc` y `amount_removed` = suma de las
líneas del producto de descuento. **`pos_discount` es dependencia obligatoria en
el manifest**: su patch de `apply_discount` no llama a `super`, así que el
nuestro solo funciona si carga después, y el orden de assets lo determina el
grafo de dependencias (sin la dependencia, alfabéticamente cargaría antes y
quedaría anulado). Ojo: agregar una dependencia nueva requiere
`ir.module.module.update_list()` — un `-u` normal no la registra.

**Cierre del bypass "cancelar el popup con la X/Escape"**: `askReason` resolvía
`null` mediante un prop `close`, pero el servicio de diálogos hace
`subProps: {...props, close}` y lo pisaba. Cerrar con X o Escape dejaba la
promesa colgada para siempre: no corría el revert del cambio ni el registro, y
el cambio quedaba aplicado sin motivo. Ahora la cancelación va por el `onClose`
del servicio, con guard `settled` para que no pise un payload ya confirmado.

## Componentes

### Modelos

**`pos.deletion.reason`** — maestro config-driven de motivos.
- `name` (Char, requerido)
- `sequence` (Integer)
- `active` (Boolean, default True)
- Se carga al POS vía `_load_pos_data_models`.
- Datos por defecto (`data/pos_deletion_reason_data.xml`):
  "Error de carga", "Cliente se arrepintió", "Duplicado".

**`pos.control.log`** — registro de trazabilidad (antes `pos.deletion.log`).
- `event_type` (Selection: `order` / `line` / `qty_reduction` / `high_discount` /
  `price_reduction`, requerido) — campo renombrado desde `deletion_type`.
- `user_id` (Many2one res.users — cajero)
- `pos_config_id` (Many2one pos.config)
- `session_id` (Many2one pos.session)
- `order_ref` (Char — uid/nombre de la orden POS; puede no existir en backend)
- `product_id` (Many2one product.product)
- `qty_removed` (Float — cantidad quitada; diferencia en reducción)
- `amount_removed` (Float — importe afectado, según el evento)
- `discount_percent` (Float — % de descuento, evento `high_discount`)
- `old_price` / `new_price` (Float — precio antes/después, evento `price_reduction`)
- `reason_id` (Many2one pos.deletion.reason)
- `reason_note` (Text — texto libre opcional)
- `event_datetime` (Datetime, default now) — renombrado desde `deletion_datetime`.
- `company_id` (Many2one res.company, default company)
- Método `@api.model log_event(vals)` (renombrado desde `log_deletion`) que crea
  el registro en `sudo()` (el cajero no tiene create directo sobre el modelo).

### Frontend (OWL / POS)

- `static/src/js/deletion_reason_popup.js` + `.xml` — popup con `<select>` de
  motivos (desde `pos.models['pos.deletion.reason']`) + textarea opcional.
  Devuelve `{reason_id, reason_note}` o `null` si cancela. Sin cambios (genérico).
- `static/src/js/control_logger.js` (antes `deletion_logger.js`) — `askReason`,
  `logEvent` (antes `logDeletion`, llama `orm.call("pos.control.log", "log_event", ...)`),
  `snapshotOrder`.
- `static/src/js/pos_store.js` — patch `deleteOrders` (evento `order`, ask-before,
  motivo único por lote — cubre trash icon vía `onDeleteOrder` y "Cancelar
  órdenes" del cierre de caja vía `ClosingPopup`) y patch `selectOrderLine`:
  captura baseline `{qty, discount, price}` de la línea
  al seleccionarla (`_captureLineBaseline`); al deseleccionar (`_resolvePendingLineChanges`)
  compara y resuelve, en orden, `_resolveQtyReduction`, `_resolveHighDiscount`,
  `_resolvePriceReduction` — cada uno pide motivo solo si corresponde y revierte
  el cambio puntual si se cancela.
- `static/src/js/order_summary.js` — patch `_setValue`: solo `remove` (evento `line`).

### Config (Ajustes POS)

`res.config.settings` / `pos.config` con toggles:
- `require_reason_order_deletion`
- `require_reason_line_deletion`
- `require_reason_qty_reduction`
- `require_reason_high_discount` + `high_discount_threshold` (Float, default 30.0;
  se pide motivo solo por encima del umbral — hasta 30 inclusive no pide)
- `require_reason_price_reduction`
- `block_zero_price_payment` (default True) — impide pasar a la pantalla de pago
  si alguna línea tiene precio unitario 0 (producto sin precio cargado). Patch de
  `PosStore.pay()`: muestra AlertDialog listando los productos y aborta. Se
  excluyen los hijos de combo (`combo_parent_id`), que legítimamente van en 0
  porque el precio lo lleva la línea padre, y las líneas de recompensa
  (`is_reward_line`). Campo nuevo con default=True → cajas existentes en True
  sin migración.
- `block_close_with_pending_orders` (default True) — impide cerrar la caja si
  quedan órdenes con productos sin finalizar. Patch de `ClosePosPopup.confirm()`
  (`static/src/js/closing_popup.js`): antes del flujo base, si hay órdenes en
  memoria con `!finalized && get_orderlines().length > 0`, muestra un AlertDialog
  y aborta el cierre. El cajero debe cobrar o cancelar (el borrado pide motivo)
  esas órdenes antes de cerrar. Campo nuevo con default=True → las cajas
  existentes lo reciben en True al crearse la columna (sin migración).

Se cargan al POS (ya disponibles en `pos.config` del frontend — **no** hay
override de `_load_pos_data_fields`, ver nota de la Task 4 corregida en el plan).

### Vistas y seguridad

- Grupo `group_pos_deletion_audit` (supervisores) — lectura del log. Sin cambio
  de nombre pese al rename del modelo (ya en uso, evita otro breaking change).
- `ir.model.access.csv`:
  - `pos.control.log`: read para el grupo audit; el cajero crea vía método sudo
    (sin fila de create directa).
  - `pos.deletion.reason`: read para usuarios POS; write/create/unlink para
    administración (grupo audit o settings).
- Vistas (`views/pos_control_log_views.xml`, antes `pos_deletion_log_views.xml`):
  lista + pivot + búsqueda con filtro por los 5 tipos, bajo menú **Punto de Venta**
  → "Trazabilidad POS".
- Menú de configuración para `pos.deletion.reason`.

### Informe de sesión imprimible

- `models/report_sale_details.py` hereda `report.point_of_sale.report_saledetails`
  y extiende `get_sale_details`: agrega `control_events` (antes `deletions`; lista
  ordenada por fecha/hora con cajero, tipo, producto, cantidad, descuento, precio
  antes/después, motivo, nota) y `control_counts` (antes `deletions_count`;
  `{order, line, qty_reduction, high_discount, price_reduction}`), con el mismo
  alcance del reporte (por sesión si hay `session_ids`, si no por rango de fecha
  + config).
- `views/report_saledetails_views.xml` hereda `point_of_sale.pos_session_sales_details`
  e inserta (xpath después de `//div[@id='discounts']`) una sección
  `t-if="control_events"` (id `control_events`, antes `deletions`) con resumen de
  contadores + tabla detallada (incluye columnas Desc.% y Precio antes→después).
  Aplica al PDF "Detalles de ventas" del backend y al reporte de cierre imprimible.

### Dashboard "Métricas de Cajeros"

Dashboard OWL en el backend siguiendo el patrón de `pos_management_metrics`,
dentro de este mismo módulo. Acceso gateado por `group_pos_deletion_audit`.

- `controllers/pos_control_metrics_controller.py` (antes `deletion_metrics_controller.py`)
  — 2 endpoints JSON (`/pos_control_metrics/filters`, `/pos_control_metrics/metrics`,
  antes `/pos_deletion_metrics/*`) con SQL crudo sobre `pos_control_log`, scoping
  multi-compañía por `request.env.companies.ids`, filtros por fecha (tz del
  usuario), caja, cajero, empresa, tipo y motivo. `_check_access` exige el grupo audit.
- Métricas: KPIs (total, órdenes/líneas/reducciones/descuentos altos/reducciones
  de precio, importe afectado, unidades quitadas, descuento promedio, tasa de
  eliminación = órdenes elim. / total órdenes del período); charts (ranking de
  cajeros apilado por los 5 tipos, distribución por motivo, tendencia diaria
  conteo+importe); tabla detalle (últimos 500, con columnas Desc.% y Precio).
- Frontend: `static/src/js/control_dashboard.js` (antes `deletion_dashboard.js`;
  componente + registro en `actions` bajo el mismo tag
  `pos_deletion_reason_log.dashboard`), `static/src/xml/control_dashboard.xml`,
  `static/src/css/control_dashboard.css`. Chart.js vía `loadJS` (CDN, igual que
  el otro módulo).
- `views/dashboard_menu_views.xml` — `ir.actions.client` + `menuitem` "Métricas
  de Cajeros" bajo Punto de Venta → Reporting.
- **Assets**: los JS del POS se listan explícitos (no glob) para que el
  dashboard backend NO entre al bundle del POS; el dashboard va en
  `web.assets_backend`.

### Migración de datos (nota operativa)

El rename de modelo (`pos.deletion.log` → `pos.control.log`) es un cambio de
`_name` en Odoo: al hacer `-u`, el ORM da de baja el modelo viejo (tabla
`pos_deletion_log` queda huérfana en la DB, con los datos que tenía) y crea
`pos_control_log` vacía. No hay migración automática de filas. En `prod` (dev
local) esto se aceptó porque solo había 3 registros de prueba/reales del cajero
en la tabla vieja. Si esto se lleva a un ambiente con datos reales acumulados,
migrar manualmente con un script de upgrade (`INSERT INTO pos_control_log
SELECT ... FROM pos_deletion_log`, mapeando `deletion_type`→`event_type`,
`deletion_datetime`→`event_datetime`) antes de instalar esta versión.

## Layout

```
pos_deletion_reason_log/
  __init__.py
  __manifest__.py
  models/
    __init__.py
    pos_deletion_reason.py
    pos_control_log.py             # antes pos_deletion_log.py
    pos_config.py                  # toggles (sin override de _load_pos_data_fields)
    pos_session.py                 # _load_pos_data_models
    res_config_settings.py
    report_sale_details.py
  controllers/
    __init__.py
    pos_control_metrics_controller.py   # antes deletion_metrics_controller.py
  data/
    pos_deletion_reason_data.xml
  security/
    security.xml                   # group_pos_deletion_audit
    ir.model.access.csv
  views/
    pos_control_log_views.xml      # antes pos_deletion_log_views.xml
    pos_deletion_reason_views.xml
    res_config_settings_views.xml
    menu_views.xml
    report_saledetails_views.xml
    dashboard_menu_views.xml
  static/src/
    js/
      deletion_reason_popup.js
      control_logger.js            # antes deletion_logger.js
      pos_store.js
      order_summary.js
      control_dashboard.js         # antes deletion_dashboard.js
    xml/
      deletion_reason_popup.xml
      control_dashboard.xml        # antes deletion_dashboard.xml
    css/
      control_dashboard.css        # antes deletion_dashboard.css
  static/description/
    icon.png
```

## Manejo de errores

- Si la RPC `log_event` falla, no bloquear al cajero: log en consola y seguir
  (la operación ya ocurrió; el registro es best-effort, no debe trabar el POS).
- Snapshot tolerante a campos ausentes (orden vacía, línea sin producto).

## Testing

- Validación de sintaxis local (XML/CSV/manifest/JS) sin DB.
- Upgrade en contenedor: `docker exec odoo-odoo-1 odoo -u
  pos_deletion_reason_log -d <db> --no-http --stop-after-init`.
- Verificación en shell de Odoo (`odoo shell`): `log_event` para los 5 tipos,
  queries SQL del controller del dashboard, render HTML del reporte de sesión
  — todo con rollback, sin dejar datos de prueba.
- Verificación manual en POS (pendiente del lado del usuario): los 5 eventos
  piden motivo y generan registro; cancelar el motivo aborta/revierte la
  operación; el dashboard renderiza los charts en el navegador.
