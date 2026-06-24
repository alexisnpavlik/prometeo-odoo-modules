# POS Global Surcharge Button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un botón "Recargo" en la pantalla principal del POS (Odoo 18) que aplica, como toggle, un recargo porcentual global (20% por defecto, configurable) como una línea de producto positiva en el pedido.

**Architecture:** Módulo espejo de `pos_discount` / `pos_global_discount_button` pero en positivo. Backend mínimo (`pos.config` con `surcharge_pc` + `surcharge_product_id`, producto `Recargo` por data, `post_init_hook` que lo asigna a las configs existentes, y vista de Ajustes del POS). Frontend: patch a `ControlButtons` con `clickSurcharge` (toggle) + getter `currentSurchargePercent`, y plantilla que ancla el botón después del de Descuento.

**Tech Stack:** Odoo 18, Python, OWL/JS (`@odoo-module`), QWeb XML templates.

## Global Constraints

- Odoo `version`: `"18.0.1.0.0"`; `author`: `"Alexis"`; `license`: `"LGPL-3"`.
- `depends = ["point_of_sale", "pos_discount", "pos_global_discount_button"]`.
- `surcharge_pc` default: `20.0`.
- snake_case en Python; nombres de archivo de módulo descriptivos.
- Docstring en cada función Python; sin comentarios sobre código obvio.
- **No hay framework de tests en estos módulos Odoo** (perfil del usuario: la mayoría de los repos no tienen tests, no agregar tests salvo pedido). El "ciclo de test" de cada tarea es: sincronizar/instalar/upgradear el módulo en el contenedor y verificar en el log + UI/POS. Se reemplazan los pasos de pytest por verificación manual.
- **Deploy local dev (contenedor `odoo-odoo-1`, DB `prod`):** el repo está bind-mounteado en `/mnt/local-addons`; un módulo nuevo (no presente en `/mnt/prometeo-addons`) se carga desde ahí. Editar archivos del repo se refleja en vivo en el contenedor.
- **Comandos de ciclo (DB `prod`):**
  - Instalar (primera vez): `docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d prod -i pos_global_surcharge_button --stop-after-init --no-http`
  - Upgrade (cambios posteriores de Python/vistas): `docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d prod -u pos_global_surcharge_button --stop-after-init --no-http`
  - Tras cambios de Python (campos/métodos/hook): además `docker restart odoo-odoo-1` (re-importa Python; el CLI solo upgradea la DB).
  - Tras cambios solo de JS/XML(owl): basta `docker restart odoo-odoo-1` (o que recarguen assets) + **Ctrl+Shift+R** en el navegador.
  - Éxito en log: `Loading module pos_global_surcharge_button`, `... loaded in Xs, N queries`, `Registry changed, signaling through the database`. Ver con `docker logs --tail 80 odoo-odoo-1`.
- `prod` es producción a efectos del clasificador: **no** consultar su DB con SQL/shell sin autorización. La verificación es por log e interfaz, no por queries a datos.

---

### Task 1: Backend foundation (módulo + manifest + config + producto + hook)

**Files:**
- Create: `pos_global_surcharge_button/__init__.py`
- Create: `pos_global_surcharge_button/__manifest__.py`
- Create: `pos_global_surcharge_button/models/__init__.py`
- Create: `pos_global_surcharge_button/models/pos_config.py`
- Create: `pos_global_surcharge_button/data/surcharge_product.xml`
- Create: `pos_global_surcharge_button/static/description/icon.png` (copia de placeholder)

**Interfaces:**
- Produces:
  - `pos.config.surcharge_pc` (Float, default `20.0`).
  - `pos.config.surcharge_product_id` (Many2one `product.product`).
  - XML id del producto: `pos_global_surcharge_button.product_product_surcharge`.
  - `post_init_hook(env)` que setea `surcharge_product_id` en las `pos.config` existentes.

- [ ] **Step 1: Crear `models/pos_config.py`**

```python
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    surcharge_pc = fields.Float(
        string="Porcentaje de recargo",
        default=20.0,
        help="Porcentaje aplicado al tocar el botón Recargo en el POS.",
    )
    surcharge_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto de recargo",
        domain="[('available_in_pos', '=', True)]",
        help="Producto usado como línea de recargo en el pedido del POS.",
    )
```

- [ ] **Step 2: Crear `models/__init__.py`**

```python
from . import pos_config
```

- [ ] **Step 3: Crear `data/surcharge_product.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo noupdate="1">
    <record id="product_product_surcharge" model="product.product">
        <field name="name">Recargo</field>
        <field name="type">service</field>
        <field name="available_in_pos">True</field>
        <field name="sale_ok" eval="False"/>
        <field name="purchase_ok" eval="False"/>
        <field name="list_price">0.0</field>
        <field name="taxes_id" eval="[(5, 0, 0)]"/>
    </record>
</odoo>
```

- [ ] **Step 4: Crear `__init__.py` con el `post_init_hook`**

```python
from . import models


def post_init_hook(env):
    """Asigna el producto Recargo a las pos.config existentes sin uno."""
    product = env.ref(
        "pos_global_surcharge_button.product_product_surcharge",
        raise_if_not_found=False,
    )
    if not product:
        return
    configs = env["pos.config"].search([("surcharge_product_id", "=", False)])
    if configs:
        configs.write({"surcharge_product_id": product.id})
```

- [ ] **Step 5: Crear `__manifest__.py`**

```python
# -*- coding: utf-8 -*-
{
    "name": "POS Global Surcharge Button",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "Botón de recargo porcentual global en la pantalla principal del POS.",
    "description": """
        Agrega un botón 'Recargo' en la pantalla principal del POS, junto al de
        Descuento. Funciona como toggle: un toque aplica el porcentaje de recargo
        configurado (20% por defecto) como una línea de producto positiva sobre la
        base del pedido; otro toque la quita. El porcentaje y el producto de recargo
        se configuran en los Ajustes del POS.
    """,
    "author": "Alexis",
    "depends": ["point_of_sale", "pos_discount", "pos_global_discount_button"],
    "data": [
        "data/surcharge_product.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
```

- [ ] **Step 6: Crear el icono (placeholder)**

```bash
mkdir -p pos_global_surcharge_button/static/description
cp pos_global_discount_button/static/description/icon.png pos_global_surcharge_button/static/description/icon.png
```

(Opcional: regenerar después con el pipeline de icono de la skill `odoo-prometeo-modules`.)

- [ ] **Step 7: Instalar el módulo en el contenedor**

Run:
```bash
docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d prod -i pos_global_surcharge_button --stop-after-init --no-http && docker restart odoo-odoo-1
```
Expected: en `docker logs --tail 80 odoo-odoo-1` aparece `Loading module pos_global_surcharge_button`, `creating or updating database tables`, `... loaded in Xs, N queries`, `Registry changed, signaling through the database`, **sin tracebacks**. El contenedor reinicia OK (`docker ps` lo muestra `Up`).

- [ ] **Step 8: Verificar que no hubo error de carga**

Run: `docker logs --tail 120 odoo-odoo-1 | grep -iE "error|traceback|pos_global_surcharge" `
Expected: líneas de carga del módulo presentes; ninguna línea de `ERROR`/`Traceback` asociada al módulo.

- [ ] **Step 9: Commit**

```bash
git add pos_global_surcharge_button/__init__.py pos_global_surcharge_button/__manifest__.py pos_global_surcharge_button/models pos_global_surcharge_button/data pos_global_surcharge_button/static/description/icon.png
git commit -m "feat(pos_global_surcharge_button): backend config, producto de recargo y post_init_hook"
```

---

### Task 2: Settings UI (res.config.settings + vista)

**Files:**
- Create: `pos_global_surcharge_button/models/res_config_settings.py`
- Modify: `pos_global_surcharge_button/models/__init__.py`
- Create: `pos_global_surcharge_button/views/res_config_settings_views.xml`
- Modify: `pos_global_surcharge_button/__manifest__.py` (agregar la vista a `data`)

**Interfaces:**
- Consumes: `pos.config.surcharge_pc`, `pos.config.surcharge_product_id` (Task 1).
- Produces:
  - `res.config.settings.pos_surcharge_pc` (related a `pos_config_id.surcharge_pc`).
  - `res.config.settings.pos_surcharge_product_id` (related a `pos_config_id.surcharge_product_id`).
  - Setting visible en Ajustes → Punto de Venta, justo después del toggle de Descuentos.

- [ ] **Step 1: Crear `models/res_config_settings.py`**

```python
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_surcharge_pc = fields.Float(
        related="pos_config_id.surcharge_pc",
        readonly=False,
        string="Porcentaje de recargo",
    )
    pos_surcharge_product_id = fields.Many2one(
        related="pos_config_id.surcharge_product_id",
        readonly=False,
        string="Producto de recargo",
    )
```

- [ ] **Step 2: Agregar el import en `models/__init__.py`**

Resultado final del archivo:
```python
from . import pos_config
from . import res_config_settings
```

- [ ] **Step 3: Crear `views/res_config_settings_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="res_config_settings_view_form_surcharge" model="ir.ui.view">
        <field name="name">res.config.settings.view.form.inherit.surcharge</field>
        <field name="model">res.config.settings</field>
        <field name="inherit_id" ref="point_of_sale.res_config_settings_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//field[@name='module_pos_discount']/ancestor::setting[1]" position="after">
                <setting string="Recargo"
                         help="Recargo porcentual global aplicado desde el botón del POS.">
                    <div class="content-group mt16">
                        <div class="row">
                            <label for="pos_surcharge_pc" class="col-lg-5 o_light_label"/>
                            <field name="pos_surcharge_pc"/>
                        </div>
                        <div class="row mt8">
                            <label for="pos_surcharge_product_id" class="col-lg-5 o_light_label"/>
                            <field name="pos_surcharge_product_id"/>
                        </div>
                    </div>
                </setting>
            </xpath>
        </field>
    </record>
</odoo>
```

Nota: el ancla `//field[@name='module_pos_discount']` existe siempre en los Ajustes del POS (toggle "Descuentos Globales" de `pos_discount`). Si esta versión de Odoo renombró ese campo, ubicar el toggle de descuentos en la vista `point_of_sale.res_config_settings_view_form` y usar su `setting` como ancla.

- [ ] **Step 4: Agregar la vista al manifest**

En `__manifest__.py`, dejar la clave `data` así:
```python
    "data": [
        "data/surcharge_product.xml",
        "views/res_config_settings_views.xml",
    ],
```

- [ ] **Step 5: Upgrade + restart**

Run:
```bash
docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d prod -u pos_global_surcharge_button --stop-after-init --no-http && docker restart odoo-odoo-1
```
Expected: log sin errores de parseo de vista (`ParseError`/`ValidationError`); módulo recargado OK.

- [ ] **Step 6: Verificar en la UI**

Abrir en el navegador: **Ajustes → Punto de Venta** (elegir el POS correspondiente). Hard refresh (Ctrl+Shift+R).
Expected: aparece la sección **"Recargo"** con el campo "Porcentaje de recargo" en **20.0** y "Producto de recargo" precargado con el producto **Recargo** (lo dejó el `post_init_hook`). Editar el % a otro valor, guardar, reabrir: el valor persiste.

- [ ] **Step 7: Commit**

```bash
git add pos_global_surcharge_button/models/res_config_settings.py pos_global_surcharge_button/models/__init__.py pos_global_surcharge_button/views/res_config_settings_views.xml pos_global_surcharge_button/__manifest__.py
git commit -m "feat(pos_global_surcharge_button): ajustes del POS para % y producto de recargo"
```

---

### Task 3: Frontend (botón + toggle + badge)

**Files:**
- Create: `pos_global_surcharge_button/static/src/js/control_buttons_patch.js`
- Create: `pos_global_surcharge_button/static/src/xml/control_buttons.xml`
- Modify: `pos_global_surcharge_button/__manifest__.py` (agregar bloque `assets`)

**Interfaces:**
- Consumes: `pos.config.surcharge_pc`, `pos.config.surcharge_product_id` (Task 1); de `pos_discount`: `order.calculate_base_amount(lines)` y `line.isGlobalDiscountApplicable()`; de `pos_global_discount_button`: el botón con clase `js_discount` en la pantalla principal (ancla del botón Recargo).
- Produces: método `clickSurcharge()` y getter `currentSurchargePercent` en `ControlButtons.prototype`; botón con clase `js_surcharge`.

- [ ] **Step 1: Crear `static/src/js/control_buttons_patch.js`**

```javascript
/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";

patch(ControlButtons.prototype, {
    /** Devuelve las líneas del pedido que son del producto de recargo. */
    _getSurchargeLines() {
        const order = this.pos.get_order();
        const product = this.pos.config.surcharge_product_id;
        if (!order || !product) {
            return [];
        }
        return order
            .get_orderlines()
            .filter((line) => line.get_product() === product);
    },

    /** Base sobre la que se calcula el recargo: líneas de producto aplicables,
     *  excluyendo la línea de recargo y la de descuento global. */
    _getSurchargeBase() {
        const order = this.pos.get_order();
        const product = this.pos.config.surcharge_product_id;
        const discountProduct = this.pos.config.discount_product_id;
        const baseLines = order.get_orderlines().filter(
            (line) =>
                line.get_product() !== product &&
                line.get_product() !== discountProduct &&
                line.isGlobalDiscountApplicable()
        );
        return order.calculate_base_amount(baseLines);
    },

    /** Porcentaje de recargo actualmente aplicado, para el badge. */
    get currentSurchargePercent() {
        const surchargeLines = this._getSurchargeLines();
        if (surchargeLines.length === 0) {
            return 0;
        }
        const order = this.pos.get_order();
        const totalSurcharge = order.calculate_base_amount(surchargeLines);
        const base = this._getSurchargeBase();
        if (base <= 0) {
            return 0;
        }
        const pc = (totalSurcharge / base) * 100;
        return Math.round(pc * 10) / 10;
    },

    /** Toggle del recargo global: si hay línea de recargo la quita; si no, la agrega. */
    clickSurcharge() {
        const order = this.pos.get_order();
        const product = this.pos.config.surcharge_product_id;
        if (!order || !product) {
            return;
        }
        const existing = this._getSurchargeLines();
        if (existing.length > 0) {
            for (const line of existing) {
                line.delete();
            }
            return;
        }
        const base = this._getSurchargeBase();
        const amount = (this.pos.config.surcharge_pc / 100.0) * base;
        if (amount > 0) {
            this.pos.addLineToCurrentOrder({
                product_id: product,
                price_unit: amount,
            });
        }
    },
});
```

- [ ] **Step 2: Verificar la API de líneas contra `pos_discount` instalado**

Esto cubre el riesgo #2 del spec (la API exacta de Odoo 18 para agregar/quitar líneas). Localizar el JS de `pos_discount` dentro del contenedor y confirmar cómo agrega/quita la línea de descuento:
```bash
docker exec odoo-odoo-1 sh -c "find / -path '*pos_discount*' -name '*.js' 2>/dev/null"
docker exec odoo-odoo-1 sh -c "grep -RnE 'addLineToCurrentOrder|add_product|removeOrderline|\\.delete\\(' \$(find / -path '*pos_discount*' -name '*.js' 2>/dev/null)"
```
Expected: ver el método `apply_discount` (o equivalente). Si usa `add_product(...)` en lugar de `addLineToCurrentOrder(...)`, o `order.removeOrderline(line)` en lugar de `line.delete()`, **ajustar el Step 1** para usar exactamente esas firmas. Confirmar también cómo fija el precio (`price_unit` vs `price`) para que no se recalcule.

- [ ] **Step 3: Crear `static/src/xml/control_buttons.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">
    <t t-name="pos_global_surcharge_button.ControlButtons" t-inherit="point_of_sale.ControlButtons" t-inherit-mode="extension">

        <!-- Agregar el botón Recargo inmediatamente después del de Descuento global -->
        <xpath expr="//button[contains(@class, 'js_discount')]" position="after">
            <button t-if="pos.config.surcharge_product_id"
                class="js_surcharge position-relative d-flex align-items-center justify-content-center gap-1"
                t-att-class="buttonClass"
                t-on-click="() => this.clickSurcharge()">
                <i class="fa fa-arrow-up me-1"/>
                <span>Recargo</span>
                <span t-if="currentSurchargePercent > 0"
                      class="badge rounded-pill bg-success text-white ms-1 px-2 py-0.5 fw-bold"
                      style="font-size: 0.8rem; box-shadow: 0 0 8px rgba(25,135,84,0.8); border: 1px solid rgba(255,255,255,0.4);">
                    <t t-esc="currentSurchargePercent"/>%
                </span>
            </button>
        </xpath>

    </t>
</templates>
```

- [ ] **Step 4: Agregar el bloque `assets` al manifest**

En `__manifest__.py`, después de `"data": [...]`, agregar:
```python
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_global_surcharge_button/static/src/js/control_buttons_patch.js",
            "pos_global_surcharge_button/static/src/xml/control_buttons.xml",
        ],
    },
```

- [ ] **Step 5: Upgrade + restart**

Run:
```bash
docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d prod -u pos_global_surcharge_button --stop-after-init --no-http && docker restart odoo-odoo-1
```
Expected: log sin errores; assets regenerados al recargar.

- [ ] **Step 6: Verificar en el POS (manual)**

Abrir el POS en el navegador, hard refresh (Ctrl+Shift+R). Crear un pedido con productos (p. ej. base $100).
Expected:
1. En la pantalla principal aparece el botón **"Recargo"** junto al de **Descuento**.
2. Tocar "Recargo" agrega una línea **Recargo** de **+$20** (20% de $100) y el badge muestra **20%**.
3. Tocar "Recargo" de nuevo **quita** la línea y el badge desaparece.
4. Cambiar `surcharge_pc` a 10% en Ajustes (+restart/refresh) → un toque agrega +$10.
5. Con descuento global aplicado, el recargo se calcula sobre los productos (no sobre la línea de descuento) y ambos conviven sin pisarse.

Si el botón no aparece: confirmar que `surcharge_product_id` está seteado en ese POS (Ajustes) y que el producto Recargo se cargó en el frontend (riesgo #1 del spec). Si el producto no resuelve (`surcharge_product_id` undefined en el front), revisar `available_in_pos=True` y, si hace falta, extender el dominio de carga de productos / `_get_special_products` como `pos_discount`.

- [ ] **Step 7: Commit**

```bash
git add pos_global_surcharge_button/static/src/js/control_buttons_patch.js pos_global_surcharge_button/static/src/xml/control_buttons.xml pos_global_surcharge_button/__manifest__.py
git commit -m "feat(pos_global_surcharge_button): botón Recargo (toggle) en pantalla principal del POS"
```

---

## Self-Review

**Spec coverage:**
- Alcance (línea de recargo global positiva) → Task 3 `clickSurcharge`. ✓
- Ubicación (pantalla principal, junto a Descuento) → Task 3 XML (ancla `js_discount`). ✓
- Producto auto-creado + editable → Task 1 (data + hook) + Task 2 (settings). ✓
- Comportamiento toggle, 20% configurable → Task 3 `clickSurcharge` + Task 1/2 `surcharge_pc`. ✓
- Badge con % actual → Task 3 `currentSurchargePercent` + XML. ✓
- Dependencias (point_of_sale, pos_discount, pos_global_discount_button) → Global Constraints + manifest. ✓
- Riesgo #1 (carga del producto) → Task 3 Step 6 nota. ✓
- Riesgo #2 (API agregar/quitar línea) → Task 3 Step 2 verificación. ✓
- Riesgo #3 (interacción con descuento) → Task 3 `_getSurchargeBase` excluye descuento. ✓
- Riesgo #4 (impuestos) → Task 1 data product sin impuestos + nota en spec. ✓

**Placeholder scan:** sin TBD/TODO; todo el código está completo. El único valor de entorno es `-d prod` (DB real del contenedor), no un placeholder de contenido.

**Type/naming consistency:** `surcharge_pc` y `surcharge_product_id` consistentes en pos_config, res_config_settings (related), hook, y JS (`this.pos.config.surcharge_pc/_product_id`). Métodos JS: `_getSurchargeLines`, `_getSurchargeBase`, `currentSurchargePercent`, `clickSurcharge`, y clase CSS `js_surcharge` usados consistentemente entre JS y XML. ✓
