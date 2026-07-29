# checking_account_withdrawals — Diseño

Fecha: 2026-07-27
Rama: `cuentav2`
Origen del requerimiento: `~/ObsidianVault/02-Prometeo/01-Odoo/Modulos/Cuenta corriente/checking_account_withdrawals.md`

## Propósito

Permitir que ciertos contactos retiren mercadería sin pagar en el momento (fiado), llevando una
cuenta corriente propia con cuotas, pagos e imputaciones, sin tocar la contabilidad fiscal de Odoo.

## Decisiones cerradas

| Decisión | Resolución |
|---|---|
| Nombre técnico | `checking_account_withdrawals` (se elimina la carpeta vacía `cuenta_corriente_retiros`) |
| Contabilidad | **Standalone**. Modelos propios prefijo `caw.`. No genera `account.move` ni `account.payment` |
| Alcance de la entrega | Spec completo: épicas 1 a 7 + dashboard + PDF |
| Cancelar retiro con pagos imputados | **Bloqueado**. El Manager debe anular primero el pago (CC-44) |
| Límite de crédito | **Por partner**, en `caw.account`: monto + modo `none` / `warn` / `block` |

## Arquitectura

### Modelos

Todos con `company_id` y `ir.rule` por compañía.

**`res.partner`** *(inherit)*
- `caw_enabled` (Boolean): al marcarlo se crea automáticamente su `caw.account` de la compañía activa.
- `caw_account_ids` (One2many), `caw_balance`, `caw_overdue_balance`, `caw_credit_balance` (computados, no editables).
- Smart button a los retiros del partner.

**`caw.account`** — cuenta corriente por partner + compañía. `mail.thread`.
- `partner_id`, `company_id` (constraint unique en el par).
- `credit_limit` (Monetary), `limit_mode` (`none` / `warn` / `block`).
- `balance` = suma de residuales de cuotas no canceladas.
- `overdue_balance` = idem, solo cuotas con `date_due < hoy` e impagas.
- `credit_balance` = saldo a favor: suma de `amount_unallocated` de los pagos publicados.
- Defaults de plan de cuotas heredados de `res.company`, sobreescribibles.

**`caw.withdrawal`** — retiro. `mail.thread`, `mail.activity.mixin`.
- `name` por `ir.sequence` propia, `account_id`, `partner_id` (related store), `date`,
  `user_id` (responsable), `company_id`, `note`.
- `line_ids`, `amount_total` (computado), `amount_residual` (computado).
- `state`: `draft` / `pending` / `partial` / `paid` / `cancel`. **Computed `store=True`, nunca editable.**
- `picking_id`, `picking_state` (related), `is_inconsistent` (picking cancelado con retiro vivo).
- `is_overdue` (mora): indicador **independiente** del estado.
- `installment_ids`.

**`caw.withdrawal.line`** — `withdrawal_id`, `product_id`, `name`, `quantity`, `price_unit`, `price_subtotal`.

**`caw.installment`** — cuota.
- `withdrawal_id`, `sequence`, `date_due`, `amount`, `amount_allocated`, `amount_residual`.
- `state`: `pending` / `partial` / `paid` / `overdue`. `paid` solo cuando `amount_residual == 0`.

**`caw.payment`** — pago sobre la cuenta, no sobre un retiro puntual. `mail.thread`.
- `name` por secuencia, `account_id`, `partner_id`, `date`, `amount`, `payment_method`
  (Selection: efectivo / transferencia / cheque / otro), `ref`.
- `state`: `draft` / `posted` / `cancel`.
- `allocation_ids`, `amount_allocated`, `amount_unallocated` (el sobrante = saldo a favor).

**`caw.allocation`** — imputación. `payment_id`, `installment_id`, `amount`, `company_id`.
Es la única fuente de verdad de "cuánto se pagó de qué cuota".

### El requisito crítico (CC-30 / CC-31)

El estado del retiro **nunca** se escribe a mano:

```
caw.allocation (write/create/unlink)
  └─> caw.installment.amount_allocated / amount_residual / state   (compute store)
        └─> caw.withdrawal.state / amount_residual / is_overdue     (compute store)
              └─> caw.account.balance / overdue_balance             (compute store)
```

- `pending`: ninguna cuota con imputación.
- `partial`: al menos una cuota con imputación y residual total > 0.
- `paid`: **todas** las cuotas en `paid` y residual del retiro = 0.
- `@api.constrains` rechaza `paid` si existe alguna cuota con `amount_residual > 0`.
- El monto total imputado **no** es criterio suficiente para `paid`.

Casos de prueba obligatorios (tests reales, excepción a la regla de "sin tests" del repo):
1. Pago excedente en cuota 1 + faltante en cuota 2, total imputado = total del retiro → `partial`.
2. Retiro de 6 cuotas con 5 canceladas → `partial`.
3. Anular un pago que dejaba el retiro en `paid` → vuelve a `partial`.

### Flujo del retiro

```
draft ──action_confirm──> pending ──(allocations)──> partial ──> paid
  │                          │
  │                          ├─ genera stock.picking de salida
  │                          └─ genera las cuotas según el plan
  └──action_cancel──> cancel     (bloqueado si hay pagos imputados)
```

`action_confirm` valida: partner habilitado, líneas presentes, total > 0. Abre el wizard
`caw.confirm.wizard`, que:
- muestra saldo actual y saldo vencido del partner;
- pide el plan: **contado en cuenta** (1 cuota a X días) o **cuotas fijas** (N cuotas,
  periodicidad configurable, día de corte configurable);
- evalúa `balance + amount_total` contra `credit_limit`:
  `warn` → aviso, el Operador continúa; `block` → corta, solo el Manager fuerza y queda en el chatter.

El redondeo se ajusta en la última cuota: la suma de cuotas siempre iguala el total del retiro.
En carga manual de cuotas (CC-21) hay constraint bloqueante sobre la suma y sobre vencimientos
anteriores a la fecha del retiro.

### Stock

El retiro crea un `stock.picking` de salida con un tipo de operación configurable por compañía
(`caw_picking_type_id` en `res.company`, default = `out_type_id` del almacén). El stock se descuenta
al **validar el picking**, no al confirmar el retiro. Si el picking se cancela con el retiro vivo,
`is_inconsistent = True` para revisión del Manager.

Los usuarios `group_cc_user` validan el picking mediante el **patrón sudo** — no se implica
`stock.group_stock_user` en el grupo restringido (rompería las reglas por OR-combination).

### Imputación de pagos

- **FIFO automático** (CC-41): orden por `date_due` ascendente, luego número de retiro.
  Puede abarcar cuotas de varios retiros del mismo partner.
- **Manual** (CC-42, solo Manager): selección de cuotas abiertas; no se puede imputar más que el
  residual de cada cuota ni más que el monto del pago.
- **Saldo a favor** (CC-43): el sobrante no se fuerza contra ninguna cuota; queda como
  `amount_unallocated` y se refleja en `caw.account.credit_balance`.
- **Anular** (CC-44): revierte todas las imputaciones, las cuotas y el retiro recalculan estado.

### Cron

`_cron_update_overdue` diario: marca cuotas impagas con `date_due < hoy` como `overdue` y recalcula
el vencido de cada cuenta. Sin intereses ni notificaciones en esta etapa.

### Dashboard (CC-53)

Copia estructural de `account_management_metrics`:
- `controllers/dashboard_controller.py`: `http.Controller` con rutas `type='json', auth='user'`,
  helper `_check_access()` que levanta `AccessError` si el usuario no está en `group_cc_manager`,
  SQL parametrizado scopeado a `request.env.companies.ids`.
- Front OWL en `static/src/js/dashboard.js`, `static/src/xml/dashboard.xml`,
  `static/src/css/dashboard.css`; Chart.js vía `loadJS` desde CDN; registro en
  `registry.category("actions")` + `ir.actions.client` + `menuitem`.
- Filtros: presets de fecha (hoy, ayer, 7/30/60/90 días, todo, custom), compañía, búsqueda con
  debounce 350 ms, limpiar filtros. Toggle dark/light con la misma paleta
  (`#3b82f6`, `#a855f7`, `#10b981`, `#f59e0b`, `#ec4899`, `#06b6d4`).
- Tabs: general (KPIs + gráficos), retiros, cuotas.
- KPIs: saldo total de cartera, saldo vencido, total retirado en el período, cantidad de retiros,
  cuotas vencidas, tasa de mora %, cobrado en el período, saldo a favor acumulado.
- Gráficos: evolución de saldo (line por compañía), cobrado vs. vencido (line), distribución de
  cuotas por estado (doughnut), top partners por saldo/mora (bar horizontal), retiros por
  compañía (bar).
- Export CSV del listado filtrado vía endpoint `type='http'`.

### Seguridad

- `group_cc_user`: crear retiros, registrar pagos, consultar.
- `group_cc_manager`: límites, imputación manual, cancelaciones, forzar sobre el límite, dashboard.
- `ir.rule` por compañía en los 7 modelos.
- `mail.thread` en retiro, cuenta y pago; se loguean confirmaciones, cancelaciones, forzados de
  límite y anulaciones.

### Reportes

`report/report_caw_statement_templates.xml`: resumen de cuenta en PDF de un partner a una fecha,
con retiros, cuotas, pagos imputados y saldo final.

## Estructura de archivos

```
checking_account_withdrawals/
  __init__.py
  __manifest__.py
  models/
    __init__.py
    res_company.py            # defaults de plan, picking type
    res_partner.py
    caw_account.py
    caw_withdrawal.py
    caw_withdrawal_line.py
    caw_installment.py
    caw_payment.py
    caw_allocation.py
  wizards/
    __init__.py
    caw_confirm_wizard.py     # plan de cuotas + chequeo de límite
    caw_allocate_wizard.py    # imputación manual
  controllers/
    __init__.py
    dashboard_controller.py
  security/
    security.xml              # res.groups + ir.rule
    ir.model.access.csv
  data/
    ir_sequence.xml
    ir_cron.xml
  views/
    caw_account_views.xml
    caw_withdrawal_views.xml
    caw_installment_views.xml
    caw_payment_views.xml
    res_partner_views.xml
    res_config_settings_views.xml
    menu_views.xml
  report/
    report_caw_statement.xml
    report_caw_statement_templates.xml
  static/src/js/dashboard.js
  static/src/xml/dashboard.xml
  static/src/css/dashboard.css
  static/description/icon.png
  tests/
    __init__.py
    test_withdrawal_state.py  # los 3 casos críticos de CC-31
```

Orden de `data` en el manifiesto: `security/*` primero, luego `data/`, `views/`, `report/`.

## Fuera de alcance

- Intereses por mora, notificaciones automáticas.
- Integración con `account.move` / `account.payment`.
- Multi-moneda (todo en la moneda de la compañía).
