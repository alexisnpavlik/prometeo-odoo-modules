# prometeo_purchase_advisor — Especificación técnica

**Versión:** 1.0
**Target:** Odoo 17/18 Community
**Autor:** Prometeo
**Estado:** Spec para implementación

---

## 0. Cómo usar este documento

Este spec está pensado para ejecutarse por fases. **Implementar en orden.** Cada fase termina en un estado funcional y testeable. No avanzar a la siguiente sin que la anterior tenga tests en verde.

Reglas transversales para toda la implementación:

- **Sin dependencias externas en el core.** Nada de `numpy`, `pandas`, `scipy`, `prophet`, `statsmodels` en `prometeo_purchase_advisor`. Solo stdlib de Python + ORM de Odoo. Los métodos que necesiten librerías pesadas van en módulos satélite con `external_dependencies`.
- **Todo el cálculo pesado va en SQL crudo**, no en loops del ORM. El objetivo es soportar 20k productos × 12 almacenes sin timeout.
- **Todo campo calculado que el usuario vea debe tener una explicación en texto legible.** Si el usuario no entiende por qué el sistema sugiere 47 unidades, no va a aprobar la orden.
- **Multi-compañía y multi-almacén desde el día uno.** No asumir `warehouse_id = 1`.
- Código en inglés (nombres de modelos, campos, métodos). Labels y ayudas de usuario en español.

---

## 1. Objetivo del módulo

Generar sugerencias de compra basadas en la demanda real observada, permitir que el usuario las revise y edite, y convertirlas en órdenes de compra agrupadas por proveedor.

**Alcance v1:**

- Cálculo de demanda diaria por producto/almacén a partir de movimientos de stock reales.
- Sugerencia de cantidad a comprar considerando lead time, stock actual, tránsito y variabilidad.
- Interfaz de revisión donde el usuario puede editar cantidades, agregar y quitar productos.
- Generación de `purchase.order` agrupadas por proveedor.
- Arquitectura de métodos de estimación intercambiables (aunque v1 implemente solo uno).

**Fuera de alcance v1** (pero la arquitectura debe permitirlo):

- Métodos estadísticos avanzados (Croston, Prophet, ARIMA).
- Optimización por presupuesto (knapsack).
- Sugerencia de traspasos entre sucursales.
- Estacionalidad.

---

## 2. Decisiones de arquitectura (no negociables)

### 2.1 Fuente de datos: `stock_move`, no `sale_order_line`

La demanda se lee de `stock_move` en estado `done` cuyo destino es una ubicación de tipo `customer`. Razones:

- Unifica ventas POS, ventas normales, y entregas manuales en una sola query.
- Da la dimensión de almacén de forma natural.
- Es el único lugar donde la salida física de mercadería queda registrada sin importar el canal.

Nunca leer de `sale.order.line` ni de `pos.order.line`.

### 2.2 Pipeline de 4 etapas desacopladas

```
DemandSeries  →  [ESTIMATOR]  →  Estimate(adu, sigma)  →  [SAFETY STOCK]  →  [QUANTITY]  →  [PRIORITY/FILTER]
  (compartido)      (varía)                                 (varía poco)      (redondeos)     (ABC, filtros)
```

Solo el estimador varía entre métodos. Agregar un método nuevo debe tocar **únicamente** la etapa de estimación. Si al implementar resulta que un método necesita cambiar otra etapa, eso es señal de que el contrato de datos está mal definido — corregir el contrato, no agregar ramas condicionales.

### 2.3 Despacho de métodos: patrón `delivery.carrier`

Selection extensible + despacho por convención de nombre de método (`_estimate_<method>`). Es el patrón que usa Odoo en `delivery.carrier` y `payment.provider`. Un módulo satélite extiende el Selection vía `super()` y agrega su método.

### 2.4 Modelo persistente, no wizard

`purchase.suggestion` es un modelo con registros permanentes, no un `TransientModel`. Esto permite auditar después qué tan buena fue cada sugerencia y comparar `qty_suggested` contra `qty_final`.

---

## 3. Contratos de datos

Clases Python planas (`@dataclass`), **no modelos Odoo**. Van en `prometeo_purchase_advisor/models/datatypes.py`.

```python
from dataclasses import dataclass, field
from datetime import date

@dataclass
class DemandSeries:
    """Serie de demanda ya materializada. Se construye UNA sola vez por corrida."""
    warehouse_id: int
    date_from: date
    date_to: date
    product_ids: list                      # list[int]
    qty: dict                              # {product_id: {date: float}}
    had_stock: dict                        # {product_id: {date: bool}}
    first_move_date: dict                  # {product_id: date} — para history_days

    def days_with_stock(self, product_id) -> int: ...
    def total_qty(self, product_id, days=None) -> float: ...
    def history_days(self, product_id) -> int: ...
    def daily_values(self, product_id, days=None) -> list: ...

@dataclass
class Estimate:
    """Salida de un estimador. Contrato estable entre métodos."""
    adu: float                             # demanda diaria promedio
    sigma: float                           # desvío estándar diario
    confidence: float                      # 0.0 - 1.0
    method_used: str                       # puede diferir del solicitado (degradación)
    explanation: str                       # texto legible en español
    warnings: list = field(default_factory=list)
```

### Sobre `confidence`

Escala sugerida (ajustable):

| Condición | confidence |
|---|---|
| < 30 días de historia | 0.2 |
| < 10 movimientos de salida en la ventana | 0.3 |
| > 50% de días sin stock | 0.4 |
| Coeficiente de variación > 1.5 | 0.5 |
| Caso normal | 0.8 – 1.0 |

Se toma el mínimo de todas las condiciones que apliquen. Líneas con `confidence < 0.5` se marcan visualmente para revisión manual.

### Sobre `method_used` y degradación

Un estimador que no puede correr con los datos disponibles **no falla**: delega en el fallback (`weighted_ma`), setea `method_used` al método realmente usado, y agrega un warning explicando por qué. Nunca devolver números inventados ni levantar excepción por falta de historia.

---

## 4. Modelo de datos

### 4.1 `prometeo.demand.model`

Configuración de un método de estimación. Es un modelo con registros para que el cliente pueda tener varios perfiles configurados simultáneamente.

| Campo | Tipo | Default | Notas |
|---|---|---|---|
| `name` | Char | — | required |
| `method` | Selection | `weighted_ma` | selection dinámico vía `_selection_method()` |
| `active` | Boolean | True | |
| `company_id` | Many2one res.company | current | |
| `lookback_days` | Integer | 90 | ventana de historia a leer |
| `service_level` | Float | 0.95 | se traduce a Z |
| `ignore_stockout_days` | Boolean | True | corrección de censura |
| `outlier_percentile` | Float | 0.95 | winsorización; 0 = desactivado |
| `min_history_days` | Integer | 21 | por debajo → confidence baja |
| `weight_config` | Char | `"14:0.5,30:0.3,90:0.2"` | solo `weighted_ma` |
| `alpha` | Float | 0.3 | solo `ewma` |

Método público principal:

```python
def estimate(self, series: DemandSeries) -> dict:
    """Devuelve {product_id: Estimate}. Despacha a _estimate_<method>."""
    self.ensure_one()
    method_fn = getattr(self, '_estimate_%s' % self.method, None)
    if method_fn is None:
        raise UserError(...)
    return method_fn(series)
```

Validaciones:
- `weight_config` debe parsear a pares `dias:peso` con pesos que sumen 1.0 (±0.01). Constraint.
- `service_level` entre 0.5 y 0.999.
- Ningún `lookback_days` menor a la ventana más grande de `weight_config`.

Tabla de Z (hardcodeada, sin scipy):

```python
Z_TABLE = {0.50: 0.00, 0.75: 0.67, 0.80: 0.84, 0.85: 1.04, 0.90: 1.28,
           0.925: 1.44, 0.95: 1.65, 0.975: 1.96, 0.98: 2.05, 0.99: 2.33, 0.995: 2.58}
# interpolar linealmente entre claves
```

### 4.2 `prometeo.demand.model.rule`

Asignación automática de método por producto. Evaluación por `sequence`, primera regla que matchea gana.

| Campo | Tipo | Notas |
|---|---|---|
| `sequence` | Integer | default 10 |
| `name` | Char | required |
| `domain` | Char | dominio sobre `product.product` |
| `abc_class` | Selection a/b/c | opcional |
| `xyz_class` | Selection x/y/z | opcional |
| `min_history_days` | Integer | opcional |
| `model_id` | Many2one demand.model | required |
| `company_id` | Many2one | |

**Cascada de resolución** (primero que resuelve gana):
1. `product.product.demand_model_id` (override manual en el producto)
2. `product.category.demand_model_id` (override en categoría)
3. Primera `demand.model.rule` que matchea
4. Default de la compañía (`res.config.settings`)

En v1 con un solo método esto parece innecesario. Implementarlo igual: la cascada es la pieza que hace que agregar el segundo método sea trivial en vez de una refactorización.

### 4.3 `prometeo.purchase.suggestion`

Modelo principal. Hereda `mail.thread` y `mail.activity.mixin`.

| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char | secuencia `PS/YYYY/NNNNN` |
| `state` | Selection | `draft` → `computed` → `confirmed` → `done` / `cancel` |
| `warehouse_id` | Many2one stock.warehouse | required |
| `company_id` | Many2one | related warehouse |
| `date_computed` | Datetime | readonly |
| `coverage_days` | Integer | días de cobertura objetivo, default 30 |
| `demand_model_id` | Many2one demand.model | override global opcional; si vacío usa la cascada |
| `line_ids` | One2many suggestion.line | |
| `purchase_order_ids` | One2many purchase.order | inverse `suggestion_id` |
| `total_amount` | Monetary | compute, suma de líneas |
| `line_count` | Integer | compute |
| `low_confidence_count` | Integer | compute, líneas con confidence < 0.5 |

Acciones:
- `action_compute()` — corre el pipeline, puebla `line_ids`, pasa a `computed`. Idempotente: si ya hay líneas, preserva las editadas manualmente (ver 6.3).
- `action_confirm()` — valida y pasa a `confirmed`.
- `action_create_purchase_orders()` — agrupa por proveedor y crea POs. Pasa a `done`.
- `action_cancel()` / `action_draft()`.

### 4.4 `prometeo.purchase.suggestion.line`

| Campo | Tipo | readonly | Notas |
|---|---|---|---|
| `suggestion_id` | Many2one | — | ondelete cascade |
| `product_id` | Many2one product.product | no | required |
| `supplier_id` | Many2one res.partner | no | default del `supplierinfo` |
| `qty_suggested` | Float | **sí** | lo que calculó el sistema |
| `qty_final` | Float | no | lo que el usuario deja — **este va a la PO** |
| `price_unit` | Float | no | del supplierinfo |
| `subtotal` | Monetary | compute | |
| `is_manual` | Boolean | **sí** | True si lo agregó el usuario |
| `was_edited` | Boolean | compute stored | `qty_final != qty_suggested` |
| — *métricas* — | | | |
| `adu` | Float | sí | demanda diaria |
| `sigma` | Float | sí | |
| `confidence` | Float | sí | |
| `coverage_days_current` | Float | sí | **campo estrella de la UI** |
| `qty_on_hand` | Float | sí | |
| `qty_incoming` | Float | sí | POs confirmadas pendientes |
| `lead_time_days` | Float | sí | medido, no configurado |
| `safety_stock` | Float | sí | |
| `abc_class` | Selection | sí | |
| `xyz_class` | Selection | sí | |
| — *trazabilidad* — | | | |
| `demand_model_id` | Many2one | sí | |
| `method_used` | Char | sí | |
| `params_snapshot` | Json | sí | parámetros exactos usados |
| `explanation` | Text | sí | texto en español |
| `warnings` | Text | sí | |

`_order = 'coverage_days_current asc, adu desc'` — lo que está por quebrar y vende mucho aparece arriba.

### 4.5 Extensiones a modelos existentes

```python
# product.product / product.template
demand_model_id = fields.Many2one('prometeo.demand.model')  # override
exclude_from_suggestion = fields.Boolean()
abc_class = fields.Selection(..., compute=..., store=True)
xyz_class = fields.Selection(..., compute=..., store=True)

# product.category
demand_model_id = fields.Many2one('prometeo.demand.model')

# purchase.order
suggestion_id = fields.Many2one('prometeo.purchase.suggestion', readonly=True)

# res.partner (proveedor)
measured_lead_time = fields.Float(compute=..., store=True)  # días, medido
fill_rate = fields.Float(compute=..., store=True)           # 0-1
```

---

## 5. Motor de cálculo

### 5.1 Construcción de `DemandSeries` (SQL)

Query base de demanda diaria. Ajustar nombres de columnas a la versión de Odoo objetivo.

```sql
SELECT
    sm.product_id,
    DATE(sm.date) AS move_date,
    SUM(sm.product_qty) AS qty
FROM stock_move sm
JOIN stock_location dest ON dest.id = sm.location_dest_id
JOIN stock_location src  ON src.id  = sm.location_id
WHERE sm.state = 'done'
  AND dest.usage = 'customer'
  AND src.usage  = 'internal'
  AND sm.company_id = %(company_id)s
  AND sm.date >= %(date_from)s
  AND sm.date <  %(date_to)s
  AND src.parent_path LIKE %(wh_location_path)s
  AND sm.product_id = ANY(%(product_ids)s)
GROUP BY sm.product_id, DATE(sm.date)
```

**Notas de implementación:**
- Filtrar por almacén vía `parent_path LIKE 'x/y/%'` de la ubicación stock del warehouse, no por `warehouse_id` directo (los movimientos POS no siempre lo tienen seteado).
- Devoluciones (`customer` → `internal`) deben **restarse**. Correr una segunda query invertida y netear.
- Convertir a UoM de referencia del producto si `product_uom` difiere.

### 5.2 Reconstrucción de `had_stock`

Esta es la parte más delicada del módulo. Sin esto el sistema se autoperpetúa: no compra lo que se agota rápido, precisamente porque se agotó.

Enfoque: reconstruir el stock hacia atrás desde el stock actual.

```
stock[hoy] = qty_available actual
stock[d-1] = stock[d] - (entradas del día d) + (salidas del día d)
had_stock[d] = stock[d] > 0
```

Query de movimientos netos diarios (entradas y salidas, todas las ubicaciones internas del almacén), acumular hacia atrás en Python. Es O(productos × días) pero con dicts es rápido — no requiere SQL recursivo.

**Casos borde:**
- Si la reconstrucción da stock negativo en algún punto (ajustes de inventario, datos sucios), clampear a 0 y agregar warning.
- Días anteriores al `first_move_date` del producto no cuentan como "sin stock" — cuentan como "no existía". Excluirlos del denominador.
- Si `days_with_stock == 0`, no se puede estimar: `Estimate(adu=0, confidence=0.0, warnings=['Sin stock en toda la ventana'])`.

### 5.3 Estimador `weighted_ma` (el único de v1)

```python
def _estimate_weighted_ma(self, series):
    result = {}
    weights = self._parse_weight_config()   # [(14, 0.5), (30, 0.3), (90, 0.2)]

    for product_id in series.product_ids:
        history = series.history_days(product_id)

        # ventanas que no caben en la historia disponible se descartan
        # y los pesos se renormalizan sobre las que quedan
        usable = [(d, w) for d, w in weights if d <= max(history, 1)]
        if not usable:
            usable = [(min(w[0] for w in weights), 1.0)]
        total_w = sum(w for _, w in usable)

        adu = 0.0
        for days, weight in usable:
            qty = series.total_qty(product_id, days=days)
            if self.ignore_stockout_days:
                denom = series.days_with_stock(product_id, days=days) or 1
            else:
                denom = min(days, history) or 1
            adu += (qty / denom) * (weight / total_w)

        values = series.daily_values(product_id, days=self.lookback_days)
        values = self._winsorize(values)          # percentil configurable
        sigma = self._stdev(values)               # statistics.stdev, stdlib

        result[product_id] = Estimate(
            adu=adu, sigma=sigma,
            confidence=self._confidence(series, product_id, adu, sigma),
            method_used='weighted_ma',
            explanation=self._build_explanation(...),
            warnings=[...],
        )
    return result
```

**Winsorización:** ordenar valores, reemplazar los que superan el percentil configurado por el valor del percentil. Evita que una venta mayorista puntual distorsione el ADU. Implementable con `sorted()` + índice, sin numpy.

### 5.4 Stock de seguridad

```
SS = Z(service_level) × sigma × sqrt(lead_time_days)
```

Si `sigma == 0` (demanda perfectamente constante), usar un piso: `SS = adu × 0.5`. Demanda con varianza cero casi siempre significa pocos datos, no estabilidad real.

### 5.5 Cantidad sugerida

```
qty_raw = adu × (lead_time_days + coverage_days) + safety_stock
          - qty_on_hand
          - qty_incoming
          + qty_outgoing_reserved

qty_suggested = aplicar_restricciones_proveedor(max(qty_raw, 0))
```

`aplicar_restricciones_proveedor()` en este orden:
1. Si `qty_raw <= 0` → 0, la línea no se crea.
2. Redondear hacia arriba al múltiplo de `product.packaging` si existe.
3. Aplicar `min_qty` de `product.supplierinfo` (subir si está por debajo).
4. Convertir a `uom_po_id` si difiere de la UoM de stock.

### 5.6 Lead time medido

No usar `product.supplierinfo.delay` (casi siempre está mal cargado). Calcular:

```sql
SELECT po.partner_id,
       AVG(EXTRACT(EPOCH FROM (sp.date_done - po.date_approve)) / 86400) AS lead_days,
       COUNT(*) AS sample_size
FROM purchase_order po
JOIN stock_picking sp ON sp.origin = po.name
WHERE po.state IN ('purchase', 'done')
  AND sp.state = 'done'
  AND po.date_approve >= NOW() - INTERVAL '365 days'
GROUP BY po.partner_id
```

Fallback si `sample_size < 3`: usar `supplierinfo.delay`. Si tampoco existe: 7 días y warning.

### 5.7 Clasificación ABC / XYZ

**ABC** — por contribución al **margen** en los últimos 180 días, no por unidades. Vender 500 medias no es lo mismo que 20 camperas. Acumulado: A = 80%, B = 80-95%, C = resto.

**XYZ** — por coeficiente de variación (`sigma / adu`): X < 0.5, Y 0.5-1.0, Z > 1.0.

Se recalculan por cron semanal, no en cada corrida de sugerencia.

Filtro por defecto: se sugieren A y B siempre; C solo si `coverage_days_current < lead_time`. Configurable.

### 5.8 Exclusiones

No entran al cálculo productos que:
- Tienen `exclude_from_suggestion = True`
- No tienen ningún `supplierinfo`
- No son de tipo almacenable (`type != 'product'`)
- Están archivados
- No tuvieron ningún movimiento de salida en la ventana **y** tienen stock > 0 (stock muerto)

---

## 6. Interfaz de usuario

### 6.1 Vista formulario de la sugerencia

Header con botones por estado: `Calcular` (draft) → `Confirmar` (computed) → `Crear órdenes de compra` (confirmed). Statusbar con los estados.

Botón inteligente hacia las POs generadas.

Panel superior con: almacén, días de cobertura, modelo de demanda (opcional), fecha de cálculo.

Alerta visible si `low_confidence_count > 0`: *"N líneas tienen baja confianza estadística. Revisar antes de confirmar."*

### 6.2 Editor de líneas

`One2many` editable inline. Columnas visibles por defecto:

`producto | cobertura (días) | stock | tránsito | ADU | sugerido | **cantidad** | proveedor | precio | subtotal`

Columnas opcionales (`optional="hide"`): sigma, safety stock, lead time, ABC, XYZ, confianza, método.

**Decoraciones:**
- `decoration-danger` si `coverage_days_current < lead_time_days` (va a quebrar antes de que llegue)
- `decoration-warning` si `confidence < 0.5`
- `decoration-info` si `is_manual`
- `decoration-muted` si `qty_final == 0`

El campo `explanation` se muestra como widget expandible por fila o en el tooltip. **Es obligatorio que esté accesible.** Texto tipo:

> Vendés 3,2 unidades/día (promedio ponderado 14/30/90 días, corregido por 6 días sin stock). Quedan 12 unidades = 4 días de cobertura. Lead time medido del proveedor: 12 días. Stock de seguridad: 18 unidades.

Agregar productos: fila nueva en el One2many. Al elegir producto, un `onchange` completa proveedor, precio, y calcula las métricas para ese producto marcándolo `is_manual = True`.

Quitar productos: poner `qty_final = 0` (se ignora al crear POs, pero queda registro) o borrar la línea.

### 6.3 Recálculo preservando ediciones

`action_compute()` sobre una sugerencia que ya tiene líneas editadas:
- Líneas con `was_edited = True` o `is_manual = True` → preservar `qty_final`, actualizar solo las métricas.
- Resto → recalcular completo.
- Mostrar notificación: *"N líneas recalculadas, M ediciones manuales preservadas."*

### 6.4 Vista lista de sugerencias

Columnas: nombre, almacén, fecha, líneas, total, estado. Filtros por estado, almacén, y "mis sugerencias". Agrupación por almacén y por estado.

---

## 7. Generación de órdenes de compra

`action_create_purchase_orders()`:

1. Filtrar líneas con `qty_final > 0`.
2. Agrupar por `supplier_id`.
3. Por cada grupo, crear una `purchase.order`:
   - `partner_id`, `company_id`, `picking_type_id` del almacén
   - `origin` = nombre de la sugerencia
   - `suggestion_id` = la sugerencia
   - `date_planned` = hoy + lead time del proveedor
4. Líneas de PO con `product_qty = qty_final`, `product_uom = uom_po_id`, `price_unit` de la línea.
5. POs quedan en estado `draft` (nunca confirmar automáticamente).
6. Sugerencia pasa a `done`.
7. Devolver acción que abre la lista de POs creadas.

**Validaciones antes de crear:**
- Líneas sin proveedor → error con lista de productos afectados.
- Si alguna línea tiene `price_unit = 0` → warning, no bloquea.
- Si no hay ninguna línea con `qty_final > 0` → error.

---

## 8. Automatización

**Cron semanal** (lunes 06:00, desactivado por defecto):
- Por cada almacén con `auto_suggestion = True`, crear sugerencia en `draft` y correr `action_compute()`.
- Crear `mail.activity` de tipo "To Do" al responsable de compras del almacén.

Esto convierte el módulo de "herramienta que hay que acordarse de usar" en "algo que aparece solo los lunes". Cambia radicalmente la adopción.

**Cron semanal de métricas** (domingo 02:00): recalcular ABC/XYZ, lead times medidos, fill rates.

---

## 9. Seguridad

Dos grupos:
- `group_purchase_advisor_user` — ver y editar sugerencias, crear POs.
- `group_purchase_advisor_manager` — además configurar `demand.model` y reglas.

Reglas de registro multi-compañía sobre `purchase.suggestion` y `demand.model`.

---

## 10. Estructura de archivos

```
prometeo_purchase_advisor/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── datatypes.py                    # DemandSeries, Estimate
│   ├── demand_series_builder.py        # SQL → DemandSeries
│   ├── demand_model.py                 # estimadores + despacho
│   ├── demand_model_rule.py
│   ├── purchase_suggestion.py
│   ├── purchase_suggestion_line.py
│   ├── product_product.py              # ABC/XYZ, overrides
│   ├── res_partner.py                  # lead time, fill rate
│   ├── purchase_order.py
│   └── res_config_settings.py
├── views/
│   ├── purchase_suggestion_views.xml
│   ├── demand_model_views.xml
│   ├── demand_model_rule_views.xml
│   ├── product_views.xml
│   ├── res_config_settings_views.xml
│   └── menus.xml
├── security/
│   ├── ir.model.access.csv
│   └── security.xml
├── data/
│   ├── ir_sequence.xml
│   ├── ir_cron.xml
│   └── demand_model_data.xml           # modelo por defecto
├── tests/
│   ├── __init__.py
│   ├── common.py                       # fixtures de datos sintéticos
│   ├── test_demand_series.py
│   ├── test_estimators.py
│   ├── test_quantity.py
│   └── test_purchase_generation.py
└── README.md
```

`__manifest__.py`: depends `['stock', 'purchase', 'product', 'mail']`. No incluir `point_of_sale` como dependencia — el módulo lee de `stock_move`, funciona con o sin POS.

---

## 11. Fases de implementación

### Fase 1 — Esqueleto y datos
Modelos, campos, vistas básicas, seguridad, secuencias, menús. Sin cálculo real: `action_compute()` puede poblar líneas con valores dummy. **Objetivo: algo clickeable para mostrar y validar la UX.**

Criterio de salida: se puede crear una sugerencia, agregar líneas a mano, y generar POs agrupadas por proveedor.

### Fase 2 — Motor de demanda
`DemandSeries` builder en SQL, reconstrucción de `had_stock`, estimador `weighted_ma`, cálculo de sigma y confidence.

Criterio de salida: tests con datos sintéticos verifican que el ADU es correcto con y sin corrección por quiebres.

### Fase 3 — Cantidad y restricciones
Lead time medido, stock de seguridad, fórmula de cantidad, redondeos de packaging, min_qty, conversión de UoM.

Criterio de salida: casos de test cubren cada restricción de proveedor por separado y combinadas.

### Fase 4 — Clasificación y filtros
ABC por margen, XYZ por CV, exclusiones, orden por cobertura, decoraciones en la vista.

### Fase 5 — Explicabilidad y pulido
Textos de `explanation`, warnings, alertas de baja confianza, preservación de ediciones en recálculo, crons.

### Fase 6 — Extensibilidad (validación)
Implementar `ewma` como segundo estimador **en un módulo satélite** (`prometeo_purchase_advisor_ewma`). Es un método trivial, pero sirve para verificar que la arquitectura de despacho funciona sin tocar el core. Si requiere modificar el core, la arquitectura falló y hay que corregirla antes de seguir.

---

## 12. Testing

Fixtures con datos sintéticos donde la respuesta correcta se conoce de antemano:

| Escenario | Verifica |
|---|---|
| Demanda constante 10/día, 90 días, sin quiebres | ADU = 10, sigma ≈ 0 |
| Demanda 10/día pero 30 días sin stock | ADU = 10 con corrección, ≈ 6.7 sin corrección |
| Producto nuevo, 15 días de historia | confidence baja, ventanas de 30/90 descartadas |
| Un outlier de 500 unidades en demanda de 10/día | winsorización lo neutraliza |
| Demanda cero en toda la ventana | no genera línea |
| Producto sin supplierinfo | excluido, no rompe |
| min_qty 50, cálculo da 12 | qty_suggested = 50 |
| packaging de 12, cálculo da 25 | qty_suggested = 36 |
| Dos proveedores en la sugerencia | dos POs separadas |
| Recálculo con líneas editadas | preserva qty_final |

Tests de performance: 5.000 productos × 1 almacén debe completar `action_compute()` en menos de 30 segundos.

---

## 13. Métricas de éxito del módulo

Instrumentar desde v1, porque son la base para decidir si hace falta un segundo método de estimación:

- **Tasa de edición**: `count(was_edited) / count(lines)`. Si supera 50%, el método está mal calibrado para ese cliente.
- **Desvío medio**: `avg(qty_final - qty_suggested)`. Si es sistemáticamente positivo, el modelo subestima.
- **Tasa de aprobación**: sugerencias que llegan a `done` sobre el total generadas.

`qty_suggested` vs `qty_final` es la métrica de calidad real del módulo — más útil que cualquier métrica estadística de error de pronóstico.

---

## 14. Ganchos para v2 (no implementar, solo no bloquear)

- **Traspasos entre sucursales**: la etapa de cantidad debe poder devolver un "origen sugerido" que no sea un proveedor. Dejar el campo `supplier_id` nullable y no asumir que toda línea termina en PO.
- **Presupuesto tope**: knapsack priorizando margen × rotación. La etapa de filtro/prioridad debe ser un método separado y sobrescribible.
- **Mínimo de pedido por proveedor**: sugerir productos adicionales cercanos al punto de reorden para alcanzar el mínimo.
- **Estacionalidad**: `DemandSeries` ya tiene las fechas; un índice por semana del año se puede aplicar como multiplicador sobre el ADU sin cambiar el contrato.
- **Backtesting**: modelo `prometeo.demand.backtest` con walk-forward. Métricas: MASE (no MAPE — explota con ceros, y en retail hay muchísimos días en cero), bias con signo, y fill rate simulado. Resultados desagregados por clase ABC/XYZ, porque el ganador global casi nunca gana en todos los segmentos.
- **Integración con `stock.warehouse.orderpoint`**: botón que escriba min/max en los orderpoints nativos como subproducto del cálculo.

---

## 15. Adaptaciones a Odoo 18 (agregadas durante la implementación)

El spec dice "Odoo 17/18". El target real de este repo es **18.0**. Tres puntos del spec cambian de forma en 18:

1. **§5.8 — "tipo almacenable"**: en Odoo 18 `product.template.type` ya no tiene el valor `'product'`. Los almacenables son `type = 'consu'` **+** `is_storable = True`. La exclusión se implementa contra `is_storable`.
2. **§5.6 — join de picking a PO**: `sp.origin = po.name` es frágil (el `origin` se pisa con merges y devoluciones). `stock.picking.purchase_id` **no sirve como alternativa**: es un related sin `store=True`, así que no existe como columna. El join real pasa por el movimiento, que sí guarda la línea de compra: `stock_move.purchase_line_id → purchase_order_line.order_id`. Además se toma la **primera** recepción de cada orden (`MIN(date_done)`), no la última: para reponer importa cuándo empezó a haber mercadería.
3. **§5.5 — packaging**: `product.packaging` sigue existiendo en 18 con campo `qty` y un booleano `purchase` que agrega el módulo `purchase`. El redondeo se hace contra el packaging de menor `qty` marcado como de compra, y si no hay ninguno se omite el paso.
4. **§5.5 — orden de las restricciones**: el spec aplica el packaging antes que el `min_qty`. Se invirtió: redondear al bulto y después subir al mínimo deja una cantidad que no es múltiplo de nada. Primero el mínimo, después el bulto.
5. **§5.3 — recorte de outliers**: el spec lo aplica solo al desvío, pero su propio comentario dice que sirve para proteger el ADU. Se aplica a los dos. Además se desactiva cuando el percentil cae en cero, que es lo que pasa con demanda esporádica.
6. **§5.3 — ventanas sin días utilizables**: se descartan y su peso se reparte entre las que quedan. Con la fórmula original el escenario de quiebre de §12 daba 2 en vez de 10.
7. **§4.5 — campos calculados**: `abc_class`, `xyz_class`, `measured_lead_time` y `fill_rate` son campos almacenados que escribe el cron, no `compute` con `store=True`. Un compute almacenado sin dependencias reales se recalcula cuando no corresponde.

Estas tres adaptaciones no cambian ninguna decisión de arquitectura del spec.
