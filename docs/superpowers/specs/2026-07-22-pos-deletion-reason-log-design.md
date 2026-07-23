# pos_deletion_reason_log — Diseño

**Fecha:** 2026-07-22
**Odoo:** 18.0
**Repo:** prometeo-odoo-modules

## Objetivo

Registrar cada vez que un empleado del POS elimina una orden completa, borra una
línea/producto de la orden, o reduce la cantidad de una línea. Al momento de
eliminar se pide un **motivo** (justificación) y luego queda un **registro** en
el backend con el motivo, el cajero, el producto y el momento — aunque la orden
nunca llegue a sincronizarse al servidor.

Convive con `pos_special_approval_omax` (que ya pide aprobación de manager al
eliminar) pero **no depende de él**: el módulo es standalone.

## Alcance

Eventos que piden motivo y quedan registrados (cada uno con toggle propio):

1. **Eliminar orden completa** — `PosStore.onDeleteOrder`.
2. **Eliminar línea/producto** — `OrderSummary._setValue` con `remove`.
3. **Reducir cantidad de una línea** — `OrderSummary._setValue` con un valor
   numérico menor a la cantidad actual (se registra la diferencia).

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

Limitación v1 aceptada: si el cajero reduce la cantidad de la última línea
tocada y cierra/cobra la orden sin volver a seleccionar otra línea, ese ajuste
no dispara la verificación (no hay un evento de "deselección final" al salir
de la pantalla). Los otros 2 eventos (orden completa, línea completa) no
tienen esta limitación — mantienen el flujo motivo-primero original.
   Si no (rechazado/cancelado) → no registrar.

## Componentes

### Modelos

**`pos.deletion.reason`** — maestro config-driven de motivos.
- `name` (Char, requerido)
- `sequence` (Integer)
- `active` (Boolean, default True)
- Se carga al POS vía `_load_pos_data_models`.
- Datos por defecto (`data/pos_deletion_reason_data.xml`):
  "Error de carga", "Cliente se arrepintió", "Duplicado".

**`pos.deletion.log`** — registro de eliminaciones.
- `deletion_type` (Selection: `order` / `line` / `qty_reduction`, requerido)
- `user_id` (Many2one res.users — cajero)
- `pos_config_id` (Many2one pos.config)
- `session_id` (Many2one pos.session)
- `order_ref` (Char — uid/nombre de la orden POS; puede no existir en backend)
- `product_id` (Many2one product.product — para línea/reducción)
- `qty_removed` (Float — cantidad quitada; diferencia en reducción)
- `amount_removed` (Float — valor quitado)
- `reason_id` (Many2one pos.deletion.reason)
- `reason_note` (Text — texto libre opcional)
- `deletion_datetime` (Datetime, default now)
- `company_id` (Many2one res.company, default company)
- Método `@api.model log_deletion(vals)` que crea el registro en `sudo()`
  (el cajero no tiene create directo sobre el modelo).

### Frontend (OWL / POS)

- `static/src/js/deletion_reason_popup.js` + `.xml` — popup con `<select>` de
  motivos (desde `pos.models['pos.deletion.reason']`) + textarea opcional.
  Devuelve `{reason_id, reason_note}` o `null` si cancela.
- `static/src/js/pos_store.js` — patch `onDeleteOrder` (evento `order`).
- `static/src/js/order_summary.js` — patch `_setValue`: distingue `remove`
  (evento `line`) de un valor numérico menor a la cantidad actual
  (evento `qty_reduction`).
- Helper compartido para snapshot + llamada `orm.call("pos.deletion.log",
  "log_deletion", [vals])` tras confirmar que la eliminación ocurrió.

### Config (Ajustes POS)

`res.config.settings` / `pos.config` con toggles:
- `require_reason_order_deletion`
- `require_reason_line_deletion`
- `require_reason_qty_reduction`

Se cargan al POS (ya disponibles en `pos.config` del frontend).

### Vistas y seguridad

- Grupo `group_pos_deletion_audit` (supervisores) — lectura del log.
- `ir.model.access.csv`:
  - `pos.deletion.log`: read para el grupo audit; el cajero crea vía método sudo
    (sin fila de create directa, o create restringido).
  - `pos.deletion.reason`: read para usuarios POS; write/create/unlink para
    administración (grupo audit o settings).
- Vistas: lista + pivot de `pos.deletion.log` bajo menú **Punto de Venta**.
- Menú de configuración para `pos.deletion.reason`.

### Informe de sesión imprimible (agregado)

- `models/report_sale_details.py` hereda `report.point_of_sale.report_saledetails`
  y extiende `get_sale_details`: agrega `deletions` (lista ordenada por fecha/hora
  con cajero, tipo, producto, cantidad, motivo, nota) y `deletions_count`
  (`{order, line, qty_reduction}`), con el mismo alcance del reporte (por sesión
  si hay `session_ids`, si no por rango de fecha + config).
- `views/report_saledetails_views.xml` hereda `point_of_sale.pos_session_sales_details`
  e inserta (xpath después de `//div[@id='discounts']`) una sección `t-if="deletions"`
  con resumen de contadores + tabla detallada. Aplica al PDF "Detalles de ventas"
  del backend y al reporte de cierre imprimible.

### Dashboard de auditoría (agregado, v1)

Dashboard OWL en el backend siguiendo el patrón de `pos_management_metrics`,
dentro de este mismo módulo. Acceso gateado por `group_pos_deletion_audit`.

- `controllers/deletion_metrics_controller.py` — 2 endpoints JSON
  (`/pos_deletion_metrics/filters`, `/pos_deletion_metrics/metrics`) con SQL
  crudo sobre `pos_deletion_log`, scoping multi-compañía por
  `request.env.companies.ids`, filtros por fecha (tz del usuario), caja, cajero,
  empresa, tipo y motivo. `_check_access` exige el grupo audit.
- Métricas v1: KPIs (total, órdenes/líneas/reducciones, importe eliminado,
  unidades quitadas, tasa de eliminación = órdenes elim. / total órdenes del
  período); charts (ranking de cajeros apilado por tipo, distribución por motivo,
  tendencia diaria conteo+importe); tabla detalle (últimas 500).
- Frontend: `static/src/js/deletion_dashboard.js` (componente + registro en
  `actions`), `static/src/xml/deletion_dashboard.xml`, `static/src/css/
  deletion_dashboard.css`. Chart.js vía `loadJS` (CDN, igual que el otro módulo).
- `views/dashboard_menu_views.xml` — `ir.actions.client` + `menuitem` bajo
  Punto de Venta → Reporting.
- **Assets**: los JS del POS se listan explícitos (no glob) para que el
  dashboard backend NO entre al bundle del POS; el dashboard va en
  `web.assets_backend`.

## Layout

```
pos_deletion_reason_log/
  __init__.py
  __manifest__.py
  models/
    __init__.py
    pos_deletion_reason.py
    pos_deletion_log.py
    pos_config.py            # toggles + _load_pos_data_models
    res_config_settings.py
  data/
    pos_deletion_reason_data.xml
  security/
    security.xml             # group_pos_deletion_audit
    ir.model.access.csv
  views/
    pos_deletion_log_views.xml
    pos_deletion_reason_views.xml
    res_config_settings_views.xml
    menu_views.xml
  static/src/
    js/
      deletion_reason_popup.js
      pos_store.js
      order_summary.js
    xml/
      deletion_reason_popup.xml
  static/description/
    icon.png
```

## Manejo de errores

- Si la RPC `log_deletion` falla, no bloquear al cajero: log en consola y seguir
  (la eliminación ya ocurrió; el registro es best-effort, no debe trabar el POS).
- Snapshot tolerante a campos ausentes (orden vacía, línea sin producto).

## Testing

- Validación de sintaxis local (XML/CSV/manifest) sin DB.
- Upgrade en contenedor: `sudo docker exec odoo-odoo-1 odoo -i
  pos_deletion_reason_log -d <db> --stop-after-init`.
- Verificación manual en POS: los 3 eventos piden motivo y generan registro;
  cancelar el motivo aborta la eliminación.
