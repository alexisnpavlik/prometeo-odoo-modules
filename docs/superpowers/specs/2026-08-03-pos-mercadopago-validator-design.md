# pos_mercadopago_validator — Diseño

**Fecha:** 2026-08-03
**Odoo:** 18.0 (verificado contra `18.0-20260409`)
**País / moneda:** Argentina, ARS
**Estado:** Fase 0 cerrada. Diseño aprobado, listo para plan de implementación.

Este documento reemplaza al brief funcional v2.0. Los cambios respecto de aquel están justificados por la evidencia de la sección 2, medida contra la cuenta real de Mercado Pago.

---

## 1. Objetivo

El comercio cobra con un QR estático de Mercado Pago pegado en cada caja. El cliente escanea, ingresa el monto y paga desde su billetera o desde la app de su banco. Hoy el cajero valida ese pago mirando la app de Mercado Pago en el celular y lo marca a mano en Odoo.

El módulo elimina esa verificación manual sin cambiar nada de la operatoria del cliente. Odoo ingesta los pagos que entran a la cuenta, y cuando el cajero cobra con el método Mercado Pago le muestra los pagos recibidos que coinciden con el monto de la venta. El cajero confirma y la línea queda cobrada con el pago real vinculado en la base.

**Lo que el sistema garantiza:** que el pago existe, que está acreditado, que el monto es el declarado y que nunca se imputa dos veces.

**Lo que no garantiza:** que ese pago corresponda a esa venta. Esa afirmación la hace el cajero. Toda la auditoría de la sección 9 existe para que ese juicio sea revisable después.

---

## 2. Fase 0 — resultado

Verificado el 2026-08-03 contra la cuenta `MEAL9306838` (user_id `430185252`, MLA), con access token de producción, sobre 89 pagos históricos y 2 pagos de prueba reales de $1.500.

### 2.1 `[BLOQUEANTE-1]` — confirmado

Los pagos del QR estático **aparecen** en `GET /v1/payments/search` y son identificables sin ambigüedad por `point_of_interaction.business_info.sub_unit == "qr"`.

La query del brief funciona tal cual:

```
GET /v1/payments/search
    ?sort=date_created&criteria=desc&range=date_created
    &begin_date=NOW-5MINUTES&end_date=NOW
Authorization: Bearer {access_token}
```

Responde con un objeto `paging {total, offset, limit}`. Rate limit de Mercado Pago ~1500 req/min por vendedor; el ingestor consume 6/min.

### 2.2 `[BLOQUEANTE-2]` — refutado en cuanto al nombre, con matiz por subcanal

**El nombre del pagador no existe en ningún canal.** `first_name` y `last_name` vinieron `null` en los 89 pagos históricos y en los 3 de prueba, sobre 15 combinaciones distintas de `(poi.type, payment_type_id)`. `GET /v1/payments/{id}` devuelve exactamente lo mismo que el `search`: no hay endpoint alternativo. **El modelo de desambiguación por nombre del brief v2.0 (§1.1) queda descartado.**

Pero la identificación del pagador **sí existe en un subcanal**, y el discriminador es `point_of_interaction.sub_type`:

| Canal | `sub_type` | `metadata` | Identificación disponible |
|---|---|---|---|
| QR desde app de **Mercado Pago** | `INTRA_PSP` | `{}` | **CUIT + email + `payer.id`** |
| QR desde **billetera externa** | `INTER_PSP` | `hide_payer_information: true` | `payer.id` + banco de origen |
| Alias / CVU | — | `{}` | ninguna, y el `payer` engaña (§2.3) |

En `INTER_PSP`, Mercado Pago suprime los datos del pagador por diseño y deja `payer: {"id": "..."}` a secas, compensado con `bank_info.payer.long_name`. En `INTRA_PSP` no hay supresión: llegan CUIT y email reales del pagador, pero no hay banco de origen porque no hay banco externo.

Los dos subcanales son complementarios: uno da identidad sin banco, el otro banco sin identidad. Nunca se queda sin ningún desambiguador.

**Consecuencia de diseño:** el CUIT del canal `INTRA_PSP` permite resolver el cliente automáticamente contra `res.partner.vat`, sin intervención humana. El mapeo manual por `payer.id` (§9) queda como mecanismo para el canal `INTER_PSP`.

### 2.3 Trampa: el `payer` de las transferencias al alias

En transferencias entrantes por CVU (`payment_method_id: "cvu"`, `sub_unit: "money_inflows"`), el objeto `payer` viene poblado con los datos **del receptor** — el propio comercio: su `id`, su email y su CUIT. Confirmado comparando contra `users/me`.

Guardar ese campo como "quién pagó" llenaría la base con el CUIT propio con apariencia de dato válido, que es peor que un campo vacío porque no se nota.

**Regla:** `payer.identification` y `payer.email` se persisten **únicamente** cuando `source == "qr"`. En el canal alias se descartan sin excepción, y la comparación contra `account.mp_user_id` sirve de red: si `payer.id` es igual al collector, el dato es del receptor y no se guarda.

### 2.4 QR y alias no son equivalentes

| | QR desde MP (`account_money`, `INTRA_PSP`) | QR desde billetera externa (`interop_transfer`, `INTER_PSP`) | Alias / CVU (`cvu`) |
|---|---|---|---|
| `business_info.sub_unit` | `qr` | `qr` | `money_inflows` |
| `pos_id` / `store_id` | sí | sí | no |
| `external_reference` | `"QR #1"` | `"QR #1"` | no |
| Banco de origen | no | `"Naranja Digital Compañía Financiera S.A."` | `null` |
| CUIT + email del pagador | **sí, reales** | no (`hide_payer_information`) | datos del receptor (engañoso) |
| `payer.id` | sí, estable | sí, estable | inútil (es el receptor) |

Ambos subcanales del QR son conciliables. El canal alias solo ofrece monto y hora.

### 2.5 El `search` devuelve también pagos donde el comercio es el pagador

Compras propias en Mercado Libre y resúmenes de tarjeta aparecen en la misma búsqueda, con `payer_id: <comercio>` y un `collector` anidado, en vez de `collector_id: <comercio>`. Sin filtrar por `collector_id`, la bandeja del cajero mostraría las compras personales del dueño.

### 2.6 Montos

`transaction_amount` (1500) ≠ `net_received_amount` (1477,50). Mercado Pago retiene impuestos en el acto — en la muestra, SIRTAC sobretasa 1,5%. **La imputación compara siempre contra `transaction_amount`.** Con el neto ninguna venta coincidiría jamás.

### 2.7 Cobertura de la verificación

Los tres canales quedaron medidos con pagos reales el 2026-08-03:

| Pago | Canal | Resultado |
|---|---|---|
| `170951482351` — $1.500 | QR desde billetera externa (Naranja) | `pos_id`, banco de origen, `payer.id`; sin identificación |
| `171858334766` — $100 | QR desde app de Mercado Pago | `pos_id`, CUIT `27964493338`, email, `payer.id`; sin banco |
| `170951666839` — $1.500 | Transferencia al alias | sin `pos_id`, sin banco, `payer` con datos del receptor |

Confirmado además que `payer.id` es **estable entre canales**: `2429168801` aparece tanto en el pago por QR como en una transferencia previa del mismo pagador.

Retenciones observadas: 1,5% (SIRTAC Santiago del Estero) en el pago externo, 2,47% en el pago desde MP. Confirma §2.6.

---

## 3. Alcance

**Dentro:** ingesta automática por webhook y consulta periódica; bandeja de pagos disponibles por caja; selección desde el diálogo de cobro del POS; imputación con unicidad garantizada en base de datos; aprobación manual con doble confirmación y auditoría; actualización en vivo entre cajas; visibilidad de pagos huérfanos en backoffice.

**Fuera:** QR dinámico por venta; terminales Point Smart; devoluciones desde el POS; división de un pago entre varias ventas o viceversa; conciliación bancaria contra extracto.

---

## 4. Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│  MOSTRADOR — un QR estático impreso POR CAJA                 │
│  Cliente escanea, tipea el monto, paga                       │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  MERCADO PAGO — cuenta(s) del comercio                       │
│   webhook ──┐               ┌── GET /v1/payments/search      │
└─────────────┼───────────────┼────────────────────────────────┘
              ▼               ▲
┌──────────────────────────────────────────────────────────────┐
│  ODOO 18 — Backend                                           │
│                                                               │
│  INGESTOR — uno por mercadopago.account                      │
│   ├── controllers/webhook.py   evento → sólo data.id         │
│   ├── data/ir_cron.xml         consulta la ventana           │
│   └── services/mp_client.py    auth, retry, timeout          │
│              │ upsert idempotente                            │
│              ▼                                                │
│   ┌──────────────────────────────────────────┐               │
│   │  mercadopago.payment   ← LA BANDEJA      │               │
│   │  unique(mp_payment_id)                   │               │
│   │  unique(pos_payment_id) where not null   │               │
│   └──────────────────────────────────────────┘               │
│              │ bus por pos.config    ▲ imputar (row lock)    │
└──────────────┼───────────────────────┼───────────────────────┘
               ▼                       │ ORM / RPC
┌──────────────────────────────────────────────────────────────┐
│  NAVEGADOR — POS (OWL)                                       │
│  PaymentMercadoPagoValidator extends PaymentInterface        │
│  MercadoPagoInboxDialog                                      │
└──────────────────────────────────────────────────────────────┘
```

### Principios

**Un solo ingestor por cuenta, muchos consumidores.** El navegador nunca habla con Mercado Pago. Dos cajas que comparten cuenta comparten la serie de consultas.

**La unicidad vive en la base de datos.** Esconder un pago ya tomado en la interfaz es una comodidad, no una garantía. La garantía es la restricción `UNIQUE` más el bloqueo de fila.

**Un único camino de escritura.** Webhook y cron llaman a la misma función de ingesta, que hace un upsert idempotente.

**Desconfianza total del webhook.** Sólo se lee `data.id`; todo lo demás se resuelve contra la API con credenciales propias.

---

## 5. Modelo de datos

### 5.1 `mercadopago.account`

| Campo | Notas |
|---|---|
| `name` | |
| `access_token` | `groups="base.group_system"`. Nunca sale del servidor |
| `mp_user_id` | Obligatorio, se completa al validar. Es parte del filtro de ingesta |
| `mode` | `sandbox` / `production` |
| `webhook_secret` | `groups="base.group_system"` |
| `active`, `company_id` | |
| `last_validated_at` | No se puede activar sin validar al menos una vez |
| `last_sync_at` | Alimenta el aviso de bandeja desactualizada |
| `last_sync_error` | |

### 5.2 `mercadopago.payment` — la bandeja

| Campo | Origen / notas |
|---|---|
| `mp_payment_id` | `id`. **UNIQUE, obligatorio** |
| `account_id` | |
| `amount` | **`transaction_amount`**, nunca `net_received_amount` |
| `currency_id` | |
| `date_approved` | Precisión al segundo. Ordena la lista |
| `source` | `qr` \| `alias` |
| `mp_pos_id` | `pos_id` — de qué QR vino |
| `payer_bank_name` | `bank_info.payer.long_name`. Sólo en `INTER_PSP` |
| `payer_vat` | `payer.identification.number`. **Sólo si `source == "qr"`** (§2.3) |
| `payer_email` | Ídem. Sólo si `source == "qr"` |
| `mp_payer_id` | `payer.id`. Anónimo pero estable entre canales |
| `partner_id` | Resuelto por `payer_vat` contra `res.partner.vat` (automático) o por `mp_payer_id` mapeado a mano |
| `payment_method_detail` | `payment_method_id` de MP |
| `raw_status` | |
| `state` | `available` \| `matched` \| `discarded` |
| `pos_payment_id` | **UNIQUE WHERE NOT NULL** |
| `pos_order_id`, `pos_session_id` | |
| `matched_by_user_id`, `matched_at` | |
| `amount_difference` | Cuando se imputó dentro de tolerancia |
| `ambiguous_pick` | Se eligió entre candidatos indistinguibles |

**No se persisten** `payer.first_name` ni `payer.last_name`: no existen en ningún canal. `payer.identification` y `payer.email` se persisten sólo en el canal QR, por la trampa de §2.3.

**Resolución del cliente**, en orden: si hay `payer_vat`, se busca `res.partner` por `vat` y se completa `partner_id`; si no, se busca un mapeo manual previo de `mp_payer_id`. Ninguna de las dos es obligatoria — un pago sin cliente resuelto se muestra igual, con banco y hora.

**Restricciones en base de datos:**

- `UNIQUE (mp_payment_id)` — el upsert nunca duplica aunque webhook y cron lleguen juntos.
- `UNIQUE (pos_payment_id) WHERE pos_payment_id IS NOT NULL` — **la restricción que sostiene el módulo**.

**Índices:** `(account_id, state, date_approved)` para la ventana; `(state, amount)` para el filtro por monto.

### 5.3 Extensiones

`pos.payment` suma `mercadopago_payment_id` y los campos de aprobación manual: `is_manual_approval`, `manual_reason`, `manual_approved_by_user_id`, `manual_approved_at`.

`pos.payment.method` suma:

| Campo | Default |
|---|---|
| `mp_account_id` (m2o) | — |
| `mp_pos_id` | — |
| `accept_alias_payments` | `False` |
| `auto_impute_single_match` | `False` |
| `search_window_minutes` | `5` |
| `poll_interval_seconds` | `10` |
| `amount_tolerance` | `0` |
| `require_manager_for_manual` | `False` |

El `many2one` a `mercadopago.account` da las dos configuraciones: varias cajas apuntando al mismo registro comparten cuenta con QR distintos; apuntando a registros distintos usan cuentas separadas.

`pos.session` suma el chequeo de cierre.

---

## 6. Ingesta

### 6.1 Filtro de ingesta — por cuenta, no por caja

El ingestor corre **por `mercadopago.account`**, y guarda todo lo que la cuenta cobró:

```python
p["collector_id"] == account.mp_user_id
and p["status"] == "approved"
and p["status_detail"] == "accredited"
and poi["business_info"]["sub_unit"] in ("qr", "money_inflows")
```

`collector_id` no es opcional: sin él entran las compras personales del dueño (§2.5).

Se persiste `source` (`qr` / `alias`) y `mp_pos_id` tal como vinieron, **sin descartar por caja**. Un pago de un QR que ningún método de pago tiene configurado igual entra a la bandeja, queda sin imputar y se reporta como huérfano — que es exactamente lo que debe pasar con dinero real que entró sin destino. Descartarlo en la ingesta lo volvería invisible.

### 6.2 Filtro de presentación — por caja

El diálogo del POS filtra la bandeja de su propia caja:

```python
state == "available"
and date_approved >= now - method.search_window_minutes
and (
    mp_pos_id == method.mp_pos_id
    or (method.accept_alias_payments and source == "alias")
)
```

Esta separación es la que hace que dos cajas nunca vean el mismo pago sin sacrificar la visibilidad de los huérfanos.

### 6.3 Canales

**Webhook** (`RF-007`, `RF-008`). Endpoint público que responde `200` en menos de 2 segundos siempre, incluso ante payloads inválidos. Del cuerpo se extrae **únicamente `data.id`**; el dato real se obtiene con una consulta autenticada. Mercado Pago documenta que en integraciones QR no se puede validar el origen por `x-Signature`, así que el endpoint se asume alcanzable por cualquiera en internet.

**Cron** (`RF-009`). Mientras haya una sesión de POS abierta, consulta la ventana a la frecuencia configurada. **Debe ser suficiente por sí solo**: el módulo tiene que funcionar con el webhook completamente deshabilitado.

Ambos llaman a la misma función de upsert idempotente.

### 6.4 Notificación a las cajas

Cuando entra un pago nuevo o uno deja de estar disponible, las cajas con diálogo abierto se enteran sin esperar al próximo ciclo.

El bus de Odoo 18 publica en el canal privado de cada `pos.config` (`pos.bus.mixin._notify`, token propio por config). **No hay canal global**: el ingestor itera los `pos.config` con sesión abierta cuyo método de pago apunta a la cuenta y al `pos_id` del pago, y notifica a cada uno.

---

## 7. Imputación

### 7.1 Unicidad

Un pago se imputa a **exactamente una** línea de pago, para siempre. Se implementa con `SELECT ... FOR UPDATE` sobre la fila del pago más la restricción `UNIQUE` como red final.

No alcanza con esconder el pago en la interfaz: dos ventas de la misma caja pueden competir por el mismo pago con milisegundos de diferencia.

### 7.2 Carrera perdida

El segundo intento encuentra el estado en `matched` y falla de forma controlada: mensaje explícito de que el pago ya fue asignado a otra venta, y refresco de la lista. Nunca falla en silencio ni imputa igual.

### 7.3 Tolerancia

Por defecto sólo monto exactamente igual. Con tolerancia configurada, se admiten pagos dentro del margen; el cajero recibe una advertencia con la diferencia y ésta queda en `amount_difference`. Fuera del margen, la selección se bloquea.

### 7.4 Reversión

Mientras la venta no está confirmada, el cajero puede deshacer y el pago vuelve a `available`. Una vez confirmada, sólo se revierte desde backoffice y queda auditado.

---

## 8. Interfaz del punto de venta

`fast_payments` en `false`: el cajero fija el monto antes de que se abra la bandeja.

El diálogo muestra los pagos de la bandeja de **esta caja** (`mp_pos_id`), dentro de la ventana, en estado `available`, cuyo monto coincide. Tres comportamientos según cuántos candidatos haya:

**Un candidato.** Resaltado, listo para confirmar de un toque. Si `auto_impute_single_match` está activo, se imputa solo mostrando un cartel con monto, hora y banco, y un botón para deshacer. Por defecto está desactivado: **imputa el cajero**.

**Ningún candidato.** Mensaje explícito de que no hay pagos con ese monto, el contador de no coincidentes desplegable (`RF-012a`) y la salida por aprobación manual.

**Dos o más.** Lista ordenada por hora, más reciente arriba. Cada fila muestra monto, hora al segundo y el mejor identificador disponible según el canal:

| Canal | Qué se muestra |
|---|---|
| QR desde Mercado Pago | **Nombre del cliente** si el CUIT resolvió contra `res.partner`; si no, el CUIT |
| QR desde billetera externa | **Banco de origen** (`"Naranja X"`), o el nombre si hay mapeo manual del `payer.id` |
| Alias | Marcado como **no identificado** |

Si hay empate de monto entre filas sin identificador distinguible, se muestra una advertencia visible y al imputar se marca `ambiguous_pick = True`.

La lista se actualiza sola por bus a medida que entran pagos.

**Aprobación manual** (`RF-016`). Primera confirmación, motivo obligatorio de texto libre, y segunda confirmación que explicita que se registra un cobro sin verificación de pago. Con `require_manager_for_manual` activo, además pide autorización de un usuario con permisos de encargado.

**Degradación** (`RF-027`, `RF-028`). Si la API no responde, el diálogo informa que la bandeja está desactualizada y desde cuándo, de forma prominente, y ofrece la aprobación manual. El POS nunca queda bloqueado. Un cajero mirando una lista congelada es peor que uno que sabe que está congelada.

---

## 9. Backoffice y control interno

**Vista de la bandeja.** Lista y formulario con filtros por estado, fecha, monto, caja y origen (`qr` / `alias`).

**Pagos huérfanos.** Los acreditados que salieron de la ventana sin imputar quedan visibles y filtrables. Este listado no puede quedar oculto: es dinero real que entró sin venta asociada, y en este modelo es un caso esperable.

**Estados.** `available` fuera de la ventana **no cambia de estado**: sigue disponible y se reporta como huérfano. La ventana es un filtro de presentación, no una transición. `matched` sólo vuelve a `available` por reversión explícita y auditada.

**Aviso al cerrar sesión.** Si hay pagos sin imputar del período de la sesión, se muestran al cajero. El cierre se permite igual; el objetivo es que el faltante se descubra en el momento.

**Reporte de aprobaciones manuales.** Vista dedicada por período, usuario y monto.

**La aprobación manual es el principal riesgo de control interno.** Permite marcar una venta como cobrada sin que haya entrado dinero. La doble confirmación disuade el error, no el abuso. Los controles reales son tres y los tres son obligatorios: el motivo escrito, el reporte revisado periódicamente, y el cruce entre aprobaciones manuales y pagos huérfanos del mismo período.

**Mapeo de pagadores.** Para el canal `INTRA_PSP` la resolución es automática por CUIT y no hace falta hacer nada. Para `INTER_PSP` —donde Mercado Pago oculta la identificación— un encargado puede asociar un `mp_payer_id` a un `res.partner`; desde ahí, todos los pagos de ese id, pasados y futuros, muestran el nombre real sacado de la base propia. Recupera la identificación para clientes recurrentes que pagan desde billeteras externas.

**Recomendación operativa.** Que el cliente escanee siempre el QR y nunca se le pase el alias. Un cobro por alias no tiene caja, ni banco de origen, ni pagador identificable: cae sistemáticamente en el camino degradado.

---

## 10. Seguridad

El `access_token` vive en `mercadopago.account` restringido a `base.group_system` y jamás abandona el servidor. Se carga desde el backoffice de Odoo, por punto de venta.

En Odoo 18, `_load_pos_data_fields()` es una whitelist explícita de los campos que se sincronizan al navegador. **Ningún campo de credenciales entra en esa lista**, y eso se verifica explícitamente. Nótese que el módulo oficial `pos_mercado_pago` guarda el token en `pos.payment.method` con `groups="point_of_sale.group_pos_manager"` y lo usa desde el frontend vía RPC; este diseño no sigue ese patrón.

El endpoint del webhook es público y no autenticable por firma en integraciones QR. La defensa no es validar el origen sino desconfiar del contenido: sólo se lee un identificador. Responde `200` sin cuerpo informativo, no confirma ni desmiente la existencia de un pago.

El `mp_payer_id` es un identificador anónimo; el mapeo a `res.partner` lo hace el comercio y vive en su base. No se vuelcan datos del pagador en logs.

---

## 11. Odoo 18 — verificado en el contenedor local

No copiar de documentación de versiones anteriores. Todo esto está confirmado contra `18.0-20260409`:

| Punto | Valor |
|---|---|
| `PaymentInterface` | `@point_of_sale/app/payment/payment_interface` |
| Registro | `register_payment_method("clave", Clase)` desde `@point_of_sale/app/store/pos_store` |
| Firma | `send_payment_request(uuid)` — **uuid, no cid**; `send_payment_cancel(order, uuid)`; `send_payment_reversal(uuid)`; `close()` |
| `pending_payment_line` | **No existe** en la interfaz. Hay `pos.getPendingPaymentLine(tipo)` en `PosStore` |
| Terminal | `_get_payment_terminal_selection()` |
| Campos al navegador | `_load_pos_data_fields()`. **`_loader_params_*` ya no existe** — el `pos_session.py` del `pos_mercado_pago` oficial es código muerto en 18 |
| Bus (server) | `config._notify('EVENTO', payload)` — `pos.bus.mixin`, canal privado por config |
| Bus (cliente) | `this.pos.data.connectWebSocket("EVENTO", cb)` |
| `fast_payments` | Override a `false` |

---

## 12. Estructura del módulo

```
pos_mercadopago_validator/
├── __manifest__.py
├── models/
│   ├── mercadopago_account.py
│   ├── mercadopago_payment.py        # LA BANDEJA — modelo central
│   ├── pos_payment.py
│   ├── pos_payment_method.py
│   └── pos_session.py
├── services/
│   ├── mp_client.py
│   ├── inbox_provider.py             # interfaz abstracta
│   └── inbox_provider_mercadopago.py
├── controllers/
│   └── webhook.py
├── security/
│   ├── ir.model.access.csv
│   └── security.xml
├── views/
│   ├── mercadopago_account_views.xml
│   ├── mercadopago_payment_views.xml
│   ├── manual_approval_report.xml
│   ├── pos_payment_method_views.xml
│   └── menus.xml
├── data/
│   └── ir_cron.xml
├── static/src/app/
│   ├── payment_mercadopago_validator.js
│   ├── inbox_dialog.js
│   ├── inbox_dialog.xml
│   └── inbox_dialog.scss
├── i18n/es_AR.po
└── tests/
    ├── test_ingestor.py
    ├── test_webhook.py
    ├── test_imputacion_unica.py      # concurrencia — crítico
    ├── test_tolerancia.py
    └── test_aprobacion_manual.py
```

La interfaz `inbox_provider` permite sumar otro procesador sin tocar el modelo de bandeja, el diálogo del POS ni la lógica de imputación. Operaciones: `fetch_payments(window_start, window_end)`, `get_payment(payment_id)`, `parse_notification(payload) -> payment_id`, `refund(payment_id, amount)`.

---

## 13. Fases

**Fase 1 — Ingestor y bandeja.** Modelos, cliente HTTP, provider, upsert idempotente, cron, filtro de §6.1. Se valida con pagos reales de monto mínimo: que aparezcan, que no se dupliquen, que el `pos_id` y el banco de origen lleguen. Al terminar, la bandeja debe poder inspeccionarse desde backoffice sin haber tocado el POS.

**Fase 2 — Webhook e idempotencia.** Controller público, camino único de escritura, prueba con notificaciones duplicadas, fuera de orden y falsificadas. Verificar que el módulo funciona igual con el webhook apagado.

**Fase 3 — Imputación y concurrencia.** Lógica de imputación, restricciones, bloqueo de fila, reversión. **La prueba de dos imputaciones simultáneas del mismo pago es criterio de salida.** No avanzar sin ella.

**Fase 4 — Interfaz del POS.** `PaymentInterface`, diálogo, los tres comportamientos de §8, actualización por bus, aprobación manual.

**Fase 5 — Backoffice y control.** Vistas de bandeja y huérfanos, mapeo de pagadores, reporte de aprobaciones manuales, aviso de cierre, traducciones.

**Fase 6 — Endurecimiento.** Prueba con dos cajas y dos QR, verificación de que ninguna credencial llega al navegador, comportamiento con la API caída.

Cada fase termina con sus tests en verde. Los bugs de esta clase de integración son de estado y concurrencia, no de presentación: no avanzar a la interfaz con el núcleo a medio verificar.

---

## 14. Criterios de aceptación

Verificados con al menos dos cajas activas y un QR por caja:

1. Un pago acreditado aparece en el diálogo del cajero en menos de 3 segundos, con monto, hora al segundo y el identificador que corresponda a su canal.
1b. Un pago por QR desde la app de Mercado Pago cuyo CUIT existe en `res.partner.vat` muestra el nombre del cliente sin intervención manual. Un pago por QR desde billetera externa muestra el banco de origen. Un pago por alias se muestra como no identificado.
1c. El CUIT y el email de un pago por alias nunca se persisten, aunque la API los devuelva.
2. El módulo funciona con el webhook completamente deshabilitado, sólo con la consulta periódica.
3. Una notificación entregada tres veces produce exactamente un registro en la bandeja.
4. **Dos ventas de la misma caja que seleccionan el mismo pago en simultáneo producen exactamente una imputación, y la segunda recibe un mensaje explícito.**
5. Un pago del QR de la caja A no aparece nunca en la bandeja de la caja B.
6. Las compras propias del dueño y los pagos donde el comercio no es `collector` no entran a la bandeja.
7. La imputación compara contra `transaction_amount`: un pago con retención se imputa a una venta por el monto bruto.
8. Con tolerancia en cero, un pago de monto distinto no aparece en la lista principal pero sí en el contador de no coincidentes. Con tolerancia configurada, aparece con la diferencia advertida y ésta queda registrada.
9. `auto_impute_single_match` desactivado exige acción del cajero aunque haya un solo candidato; activado, imputa solo y permite deshacer.
10. La aprobación manual exige dos confirmaciones y un motivo, y queda visible en el reporte dedicado.
11. Los pagos no imputados se muestran al cerrar la sesión sin impedir el cierre, y quedan como huérfanos.
12. Con la API caída, el diálogo advierte que la bandeja está desactualizada e informa desde cuándo.
13. El `access_token` no aparece en ninguna respuesta que reciba el navegador, verificado inspeccionando el tráfico.
14. El módulo se instala y desinstala en una base limpia sin errores ni residuos.

---

## Fuentes

- [Buscar pagos — `/v1/payments/search`](https://www.mercadopago.com.ar/developers/es/reference/payments/_payments_search/get)
- [Código QR — modelos estático, dinámico e híbrido](https://www.mercadopago.com.ar/developers/es/reference/in-person-payments/qr-code/overview)
- [Notificaciones — webhooks](https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications)
- [Odoo 18 — Terminales de pago en POS](https://www.odoo.com/documentation/18.0/applications/sales/point_of_sale/payment_methods/terminals.html)
- Verificación empírica: cuenta `MEAL9306838`, 2026-08-03, 89 pagos históricos + 2 pagos de prueba.
