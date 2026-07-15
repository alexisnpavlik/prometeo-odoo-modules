# Diseño — `product_price_change_metrics`

Fecha: 2026-07-15
Estado: aprobado (brainstorming)

## Objetivo

Herramienta **operativa** para que cada sucursal sepa qué productos cambiaron de
precio recientemente y pueda **ir a cambiar las etiquetas en la góndola**. No es
un tablero gerencial de métricas: el centro es una **lista de trabajo accionable**
con un checklist de pendiente / actualizado por sucursal.

Trackea dos orígenes de cambio de precio:
- **Global**: `product.template.list_price`.
- **Lista de precios**: `product.pricelist.item` (cuando la empresa tiene una
  lista configurada).

Enfoque: *feed de cambios recientes* + *checklist de góndola*. No compara estado
actual (eso ya lo hace `pricelist_management_metrics`) ni detecta "productos
desactualizados por antigüedad".

## Contexto del repo

- `pricelist_management_metrics`: snapshot comparativo precio base vs listas por
  sucursal (controller JSON + OWL + Chart.js). Patrón de referencia para el
  dashboard OWL.
- `product_change_history`: ya escribe `mail.tracking.value` en el chatter de
  cada producto al cambiar cualquier campo (incluido `list_price`), pero **no**
  trackea `product.pricelist.item`. Se lo deja intacto; este módulo es
  independiente y no depende de él.

### Decisiones de alcance (brainstorming)

- **Cambios crudos**: se muestran los cambios de `list_price` global y los cambios
  de la lista de cada sucursal, **sin** cruzar cuál precio pisa a cuál. Un cambio
  global le aparece a una sucursal aunque esa sucursal tenga su propia lista.
- **Checklist por sucursal**: cada fila tiene estado pendiente/actualizado; el
  empleado marca "ya cambié la etiqueta" (guarda usuario + fecha). Cada sucursal
  ve solo sus filas.
- **Dashboard OWL** enfocado en la lista accionable. **Sin gráficos** de métricas
  porcentuales.

### Dato clave de modelado — fan-out por empresa

`list_price` en Odoo estándar **no es por compañía**: un cambio global afecta a
todas las sucursales, pero cada una debe marcarlo como hecho por separado. Por eso:

- Cambio **global** → se crea **una fila `product.price.log` por cada empresa
  activa** (fan-out). Cada sucursal tiene su propia fila con su estado.
- Cambio de **lista** → se crea **una sola fila** para `pricelist.company_id`
  (la sucursal dueña de la lista). Si la lista no tiene `company_id` (global),
  se hace fan-out a todas las empresas.

Volumen: los cambios masivos globales multiplican filas por Nº de empresas. Como
las sucursales son pocas, es aceptable y mantiene la consulta trivial (una tabla,
filtrar por `company_id` + `state`).

## Arquitectura

Módulo nuevo `product_price_change_metrics` (`18.0.1.0.0`, depends
`["product", "web"]`), estructura estándar del repo:

```
product_price_change_metrics/
  __init__.py
  __manifest__.py
  models/
    __init__.py
    product_price_log.py        # modelo product.price.log (con estado de góndola)
    product_template.py         # override write() -> log de list_price (fan-out)
    product_pricelist_item.py   # override create()/write() -> log de items
  controllers/
    __init__.py
    price_change_controller.py  # endpoints JSON del dashboard + marcar hecho
  security/
    security.xml                # grupo group_price_change_metrics_user + record rule
    ir.model.access.csv         # acceso read al modelo para el grupo
  views/
    menu_views.xml              # menú/acción que abre el dashboard
  static/
    description/icon.png
    src/css/dashboard.css
    src/js/dashboard.js
    src/xml/dashboard.xml
```

Los `write()` sólo escriben filas en `product.price.log`; el dashboard lee y
actualiza únicamente el estado de góndola (vía endpoint con sudo).

## Modelo `product.price.log`

Una fila por (cambio de precio, empresa). Es a la vez registro del cambio y tarea
de góndola de esa sucursal.

| Campo | Tipo | Nota |
|---|---|---|
| `product_tmpl_id` | many2one product.template (required, ondelete cascade, index) | producto afectado; base del click → inventario |
| `product_id` | many2one product.product (index) | variante si el cambio fue a nivel variante; null si plantilla |
| `source` | selection `[('global',…),('pricelist',…)]` (required) | origen del cambio |
| `pricelist_id` | many2one product.pricelist | sólo si `source=pricelist` |
| `company_id` | many2one res.company (required, index) | sucursal dueña de esta tarea (fan-out) |
| `price_type` | selection `[('fixed',…),('percent',…)]` | regla fija vs porcentaje |
| `old_price` | float | valor previo |
| `new_price` | float | valor nuevo |
| `diff_amount` | float (computed, stored) | `new_price - old_price` (para mostrar "subió $X") |
| `change_date` | datetime (default now, index) | lineage por defecto |
| `user_id` | many2one res.users (default env.user) | autor del cambio de precio |
| `state` | selection `[('pending','Pendiente'),('done','Actualizado')]` (default `pending`, index) | estado de góndola |
| `done_user_id` | many2one res.users | quién marcó la etiqueta actualizada |
| `done_date` | datetime | cuándo se marcó |

Notas:
- No se crea fila si `old_price == new_price`.
- `diff_amount` computed **stored** para ordenar/mostrar; no se calcula % (fuera
  de foco).
- El estado (`state`, `done_user_id`, `done_date`) es lo único mutable desde la UI,
  y sólo vía el endpoint del controller.

## Captura de cambios

### `product.template.write()`
- Si `list_price` está en `vals`: capturar `old = record.list_price` por registro
  antes del `super()`, comparar con el nuevo. Si cambió, **fan-out**: crear una
  fila `source=global`, `price_type=fixed`, por cada empresa activa
  (`res.company.search([])`), con `company_id` = cada empresa.
- Sólo plantilla → `product_id` null.

### `product.pricelist.item` — `create()` y `write()`
- Detectar cambios en `fixed_price`, `percent_price`, `compute_price`.
- `price_type`: `fixed` si `compute_price=fixed` (usar `fixed_price`); `percent`
  si `compute_price=percentage` (usar `percent_price`). Reglas `formula` se
  ignoran (no comparables).
- `company_id = item.pricelist_id.company_id`; si es null (lista global), fan-out
  a todas las empresas activas.
- `product_tmpl_id` / `product_id`: desde el `applied_on` del item. Items
  `applied_on` de categoría o globales (sin producto) se ignoran.
- `create()`: se registra como alta (`old_price=0`) sólo si define un precio
  concreto (`fixed`/`percentage`).

### Robustez
Ambos override envuelven la lógica de logging en `try/except Exception as e` con
`_logger.warning`. **El log nunca debe abortar el guardado**. El `super()` se
llama siempre.

## Dashboard OWL

Controller `PriceChangeMetricsController` con `_check_access()` que valida
`group_price_change_metrics_user` (patrón idéntico a `pricelist_management_metrics`).
Respeta `request.env.companies` para multi-compañía.

### Endpoints (type='json', auth='user')
- `/product_price_change_metrics/filters` → empresas permitidas, categorías,
  orígenes.
- `/product_price_change_metrics/changes` → lista paginada de cambios filtrados
  (la tabla de trabajo).
- `/product_price_change_metrics/mark_done` → marca una o varias filas como
  actualizadas (setea `state=done`, `done_user_id`, `done_date`). Usa **sudo**;
  valida que las filas pertenezcan a `request.env.companies`.

### Filtros
- Empresa / sucursal (**default: la empresa del usuario**, `env.company`).
- Estado: **pendiente** (default) / actualizado / todos.
- Ventana temporal: últimos 7 / 30 / 90 días / todo (default 30).
- Categoría, búsqueda por nombre de producto.
- Origen (global / lista) — secundario.

### Lista de trabajo (tabla)
Columnas: `[✓]` · Producto · Categoría · Origen (Global / nombre sucursal) ·
Precio anterior → nuevo · Fecha · Estado.

- **Click en el nombre del producto → abre su formulario** vía
  `this.action.doAction` con `res_model:'product.template'`, `res_id`,
  `views:[[false,'form']]` (cae en la app Inventario).
- **Marcar actualizado**: checkbox por fila + botón "Marcar seleccionados como
  actualizados" (acción en lote) → llama a `mark_done`. Las filas marcadas
  muestran usuario + fecha.
- Ordenada por `change_date` desc (lo más nuevo arriba).
- Agrupable/filtrable por categoría para recorrer las góndolas por sector.

### Resumen liviano (sin gráficos)
Un contador simple arriba: "**N pendientes** de actualizar en góndola" para la
empresa/filtros actuales. Nada de Chart.js.

## Seguridad

- `security/security.xml`:
  - `group_price_change_metrics_user`.
  - **Record rule** multi-compañía: el usuario sólo ve filas con
    `company_id in company_ids`.
- `security/ir.model.access.csv`: **solo lectura** de `product.price.log` para el
  grupo. Las filas se crean por los override (sudo) y el cambio de estado va por
  el endpoint `mark_done` (sudo con validación de compañía). Sin create/write/
  unlink directos desde UI para usuarios.

## Casos borde

- `old_price == new_price`: no se registra.
- `list_price` cambia junto a otros campos: sólo se mira `list_price`.
- Item de lista `compute_price = formula`: se ignora (no comparable).
- Item `applied_on` categoría/global (sin producto concreto): se ignora.
- Lista de precios sin `company_id` (global): fan-out a todas las empresas.
- Baja de producto: `ondelete='cascade'` elimina sus logs.
- Fan-out con muchas empresas: volumen aceptable por Nº bajo de sucursales;
  evaluar en el plan un flag de contexto para saltar el logging en cargas masivas
  de datos/instalación si hace ruido.
- `mark_done` sobre filas de otra compañía: rechazado por la validación de
  `env.companies`.

## Fuera de alcance (YAGNI)

- Cruce "precio efectivo" (filtrar cambios globales que la sucursal pisa con su
  lista) — se eligió cambios crudos.
- Gráficos / métricas porcentuales gerenciales.
- Detección de "productos desactualizados" por antigüedad.
- Backfill retroactivo desde `mail.tracking.value`.
- Tracking de costo (`standard_price`).
- Notificaciones/alertas automáticas.

## Entregables

- Módulo instalable en Odoo 18 (`-u`/`-i` por CLI en el contenedor de dev).
- Icono `static/description/icon.png` (plantilla Cyber-Glassmorphic del repo).
