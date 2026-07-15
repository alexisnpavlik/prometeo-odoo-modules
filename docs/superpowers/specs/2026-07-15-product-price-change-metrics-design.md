# Diseño — `product_price_change_metrics`

Fecha: 2026-07-15
Estado: aprobado (brainstorming)

## Objetivo

Unificar y mostrar los **cambios recientes de precio** de los productos para que
las sucursales detecten rápido qué productos cambiaron de precio. Trackea dos
orígenes: el **precio global** (`product.template.list_price`) y los **precios de
lista** (`product.pricelist.item`) cuando la empresa tiene una lista configurada.

Enfoque: *feed de cambios recientes* (qué cambió, cuándo, de cuánto a cuánto, en
qué empresa). No es un comparador de estado actual (eso ya lo hace
`pricelist_management_metrics`) ni un detector de "productos desactualizados".

## Contexto del repo

- `pricelist_management_metrics`: snapshot comparativo precio base vs listas por
  sucursal (controller JSON + OWL + Chart.js). Patrón de referencia para el
  dashboard.
- `product_change_history`: ya escribe `mail.tracking.value` en el chatter de
  cada producto al cambiar cualquier campo (incluido `list_price`), pero **no**
  trackea `product.pricelist.item`. Se lo deja intacto; este módulo es
  independiente y no depende de él.

### Dato clave de modelado

`list_price` en Odoo estándar **no es por compañía** — es el mismo para todas las
sucursales. La diferenciación por sucursal viene de las listas de precios
(`product.pricelist.company_id`). Por eso el log distingue:

- `source = global`: cambio de `list_price` — afecta a todas las sucursales.
  `company_id` = compañía del autor del cambio (`env.company`), como contexto.
- `source = pricelist`: cambio de un item de lista — pertenece a una sucursal
  concreta vía `pricelist.company_id`.

## Arquitectura

Módulo nuevo `product_price_change_metrics` (`18.0.1.0.0`, depends
`["product", "web"]`), estructura estándar del repo:

```
product_price_change_metrics/
  __init__.py
  __manifest__.py
  models/
    __init__.py
    product_price_log.py        # modelo product.price.log
    product_template.py         # override write() -> log de list_price
    product_pricelist_item.py   # override create()/write() -> log de items
  controllers/
    __init__.py
    price_change_controller.py  # endpoints JSON del dashboard
  security/
    security.xml                # grupo group_price_change_metrics_user
    ir.model.access.csv         # acceso al modelo product.price.log
  views/
    menu_views.xml              # menú/acción que abre el dashboard
  static/
    description/icon.png
    src/css/dashboard.css
    src/js/dashboard.js
    src/xml/dashboard.xml
```

Sin estado compartido entre captura y presentación: los `write()` sólo escriben
filas en `product.price.log`; el dashboard sólo lee.

## Modelo `product.price.log`

Una fila por cada cambio de precio detectado.

| Campo | Tipo | Nota |
|---|---|---|
| `product_tmpl_id` | many2one product.template (required, ondelete cascade, index) | producto afectado; base del click → inventario |
| `product_id` | many2one product.product (index) | variante si el cambio fue a nivel variante; null si plantilla |
| `source` | selection `[('global',...),('pricelist',...)]` (required) | origen del cambio |
| `pricelist_id` | many2one product.pricelist | sólo si `source=pricelist` |
| `company_id` | many2one res.company (index) | global→`env.company`; pricelist→`pricelist.company_id` |
| `price_type` | selection `[('fixed',...),('percent',...)]` | regla fija vs porcentaje |
| `old_price` | float | valor previo |
| `new_price` | float | valor nuevo |
| `diff_amount` | float (computed, stored) | `new_price - old_price` |
| `diff_percent` | float (computed, stored) | `(new-old)/old*100`; 0 si `old==0` |
| `change_date` | datetime (default now, index) | lineage por defecto |
| `user_id` | many2one res.users (default env.user) | autor del cambio |

Notas:
- `diff_amount` / `diff_percent` computed **stored** para poder ordenar/filtrar
  en SQL desde el controller.
- No se crea fila si `old_price == new_price`.

## Captura de cambios

### `product.template.write()`
- Si `list_price` está en `vals`: capturar `old = record.list_price` por registro
  antes del `super()`, comparar con el nuevo, y crear log `source=global`,
  `price_type=fixed`, `company_id=env.company`.
- Sólo plantilla (no variante) → `product_id` null.

### `product.pricelist.item` — `create()` y `write()`
- Detectar cambios en `fixed_price`, `percent_price`, `compute_price`.
- `create()`: se registra como cambio desde 0 (o desde base según tipo) sólo si
  representa un precio nuevo real; ver "Casos borde".
- `price_type`: `fixed` si `compute_price=fixed` (usar `fixed_price`); `percent`
  si `compute_price=percentage` (usar `percent_price`). Reglas `formula` se
  ignoran (no comparables, igual que en `pricelist_management_metrics`).
- `company_id = item.pricelist_id.company_id` (puede ser null si la lista es
  global; en ese caso queda null y el dashboard lo trata como "todas").
- `product_tmpl_id` / `product_id`: desde el `applied_on` del item
  (`product_tmpl_id` o `product_id.product_tmpl_id`). Items `applied_on` de
  categoría o globales (sin producto) se ignoran — no son cambios de un producto.

### Robustez
Ambos override envuelven la lógica de logging en `try/except Exception as e` con
`_logger.warning`. **El log nunca debe abortar el guardado** (mismo criterio que
`product_change_history`). El `super().write()` se llama siempre.

## Dashboard

Controller `PriceChangeMetricsController` con `_check_access()` que valida
`group_price_change_metrics_user` (patrón idéntico a `pricelist_management_metrics`).
Respeta `request.env.companies` para multi-compañía.

### Endpoints (type='json', auth='user')
- `/product_price_change_metrics/filters` → empresas permitidas, categorías,
  productos (con nombre traducido según `lang`), orígenes.
- `/product_price_change_metrics/changes` → tabla paginada de cambios filtrados.
- `/product_price_change_metrics/metrics` → KPIs + datos del gráfico.

### Filtros
- Ventana temporal: **default últimos 30 días**; opciones 7 / 30 / 90 / todo.
- Empresa / sucursal.
- Origen (global / lista).
- Categoría, producto, búsqueda por nombre.

### KPIs
- Nº de cambios en la ventana.
- Nº de productos afectados (distinct `product_tmpl_id`).
- Variación promedio %.
- Mayor subida y mayor baja (producto + %).

### Tabla
Columnas: producto · categoría · origen (Global / nombre sucursal) · precio
anterior → nuevo · Δ% (verde sube / rojo baja) · fecha · usuario. Paginada.

**Click en la fila → abre el producto en su formulario** vía `this.action.doAction`
con `res_model: 'product.template'`, `res_id`, `views: [[false, 'form']]`. Odoo lo
resuelve en el contexto de la app Inventario.

### Gráfico
Chart.js: barras horizontales **Top-N productos por magnitud absoluta de cambio**
(`|Δ%|`) en la ventana, coloreadas por signo (sube/baja). Consistente con el gráfico
de mayores diferencias de `pricelist_management_metrics`.

## Seguridad

- `security/security.xml`: `group_price_change_metrics_user`.
- `security/ir.model.access.csv`: lectura de `product.price.log` para el grupo;
  el modelo se escribe sólo por el sistema (sudo en los override), sin
  create/write/unlink desde UI para usuarios.

## Casos borde

- `old_price == new_price`: no se registra.
- `list_price` cambia junto a otros campos: sólo se mira `list_price`.
- Item de lista `compute_price = formula`: se ignora (no comparable).
- Item `applied_on` categoría/global (sin producto concreto): se ignora.
- `create()` de item de lista: registrar sólo si define un precio concreto
  (`fixed`/`percentage`); tratar `old_price=0` y marcar como alta. Evitar ruido
  al importar/instalar datos masivos si es necesario (evaluar flag de contexto en
  el plan).
- Lista de precios sin `company_id` (global): `company_id` null; el dashboard lo
  muestra como cambio que aplica a todas.
- Baja de producto: `ondelete='cascade'` elimina sus logs.

## Fuera de alcance (YAGNI)

- Detección de "productos desactualizados" (no cambian hace X tiempo).
- Backfill retroactivo desde `mail.tracking.value`.
- Tracking de costo (`standard_price`).
- Notificaciones/alertas automáticas.

## Entregables

- Módulo instalable en Odoo 18 (`-u`/`-i` por CLI en el contenedor de dev).
- Icono `static/description/icon.png` (plantilla Cyber-Glassmorphic del repo).
