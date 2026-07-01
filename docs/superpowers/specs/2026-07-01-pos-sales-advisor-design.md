# Diseño: pos_sales_advisor — Trackeo de Asesores de Venta en POS

**Fecha:** 2026-07-01
**Odoo:** 18.0
**Módulo:** `pos_sales_advisor` (único módulo autocontenido)

## Objetivo

Medir cuántas ventas produce cada asesor de venta en el punto de venta para
calcular compensaciones económicas. El asesor se selecciona en la pantalla de
pago del POS, se guarda en la orden y se analiza en un dashboard gerencial con
el mismo lenguaje de diseño de `pos_management_metrics`.

## Decisiones de diseño

| Decisión | Elección |
|---|---|
| Qué es un asesor | Modelo propio simple `pos.sales.advisor` (sin dependencia de `hr` ni `res.users`) |
| Cardinalidad | Un asesor por orden (`Many2one` en `pos.order`) |
| Obligatoriedad | Configurable por caja (`require_sales_advisor` en `pos.config`) |
| Comisiones | Solo métricas; el cálculo de compensación se hace fuera del sistema |
| Persistencia POS | Data-layer nativo de POS 18 (`_load_pos_data_models`); sincroniza offline |
| Empaquetado | Un solo módulo con modelo + UI POS + dashboard |

## 1. Modelo de datos

### `pos.sales.advisor` (nuevo — `models/pos_sales_advisor.py`)

| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char, required | Nombre del asesor |
| `active` | Boolean, default True | Archivar sin perder histórico |
| `company_id` | Many2one `res.company`, opcional, default compañía actual | Vacío = compartido entre empresas |

### `pos.order` (`models/pos_order.py`)

- `sales_advisor_id`: Many2one `pos.sales.advisor`, editable en backend para
  correcciones posteriores.
- **Devoluciones:** al crear un refund desde POS, hereda el asesor de la orden
  original, de modo que la devolución reste en la métrica del asesor (neto).

### `pos.config` + `res.config.settings` (`models/pos_config.py`, `wizards/res_config_settings.py`)

- `require_sales_advisor`: Boolean. Si está activo, el POS no permite validar
  el pago sin asesor seleccionado.

## 2. Carga al frontend POS

- `models/pos_session.py`: `_load_pos_data_models(config_id)` agrega
  `"pos.sales.advisor"` (patrón de `pos_product_pack`).
- `pos.sales.advisor._load_pos_data_fields` → `["id", "name"]`; el dominio de
  carga filtra activos y compañía de la caja (o sin compañía).
- `pos.order._load_pos_data_fields` incluye `sales_advisor_id` para que el
  campo viaje con la sincronización nativa de la orden (funciona offline).
- `pos.config._load_pos_data_fields` incluye `require_sales_advisor`.

## 3. UI en pantalla de pago (POS)

- `static/src/xml/advisor_button.xml`: `t-inherit="point_of_sale.PaymentScreenButtons"`
  modo extension, xpath `inside` del div `payment-buttons`:
  - Botón **"Asesor de Venta"** (`fa fa-user`).
  - **Badge flotante** abajo a la derecha (mismo patrón visual del badge de
    `card_installment`): verde + nombre del asesor si hay selección; amarillo
    "Sin seleccionar" cuando la caja lo requiere y falta.
- `static/src/js/payment_screen_patch.js`: patch de `PaymentScreen.prototype`:
  - `onClickAdvisor()`: popup de selección nativo (`makeAwaitable` +
    `SelectionPopup`) con asesores activos + opción "Quitar asesor". Setea
    `sales_advisor_id` en la orden actual.
  - Override de `validateOrder()`: si `config.require_sales_advisor` y la orden
    no tiene asesor → diálogo de error y no valida.

## 4. Backend (vistas y menú)

- `views/pos_sales_advisor_views.xml`: list + form simples; menú
  **"Asesores de Venta"** bajo Punto de Venta → Configuración, visible para
  `point_of_sale.group_pos_manager`.
- `views/pos_order_views.xml`: campo en form, columna opcional en list,
  filtro y "Agrupar por asesor" en search.
- `views/res_config_settings_views.xml`: checkbox en ajustes del POS.

## 5. Dashboard "Métricas de Asesores"

Mismo lenguaje de diseño de `pos_management_metrics`: componente OWL backend,
Chart.js por CDN, sidebar glassmorphic, KPI cards, tema dark/light.

### Frontend (`static/src/js/dashboard.js`, `xml/dashboard.xml`, `css/dashboard.css`)

- Sidebar: presets de fecha (Hoy / Ayer / 7 / 30 / 60 / 90 días / Todo + rango
  custom) y filtros: asesor, caja (pos.config), empresa. Botones Aplicar/Limpiar.
- **KPIs:** ventas netas atribuidas, # órdenes con asesor, ticket promedio,
  **% de órdenes sin asesor** (control de adopción por los cajeros).
- **Gráficos:** ranking de asesores (barras horizontales por monto neto),
  evolución temporal comparada (líneas, top asesores), participación % (donut).
- **Tabla detalle por asesor:** ventas brutas, devoluciones, neto, # órdenes,
  ticket promedio; búsqueda por nombre; **export CSV** (insumo directo para
  liquidar compensaciones).
- Registro vía `registry.category("actions")` + `ir.actions.client` + menú raíz
  propio con `web_icon`.

### Controller (`controllers/advisor_controller.py`)

- `http.Controller`, rutas `type='json'`, `auth='user'`:
  - `/pos_sales_advisor/filters_metadata`
  - `/pos_sales_advisor/metrics`
- `_check_access()` que exige `pos_sales_advisor.group_pos_advisor_metrics`.
- SQL parametrizado sobre `pos_order LEFT JOIN pos_sales_advisor`, estados
  `('paid','done','invoiced')` — a diferencia de `metrics_controller` (que usa
  solo `done/invoiced`) se incluye `paid` deliberadamente para ver las ventas
  del día antes del cierre de sesión. Filtro multi-compañía
  (`request.env.companies.ids`) y fechas timezone-aware (mismo patrón
  `AT TIME ZONE` del controller existente).
- Órdenes sin asesor: se computan solo para el KPI "% sin asesor" (no aparecen
  en ranking ni tabla).

## 6. Seguridad

- `security/security.xml`: `group_pos_advisor_metrics` (categoría
  `base.module_category_usability`, con `comment`) — acceso al menú/dashboard.
- `security/ir.model.access.csv`:
  - `pos.sales.advisor`: read para `point_of_sale.group_pos_user` (la caja
    necesita leer la lista); read/write/create/unlink para
    `point_of_sale.group_pos_manager`.
- Sin `ir.rule` restrictivas (no aplica el gotcha de OR-combination).

## 7. Manifest

- `depends`: `["point_of_sale", "web"]`.
- `data`: security primero, luego views.
- `assets`: `point_of_sale._assets_pos` (botón + patch de pago) y
  `web.assets_backend` (dashboard css/js/xml).
- `application: True` (tiene menú raíz propio, como pos_management_metrics).

## 8. Icono

Cyber-Glassmorphic 3D desde `assets/cyber-glass-icon.svg` del skill, glyph
"A", render a `static/description/icon.png` con Chrome headless.

## 9. Casos borde

- **Orden sin asesor (caja no exigente):** válida; solo alimenta el KPI de
  control "% sin asesor".
- **Asesor archivado:** desaparece del POS y de los filtros de alta, pero su
  histórico sigue visible en el dashboard.
- **Devoluciones:** heredan asesor de la orden origen; el dashboard reporta
  bruto, devoluciones y neto por separado.
- **Multi-compañía:** asesores con `company_id` solo cargan en cajas de esa
  compañía; el dashboard respeta las compañías activas del usuario.

## 10. Validación

- Sintaxis local: XML (`xml.dom.minidom`), CSV (columnas consistentes),
  manifest (`ast.parse`).
- Upgrade en container local:
  `sudo docker exec odoo-odoo-1 odoo -u pos_sales_advisor -d <db> --stop-after-init`.
- Prueba manual: sesión POS → seleccionar asesor en pago → validar → verificar
  campo en la orden backend → verificar métricas en dashboard.
- Sin tests unitarios (convención del repo).
