# pos_sales_advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Módulo Odoo 18 que define asesores de venta, los hace seleccionables en la pantalla de pago del POS, los guarda en `pos.order` y expone un dashboard gerencial de métricas por asesor para calcular compensaciones.

**Architecture:** Un solo módulo autocontenido. Catálogo `pos.sales.advisor` cargado al POS por el data-layer nativo de Odoo 18 (`pos.load.mixin` + `_load_pos_data_models`); campo `sales_advisor_id` en `pos.order` que viaja con la sincronización nativa (funciona offline). Dashboard OWL backend + Chart.js con controller JSON de SQL parametrizado, calcado del lenguaje de diseño de `pos_management_metrics`.

**Tech Stack:** Odoo 18 (Python, OWL, QWeb), Chart.js por CDN, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-07-01-pos-sales-advisor-design.md`

## Global Constraints

- Versión de módulo: `18.0.1.0.0`; `license: LGPL-3`; `author: Alexis Medina`; `website: alexis.medn@gmail.com`.
- snake_case en todo; un archivo Python por modelo; docstring en cada método, en español.
- Strings de UI en español.
- En manifest `data`: `security/*` SIEMPRE antes que `views/`.
- Traducciones estilo Odoo 18: `_("texto %s", arg)` (coma, no `%`).
- Odoo 18 usa `<list>` (no `<tree>`) en vistas.
- Sin tests unitarios (convención del repo). Validación = sintaxis local + install/upgrade en container + prueba manual.
- El repo está bind-mounteado en el container: `/home/alexis/Documents/Github/prometeo-odoo-modules` → `/mnt/local-addons`. Los archivos escritos son visibles al instante.
- Comando de install/upgrade (docker funciona sin sudo en esta sesión):
  `docker exec odoo-odoo-1 odoo -i pos_sales_advisor -d prod --stop-after-init` (primera vez `-i`, luego `-u`). Verificar que el log NO contenga `ERROR` ni traceback. Existe también la DB `calidad` como alternativa de prueba.
- Working dir para comandos git: `/home/alexis/Documents/Github/prometeo-odoo-modules`.

---

### Task 1: Esqueleto del módulo + modelo `pos.sales.advisor` + seguridad + vistas backend

**Files:**
- Create: `pos_sales_advisor/__init__.py`
- Create: `pos_sales_advisor/__manifest__.py`
- Create: `pos_sales_advisor/models/__init__.py`
- Create: `pos_sales_advisor/models/pos_sales_advisor.py`
- Create: `pos_sales_advisor/security/security.xml`
- Create: `pos_sales_advisor/security/ir.model.access.csv`
- Create: `pos_sales_advisor/views/pos_sales_advisor_views.xml`

**Interfaces:**
- Produces: modelo `pos.sales.advisor` (campos `name: Char`, `active: Boolean`, `company_id: Many2one res.company`) con `pos.load.mixin` (`_load_pos_data_fields` → `["id", "name"]`). Grupo `pos_sales_advisor.group_pos_advisor_metrics`. Los usa Task 4 (carga POS), Task 5 (SQL `pos_sales_advisor`) y Task 6 (menú/grupo).

- [ ] **Step 1: Crear estructura y archivos Python**

`pos_sales_advisor/__init__.py`:
```python
from . import models
```

`pos_sales_advisor/models/__init__.py`:
```python
from . import pos_sales_advisor
```

`pos_sales_advisor/models/pos_sales_advisor.py`:
```python
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosSalesAdvisor(models.Model):
    _name = "pos.sales.advisor"
    _inherit = ["pos.load.mixin"]
    _description = "Asesor de Venta POS"
    _order = "name"

    name = fields.Char(string="Nombre", required=True)
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        help="Dejar vacío para que el asesor esté disponible en todas las compañías.",
    )

    @api.model
    def _load_pos_data_domain(self, data):
        """Dominio de carga al POS: asesores de la compañía de la caja o compartidos.

        Los archivados quedan excluidos automáticamente por el campo active.
        """
        config = self.env["pos.config"].browse(data["pos.config"]["data"][0]["id"])
        return [
            "|",
            ("company_id", "=", False),
            ("company_id", "=", config.company_id.id),
        ]

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Campos del asesor expuestos al frontend del POS."""
        return ["id", "name"]
```

`pos_sales_advisor/__manifest__.py`:
```python
# -*- coding: utf-8 -*-
{
    "name": "POS - Asesores de Venta",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Trackeo de asesores de venta: selección en la pantalla de pago, registro en la orden y dashboard de métricas para compensaciones",
    "description": """
        Permite definir asesores de venta, seleccionarlos en la pantalla de pago del POS,
        guardarlos en la orden y analizar sus métricas de venta en un dashboard gerencial
        para el cálculo de compensaciones económicas.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/pos_sales_advisor_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": True,
}
```

- [ ] **Step 2: Crear seguridad**

`pos_sales_advisor/security/security.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="group_pos_advisor_metrics" model="res.groups">
        <field name="name">Acceso a Métricas de Asesores de Venta</field>
        <field name="category_id" ref="base.module_category_usability"/>
        <field name="comment">Permite acceder al menú de Métricas de Asesores y visualizar el dashboard de ventas por asesor.</field>
    </record>
</odoo>
```

`pos_sales_advisor/security/ir.model.access.csv`:
```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_pos_sales_advisor_pos_user,pos.sales.advisor.pos.user,model_pos_sales_advisor,point_of_sale.group_pos_user,1,0,0,0
access_pos_sales_advisor_pos_manager,pos.sales.advisor.pos.manager,model_pos_sales_advisor,point_of_sale.group_pos_manager,1,1,1,1
```

- [ ] **Step 3: Crear vistas backend y menú del catálogo**

`pos_sales_advisor/views/pos_sales_advisor_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_pos_sales_advisor_list" model="ir.ui.view">
        <field name="name">pos.sales.advisor.list</field>
        <field name="model">pos.sales.advisor</field>
        <field name="arch" type="xml">
            <list string="Asesores de Venta">
                <field name="name"/>
                <field name="company_id" optional="show"/>
            </list>
        </field>
    </record>

    <record id="view_pos_sales_advisor_form" model="ir.ui.view">
        <field name="name">pos.sales.advisor.form</field>
        <field name="model">pos.sales.advisor</field>
        <field name="arch" type="xml">
            <form string="Asesor de Venta">
                <sheet>
                    <widget name="web_ribbon" title="Archivado" bg_color="text-bg-danger" invisible="active"/>
                    <group>
                        <field name="name"/>
                        <field name="company_id"/>
                        <field name="active" invisible="1"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_pos_sales_advisor" model="ir.actions.act_window">
        <field name="name">Asesores de Venta</field>
        <field name="res_model">pos.sales.advisor</field>
        <field name="view_mode">list,form</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Crea tu primer asesor de venta</p>
            <p>Los asesores se seleccionan en la pantalla de pago del POS y sus ventas se miden en el dashboard de métricas.</p>
        </field>
    </record>

    <menuitem id="menu_pos_sales_advisor"
              name="Asesores de Venta"
              parent="point_of_sale.menu_point_config_product"
              action="action_pos_sales_advisor"
              groups="point_of_sale.group_pos_manager"
              sequence="60"/>
</odoo>
```

- [ ] **Step 4: Validar sintaxis local**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('pos_sales_advisor/__manifest__.py').read()); print('manifest OK')"
python3 -c "import xml.dom.minidom as m; m.parse('pos_sales_advisor/security/security.xml'); m.parse('pos_sales_advisor/views/pos_sales_advisor_views.xml'); print('XML OK')"
python3 -c "import csv; rows=list(csv.reader(open('pos_sales_advisor/security/ir.model.access.csv'))); print('CSV cols:', {len(r) for r in rows})"
```
Expected: `manifest OK`, `XML OK`, `CSV cols: {8}`.

- [ ] **Step 5: Instalar el módulo en el container**

```bash
docker exec odoo-odoo-1 odoo -i pos_sales_advisor -d prod --stop-after-init 2>&1 | grep -iE "error|traceback|pos_sales_advisor" | head -20
```
Expected: líneas de carga del módulo, sin `ERROR` ni traceback.

- [ ] **Step 6: Commit**

```bash
git add pos_sales_advisor/
git commit -m "feat(pos_sales_advisor): modelo de asesores, seguridad y catálogo backend"
```

---

### Task 2: `require_sales_advisor` en pos.config + ajustes del POS

**Files:**
- Create: `pos_sales_advisor/models/pos_config.py`
- Create: `pos_sales_advisor/models/res_config_settings.py`
- Create: `pos_sales_advisor/views/res_config_settings_views.xml`
- Modify: `pos_sales_advisor/models/__init__.py`
- Modify: `pos_sales_advisor/__manifest__.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `pos.config.require_sales_advisor: Boolean` — lo usa Task 4 en el frontend como `pos.config.require_sales_advisor` (carga automática: el loader de `pos.config` lee todos los campos).

- [ ] **Step 1: Crear los modelos**

`pos_sales_advisor/models/pos_config.py`:
```python
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    require_sales_advisor = fields.Boolean(
        string="Requerir asesor de venta",
        default=False,
        help="Si está activo, no se puede validar el pago sin seleccionar un asesor de venta.",
    )
```

`pos_sales_advisor/models/res_config_settings.py`:
```python
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_require_sales_advisor = fields.Boolean(
        related="pos_config_id.require_sales_advisor",
        readonly=False,
    )
```

`pos_sales_advisor/models/__init__.py` queda:
```python
from . import pos_config
from . import pos_sales_advisor
from . import res_config_settings
```

- [ ] **Step 2: Crear la vista de ajustes**

`pos_sales_advisor/views/res_config_settings_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="res_config_settings_view_form" model="ir.ui.view">
        <field name="name">res.config.settings.view.form.inherit.pos.sales.advisor</field>
        <field name="model">res.config.settings</field>
        <field name="inherit_id" ref="point_of_sale.res_config_settings_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//block[@id='pos_interface_section']" position="inside">
                <setting id="pos_require_sales_advisor"
                         string="Requerir asesor de venta"
                         help="Bloquea la validación del pago si la orden no tiene un asesor de venta seleccionado.">
                    <field name="pos_require_sales_advisor"/>
                </setting>
            </xpath>
        </field>
    </record>
</odoo>
```

- [ ] **Step 3: Agregar la vista al manifest**

En `pos_sales_advisor/__manifest__.py`, el bloque `data` queda:
```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/pos_sales_advisor_views.xml",
        "views/res_config_settings_views.xml",
    ],
```

- [ ] **Step 4: Validar sintaxis + upgrade**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; m.parse('pos_sales_advisor/views/res_config_settings_views.xml'); print('XML OK')"
docker exec odoo-odoo-1 odoo -u pos_sales_advisor -d prod --stop-after-init 2>&1 | grep -iE "error|traceback" | head -10
```
Expected: `XML OK`, sin `ERROR`.

- [ ] **Step 5: Commit**

```bash
git add pos_sales_advisor/
git commit -m "feat(pos_sales_advisor): opción 'Requerir asesor de venta' por caja"
```

---

### Task 3: Campo `sales_advisor_id` en pos.order + herencia en devoluciones + vistas de orden

**Files:**
- Create: `pos_sales_advisor/models/pos_order.py`
- Create: `pos_sales_advisor/views/pos_order_views.xml`
- Modify: `pos_sales_advisor/models/__init__.py`
- Modify: `pos_sales_advisor/__manifest__.py`

**Interfaces:**
- Consumes: modelo `pos.sales.advisor` (Task 1).
- Produces: `pos.order.sales_advisor_id: Many2one pos.sales.advisor` — lo usa Task 4 (frontend, se carga automático porque el loader de `pos.order` lee todos los campos) y Task 5 (columna SQL `po.sales_advisor_id`).

- [ ] **Step 1: Crear el modelo**

`pos_sales_advisor/models/pos_order.py`:
```python
from odoo import fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    sales_advisor_id = fields.Many2one(
        "pos.sales.advisor",
        string="Asesor de Venta",
        index=True,
        help="Asesor de venta al que se atribuye esta orden para métricas y compensaciones.",
    )

    def _prepare_refund_values(self, current_session):
        """La devolución hereda el asesor de la orden original para que reste en sus métricas."""
        vals = super()._prepare_refund_values(current_session)
        vals["sales_advisor_id"] = self.sales_advisor_id.id
        return vals
```

`pos_sales_advisor/models/__init__.py` queda:
```python
from . import pos_config
from . import pos_order
from . import pos_sales_advisor
from . import res_config_settings
```

- [ ] **Step 2: Crear las vistas de orden**

`pos_sales_advisor/views/pos_order_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_pos_pos_form" model="ir.ui.view">
        <field name="name">pos.order.form.inherit.pos.sales.advisor</field>
        <field name="model">pos.order</field>
        <field name="inherit_id" ref="point_of_sale.view_pos_pos_form"/>
        <field name="arch" type="xml">
            <xpath expr="//field[@name='partner_id']" position="after">
                <field name="sales_advisor_id"/>
            </xpath>
        </field>
    </record>

    <record id="view_pos_order_tree" model="ir.ui.view">
        <field name="name">pos.order.list.inherit.pos.sales.advisor</field>
        <field name="model">pos.order</field>
        <field name="inherit_id" ref="point_of_sale.view_pos_order_tree"/>
        <field name="arch" type="xml">
            <xpath expr="//field[@name='partner_id']" position="after">
                <field name="sales_advisor_id" optional="show"/>
            </xpath>
        </field>
    </record>

    <record id="view_pos_order_filter" model="ir.ui.view">
        <field name="name">pos.order.search.inherit.pos.sales.advisor</field>
        <field name="model">pos.order</field>
        <field name="inherit_id" ref="point_of_sale.view_pos_order_filter"/>
        <field name="arch" type="xml">
            <xpath expr="//filter[@name='customer']" position="after">
                <filter string="Asesor de Venta" name="sales_advisor" domain="[]" context="{'group_by': 'sales_advisor_id'}"/>
            </xpath>
            <xpath expr="//field[@name='partner_id']" position="after">
                <field name="sales_advisor_id"/>
            </xpath>
        </field>
    </record>
</odoo>
```

Nota: si el xpath de `partner_id` en la vista search falla en el upgrade (el anchor exacto puede variar), quitar ese segundo xpath y dejar solo el filtro de agrupación — el filtro `customer` sí existe en `view_pos_order_filter`.

- [ ] **Step 3: Agregar la vista al manifest**

En `pos_sales_advisor/__manifest__.py`, el bloque `data` queda:
```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/pos_sales_advisor_views.xml",
        "views/pos_order_views.xml",
        "views/res_config_settings_views.xml",
    ],
```

- [ ] **Step 4: Validar sintaxis + upgrade**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; m.parse('pos_sales_advisor/views/pos_order_views.xml'); print('XML OK')"
docker exec odoo-odoo-1 odoo -u pos_sales_advisor -d prod --stop-after-init 2>&1 | grep -iE "error|traceback" | head -10
```
Expected: `XML OK`, sin `ERROR`.

- [ ] **Step 5: Commit**

```bash
git add pos_sales_advisor/
git commit -m "feat(pos_sales_advisor): campo asesor en pos.order con herencia en devoluciones"
```

---

### Task 4: Carga al POS + UI de pantalla de pago (botón, popup, badge, bloqueo)

**Files:**
- Create: `pos_sales_advisor/models/pos_session.py`
- Create: `pos_sales_advisor/static/src/xml/advisor_button.xml`
- Create: `pos_sales_advisor/static/src/js/payment_screen_patch.js`
- Create: `pos_sales_advisor/static/src/js/ticket_screen_patch.js`
- Modify: `pos_sales_advisor/models/__init__.py`
- Modify: `pos_sales_advisor/__manifest__.py`

**Interfaces:**
- Consumes: `pos.sales.advisor` con `pos.load.mixin` (Task 1), `pos.config.require_sales_advisor` (Task 2), `pos.order.sales_advisor_id` (Task 3).
- Produces: en el frontend POS, `this.pos.models["pos.sales.advisor"]` y `order.sales_advisor_id` (registro del data-layer, se serializa como id al backend). Getter `currentOrderAdvisor` usado por el template del badge.

- [ ] **Step 1: Registrar el modelo en el data-layer**

`pos_sales_advisor/models/pos_session.py`:
```python
from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config_id):
        """Agrega los asesores de venta a los modelos que carga el POS."""
        res = super()._load_pos_data_models(config_id)
        res.append("pos.sales.advisor")
        return res
```

`pos_sales_advisor/models/__init__.py` queda:
```python
from . import pos_config
from . import pos_order
from . import pos_sales_advisor
from . import pos_session
from . import res_config_settings
```

- [ ] **Step 2: Template del botón + badge en la pantalla de pago**

`pos_sales_advisor/static/src/xml/advisor_button.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

    <!-- Botón de selección de asesor + badge flotante (mismo patrón que card_installment) -->
    <t t-inherit="point_of_sale.PaymentScreenButtons" t-inherit-mode="extension">
        <xpath expr="//div[contains(@class, 'payment-buttons')]" position="inside">

            <button class="button btn btn-light btn-lg lh-lg" id="button_sales_advisor"
                    t-on-click="() => this.onClickSalesAdvisor()">
                <i class="fa fa-user me-2"/>
                Asesor de Venta
            </button>

            <!-- Indicador visual flotante del asesor seleccionado -->
            <div class="advisor-selected-badge position-absolute bottom-0 end-0 m-3 p-3 rounded-3 shadow-lg d-flex align-items-center bg-white border border-2"
                 t-att-class="currentOrderAdvisor ? 'border-success' : (pos.config.require_sales_advisor ? 'border-warning' : 'border-secondary')"
                 style="z-index: 1000; min-width: 240px; pointer-events: none;">
                <div class="me-3 rounded-circle d-flex align-items-center justify-content-center"
                     t-att-class="currentOrderAdvisor ? 'bg-success text-white' : (pos.config.require_sales_advisor ? 'bg-warning text-dark' : 'bg-secondary text-white')"
                     style="width: 40px; height: 40px; font-size: 1.2rem;">
                    <i t-att-class="currentOrderAdvisor ? 'fa fa-check-circle' : 'fa fa-user'"/>
                </div>
                <div>
                    <div class="text-muted small fw-bold" style="font-size: 0.75rem;">ASESOR DE VENTA</div>
                    <div class="fw-bold"
                         t-att-class="currentOrderAdvisor ? 'text-success' : (pos.config.require_sales_advisor ? 'text-warning' : 'text-muted')"
                         style="font-size: 1rem;">
                        <t t-if="currentOrderAdvisor" t-esc="currentOrderAdvisor.name"/>
                        <t t-else="">Sin seleccionar</t>
                    </div>
                </div>
            </div>

        </xpath>
    </t>

</templates>
```

- [ ] **Step 3: Patch del PaymentScreen (popup de selección + bloqueo de validación)**

`pos_sales_advisor/static/src/js/payment_screen_patch.js`:
```javascript
/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {
    /**
     * Asesor seleccionado en la orden actual (registro del data-layer o null).
     */
    get currentOrderAdvisor() {
        return this.currentOrder?.sales_advisor_id || null;
    },

    /**
     * Abre el popup de selección de asesor. "Quitar asesor" limpia la selección;
     * cancelar el popup no modifica nada.
     */
    async onClickSalesAdvisor() {
        const advisors = this.pos.models["pos.sales.advisor"].getAll();
        const list = advisors.map((advisor) => ({
            id: advisor.id,
            label: advisor.name,
            isSelected: this.currentOrderAdvisor?.id === advisor.id,
            item: advisor,
        }));
        if (this.currentOrderAdvisor) {
            list.push({ id: 0, label: _t("Quitar asesor"), isSelected: false, item: false });
        }
        const selected = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Seleccionar asesor de venta"),
            list: list,
        });
        if (selected === undefined) {
            return;
        }
        this.currentOrder.update({ sales_advisor_id: selected || false });
    },

    /**
     * Bloquea la validación si la caja requiere asesor y la orden no tiene uno.
     */
    async _isOrderValid(isForceValidate) {
        if (this.pos.config.require_sales_advisor && !this.currentOrderAdvisor) {
            this.dialog.add(AlertDialog, {
                title: _t("Falta el asesor de venta"),
                body: _t("Esta caja requiere seleccionar un asesor de venta antes de validar el pago."),
            });
            return false;
        }
        return super._isOrderValid(isForceValidate);
    },
});
```

- [ ] **Step 4: Patch del TicketScreen (devoluciones heredan asesor)**

`pos_sales_advisor/static/src/js/ticket_screen_patch.js`:
```javascript
/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

patch(TicketScreen.prototype, {
    /**
     * La orden de devolución hereda el asesor de la orden original.
     */
    async addAdditionalRefundInfo(order, destinationOrder) {
        if (order.sales_advisor_id) {
            destinationOrder.update({ sales_advisor_id: order.sales_advisor_id });
        }
        return super.addAdditionalRefundInfo(order, destinationOrder);
    },
});
```

- [ ] **Step 5: Agregar assets POS al manifest**

En `pos_sales_advisor/__manifest__.py`, después del bloque `data`, agregar:
```python
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_sales_advisor/static/src/js/payment_screen_patch.js",
            "pos_sales_advisor/static/src/js/ticket_screen_patch.js",
            "pos_sales_advisor/static/src/xml/advisor_button.xml",
        ],
    },
```

- [ ] **Step 6: Validar sintaxis + upgrade**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; m.parse('pos_sales_advisor/static/src/xml/advisor_button.xml'); print('XML OK')"
python3 -c "import ast; ast.parse(open('pos_sales_advisor/__manifest__.py').read()); print('manifest OK')"
node --check pos_sales_advisor/static/src/js/payment_screen_patch.js 2>/dev/null || echo "node no disponible, saltar"
docker exec odoo-odoo-1 odoo -u pos_sales_advisor -d prod --stop-after-init 2>&1 | grep -iE "error|traceback" | head -10
```
Expected: `XML OK`, `manifest OK`, sin `ERROR` en upgrade.

- [ ] **Step 7: Prueba manual en el POS**

1. Backend: Punto de Venta → Configuración → Asesores de Venta → crear 2 asesores de prueba.
2. Abrir una sesión POS, cargar un producto, ir a Pago.
3. Verificar botón "Asesor de Venta" y badge "Sin seleccionar" (gris si la caja no lo requiere).
4. Seleccionar un asesor → badge verde con el nombre.
5. Validar la orden → en backend, Punto de Venta → Órdenes: la orden tiene el asesor.
6. Ajustes POS → activar "Requerir asesor de venta" → nueva orden sin asesor → Validar → debe aparecer el diálogo de error y bloquear.
7. Ticket → devolución de la orden con asesor → la orden de devolución conserva el asesor.

- [ ] **Step 8: Commit**

```bash
git add pos_sales_advisor/
git commit -m "feat(pos_sales_advisor): selección de asesor en pantalla de pago con badge y bloqueo configurable"
```

---

### Task 5: Controller JSON del dashboard + export CSV

**Files:**
- Create: `pos_sales_advisor/controllers/__init__.py`
- Create: `pos_sales_advisor/controllers/advisor_controller.py`
- Modify: `pos_sales_advisor/__init__.py`

**Interfaces:**
- Consumes: columna `po.sales_advisor_id` (Task 3), tabla `pos_sales_advisor` (Task 1), grupo `pos_sales_advisor.group_pos_advisor_metrics` (Task 1).
- Produces (para Task 6):
  - `POST /pos_sales_advisor/filters` (json) → `{advisors: [str], pos_configs: [str], companies: [str], min_date: str, max_date: str}`
  - `POST /pos_sales_advisor/metrics` (json, params `start_date, end_date, advisor, pos, company`) → `{kpis: {net_sales, gross_sales, refunds, orders_count, ticket_average, without_advisor_count, without_advisor_pct}, charts: {advisor_ranking: {labels, values}, sales_trend: {labels, advisors, timeframe}, advisor_share: {labels, values}}, table: [{asesor, bruto, devoluciones, neto, ordenes, ticket_promedio}]}`
  - `GET /pos_sales_advisor/export` (http, mismos params) → descarga CSV.

- [ ] **Step 1: Crear el controller**

`pos_sales_advisor/controllers/__init__.py`:
```python
from . import advisor_controller
```

`pos_sales_advisor/__init__.py` queda:
```python
from . import controllers
from . import models
```

`pos_sales_advisor/controllers/advisor_controller.py`:
```python
# -*- coding: utf-8 -*-
import csv
import io
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

POS_ORDER_STATES = ("paid", "done", "invoiced")


class PosSalesAdvisorController(http.Controller):

    def _check_access(self):
        """Valida que el usuario tenga el grupo de métricas de asesores."""
        if not request.env.user.has_group("pos_sales_advisor.group_pos_advisor_metrics"):
            raise AccessError("No tienes permisos para acceder a las métricas de asesores de venta.")

    def _get_timezone(self):
        """Timezone del usuario para convertir date_order (UTC) a hora local."""
        return request.env.user.tz or "America/Argentina/Buenos_Aires"

    def _build_where_clause(self, start_date=None, end_date=None, advisor="all", pos="all", company="all"):
        """Construye el WHERE parametrizado común a todas las consultas.

        Nota: se incluye el estado 'paid' (a diferencia de pos_management_metrics)
        para ver las ventas del día antes del cierre de sesión.
        """
        allowed_companies = tuple(request.env.companies.ids)
        where = "po.state IN %s AND po.company_id IN %s"
        params = [POS_ORDER_STATES, allowed_companies]
        tz = self._get_timezone()

        if start_date:
            where += " AND po.date_order >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            where += " AND po.date_order <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{end_date} 23:59:59", tz])
        if advisor and advisor != "all":
            where += " AND psa.name = %s"
            params.append(advisor)
        if pos and pos != "all":
            where += " AND pc.name = %s"
            params.append(pos)
        if company and company != "all":
            where += " AND rc.name = %s"
            params.append(company)
        return where, params

    def _base_from(self):
        """FROM común: orden + caja + compañía + asesor (LEFT para medir órdenes sin asesor)."""
        return """
            FROM pos_order po
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN res_company rc ON rc.id = po.company_id
            LEFT JOIN pos_sales_advisor psa ON psa.id = po.sales_advisor_id
        """

    def _get_advisor_rows(self, where, params):
        """Filas agregadas por asesor: bruto, devoluciones, neto, órdenes y ticket promedio."""
        cr = request.env.cr
        cr.execute(f"""
            SELECT psa.name AS asesor,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total >= 0), 0) AS bruto,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total < 0), 0) AS devoluciones,
                   COALESCE(SUM(po.amount_total), 0) AS neto,
                   COUNT(*) FILTER (WHERE po.amount_total >= 0) AS ordenes
            {self._base_from()}
            WHERE {where} AND po.sales_advisor_id IS NOT NULL
            GROUP BY psa.name
            ORDER BY neto DESC
        """, params)
        rows = []
        for asesor, bruto, devoluciones, neto, ordenes in cr.fetchall():
            rows.append({
                "asesor": asesor,
                "bruto": float(bruto),
                "devoluciones": float(devoluciones),
                "neto": float(neto),
                "ordenes": int(ordenes),
                "ticket_promedio": float(bruto) / int(ordenes) if ordenes else 0.0,
            })
        return rows

    @http.route("/pos_sales_advisor/filters", type="json", auth="user")
    def filters_metadata(self):
        """Metadatos para los selects del sidebar del dashboard."""
        self._check_access()
        cr = request.env.cr
        allowed_companies = tuple(request.env.companies.ids)

        cr.execute("SELECT name FROM pos_sales_advisor ORDER BY name")
        advisors = [r[0] for r in cr.fetchall()]

        cr.execute("SELECT name FROM pos_config WHERE company_id IN %s ORDER BY name", [allowed_companies])
        pos_configs = [r[0] for r in cr.fetchall()]

        companies = request.env.companies.mapped("name")

        cr.execute("SELECT MIN(po.date_order)::date, MAX(po.date_order)::date FROM pos_order po WHERE po.company_id IN %s", [allowed_companies])
        min_date, max_date = cr.fetchone()

        return {
            "advisors": advisors,
            "pos_configs": pos_configs,
            "companies": sorted(companies),
            "min_date": str(min_date or ""),
            "max_date": str(max_date or ""),
        }

    @http.route("/pos_sales_advisor/metrics", type="json", auth="user")
    def metrics(self, start_date=None, end_date=None, advisor="all", pos="all", company="all"):
        """KPIs, gráficos y tabla de detalle por asesor para el período filtrado."""
        self._check_access()
        cr = request.env.cr
        where, params = self._build_where_clause(start_date, end_date, advisor, pos, company)
        tz = self._get_timezone()

        # --- KPIs de órdenes con asesor ---
        cr.execute(f"""
            SELECT COALESCE(SUM(po.amount_total), 0) AS net_sales,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total >= 0), 0) AS gross_sales,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total < 0), 0) AS refunds,
                   COUNT(*) FILTER (WHERE po.amount_total >= 0) AS orders_count
            {self._base_from()}
            WHERE {where} AND po.sales_advisor_id IS NOT NULL
        """, params)
        net_sales, gross_sales, refunds, orders_count = cr.fetchone()

        # --- KPI de control: órdenes sin asesor en el período (sin filtro de asesor) ---
        where_no_adv, params_no_adv = self._build_where_clause(start_date, end_date, "all", pos, company)
        cr.execute(f"""
            SELECT COUNT(*) FILTER (WHERE po.sales_advisor_id IS NULL) AS without_advisor,
                   COUNT(*) AS total
            {self._base_from()}
            WHERE {where_no_adv}
        """, params_no_adv)
        without_advisor, total_orders = cr.fetchone()

        # --- Tabla / ranking por asesor ---
        table = self._get_advisor_rows(where, params)

        # --- Evolución diaria por asesor (top 6 por neto) ---
        top_names = [r["asesor"] for r in table[:6]]
        trend = {"labels": [], "advisors": {}, "timeframe": "Diario"}
        if top_names:
            cr.execute(f"""
                SELECT to_char(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s, 'YYYY-MM-DD') AS dia,
                       psa.name AS asesor,
                       SUM(po.amount_total) AS neto
                {self._base_from()}
                WHERE {where} AND psa.name IN %s
                GROUP BY 1, 2
                ORDER BY 1
            """, [tz] + params + [tuple(top_names)])
            raw = cr.fetchall()
            days = sorted({r[0] for r in raw})
            by_advisor = {name: {d: 0.0 for d in days} for name in top_names}
            for dia, asesor, neto in raw:
                by_advisor[asesor][dia] = float(neto)
            trend["labels"] = days
            trend["advisors"] = {name: [by_advisor[name][d] for d in days] for name in top_names}

        # --- Participación (top 8 + Otros) ---
        share_labels = [r["asesor"] for r in table[:8]]
        share_values = [r["neto"] for r in table[:8]]
        rest = sum(r["neto"] for r in table[8:])
        if rest > 0:
            share_labels.append("Otros")
            share_values.append(rest)

        return {
            "kpis": {
                "net_sales": float(net_sales),
                "gross_sales": float(gross_sales),
                "refunds": float(refunds),
                "orders_count": int(orders_count),
                "ticket_average": float(gross_sales) / int(orders_count) if orders_count else 0.0,
                "without_advisor_count": int(without_advisor),
                "without_advisor_pct": round(100.0 * int(without_advisor) / int(total_orders), 1) if total_orders else 0.0,
            },
            "charts": {
                "advisor_ranking": {
                    "labels": [r["asesor"] for r in table[:10]],
                    "values": [r["neto"] for r in table[:10]],
                },
                "sales_trend": trend,
                "advisor_share": {"labels": share_labels, "values": share_values},
            },
            "table": table,
        }

    @http.route("/pos_sales_advisor/export", type="http", auth="user")
    def export_csv(self, start_date=None, end_date=None, advisor="all", pos="all", company="all", **kwargs):
        """Exporta la tabla de detalle por asesor como CSV (insumo para compensaciones)."""
        self._check_access()
        where, params = self._build_where_clause(start_date or None, end_date or None, advisor, pos, company)
        rows = self._get_advisor_rows(where, params)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Asesor", "Ventas Brutas", "Devoluciones", "Ventas Netas", "Órdenes", "Ticket Promedio"])
        for r in rows:
            writer.writerow([
                r["asesor"],
                f"{r['bruto']:.2f}",
                f"{r['devoluciones']:.2f}",
                f"{r['neto']:.2f}",
                r["ordenes"],
                f"{r['ticket_promedio']:.2f}",
            ])

        filename = f"metricas_asesores_{start_date or 'inicio'}_{end_date or 'hoy'}.csv"
        return request.make_response(
            output.getvalue(),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
```

- [ ] **Step 2: Validar sintaxis + upgrade**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('pos_sales_advisor/controllers/advisor_controller.py').read()); print('controller OK')"
docker exec odoo-odoo-1 odoo -u pos_sales_advisor -d prod --stop-after-init 2>&1 | grep -iE "error|traceback" | head -10
```
Expected: `controller OK`, sin `ERROR`.

- [ ] **Step 3: Commit**

```bash
git add pos_sales_advisor/
git commit -m "feat(pos_sales_advisor): controller JSON de métricas por asesor y export CSV"
```

---

### Task 6: Dashboard OWL (frontend) + menú raíz

**Files:**
- Create: `pos_sales_advisor/static/src/css/dashboard.css` (copiado y renombrado desde pos_management_metrics)
- Create: `pos_sales_advisor/static/src/js/dashboard.js`
- Create: `pos_sales_advisor/static/src/xml/dashboard.xml`
- Create: `pos_sales_advisor/views/menu_views.xml`
- Modify: `pos_sales_advisor/__manifest__.py`

**Interfaces:**
- Consumes: endpoints de Task 5 (`/pos_sales_advisor/filters`, `/pos_sales_advisor/metrics`, `/pos_sales_advisor/export`) con las estructuras exactas ahí definidas; grupo `pos_sales_advisor.group_pos_advisor_metrics` (Task 1).
- Produces: client action tag `pos_sales_advisor.dashboard` + menú raíz "Métricas de Asesores".

- [ ] **Step 1: Copiar el CSS del dashboard existente renombrando la clase raíz**

Reutilizamos el lenguaje de diseño completo (glassmorphic, KPI cards, sidebar, tablas, tooltips) con la clase raíz renombrada para no colisionar:

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
sed 's/pos-dashboard-wrap/advisor-dashboard-wrap/g' \
    pos_management_metrics/static/src/css/dashboard.css \
    > pos_sales_advisor/static/src/css/dashboard.css
grep -c "advisor-dashboard-wrap" pos_sales_advisor/static/src/css/dashboard.css
```
Expected: un conteo > 100 (todas las ocurrencias renombradas).

- [ ] **Step 2: Componente OWL**

`pos_sales_advisor/static/src/js/dashboard.js`:
```javascript
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

class PosSalesAdvisorDashboard extends Component {
    static template = "pos_sales_advisor.DashboardTemplate";

    setup() {
        this.state = useState({
            preset: "30days",
            startDate: "",
            endDate: "",
            advisor: "all",
            pos: "all",
            company: "all",
            search: "",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
        });

        this.filtersData = useState({
            advisors: [],
            pos_configs: [],
            companies: [],
            min_date: "",
            max_date: "",
        });

        this.metricsData = useState({
            kpis: {
                net_sales: 0,
                gross_sales: 0,
                refunds: 0,
                orders_count: 0,
                ticket_average: 0,
                without_advisor_count: 0,
                without_advisor_pct: 0,
            },
            charts: {
                advisor_ranking: { labels: [], values: [] },
                sales_trend: { labels: [], advisors: {}, timeframe: "Diario" },
                advisor_share: { labels: [], values: [] },
            },
            table: [],
        });

        this.charts = {};

        onWillStart(async () => {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
            this.setPresetDates(this.state.preset);
            await this.loadFiltersMetadata();
            await this.refreshData();
        });

        onMounted(() => {
            this.renderAllCharts();
        });

        onWillUnmount(() => {
            Object.values(this.charts).forEach((chart) => {
                if (chart) {
                    chart.destroy();
                }
            });
        });
    }

    // --- Getters reactivos ---
    get filteredTableRows() {
        const search = (this.state.search || "").toLowerCase().trim();
        if (!search) return this.metricsData.table;
        return this.metricsData.table.filter(
            (r) => r.asesor && r.asesor.toLowerCase().includes(search)
        );
    }

    // --- Manejo de eventos ---
    onPresetClick(preset) {
        this.state.preset = preset;
        this.setPresetDates(preset);
    }

    onStartDateChange(ev) {
        this.state.preset = "custom";
        this.state.startDate = ev.target.value;
    }

    onEndDateChange(ev) {
        this.state.preset = "custom";
        this.state.endDate = ev.target.value;
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        setTimeout(() => this.renderAllCharts(), 50);
    }

    async applyFilters() {
        await this.refreshData();
    }

    async clearFilters() {
        this.state.preset = "30days";
        this.setPresetDates("30days");
        this.state.advisor = "all";
        this.state.pos = "all";
        this.state.company = "all";
        this.state.search = "";
        await this.refreshData();
    }

    // --- Formateadores ---
    formatCurrency(val) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency",
            currency: "ARS",
            minimumFractionDigits: 2,
        }).format(val || 0);
    }

    formatPercent(val) {
        return `${(val || 0).toFixed(1)}%`;
    }

    // --- Fechas predefinidas ---
    setPresetDates(preset) {
        const today = new Date();
        let start = new Date();
        let end = new Date();

        switch (preset) {
            case "today":
                break;
            case "yesterday":
                start.setDate(today.getDate() - 1);
                end.setDate(today.getDate() - 1);
                break;
            case "7days":
                start.setDate(today.getDate() - 7);
                break;
            case "30days":
                start.setDate(today.getDate() - 30);
                break;
            case "60days":
                start.setDate(today.getDate() - 60);
                break;
            case "90days":
                start.setDate(today.getDate() - 90);
                break;
            case "all":
                start = null;
                end = null;
                break;
        }

        const formatDate = (d) => {
            if (!d) return "";
            const year = d.getFullYear();
            const month = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            return `${year}-${month}-${day}`;
        };

        this.state.startDate = formatDate(start);
        this.state.endDate = formatDate(end);
    }

    // --- RPC ---
    async loadFiltersMetadata() {
        try {
            const data = await rpc("/pos_sales_advisor/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const metrics = await rpc("/pos_sales_advisor/metrics", {
                start_date: this.state.startDate || null,
                end_date: this.state.endDate || null,
                advisor: this.state.advisor,
                pos: this.state.pos,
                company: this.state.company,
            });
            Object.assign(this.metricsData, metrics);
            setTimeout(() => this.renderAllCharts(), 50);
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas de asesores:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    exportCSV() {
        const params = new URLSearchParams({
            start_date: this.state.startDate || "",
            end_date: this.state.endDate || "",
            advisor: this.state.advisor,
            pos: this.state.pos,
            company: this.state.company,
        });
        window.open(`/pos_sales_advisor/export?${params.toString()}`, "_blank");
    }

    // --- Gráficos ---
    createOrUpdateChart(canvasId, type, data, extraOptions = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
        this.charts[canvasId] = new Chart(canvas, {
            type: type,
            data: data,
            options: Object.assign(
                {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                },
                extraOptions
            ),
        });
    }

    renderAllCharts() {
        const isLight = this.state.theme === "light";
        const textColor = isLight ? "#475569" : "#94a3b8";
        const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)";
        Chart.defaults.color = textColor;

        const gridConfig = {
            color: gridColor,
            borderColor: "transparent",
            drawBorder: false,
        };

        const palette = [
            { border: "#3b82f6", bg: "rgba(59, 130, 246, 0.08)" },
            { border: "#a855f7", bg: "rgba(168, 85, 247, 0.08)" },
            { border: "#10b981", bg: "rgba(16, 185, 129, 0.08)" },
            { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.08)" },
            { border: "#ec4899", bg: "rgba(236, 72, 153, 0.08)" },
            { border: "#06b6d4", bg: "rgba(6, 182, 212, 0.08)" },
        ];

        // 1. Ranking de asesores (barras horizontales por neto)
        const ranking = this.metricsData.charts.advisor_ranking;
        this.createOrUpdateChart("chart-advisor-ranking", "bar", {
            labels: ranking.labels,
            datasets: [{
                label: "Ventas Netas",
                data: ranking.values,
                backgroundColor: "rgba(59, 130, 246, 0.5)",
                borderColor: "#3b82f6",
                borderWidth: 2,
                borderRadius: 6,
            }],
        }, {
            indexAxis: "y",
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
                y: { grid: gridConfig },
            },
        });

        // 2. Evolución temporal por asesor (líneas, top 6)
        const trend = this.metricsData.charts.sales_trend;
        const datasets = [];
        let colorIdx = 0;
        Object.keys(trend.advisors).forEach((advisorName) => {
            const color = palette[colorIdx % palette.length];
            colorIdx++;
            datasets.push({
                label: advisorName,
                data: trend.advisors[advisorName],
                borderColor: color.border,
                backgroundColor: color.bg,
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointBackgroundColor: color.border,
                pointHoverRadius: 6,
            });
        });
        this.createOrUpdateChart("chart-advisor-trend", "line", {
            labels: trend.labels,
            datasets: datasets,
        }, {
            plugins: {
                legend: {
                    display: true,
                    position: "top",
                    labels: {
                        color: textColor,
                        boxWidth: 12,
                        boxHeight: 12,
                        usePointStyle: true,
                        pointStyle: "circle",
                        font: { size: 11, weight: "bold" },
                        padding: 15,
                    },
                },
            },
            scales: {
                x: { grid: gridConfig },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
            },
        });

        // 3. Participación por asesor (doughnut)
        const share = this.metricsData.charts.advisor_share;
        this.createOrUpdateChart("chart-advisor-share", "doughnut", {
            labels: share.labels,
            datasets: [{
                data: share.values,
                backgroundColor: palette.map((c) => c.border),
                borderWidth: 0,
            }],
        }, {
            cutout: "62%",
            plugins: {
                legend: {
                    display: true,
                    position: "bottom",
                    labels: {
                        color: textColor,
                        boxWidth: 10,
                        boxHeight: 10,
                        usePointStyle: true,
                        pointStyle: "circle",
                        font: { size: 11 },
                        padding: 10,
                    },
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const total = share.values.reduce((a, b) => a + b, 0);
                            const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                            return ` ${ctx.label}: ${pct}% (${this.formatCurrency(ctx.parsed)})`;
                        },
                    },
                },
            },
        });
    }
}

registry.category("actions").add("pos_sales_advisor.dashboard", PosSalesAdvisorDashboard);
```

- [ ] **Step 3: Template QWeb del dashboard**

`pos_sales_advisor/static/src/xml/dashboard.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<templates xml:space="preserve">
    <t t-name="pos_sales_advisor.DashboardTemplate">
        <div t-att-class="'advisor-dashboard-wrap ' + (state.theme === 'light' ? 'theme-light' : '')">
            <!-- Sidebar de Filtros (Glassmorphic) -->
            <aside class="sidebar" id="sidebar">
                <div class="sidebar-brand">
                    <svg class="brand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                        <circle cx="9" cy="7" r="4"></circle>
                        <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                        <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                    </svg>
                    <div class="brand-text">
                        <h2>Asesores de Venta</h2>
                        <span>Metrics Hub</span>
                    </div>
                </div>

                <!-- Rango de Fechas Predefinido -->
                <div class="sidebar-section">
                    <h3>Rango de Fecha</h3>
                    <div class="preset-dates">
                        <button t-att-class="'btn-preset ' + (state.preset === 'today' ? 'active' : '')"
                                t-on-click="() => this.onPresetClick('today')">Hoy</button>
                        <button t-att-class="'btn-preset ' + (state.preset === 'yesterday' ? 'active' : '')"
                                t-on-click="() => this.onPresetClick('yesterday')">Ayer</button>
                        <button t-att-class="'btn-preset ' + (state.preset === '7days' ? 'active' : '')"
                                t-on-click="() => this.onPresetClick('7days')">Últimos 7 días</button>
                        <button t-att-class="'btn-preset ' + (state.preset === '30days' ? 'active' : '')"
                                t-on-click="() => this.onPresetClick('30days')">Últimos 30 días</button>
                        <button t-att-class="'btn-preset ' + (state.preset === '60days' ? 'active' : '')"
                                t-on-click="() => this.onPresetClick('60days')">Últimos 60 días</button>
                        <button t-att-class="'btn-preset ' + (state.preset === '90days' ? 'active' : '')"
                                t-on-click="() => this.onPresetClick('90days')">Últimos 90 días</button>
                        <button t-att-class="'btn-preset ' + (state.preset === 'all' ? 'active' : '')"
                                t-on-click="() => this.onPresetClick('all')">Todo</button>
                    </div>

                    <div class="custom-date-inputs">
                        <div class="input-group">
                            <label>Desde</label>
                            <input type="date" t-att-value="state.startDate" t-on-change="onStartDateChange"/>
                        </div>
                        <div class="input-group">
                            <label>Hasta</label>
                            <input type="date" t-att-value="state.endDate" t-on-change="onEndDateChange"/>
                        </div>
                    </div>
                </div>

                <!-- Filtros Avanzados -->
                <div class="sidebar-section">
                    <h3>Filtros Avanzados</h3>

                    <div class="input-group">
                        <label>Asesor de Venta</label>
                        <div class="select-wrapper">
                            <select t-model="state.advisor">
                                <option value="all">Todos los asesores</option>
                                <t t-foreach="filtersData.advisors" t-as="adv" t-key="adv">
                                    <option t-att-value="adv"><t t-esc="adv"/></option>
                                </t>
                            </select>
                        </div>
                    </div>

                    <div class="input-group">
                        <label>Punto de Venta (Caja)</label>
                        <div class="select-wrapper">
                            <select t-model="state.pos">
                                <option value="all">Todas las cajas</option>
                                <t t-foreach="filtersData.pos_configs" t-as="pos" t-key="pos">
                                    <option t-att-value="pos"><t t-esc="pos"/></option>
                                </t>
                            </select>
                        </div>
                    </div>

                    <div class="input-group">
                        <label>Empresa</label>
                        <div class="select-wrapper">
                            <select t-model="state.company">
                                <option value="all">Todas las empresas</option>
                                <t t-foreach="filtersData.companies" t-as="company" t-key="company">
                                    <option t-att-value="company"><t t-esc="company"/></option>
                                </t>
                            </select>
                        </div>
                    </div>
                </div>

                <div class="sidebar-footer" style="display: flex; gap: 8px;">
                    <button class="btn btn-primary" style="flex: 1;" t-on-click="applyFilters">
                        <span>Aplicar</span>
                    </button>
                    <button class="btn btn-secondary" style="flex: 1;" t-on-click="clearFilters">
                        <span>Limpiar</span>
                    </button>
                </div>
            </aside>

            <!-- Main Content Area -->
            <main class="main-content">
                <header class="main-header">
                    <div class="header-left">
                        <h1>Dashboard de Asesores de Venta</h1>
                    </div>

                    <div class="header-right">
                        <button class="btn btn-secondary btn-icon-only" t-on-click="toggleTheme" t-att-title="state.theme === 'light' ? 'Modo Noche' : 'Modo Día'">
                            <t t-if="state.theme === 'light'">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px; height:16px;">
                                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                                </svg>
                            </t>
                            <t t-else="">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px; height:16px;">
                                    <circle cx="12" cy="12" r="5"></circle>
                                    <line x1="12" y1="1" x2="12" y2="3"></line>
                                    <line x1="12" y1="21" x2="12" y2="23"></line>
                                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                                    <line x1="1" y1="12" x2="3" y2="12"></line>
                                    <line x1="21" y1="12" x2="23" y2="12"></line>
                                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                                </svg>
                            </t>
                        </button>

                        <div class="sync-status">
                            <span t-att-class="'status-dot ' + (state.loading ? 'anim-spin' : 'green')"></span>
                            <span class="status-text" t-esc="state.syncTime">Cargando...</span>
                        </div>

                        <button class="btn btn-secondary btn-icon-only" t-on-click="() => this.refreshData()" title="Sincronizar ahora">
                            <svg t-att-class="state.loading ? 'icon-spin-target spinning' : 'icon-spin-target'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path>
                            </svg>
                        </button>
                    </div>
                </header>

                <div class="tab-content">
                    <section class="tab-pane active">
                        <!-- KPI Cards Grid -->
                        <div class="kpi-grid">
                            <div class="kpi-card shadow-glow green">
                                <div class="kpi-card-inner">
                                    <div class="kpi-meta">
                                        <span class="kpi-title">Ventas Netas Atribuidas</span>
                                        <div class="kpi-icon">
                                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <line x1="12" y1="1" x2="12" y2="23"></line>
                                                <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
                                            </svg>
                                        </div>
                                    </div>
                                    <div class="kpi-value"><t t-esc="formatCurrency(metricsData.kpis.net_sales)"/></div>
                                    <div class="kpi-footer">
                                        <span class="kpi-subtext">Bruto: <t t-esc="formatCurrency(metricsData.kpis.gross_sales)"/> · Dev.: <t t-esc="formatCurrency(metricsData.kpis.refunds)"/></span>
                                    </div>
                                </div>
                            </div>

                            <div class="kpi-card shadow-glow blue">
                                <div class="kpi-card-inner">
                                    <div class="kpi-meta">
                                        <span class="kpi-title">Órdenes con Asesor</span>
                                        <div class="kpi-icon">
                                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                                <polyline points="14 2 14 8 20 8"></polyline>
                                                <line x1="16" y1="13" x2="8" y2="13"></line>
                                                <line x1="16" y1="17" x2="8" y2="17"></line>
                                            </svg>
                                        </div>
                                    </div>
                                    <div class="kpi-value"><t t-esc="metricsData.kpis.orders_count.toLocaleString()"/></div>
                                    <div class="kpi-footer">
                                        <span class="kpi-subtext">En el período filtrado</span>
                                    </div>
                                </div>
                            </div>

                            <div class="kpi-card shadow-glow purple">
                                <div class="kpi-card-inner">
                                    <div class="kpi-meta">
                                        <span class="kpi-title">Ticket Promedio</span>
                                        <div class="kpi-icon">
                                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <circle cx="9" cy="21" r="1"></circle>
                                                <circle cx="20" cy="21" r="1"></circle>
                                                <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path>
                                            </svg>
                                        </div>
                                    </div>
                                    <div class="kpi-value"><t t-esc="formatCurrency(metricsData.kpis.ticket_average)"/></div>
                                    <div class="kpi-footer">
                                        <span class="kpi-subtext">Por orden con asesor</span>
                                    </div>
                                </div>
                            </div>

                            <div t-att-class="'kpi-card shadow-glow ' + (metricsData.kpis.without_advisor_pct > 20 ? 'red' : 'amber')">
                                <div class="kpi-card-inner">
                                    <div class="kpi-meta">
                                        <span class="kpi-title">Órdenes sin Asesor</span>
                                        <div class="kpi-icon">
                                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <circle cx="12" cy="12" r="10"></circle>
                                                <line x1="12" y1="8" x2="12" y2="12"></line>
                                                <line x1="12" y1="16" x2="12.01" y2="16"></line>
                                            </svg>
                                        </div>
                                    </div>
                                    <div class="kpi-value"><t t-esc="formatPercent(metricsData.kpis.without_advisor_pct)"/></div>
                                    <div class="kpi-footer">
                                        <span class="kpi-subtext"><t t-esc="metricsData.kpis.without_advisor_count.toLocaleString()"/> órdenes sin atribuir (control de adopción)</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Charts Grid -->
                        <div class="charts-grid">
                            <!-- Ranking de Asesores -->
                            <div class="chart-container span-two-cols glass-panel">
                                <div class="chart-header" style="position: relative;">
                                    <h3>Ranking de Asesores</h3>
                                    <div class="info-tooltip-wrapper tooltip-right">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="info-icon">
                                            <circle cx="12" cy="12" r="10"></circle>
                                            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                                            <line x1="12" y1="17" x2="12.01" y2="17"></line>
                                        </svg>
                                        <div class="info-tooltip-text">
                                            Top 10 asesores por ventas netas (ventas menos devoluciones) en el período. Es la base directa para el cálculo de compensaciones.
                                        </div>
                                    </div>
                                </div>
                                <div class="chart-body">
                                    <canvas id="chart-advisor-ranking"></canvas>
                                </div>
                            </div>

                            <!-- Evolución Temporal -->
                            <div class="chart-container span-two-cols glass-panel">
                                <div class="chart-header" style="position: relative;">
                                    <h3>Evolución de Ventas por Asesor</h3>
                                    <div class="chart-options" style="display: flex; align-items: center; gap: 8px;">
                                        <span class="badge" t-esc="metricsData.charts.sales_trend.timeframe">Diario</span>
                                        <div class="info-tooltip-wrapper tooltip-right">
                                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="info-icon">
                                                <circle cx="12" cy="12" r="10"></circle>
                                                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                                                <line x1="12" y1="17" x2="12.01" y2="17"></line>
                                            </svg>
                                            <div class="info-tooltip-text">
                                                Ventas netas diarias de los 6 mejores asesores del período. Permite comparar consistencia y detectar picos.
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="chart-body">
                                    <canvas id="chart-advisor-trend"></canvas>
                                </div>
                            </div>

                            <!-- Participación -->
                            <div class="chart-container glass-panel">
                                <div class="chart-header" style="position: relative;">
                                    <h3>Participación por Asesor</h3>
                                    <div class="info-tooltip-wrapper tooltip-right">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="info-icon">
                                            <circle cx="12" cy="12" r="10"></circle>
                                            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                                            <line x1="12" y1="17" x2="12.01" y2="17"></line>
                                        </svg>
                                        <div class="info-tooltip-text">
                                            Porcentaje de las ventas netas totales que aporta cada asesor en el período seleccionado.
                                        </div>
                                    </div>
                                </div>
                                <div class="chart-body">
                                    <canvas id="chart-advisor-share"></canvas>
                                </div>
                            </div>

                            <!-- Tabla Detalle -->
                            <div class="chart-container glass-panel">
                                <div class="chart-header" style="position: relative;">
                                    <h3>Detalle por Asesor</h3>
                                    <div class="chart-options" style="display: flex; align-items: center; gap: 8px;">
                                        <button class="btn btn-secondary" t-on-click="exportCSV">
                                            <span>Exportar CSV</span>
                                        </button>
                                    </div>
                                </div>
                                <div class="input-group" style="margin-bottom: 10px;">
                                    <input type="text" placeholder="Buscar asesor..." t-att-value="state.search" t-on-input="onSearchInput"/>
                                </div>
                                <div class="table-responsive">
                                    <table class="data-table">
                                        <thead>
                                            <tr>
                                                <th>Asesor</th>
                                                <th>Ventas Brutas</th>
                                                <th>Devoluciones</th>
                                                <th>Ventas Netas</th>
                                                <th>Órdenes</th>
                                                <th>Ticket Promedio</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <t t-if="filteredTableRows.length === 0">
                                                <tr><td colspan="6" style="text-align:center;">Sin datos para el período seleccionado</td></tr>
                                            </t>
                                            <t t-foreach="filteredTableRows" t-as="row" t-key="row.asesor">
                                                <tr>
                                                    <td t-esc="row.asesor"/>
                                                    <td t-esc="formatCurrency(row.bruto)"/>
                                                    <td t-esc="formatCurrency(row.devoluciones)"/>
                                                    <td t-esc="formatCurrency(row.neto)"/>
                                                    <td t-esc="row.ordenes.toLocaleString()"/>
                                                    <td t-esc="formatCurrency(row.ticket_promedio)"/>
                                                </tr>
                                            </t>
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </section>
                </div>
            </main>
        </div>
    </t>
</templates>
```

- [ ] **Step 4: Client action + menú raíz**

`pos_sales_advisor/views/menu_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_pos_sales_advisor_dashboard" model="ir.actions.client">
        <field name="name">Métricas de Asesores</field>
        <field name="tag">pos_sales_advisor.dashboard</field>
    </record>

    <menuitem id="menu_pos_sales_advisor_dashboard_root"
              name="Métricas de Asesores"
              action="action_pos_sales_advisor_dashboard"
              groups="pos_sales_advisor.group_pos_advisor_metrics"
              web_icon="pos_sales_advisor,static/description/icon.png"
              sequence="51"/>
</odoo>
```

- [ ] **Step 5: Actualizar manifest (data + assets backend)**

En `pos_sales_advisor/__manifest__.py`, `data` queda:
```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/pos_sales_advisor_views.xml",
        "views/pos_order_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
```
y `assets` queda:
```python
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_sales_advisor/static/src/js/payment_screen_patch.js",
            "pos_sales_advisor/static/src/js/ticket_screen_patch.js",
            "pos_sales_advisor/static/src/xml/advisor_button.xml",
        ],
        "web.assets_backend": [
            "pos_sales_advisor/static/src/css/dashboard.css",
            "pos_sales_advisor/static/src/js/dashboard.js",
            "pos_sales_advisor/static/src/xml/dashboard.xml",
        ],
    },
```

- [ ] **Step 6: Validar sintaxis + upgrade**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; m.parse('pos_sales_advisor/static/src/xml/dashboard.xml'); m.parse('pos_sales_advisor/views/menu_views.xml'); print('XML OK')"
python3 -c "import ast; ast.parse(open('pos_sales_advisor/__manifest__.py').read()); print('manifest OK')"
docker exec odoo-odoo-1 odoo -u pos_sales_advisor -d prod --stop-after-init 2>&1 | grep -iE "error|traceback" | head -10
```
Expected: `XML OK`, `manifest OK`, sin `ERROR`.

- [ ] **Step 7: Prueba manual del dashboard**

1. Asignar el grupo "Acceso a Métricas de Asesores de Venta" al usuario admin (Ajustes → Usuarios).
2. Refrescar el navegador → debe aparecer el menú raíz "Métricas de Asesores".
3. Abrir el dashboard: sidebar con presets/filtros, 4 KPIs, ranking, evolución, donut y tabla con los datos de las órdenes de prueba de Task 4.
4. Probar presets de fecha, filtro por asesor, tema claro/oscuro y "Exportar CSV" (debe descargar el archivo con las columnas Asesor;Ventas Brutas;...).

- [ ] **Step 8: Commit**

```bash
git add pos_sales_advisor/
git commit -m "feat(pos_sales_advisor): dashboard OWL de métricas por asesor con lenguaje de diseño del Metrics Hub"
```

---

### Task 7: Icono del módulo + verificación integral

**Files:**
- Create: `pos_sales_advisor/static/description/icon.png`

**Interfaces:**
- Consumes: template SVG `~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg`; el menú de Task 6 referencia `pos_sales_advisor,static/description/icon.png`.

- [ ] **Step 1: Generar el icono Cyber-Glassmorphic 3D**

```bash
mkdir -p /home/alexis/Documents/Github/prometeo-odoo-modules/pos_sales_advisor/static/description
cp ~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg /tmp/claude-1000/-home-alexis-Documents-Github/a59faafa-6f2e-4188-986c-4faac22eb853/scratchpad/advisor-icon.svg
```
Editar el SVG copiado (con Read/Edit): reemplazar el contenido del elemento `<text>` (el glyph) por `A`. Mantener los acentos cyan `#22e6ff` y magenta `#ff3df0`.

```bash
cd /tmp/claude-1000/-home-alexis-Documents-Github/a59faafa-6f2e-4188-986c-4faac22eb853/scratchpad
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="/home/alexis/Documents/Github/prometeo-odoo-modules/pos_sales_advisor/static/description/icon.png" \
  "file://$PWD/advisor-icon.svg"
```
Expected: `icon.png` de 512x512 con fondo transparente. NO usar ImageMagick (pierde el glyph y los gradientes). Verificar visualmente con Read.

- [ ] **Step 2: Upgrade final y revisión de log completa**

```bash
docker exec odoo-odoo-1 odoo -u pos_sales_advisor -d prod --stop-after-init 2>&1 | tail -15
```
Expected: `Modules loaded` / registry ok, sin `ERROR` ni `WARNING` del módulo.

- [ ] **Step 3: Checklist integral (manual)**

1. Apps → buscar "POS - Asesores de Venta" → icono visible.
2. Flujo completo: crear asesor → venta en POS con asesor → orden en backend con el campo → dashboard refleja la venta → devolución → dashboard muestra la devolución y el neto baja.
3. Caja con "Requerir asesor" activo bloquea la validación sin asesor.
4. Usuario sin el grupo de métricas no ve el menú "Métricas de Asesores".

- [ ] **Step 4: Commit final**

```bash
git add pos_sales_advisor/
git commit -m "feat(pos_sales_advisor): icono cyber-glassmorphic del módulo"
```
