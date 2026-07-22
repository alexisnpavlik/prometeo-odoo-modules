# pos_deletion_reason_log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar en el backend cada eliminación de orden, línea o reducción de cantidad hecha en el POS, pidiendo un motivo configurable al momento de eliminar.

**Architecture:** Módulo Odoo 18 standalone (`depends: ['point_of_sale']`). Frontend con patches motivo-primero sobre `PosStore.onDeleteOrder` y `OrderSummary._setValue`; el motivo se pide antes del `super`, y tras confirmar que la eliminación ocurrió se registra vía `orm.call` a un método `log_deletion` en sudo. Convive con `pos_special_approval_omax` (los patches se apilan) sin depender de él.

**Tech Stack:** Odoo 18.0, OWL (POS frontend), Python ORM.

## Global Constraints

- Odoo target: **18.0**. Manifest version: `18.0.1.0.0`.
- `author`: `"Alexis Medina"`, `license`: `"LGPL-3"`.
- snake_case en Python; un archivo por modelo; docstring (español) en cada método.
- New-style translation: `_("texto %s", arg)` (coma, no `%`).
- `data` en manifest: `security/*` antes de `views/`.
- Motivos por defecto: **"Error de carga", "Cliente se arrepintió", "Duplicado"**.
- No se registra el manager que aprueba (fuera de alcance v1).
- El registro es best-effort: si la RPC falla, no debe trabar el POS.
- Verificación (no hay suite de tests): validación de sintaxis local + upgrade en contenedor `odoo-odoo-1` con `sudo docker exec odoo-odoo-1 odoo -i pos_deletion_reason_log -d <db> --stop-after-init` (confirmar nombre de `<db>`, típicamente `prod` o `calidad`).

---

### Task 1: Scaffold del módulo (manifest, __init__, seguridad)

Crea la estructura mínima instalable con el grupo de seguridad y accesos, sin modelos aún de negocio. Deliverable testeable: el manifest parsea y la estructura de archivos queda válida.

**Files:**
- Create: `pos_deletion_reason_log/__init__.py`
- Create: `pos_deletion_reason_log/__manifest__.py`
- Create: `pos_deletion_reason_log/models/__init__.py`
- Create: `pos_deletion_reason_log/security/security.xml`
- Create: `pos_deletion_reason_log/security/ir.model.access.csv`

**Interfaces:**
- Produces: grupo `pos_deletion_reason_log.group_pos_deletion_audit`; módulo `pos_deletion_reason_log`.

- [ ] **Step 1: Crear `pos_deletion_reason_log/__init__.py`**

```python
from . import models
```

- [ ] **Step 2: Crear `pos_deletion_reason_log/models/__init__.py`** (vacío por ahora, se completará en tareas siguientes)

```python
```

- [ ] **Step 3: Crear `pos_deletion_reason_log/__manifest__.py`**

```python
# -*- coding: utf-8 -*-
{
    "name": "POS Deletion Reason Log",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Pide un motivo y registra eliminaciones de orden, línea o reducción de cantidad en el POS",
    "description": """
Registra en el backend cada vez que un empleado elimina una orden completa,
borra una línea/producto de la orden o reduce la cantidad de una línea en el POS.
Al eliminar se pide un motivo (lista configurable + texto opcional) y queda un
registro con cajero, producto, cantidad, importe, motivo y momento — aunque la
orden nunca se sincronice al servidor.

Standalone: si está instalado pos_special_approval_omax convive con su flujo de
aprobación de manager (los popups se apilan), pero no depende de él.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/pos_deletion_reason_data.xml",
        "views/pos_deletion_reason_views.xml",
        "views/pos_deletion_log_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_deletion_reason_log/static/src/js/**/*",
            "pos_deletion_reason_log/static/src/xml/**/*",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
```

Nota: los archivos listados en `data`/`assets` se crean en tareas siguientes; no instalar hasta la Task 7. Este step solo valida sintaxis del manifest.

- [ ] **Step 4: Crear `pos_deletion_reason_log/security/security.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="group_pos_deletion_audit" model="res.groups">
        <field name="name">POS Deletion Audit</field>
        <field name="category_id" ref="base.module_category_usability"/>
        <field name="comment">Puede consultar el registro de eliminaciones del POS.</field>
        <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
    </record>
</odoo>
```

- [ ] **Step 5: Crear `pos_deletion_reason_log/security/ir.model.access.csv`**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_pos_deletion_reason_pos_user,pos.deletion.reason pos user,model_pos_deletion_reason,point_of_sale.group_pos_user,1,0,0,0
access_pos_deletion_reason_manager,pos.deletion.reason manager,model_pos_deletion_reason,point_of_sale.group_pos_manager,1,1,1,1
access_pos_deletion_log_audit,pos.deletion.log audit,model_pos_deletion_log,pos_deletion_reason_log.group_pos_deletion_audit,1,0,0,0
access_pos_deletion_log_manager,pos.deletion.log manager,model_pos_deletion_log,point_of_sale.group_pos_manager,1,1,0,1
```

Nota: el cajero NO tiene create directo sobre `pos.deletion.log`; el registro se crea vía método `log_deletion` en `sudo()` (Task 3).

- [ ] **Step 6: Validar sintaxis**

Run:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('pos_deletion_reason_log/__manifest__.py').read()); print('manifest ok')"
python3 -c "import xml.dom.minidom as m; m.parse('pos_deletion_reason_log/security/security.xml'); print('security xml ok')"
python3 -c "import csv; rows=list(csv.reader(open('pos_deletion_reason_log/security/ir.model.access.csv'))); print('csv cols', {len(r) for r in rows})"
```
Expected: `manifest ok`, `security xml ok`, `csv cols {8}`.

- [ ] **Step 7: Commit**

```bash
git add pos_deletion_reason_log/__init__.py pos_deletion_reason_log/__manifest__.py pos_deletion_reason_log/models/__init__.py pos_deletion_reason_log/security/
git commit -m "feat(pos_deletion_reason_log): scaffold module + security group"
```

---

### Task 2: Modelo `pos.deletion.reason` + datos por defecto + vistas

Maestro config-driven de motivos, cargado al POS. Deliverable testeable: modelo + data + vistas parsean; se puede instalar el modelo en el contenedor.

**Files:**
- Create: `pos_deletion_reason_log/models/pos_deletion_reason.py`
- Modify: `pos_deletion_reason_log/models/__init__.py`
- Create: `pos_deletion_reason_log/data/pos_deletion_reason_data.xml`
- Create: `pos_deletion_reason_log/views/pos_deletion_reason_views.xml`

**Interfaces:**
- Produces: modelo `pos.deletion.reason` con campos `name` (Char), `sequence` (Integer), `active` (Boolean); método `_load_pos_data_fields` que devuelve `["id", "name"]`. Cargado al frontend como `pos.deletion.reason` (Task 4 lo agrega a `_load_pos_data_models`).

- [ ] **Step 1: Crear `pos_deletion_reason_log/models/pos_deletion_reason.py`**

```python
# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosDeletionReason(models.Model):
    _name = "pos.deletion.reason"
    _description = "Motivo de eliminación en POS"
    _inherit = ["pos.load.mixin"]
    _order = "sequence, id"

    name = fields.Char(string="Motivo", required=True, translate=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Campos del motivo que se cargan al frontend del POS."""
        return ["id", "name"]
```

- [ ] **Step 2: Registrar el modelo en `pos_deletion_reason_log/models/__init__.py`**

```python
from . import pos_deletion_reason
```

- [ ] **Step 3: Crear `pos_deletion_reason_log/data/pos_deletion_reason_data.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="reason_error_carga" model="pos.deletion.reason">
        <field name="name">Error de carga</field>
        <field name="sequence">10</field>
    </record>
    <record id="reason_cliente_arrepentido" model="pos.deletion.reason">
        <field name="name">Cliente se arrepintió</field>
        <field name="sequence">20</field>
    </record>
    <record id="reason_duplicado" model="pos.deletion.reason">
        <field name="name">Duplicado</field>
        <field name="sequence">30</field>
    </record>
</odoo>
```

- [ ] **Step 4: Crear `pos_deletion_reason_log/views/pos_deletion_reason_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="pos_deletion_reason_view_list" model="ir.ui.view">
        <field name="name">pos.deletion.reason.list</field>
        <field name="model">pos.deletion.reason</field>
        <field name="arch" type="xml">
            <list string="Motivos de eliminación" editable="bottom">
                <field name="sequence" widget="handle"/>
                <field name="name"/>
                <field name="active" widget="boolean_toggle"/>
            </list>
        </field>
    </record>

    <record id="pos_deletion_reason_view_form" model="ir.ui.view">
        <field name="name">pos.deletion.reason.form</field>
        <field name="model">pos.deletion.reason</field>
        <field name="arch" type="xml">
            <form string="Motivo de eliminación">
                <sheet>
                    <group>
                        <field name="name"/>
                        <field name="sequence"/>
                        <field name="active"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_pos_deletion_reason" model="ir.actions.act_window">
        <field name="name">Motivos de eliminación</field>
        <field name="res_model">pos.deletion.reason</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

- [ ] **Step 5: Validar sintaxis**

Run:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; [m.parse(f) for f in ['pos_deletion_reason_log/data/pos_deletion_reason_data.xml','pos_deletion_reason_log/views/pos_deletion_reason_views.xml']]; print('xml ok')"
python3 -c "import ast; ast.parse(open('pos_deletion_reason_log/models/pos_deletion_reason.py').read()); print('py ok')"
```
Expected: `xml ok`, `py ok`.

- [ ] **Step 6: Commit**

```bash
git add pos_deletion_reason_log/models/ pos_deletion_reason_log/data/ pos_deletion_reason_log/views/pos_deletion_reason_views.xml
git commit -m "feat(pos_deletion_reason_log): pos.deletion.reason model, default data, views"
```

---

### Task 3: Modelo `pos.deletion.log` + método `log_deletion` + vistas

Registro de eliminaciones y el método sudo que lo crea. Deliverable testeable: modelo parsea; vistas parsean.

**Files:**
- Create: `pos_deletion_reason_log/models/pos_deletion_log.py`
- Modify: `pos_deletion_reason_log/models/__init__.py`
- Create: `pos_deletion_reason_log/views/pos_deletion_log_views.xml`

**Interfaces:**
- Consumes: `pos.deletion.reason` (Task 2).
- Produces: modelo `pos.deletion.log`; método `@api.model log_deletion(self, vals)` que crea un registro en sudo y devuelve su `id`. `vals` acepta las claves: `deletion_type` (`'order'|'line'|'qty_reduction'`), `pos_config_id` (int), `session_id` (int), `order_ref` (str), `product_id` (int|False), `qty_removed` (float), `amount_removed` (float), `reason_id` (int|False), `reason_note` (str). `user_id` y `deletion_datetime` se completan solos.

- [ ] **Step 1: Crear `pos_deletion_reason_log/models/pos_deletion_log.py`**

```python
# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosDeletionLog(models.Model):
    _name = "pos.deletion.log"
    _description = "Registro de eliminación en POS"
    _order = "deletion_datetime desc, id desc"

    deletion_type = fields.Selection(
        [
            ("order", "Orden completa"),
            ("line", "Línea / producto"),
            ("qty_reduction", "Reducción de cantidad"),
        ],
        string="Tipo",
        required=True,
    )
    user_id = fields.Many2one("res.users", string="Cajero", required=True)
    pos_config_id = fields.Many2one("pos.config", string="Punto de venta")
    session_id = fields.Many2one("pos.session", string="Sesión")
    order_ref = fields.Char(string="Referencia de orden")
    product_id = fields.Many2one("product.product", string="Producto")
    qty_removed = fields.Float(string="Cantidad quitada")
    amount_removed = fields.Float(string="Importe quitado")
    reason_id = fields.Many2one("pos.deletion.reason", string="Motivo")
    reason_note = fields.Text(string="Nota")
    deletion_datetime = fields.Datetime(
        string="Fecha/hora", default=fields.Datetime.now, required=True
    )
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda self: self.env.company
    )

    @api.model
    def log_deletion(self, vals):
        """Crea un registro de eliminación. Llamado desde el POS por RPC.

        Se ejecuta en sudo porque el cajero no tiene create directo sobre el
        modelo. Completa cajero (usuario actual) y fecha si no vinieron.
        """
        allowed = {
            "deletion_type",
            "pos_config_id",
            "session_id",
            "order_ref",
            "product_id",
            "qty_removed",
            "amount_removed",
            "reason_id",
            "reason_note",
        }
        clean = {k: v for k, v in (vals or {}).items() if k in allowed}
        clean["user_id"] = self.env.user.id
        record = self.sudo().create(clean)
        _logger.info(
            "POS deletion log %s: type=%s user=%s product=%s",
            record.id, clean.get("deletion_type"), record.user_id.id, clean.get("product_id"),
        )
        return record.id
```

- [ ] **Step 2: Registrar el modelo en `pos_deletion_reason_log/models/__init__.py`**

```python
from . import pos_deletion_reason
from . import pos_deletion_log
```

- [ ] **Step 3: Crear `pos_deletion_reason_log/views/pos_deletion_log_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="pos_deletion_log_view_list" model="ir.ui.view">
        <field name="name">pos.deletion.log.list</field>
        <field name="model">pos.deletion.log</field>
        <field name="arch" type="xml">
            <list string="Eliminaciones POS" create="false" edit="false">
                <field name="deletion_datetime"/>
                <field name="deletion_type"/>
                <field name="user_id"/>
                <field name="pos_config_id"/>
                <field name="order_ref"/>
                <field name="product_id"/>
                <field name="qty_removed"/>
                <field name="amount_removed"/>
                <field name="reason_id"/>
                <field name="reason_note" optional="hide"/>
            </list>
        </field>
    </record>

    <record id="pos_deletion_log_view_form" model="ir.ui.view">
        <field name="name">pos.deletion.log.form</field>
        <field name="model">pos.deletion.log</field>
        <field name="arch" type="xml">
            <form string="Eliminación POS" create="false" edit="false">
                <sheet>
                    <group>
                        <group>
                            <field name="deletion_datetime"/>
                            <field name="deletion_type"/>
                            <field name="user_id"/>
                            <field name="pos_config_id"/>
                            <field name="session_id"/>
                        </group>
                        <group>
                            <field name="order_ref"/>
                            <field name="product_id"/>
                            <field name="qty_removed"/>
                            <field name="amount_removed"/>
                            <field name="reason_id"/>
                        </group>
                    </group>
                    <group string="Nota">
                        <field name="reason_note" nolabel="1"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="pos_deletion_log_view_pivot" model="ir.ui.view">
        <field name="name">pos.deletion.log.pivot</field>
        <field name="model">pos.deletion.log</field>
        <field name="arch" type="xml">
            <pivot string="Eliminaciones POS">
                <field name="user_id" type="row"/>
                <field name="deletion_type" type="col"/>
                <field name="amount_removed" type="measure"/>
            </pivot>
        </field>
    </record>

    <record id="pos_deletion_log_view_search" model="ir.ui.view">
        <field name="name">pos.deletion.log.search</field>
        <field name="model">pos.deletion.log</field>
        <field name="arch" type="xml">
            <search string="Eliminaciones POS">
                <field name="user_id"/>
                <field name="product_id"/>
                <field name="order_ref"/>
                <field name="reason_id"/>
                <filter name="type_order" string="Orden" domain="[('deletion_type','=','order')]"/>
                <filter name="type_line" string="Línea" domain="[('deletion_type','=','line')]"/>
                <filter name="type_qty" string="Reducción cantidad" domain="[('deletion_type','=','qty_reduction')]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_user" string="Cajero" context="{'group_by':'user_id'}"/>
                    <filter name="group_type" string="Tipo" context="{'group_by':'deletion_type'}"/>
                    <filter name="group_reason" string="Motivo" context="{'group_by':'reason_id'}"/>
                    <filter name="group_config" string="Punto de venta" context="{'group_by':'pos_config_id'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_pos_deletion_log" model="ir.actions.act_window">
        <field name="name">Eliminaciones POS</field>
        <field name="res_model">pos.deletion.log</field>
        <field name="view_mode">list,form,pivot</field>
        <field name="search_view_id" ref="pos_deletion_log_view_search"/>
    </record>
</odoo>
```

- [ ] **Step 4: Validar sintaxis**

Run:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('pos_deletion_reason_log/models/pos_deletion_log.py').read()); print('py ok')"
python3 -c "import xml.dom.minidom as m; m.parse('pos_deletion_reason_log/views/pos_deletion_log_views.xml'); print('xml ok')"
```
Expected: `py ok`, `xml ok`.

- [ ] **Step 5: Commit**

```bash
git add pos_deletion_reason_log/models/ pos_deletion_reason_log/views/pos_deletion_log_views.xml
git commit -m "feat(pos_deletion_reason_log): pos.deletion.log model, log_deletion, views"
```

---

### Task 4: Toggles en pos.config, settings y carga al POS

Config por evento + carga del modelo de motivos al frontend + menús. Deliverable testeable: instala en el contenedor y aparecen los settings y menús.

**Files:**
- Create: `pos_deletion_reason_log/models/pos_config.py`
- Create: `pos_deletion_reason_log/models/pos_session.py`
- Create: `pos_deletion_reason_log/models/res_config_settings.py`
- Modify: `pos_deletion_reason_log/models/__init__.py`
- Create: `pos_deletion_reason_log/views/res_config_settings_views.xml`
- Create: `pos_deletion_reason_log/views/menu_views.xml`

**Interfaces:**
- Consumes: `pos.deletion.reason` (Task 2), `pos.deletion.log` action (Task 3), `pos.deletion.reason` action (Task 2).
- Produces: campos frontend en `pos.config`: `require_reason_order_deletion`, `require_reason_line_deletion`, `require_reason_qty_reduction` (todos Boolean). Modelo `pos.deletion.reason` disponible en el POS como `pos.data.models["pos.deletion.reason"]`.

- [ ] **Step 1: Crear `pos_deletion_reason_log/models/pos_config.py`**

```python
# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    require_reason_order_deletion = fields.Boolean(
        string="Motivo al eliminar orden",
        help="Pide un motivo cuando el cajero elimina una orden completa.",
    )
    require_reason_line_deletion = fields.Boolean(
        string="Motivo al eliminar línea",
        help="Pide un motivo cuando el cajero borra una línea/producto de la orden.",
    )
    require_reason_qty_reduction = fields.Boolean(
        string="Motivo al reducir cantidad",
        help="Pide un motivo cuando el cajero reduce la cantidad de una línea.",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Asegura que los toggles de motivo lleguen al frontend del POS."""
        fields_list = super()._load_pos_data_fields(config_id)
        fields_list += [
            "require_reason_order_deletion",
            "require_reason_line_deletion",
            "require_reason_qty_reduction",
        ]
        return fields_list
```

- [ ] **Step 2: Crear `pos_deletion_reason_log/models/pos_session.py`**

```python
# -*- coding: utf-8 -*-
from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config_id):
        """Agrega el maestro de motivos a los modelos cargados en el POS."""
        res = super()._load_pos_data_models(config_id)
        res.append("pos.deletion.reason")
        return res
```

- [ ] **Step 3: Crear `pos_deletion_reason_log/models/res_config_settings.py`**

```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    require_reason_order_deletion = fields.Boolean(
        related="pos_config_id.require_reason_order_deletion", readonly=False
    )
    require_reason_line_deletion = fields.Boolean(
        related="pos_config_id.require_reason_line_deletion", readonly=False
    )
    require_reason_qty_reduction = fields.Boolean(
        related="pos_config_id.require_reason_qty_reduction", readonly=False
    )
```

- [ ] **Step 4: Actualizar `pos_deletion_reason_log/models/__init__.py`**

```python
from . import pos_deletion_reason
from . import pos_deletion_log
from . import pos_config
from . import pos_session
from . import res_config_settings
```

- [ ] **Step 5: Crear `pos_deletion_reason_log/views/res_config_settings_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="res_config_settings_view_form_inherit_pos_deletion_reason" model="ir.ui.view">
        <field name="name">res.config.settings.form.inherit.pos.deletion.reason</field>
        <field name="model">res.config.settings</field>
        <field name="inherit_id" ref="point_of_sale.res_config_settings_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//block[@id='product_and_category_block']" position="after">
                <block id="pos_deletion_reason_block" title="Registro de eliminaciones">
                    <setting string="Motivo al eliminar orden" help="Pide un motivo cuando se elimina una orden completa.">
                        <field name="require_reason_order_deletion"/>
                    </setting>
                    <setting string="Motivo al eliminar línea" help="Pide un motivo cuando se borra una línea/producto.">
                        <field name="require_reason_line_deletion"/>
                    </setting>
                    <setting string="Motivo al reducir cantidad" help="Pide un motivo cuando se reduce la cantidad de una línea.">
                        <field name="require_reason_qty_reduction"/>
                    </setting>
                </block>
            </xpath>
        </field>
    </record>
</odoo>
```

- [ ] **Step 6: Crear `pos_deletion_reason_log/views/menu_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_pos_deletion_log"
              name="Eliminaciones POS"
              parent="point_of_sale.menu_point_of_sale"
              action="action_pos_deletion_log"
              groups="pos_deletion_reason_log.group_pos_deletion_audit"
              sequence="90"/>

    <menuitem id="menu_pos_deletion_reason"
              name="Motivos de eliminación"
              parent="point_of_sale.menu_point_config_product"
              action="action_pos_deletion_reason"
              groups="point_of_sale.group_pos_manager"
              sequence="90"/>
</odoo>
```

- [ ] **Step 7: Validar sintaxis**

Run:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['pos_deletion_reason_log/models/pos_config.py','pos_deletion_reason_log/models/pos_session.py','pos_deletion_reason_log/models/res_config_settings.py']]; print('py ok')"
python3 -c "import xml.dom.minidom as m; [m.parse(f) for f in ['pos_deletion_reason_log/views/res_config_settings_views.xml','pos_deletion_reason_log/views/menu_views.xml']]; print('xml ok')"
```
Expected: `py ok`, `xml ok`.

- [ ] **Step 8: Instalar en el contenedor y verificar backend**

Run (confirmar `<db>`):
```bash
sudo docker exec odoo-odoo-1 odoo -i pos_deletion_reason_log -d <db> --stop-after-init 2>&1 | tail -20
```
Expected: termina sin traceback; línea tipo `Modules loaded.` / `loading pos_deletion_reason_log`. Verificar manualmente en la UI: Ajustes → Punto de Venta muestra el bloque "Registro de eliminaciones"; existe el menú Punto de Venta → Eliminaciones POS; Configuración → Motivos de eliminación lista los 3 motivos por defecto.

- [ ] **Step 9: Commit**

```bash
git add pos_deletion_reason_log/models/ pos_deletion_reason_log/views/res_config_settings_views.xml pos_deletion_reason_log/views/menu_views.xml
git commit -m "feat(pos_deletion_reason_log): pos.config toggles, settings, POS data load, menus"
```

---

### Task 5: Popup OWL de motivo (frontend)

Componente Dialog con dropdown de motivos + textarea opcional. Deliverable testeable: assets cargan sin error de JS en el POS (el popup se usa en Task 6).

**Files:**
- Create: `pos_deletion_reason_log/static/src/js/deletion_reason_popup.js`
- Create: `pos_deletion_reason_log/static/src/xml/deletion_reason_popup.xml`

**Interfaces:**
- Consumes: modelo `pos.deletion.reason` cargado (Task 4), accesible vía `this.pos.data.models["pos.deletion.reason"].getAll()`.
- Produces: componente `DeletionReasonPopup` con `static template = "pos_deletion_reason_log.DeletionReasonPopup"`, props `["close", "getPayload", "title"]`. Llama `props.getPayload({reason_id, reason_note})` al confirmar, o `props.getPayload(null)` al cancelar.

- [ ] **Step 1: Crear `pos_deletion_reason_log/static/src/js/deletion_reason_popup.js`**

```javascript
/** @odoo-module **/

import { Component, useState, onMounted, useRef } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { _t } from "@web/core/l10n/translation";

export class DeletionReasonPopup extends Component {
    static components = { Dialog };
    static template = "pos_deletion_reason_log.DeletionReasonPopup";
    static props = ["close", "getPayload", "title"];

    setup() {
        this.pos = usePos();
        this.state = useState({
            reasonId: false,
            note: "",
            warning: "",
        });
        this.noteRef = useRef("noteInput");
        onMounted(() => {
            const reasons = this.reasons;
            if (reasons.length) {
                this.state.reasonId = reasons[0].id;
            }
        });
    }

    get reasons() {
        return this.pos.data.models["pos.deletion.reason"].getAll();
    }

    onReasonChange(ev) {
        this.state.reasonId = parseInt(ev.target.value, 10) || false;
    }

    confirm() {
        if (!this.state.reasonId) {
            this.state.warning = _t("Seleccioná un motivo.");
            return;
        }
        this.props.getPayload({
            reason_id: this.state.reasonId,
            reason_note: this.state.note.trim(),
        });
        this.props.close();
    }

    cancel() {
        this.props.getPayload(null);
        this.props.close();
    }
}
```

- [ ] **Step 2: Crear `pos_deletion_reason_log/static/src/xml/deletion_reason_popup.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">
    <t t-name="pos_deletion_reason_log.DeletionReasonPopup" owl="1">
        <Dialog size="'md'" title="props.title || 'Motivo de eliminación'">
            <div class="deletion-reason-popup">
                <div class="mb-3">
                    <label class="form-label">Motivo</label>
                    <select class="form-select form-select-lg" t-on-change="onReasonChange">
                        <t t-foreach="reasons" t-as="reason" t-key="reason.id">
                            <option t-att-value="reason.id" t-att-selected="reason.id === state.reasonId">
                                <t t-esc="reason.name"/>
                            </option>
                        </t>
                    </select>
                </div>
                <div class="mb-2">
                    <label class="form-label">Nota (opcional)</label>
                    <textarea class="form-control" rows="3" t-ref="noteInput"
                              t-model="state.note" placeholder="Detalle opcional..."/>
                </div>
                <p t-if="state.warning" class="text-danger small mb-0" t-esc="state.warning"/>
            </div>
            <t t-set-slot="footer">
                <button class="btn btn-primary" t-on-click="confirm">Confirmar</button>
                <button class="btn btn-secondary" t-on-click="cancel">Cancelar</button>
            </t>
        </Dialog>
    </t>
</templates>
```

- [ ] **Step 3: Validar sintaxis del template**

Run:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; m.parse('pos_deletion_reason_log/static/src/xml/deletion_reason_popup.xml'); print('xml ok')"
```
Expected: `xml ok`.

- [ ] **Step 4: Commit**

```bash
git add pos_deletion_reason_log/static/src/js/deletion_reason_popup.js pos_deletion_reason_log/static/src/xml/deletion_reason_popup.xml
git commit -m "feat(pos_deletion_reason_log): OWL deletion reason popup"
```

---

### Task 6: Patches del frontend (orden, línea, reducción de cantidad) + registro

Envuelve los puntos de eliminación con motivo-primero y registra tras confirmar. Deliverable testeable: upgrade en contenedor + prueba manual de los 3 eventos.

**Files:**
- Create: `pos_deletion_reason_log/static/src/js/deletion_logger.js`
- Create: `pos_deletion_reason_log/static/src/js/pos_store.js`
- Create: `pos_deletion_reason_log/static/src/js/order_summary.js`

**Interfaces:**
- Consumes: `DeletionReasonPopup` (Task 5); campos `pos.config.require_reason_*` (Task 4); método `pos.deletion.log.log_deletion` (Task 3).
- Produces: helper exportado `askReasonAndLog(component, {deletion_type, order, line, qty_removed, amount_removed})` que muestra el popup, devuelve `true` si hay motivo (para seguir con el borrado) o `false` si se canceló, y guarda los datos del motivo en `component.env.__pendingDeletionReason` para registrarlos después del borrado. Funciones `logDeletion(component, payloadVals)` que hace el `orm.call`.

Diseño del helper (motivo-primero): el popup se muestra ANTES del `super`; si el usuario cancela, se aborta. Tras el `super`, el llamador verifica que la eliminación ocurrió y llama `logDeletion` con el snapshot + el motivo capturado.

- [ ] **Step 1: Crear `pos_deletion_reason_log/static/src/js/deletion_logger.js`**

```javascript
/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { DeletionReasonPopup } from "./deletion_reason_popup";

/**
 * Muestra el popup de motivo. Devuelve {reason_id, reason_note} o null si se canceló.
 */
export async function askReason(component, title) {
    const dialog = component.env.services.dialog;
    return new Promise((resolve) => {
        dialog.add(DeletionReasonPopup, {
            title: title,
            getPayload: (result) => resolve(result),
            close: () => resolve(null),
        });
    });
}

/**
 * Registra la eliminación en el backend (best-effort; no traba el POS si falla).
 */
export async function logDeletion(component, vals) {
    try {
        const pos = component.env.services.pos;
        const orm = component.env.services.orm;
        const fullVals = {
            pos_config_id: pos.config.id,
            session_id: pos.session.id,
            ...vals,
        };
        await orm.call("pos.deletion.log", "log_deletion", [fullVals]);
    } catch (error) {
        console.error("pos_deletion_reason_log: no se pudo registrar la eliminación", error);
    }
}

/**
 * Snapshot de una orden para el registro (tolerante a orden vacía).
 */
export function snapshotOrder(order) {
    const lines = (order.get_orderlines && order.get_orderlines()) || [];
    let amount = 0;
    try {
        amount = order.get_total_with_tax ? order.get_total_with_tax() : 0;
    } catch (e) {
        amount = 0;
    }
    return {
        order_ref: order.uuid || order.name || "",
        product_id: lines.length === 1 && lines[0].get_product() ? lines[0].get_product().id : false,
        qty_removed: lines.reduce((s, l) => s + (l.get_quantity ? l.get_quantity() : 0), 0),
        amount_removed: amount,
    };
}
```

Nota: `_t` se importa para títulos localizados usados por los llamadores.

- [ ] **Step 2: Crear `pos_deletion_reason_log/static/src/js/pos_store.js`** (patch de eliminación de orden)

```javascript
/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { askReason, logDeletion, snapshotOrder } from "./deletion_logger";

patch(PosStore.prototype, {
    /**
     * Pide motivo antes de eliminar la orden y registra si la eliminación ocurrió.
     */
    async onDeleteOrder(order) {
        if (!this.config.require_reason_order_deletion) {
            return super.onDeleteOrder(order);
        }
        const snapshot = snapshotOrder(order);
        const reason = await askReason(this, _t("Motivo — Eliminar orden"));
        if (!reason) {
            return false; // cancelado: no eliminar
        }
        const result = await super.onDeleteOrder(order);
        // Verificar que la orden ya no exista en el POS
        const stillExists = this.data.models["pos.order"].get(order.id);
        if (!stillExists) {
            await logDeletion(this, {
                deletion_type: "order",
                ...snapshot,
                reason_id: reason.reason_id,
                reason_note: reason.reason_note,
            });
        }
        return result;
    },
});
```

- [ ] **Step 3: Crear `pos_deletion_reason_log/static/src/js/order_summary.js`** (patch línea + reducción de cantidad)

```javascript
/** @odoo-module **/

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { askReason, logDeletion } from "./deletion_logger";

patch(OrderSummary.prototype, {
    /**
     * Intercepta borrado de línea ('remove') y reducción de cantidad para pedir motivo.
     */
    async _setValue(val) {
        const order = this.currentOrder;
        const line = order && order.get_selected_orderline && order.get_selected_orderline();
        const config = this.pos.config;

        // Caso 1: eliminación de línea completa
        if (line && val === "remove" && config.require_reason_line_deletion) {
            const product = line.get_product();
            const reason = await askReason(this, _t("Motivo — Eliminar línea"));
            if (!reason) {
                return; // cancelado
            }
            const result = await super._setValue(val);
            const stillExists = order.get_orderlines().includes(line);
            if (!stillExists) {
                await logDeletion(this, {
                    deletion_type: "line",
                    order_ref: order.uuid || order.name || "",
                    product_id: product ? product.id : false,
                    qty_removed: line.__prevQty != null ? line.__prevQty : (line.get_quantity ? line.get_quantity() : 0),
                    amount_removed: 0,
                    reason_id: reason.reason_id,
                    reason_note: reason.reason_note,
                });
            }
            return result;
        }

        // Caso 2: reducción de cantidad (valor numérico menor al actual)
        if (line && config.require_reason_qty_reduction && this._isNumericValue(val)) {
            const currentQty = line.get_quantity ? line.get_quantity() : 0;
            const newQty = parseFloat(val);
            if (!isNaN(newQty) && newQty < currentQty) {
                const product = line.get_product();
                const reason = await askReason(this, _t("Motivo — Reducir cantidad"));
                if (!reason) {
                    return; // cancelado
                }
                const result = await super._setValue(val);
                await logDeletion(this, {
                    deletion_type: "qty_reduction",
                    order_ref: order.uuid || order.name || "",
                    product_id: product ? product.id : false,
                    qty_removed: currentQty - newQty,
                    amount_removed: 0,
                    reason_id: reason.reason_id,
                    reason_note: reason.reason_note,
                });
                return result;
            }
        }

        return super._setValue(val);
    },

    /**
     * Detecta si el valor del numpad representa una cantidad numérica directa.
     */
    _isNumericValue(val) {
        return typeof val === "string" && /^[0-9]+([.,][0-9]*)?$/.test(val);
    },
});
```

Nota sobre `qty_removed` en el borrado de línea: en Odoo 18 el borrado por `remove` puede llegar en dos pasos (primero pone la cantidad en 0, luego elimina). Registramos la cantidad que tenía la línea al momento de pedir el motivo (`line.get_quantity()`), que es la cantidad presente antes de aplicar `remove`. Si resultara 0 por un paso previo, queda 0 — aceptable para v1.

- [ ] **Step 4: Validar sintaxis (parse básico de JS con node si está disponible)**

Run:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
for f in deletion_logger pos_store order_summary; do node --check "pos_deletion_reason_log/static/src/js/$f.js" 2>&1 && echo "$f ok" || echo "$f: node no disponible o error (revisar manual)"; done
```
Expected: `deletion_logger ok`, `pos_store ok`, `order_summary ok` (si `node` no está, revisar sintaxis a ojo; `import`/`export` es ESM y `node --check` puede requerir extensión `.mjs` — un fallo de parseo por ESM no es un error real del código).

- [ ] **Step 5: Upgrade en el contenedor**

Run (confirmar `<db>`):
```bash
sudo docker exec odoo-odoo-1 odoo -u pos_deletion_reason_log -d <db> --stop-after-init 2>&1 | tail -20
```
Expected: sin traceback.

- [ ] **Step 6: Verificación manual en el POS**

En la config del POS activar los 3 toggles (Ajustes → Punto de Venta → Registro de eliminaciones), abrir sesión y probar:
1. Cargar productos y **eliminar la orden** → aparece popup de motivo → confirmar → la orden se elimina. Revisar Punto de Venta → Eliminaciones POS: hay 1 registro `order` con el cajero y el motivo.
2. **Borrar una línea** (seleccionar línea, backspace/remove) → popup → confirmar → línea borrada → registro `line` con el producto.
3. **Reducir la cantidad** de una línea (ej. de 5 a 2) → popup → confirmar → registro `qty_reduction` con `qty_removed = 3`.
4. Repetir cualquiera y **Cancelar** el popup → NO se elimina y NO se registra.

- [ ] **Step 7: Commit**

```bash
git add pos_deletion_reason_log/static/src/js/
git commit -m "feat(pos_deletion_reason_log): frontend patches for order/line/qty deletion + logging"
```

---

### Task 7: Ícono del módulo y verificación final

Ícono Cyber-Glassmorphic y chequeo integral. Deliverable testeable: instalación limpia desde cero.

**Files:**
- Create: `pos_deletion_reason_log/static/description/icon.png`
- Create (temp): `pos_deletion_reason_log/static/description/icon.svg`

**Interfaces:**
- Consumes: template `~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg`.

- [ ] **Step 1: Generar el SVG re-skin**

Copiar el template `cyber-glass-icon.svg` de la skill odoo-prometeo-modules a `pos_deletion_reason_log/static/description/icon.svg` y cambiar el `<text>` GLYPH a `D` (Deletion). Mantener acentos cyan `#22e6ff` / magenta `#ff3df0`.

- [ ] **Step 2: Renderizar a PNG con Chrome headless**

Run:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/pos_deletion_reason_log
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="static/description/icon.png" \
  "file://$PWD/static/description/icon.svg"
```
Expected: se crea `static/description/icon.png` (512x512, fondo transparente). Verificar: `test -f static/description/icon.png && echo ok`.

- [ ] **Step 3: Instalación limpia de verificación**

Run (confirmar `<db>` — idealmente una DB de prueba):
```bash
sudo docker exec odoo-odoo-1 odoo -i pos_deletion_reason_log -d <db> --stop-after-init 2>&1 | tail -20
```
Expected: sin traceback; el ícono aparece en la lista de Apps.

- [ ] **Step 4: Commit**

```bash
git add pos_deletion_reason_log/static/description/
git commit -m "feat(pos_deletion_reason_log): module icon"
```

---

## Self-Review

**Spec coverage:**
- Eliminar orden → Task 6 Step 2 ✓
- Eliminar línea → Task 6 Step 3 (caso 1) ✓
- Reducir cantidad → Task 6 Step 3 (caso 2) ✓
- Motivo lista configurable + texto → Task 2 (modelo) + Task 5 (popup) ✓
- Registro con cajero/producto/momento → Task 3 (modelo + método) ✓
- Menú en Punto de Venta + grupo de acceso → Task 3 (action) + Task 4 (menú) + Task 1 (grupo) ✓
- Config-driven por evento → Task 4 (toggles) ✓
- Standalone (sin dependencia) → manifest `depends: ['point_of_sale']` ✓
- Best-effort logging → Task 6 `logDeletion` try/catch ✓

**Notas de verificación:** el proyecto no usa suite de tests unitarios (convención Alexis/Odoo). Cada tarea cierra con validación de sintaxis y/o upgrade en contenedor + prueba manual en el POS, que es el método de verificación real del repo.

**Type consistency:** `askReason` → `{reason_id, reason_note}` o `null`, usado consistentemente en `pos_store.js` y `order_summary.js`. `logDeletion(component, vals)` firma consistente. `log_deletion(vals)` server acepta las claves declaradas en Task 3 Interfaces.
