# Diseño: `pos_global_surcharge_button`

**Fecha:** 2026-06-24
**Autor:** Alexis
**Estado:** Aprobado (brainstorming)

## Objetivo

Agregar un botón **"Recargo"** en la pantalla principal del POS (Odoo 18) que aplica
un recargo porcentual global al pedido. Es el espejo en positivo del botón de descuento
global: en vez de restar, suma una línea de producto con el monto del recargo.

El porcentaje por defecto es **20%**, configurable en los Ajustes del POS.

## Decisiones de diseño (cerradas en brainstorming)

1. **Alcance:** una sola línea de recargo global por pedido (espeja `pos_discount`),
   con monto positivo `= (surcharge_pc / 100) × base`.
2. **Ubicación:** botón en la pantalla principal del POS, junto al de Descuento.
3. **Producto de recargo:** se crea automáticamente por data al instalar (producto
   `Recargo`), asignado por defecto en la `pos.config`, y editable en Ajustes del POS.
4. **Comportamiento al hacer clic:** toggle. Un toque aplica el `surcharge_pc` de config;
   un segundo toque (cuando ya hay línea de recargo) la elimina. Sin popup ni ajuste manual
   por pedido.

## Dependencias

- `point_of_sale`
- `pos_discount` — se reutilizan `order.calculate_base_amount()` y
  `line.isGlobalDiscountApplicable()`, que ya emplea `pos_global_discount_button`.
  Además garantiza que existe la infraestructura de "producto especial" en el POS.
- `pos_global_discount_button` — es el módulo que mueve el botón de Descuento a la
  pantalla principal. Se depende de él para que la herencia de plantilla aplique antes
  y poder anclar el botón "Recargo" inmediatamente después del de Descuento
  (`//button[contains(@class, 'js_discount')]`).

## Arquitectura

Toda la lógica de aplicación vive en el frontend (patch a `ControlButtons`). El backend
aporta únicamente la configuración (`pos.config` + vista de ajustes) y el producto de
recargo por defecto.

### Backend (Python)

**`models/pos_config.py`** — extiende `pos.config`:

- `surcharge_pc` (`fields.Float`, default `20.0`) — porcentaje de recargo.
- `surcharge_product_id` (`fields.Many2one`, `comodel_name="product.product"`) —
  producto que se agrega como línea de recargo.

**`models/res_config_settings.py`** — extiende `res.config.settings` con campos
relacionados (`related="pos_config_id.surcharge_pc"` y `..surcharge_product_id`,
`readonly=False`) para poder editarlos desde la pantalla de Ajustes del POS.

**`views/res_config_settings_views.xml`** — agrega una sección "Recargo" dentro del
bloque de configuración del Point of Sale, con los dos campos.

**`data/surcharge_product.xml`** (`noupdate="1"`) — crea un `product.product` llamado
`Recargo`:

- `available_in_pos = True` (necesario para que cargue en el frontend).
- `type = 'service'` (no afecta stock).
- `sale_ok = False`, `purchase_ok = False`, `list_price = 0.0`, sin impuestos por
  defecto (el usuario configura el impuesto para que coincida con el del producto de
  descuento; ver "Impuestos").

**`post_init_hook`** (en `__init__.py`, declarado en el manifest) — asigna el producto
`Recargo` como `surcharge_product_id` en todas las `pos.config` existentes que aún no
tengan uno, para que funcione out-of-the-box al instalar sin tocar la config. Las
`pos.config` nuevas lo toman del default del campo.

### Frontend (JS + XML)

**`static/src/js/control_buttons_patch.js`** — `patch(ControlButtons.prototype, {...})`:

- `get currentSurchargePercent()` — espejo de `currentDiscountPercent` del módulo de
  descuento, pero en positivo. Calcula el % real aplicado a partir del monto de las
  líneas de recargo sobre la base, para mostrarlo en el badge. Devuelve `0` si no hay
  pedido, producto o líneas.
- `clickSurcharge()` — toggle:
  1. Obtiene el pedido y `product = this.pos.config.surcharge_product_id`. Si falta
     alguno, no hace nada.
  2. Busca líneas existentes cuyo producto sea el de recargo.
     - Si **existen** → las elimina (apaga el recargo) y termina.
  3. Si **no existen** → calcula la base con `order.calculate_base_amount()` sobre las
     líneas aplicables (`line.isGlobalDiscountApplicable()`), excluyendo las líneas del
     producto de recargo **y** las del producto de descuento.
  4. `amount = (this.pos.config.surcharge_pc / 100) × base`. Si `amount > 0`, agrega una
     línea del producto de recargo con ese precio fijo (precio "automático", no editable
     por el flujo normal).

**`static/src/xml/control_buttons.xml`** — `t-inherit` en modo `extension` sobre
`point_of_sale.ControlButtons`:

- Agrega el botón "Recargo" en la pantalla principal, junto al de Descuento.
- `t-if="pos.config.surcharge_product_id"` para mostrarlo sólo si está configurado.
- Ícono propio (p. ej. `fa fa-plus` / `fa fa-arrow-up`) y badge con
  `currentSurchargePercent%`, con color distinto al del descuento (p. ej. verde/azul) para
  diferenciarlos visualmente.

## Estructura de archivos

```
pos_global_surcharge_button/
├── __init__.py
├── __manifest__.py
├── data/
│   └── surcharge_product.xml
├── models/
│   ├── __init__.py
│   ├── pos_config.py
│   └── res_config_settings.py
├── views/
│   └── res_config_settings_views.xml
└── static/
    ├── description/
    │   └── icon.png
    └── src/
        ├── js/
        │   └── control_buttons_patch.js
        └── xml/
            └── control_buttons.xml
```

`__manifest__.py` declara `depends = ["point_of_sale", "pos_discount"]`, registra los
assets en `point_of_sale._assets_pos` (JS + XML) y carga `data/` y `views/`.

## Riesgos / a verificar en implementación

1. **Carga del producto en el POS (riesgo principal):** `surcharge_product_id` debe estar
   disponible en el frontend para que `this.pos.config.surcharge_product_id` resuelva al
   registro. Con `available_in_pos=True` suele alcanzar; si no carga, hay que extender el
   dominio de carga de productos / `_get_special_products` igual que `pos_discount`. Se
   confirma probando en el contenedor `odoo-odoo-1` (DB de prod, módulos en
   `/mnt/local-addons`, upgrade con `-u`).
2. **API exacta de Odoo 18 para agregar/quitar líneas** (`addLineToCurrentOrder` vs
   `add_product`; `line.delete()` vs `removeOrderline`): copiar la firma exacta del
   `pos_discount` instalado al implementar el `clickSurcharge`.
3. **Interacción con el descuento global:** la base del recargo se calcula sobre las
   líneas de producto reales, excluyendo tanto la línea de descuento como la de recargo,
   para que descuento y recargo no se pisen ni se realimenten.
4. **Impuestos:** la línea de recargo hereda los impuestos del producto de recargo. El
   producto por defecto se configura espejando al producto de descuento de la instancia
   para mantener coherencia fiscal.

## Fuera de alcance (YAGNI)

- Recargo por línea individual de producto.
- Popup con porcentaje editable por pedido.
- Recargo escalonado / por método de pago / por financiación (eso es dominio de
  `card_installment`).
- Reportes o métricas específicas del recargo.
