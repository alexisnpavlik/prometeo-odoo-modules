# customer_checking_account — Diseño

**Fecha:** 2026-10-13
**Base destino:** `kiosco` (Odoo 18)
**Rama:** `feat/customer-checking-account`

## Objetivo

Registrar retiros de mercadería de clientes que pagan después: en cuotas o con pagos parciales. Lo opera **una sola persona**. Es una versión simplificada de `checking_account_withdrawals` (`caw.`), pensada para un comercio chico y no para una empresa con roles separados.

## Diferencias con `checking_account_withdrawals`

| Tema | `caw` | `cca` (nuevo) |
|---|---|---|
| Quién puede retirar | Contactos habilitados (`caw_enabled`) | Cualquier contacto |
| Identificación | Opcional | DNI (`vat`) obligatorio para confirmar; búsqueda por DNI |
| Precio | Lista de precios por retiro | `list_price` del producto |
| Recargo | No existe | % por retiro, aplicado a todas las líneas |
| Cuotas | Definidas en un asistente | Calculadas en vivo en el formulario |
| Stock | Confirmar → entregar → validar albarán | El albarán se crea y se valida al confirmar |
| Pagos | Borrador → publicar → asistente de imputación | Registro directo con imputación FIFO automática |
| Grupos | Usuario + Manager | Un único grupo |
| Se conserva | — | Estado de cuenta PDF, dashboard, límite de crédito, cron de vencidos |

Los dos módulos pueden convivir instalados: no comparten modelos ni campos.

## Modelos

Prefijo `cca.`. Un archivo por modelo.

- **`cca.account`**: una cuenta por (contacto, compañía). Se crea sola en el primer retiro. Campos: `partner_id`, `company_id`, `credit_limit`, `limit_mode` (`none`/`warn`/`block`), y saldos computados (`balance`, `overdue_balance`, `credit_balance`).
- **`cca.withdrawal`**: `name` (secuencia), `account_id`, `partner_id`, `partner_vat` (related), `date`, `line_ids`, `surcharge_percent`, `installment_count` (mín. 1), `first_due_date`, `frequency` (`monthly`/`weekly`), `installment_ids`, `amount_untaxed` (suma de líneas sin recargo), `amount_surcharge`, `amount_total`, `amount_residual`, `state`, `is_overdue`, `picking_id`, `note`.
- **`cca.withdrawal.line`**: `product_id`, `name`, `quantity`, `price_unit` (por defecto `list_price`, editable en borrador), `price_subtotal` = `quantity × price_unit` (sin recargo; el recargo se muestra en el total del retiro).
- **`cca.installment`**: `withdrawal_id`, `sequence`, `date_due`, `amount`, `amount_allocated`, `amount_residual`, `state` (`pending`/`partial`/`paid`/`overdue`).
- **`cca.payment`**: `name` (secuencia), `account_id`, `partner_id`, `date`, `amount`, `payment_method` (selección fija: efectivo, transferencia, tarjeta, otro), `ref`, `state` (`posted`/`cancel`), `amount_allocated`, `amount_unallocated`.
- **`cca.allocation`**: `payment_id`, `installment_id`, `amount`. Es interno: no tiene vista propia.

### Cálculo de recargo y cuotas

- `amount_surcharge = round(amount_untaxed × surcharge_percent / 100, 2)`
- `amount_total = amount_untaxed + amount_surcharge`
- Monto de cada cuota = `round(amount_total / installment_count, 2)`. La **última cuota absorbe la diferencia de redondeo**.
- Vencimiento: la cuota *n* vence `first_due_date + (n-1)` meses o semanas, según `frequency`.
- En borrador, las cuotas se regeneran con `@api.onchange` en `surcharge_percent`, `installment_count`, `first_due_date`, `frequency` y `line_ids`. En el formulario se ven en vivo, sin guardar. Al confirmar se congelan.
- `surcharge_percent` no puede ser negativo. `installment_count` tiene que ser ≥ 1.

## Flujo

**Estados del retiro:** `draft → pending → partial → paid` y `cancel` (mismos valores que `caw` sin `delivered`, así el dashboard se porta sin cambiar estados; `pending`/`partial`/`paid` son "confirmado"). `is_overdue` es un flag aparte: es verdadero cuando el retiro está confirmado y alguna cuota abierta está vencida. El estado `paid` se deriva de las cuotas y se da solo cuando **todas** quedan pagadas.

**Confirmar** (`action_confirm`), un solo paso:
1. Valida: el contacto tiene `vat`, hay al menos una línea y la suma de las cuotas es igual a `amount_total`.
2. Controla el límite: saldo actual + `amount_total` comparado con `credit_limit`. Con `warn` muestra una notificación y continúa. Con `block` lanza `UserError`; el usuario sube el límite en la cuenta y reintenta.
3. Crea el albarán de salida (tipo de operación de salida del almacén de la compañía), con `quantity = demanda`, y lo valida.
4. Congela líneas y cuotas.
5. Imputa por FIFO el saldo a favor que tenga la cuenta.

**Cancelar** (`action_cancel`): solo se permite si ninguna cuota tiene imputaciones. Si había albarán validado, crea y valida una devolución. Las cuotas se borran (como en `caw`); al volver a borrador se regeneran como vista previa.

**Volver a borrador:** solo desde `cancelled`.

**Pagos:**
- Al crear un pago queda `posted` y se imputa por FIFO a las cuotas abiertas de la cuenta, ordenadas por `date_due` y después por `id`.
- Lo que sobra queda como `amount_unallocated` (saldo a favor) y se imputa al confirmar el próximo retiro.
- `action_cancel` del pago borra sus imputaciones y recalcula el estado de las cuotas.

**Cron diario:** recalcula el estado vencido de cuotas y retiros. Se porta de `caw`.

## Seguridad

- Un grupo: `customer_checking_account.group_cca_user` (Cuenta corriente), con acceso CRUD completo a todos los modelos `cca.*`.
- `ir.rule` multi-company en cada modelo con `company_id`.
- Las operaciones de stock al confirmar o cancelar corren con `sudo()`, para que el usuario no necesite el grupo de inventario.

## Pantallas

**Menú raíz "Cuenta Corriente"** (`application: True`):
- **Retiros:** lista con cliente, DNI, fecha, total, saldo y estado. Filtros: Vencidos, Impagos y Pagados. Agrupa por cliente.
- **Pagos:** lista y formulario de alta.
- **Clientes:** cuentas con saldo, vencido y límite. Smart buttons a retiros, pagos y estado de cuenta.
- **Dashboard.**
- **Ajustes:** app propia en Ajustes (`<app>` con un `<block>` por sección): `limit_mode` y `credit_limit` por defecto para las cuentas nuevas, y tipo de operación del albarán.

**Formulario de retiro:**
1. Cliente (búsqueda por nombre o DNI), DNI visible y saldo actual de la cuenta.
2. Líneas de productos.
3. Bloque **Financiación**: `surcharge_percent`, `installment_count`, `first_due_date` y `frequency`.
4. Resumen: subtotal, recargo y total.
5. Tabla de cuotas: número, vencimiento y monto. Una vez confirmado, también saldo y estado.
6. Botones: Confirmar, Cancelar y Volver a borrador.

**Búsqueda por DNI:** el `name_search` del contacto, en el campo `partner_id` del retiro, también matchea por `vat`. El `display_name` en ese contexto muestra `Nombre (DNI)`.

**Contacto:** smart button "Cuenta corriente" con el saldo, visible solo si la cuenta existe.

**Estado de cuenta PDF:** asistente con cliente y rango de fechas. Se adapta el reporte QWeb de `caw` e incluye retiros, pagos, cuotas pendientes y saldo final.

**Dashboard:** se adapta el de `caw`, con KPIs de deuda total, vencido y cobrado en el período, y top deudores. Respeta el skill `odoo-metrics-dashboard`: scroll en el celular, presets de fecha en zona horaria AR y SQL acotado a `env.companies`.

## Tests

Se portan de `caw` los que aplican: saldo, cuotas, pagos FIFO, límite y cancelación, stock y controlador del dashboard. Se suman:
- recargo: total, redondeo y última cuota;
- onchange de cuotas: cambiar el %, la cantidad o la frecuencia regenera las cuotas;
- DNI obligatorio al confirmar;
- búsqueda de contacto por DNI;
- saldo a favor imputado al confirmar un retiro nuevo;
- confirmar valida el albarán y cancelar lo devuelve.

Los tests se corren en una base de prueba, no en `kiosco`.

## Fuera de alcance

- Asientos contables y comprobantes fiscales.
- Listas de precios.
- Integración con POS.
- Roles separados de operador y manager.
