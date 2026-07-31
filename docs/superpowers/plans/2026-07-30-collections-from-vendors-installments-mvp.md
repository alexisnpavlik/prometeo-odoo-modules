# Collections from Vendors and Installments — MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el módulo Odoo 18 `collections_from_vendors_installments`, que soporta el circuito completo de venta domiciliaria financiada: entrega de mercadería al vendedor, venta en cuotas puerta a puerta, enrutamiento de la tarjeta a un cobrador y registro de la cobranza hasta saldar.

**Architecture:** Modelos propios con prefijo `cvi.` (`cvi.product.plan`, `cvi.card`, `cvi.installment`, `cvi.payment`, `cvi.allocation`) que llevan la deuda sin generar asientos contables, más ubicaciones de stock nativas de Odoo (una por vendedor) para saber qué mercadería tiene cada vendedor en la calle. El estado de la tarjeta se deriva siempre del residual de sus cuotas; la imputación de cobros es FIFO por vencimiento. La visibilidad por rol se resuelve con `ir.rule` (vendedor ve sus ventas, cobrador su cartera, administrador todo).

**Tech Stack:** Odoo 18.0 Community, Python 3.12, PostgreSQL 18, `dateutil.relativedelta`, framework de tests `odoo.tests.common.TransactionCase`.

## Global Constraints

- Módulo: `collections_from_vendors_installments`, en `/home/alexis/Documents/Github/prometeo-odoo-modules/`.
- Prefijo de modelos: `cvi.` — todos los modelos nuevos lo usan.
- Versión de manifest: `18.0.1.0.0`. Autor `Alexis Medina`, website `alexis.medn@gmail.com`, licencia `LGPL-3`.
- `depends: ["base", "mail", "stock", "product", "web"]`.
- Alcance de este plan: **solo MVP** — HU-01 a HU-06, HU-09 a HU-17, HU-30, HU-31. Las etapas 2 (HU-18 a HU-29) y 3 (HU-07, HU-08, HU-32) se planifican por separado y **no** se implementan acá.
- Decisión del punto abierto 8 del spec: el sistema **solo advierte, nunca bloquea** (aplica a GPS, fotos y clientes problemáticos, todos de etapas posteriores; se deja registrado acá para que los planes siguientes lo respeten).
- Sin operación offline (RNF-02): el MVP requiere conectividad. Se asume backend web de Odoo sobre HTTPS.
- Precios: el vendedor no carga el precio, solo elige una opción. Cada modelo de mueble lleva en su ficha una tabla de planes (cantidad de cuotas + importe de cuota + modalidad mensual o semanal); elegir el plan fija los tres valores y el total sale de cuotas × importe. El importe **incluye el interés**, así que no es división exacta de ningún precio, y el `list_price` del producto no interviene en ningún cálculo. **Solo el administrador** puede vender con valores distintos a los del plan.
- Stock: ubicaciones internas nativas de Odoo, una por vendedor, creadas on-demand. No se crean tipos de operación propios; se usan los del almacén forzando ubicaciones origen/destino.
- Textos de UI y docstrings en español; nombres de campos, modelos y métodos en inglés snake_case.
- Traducciones estilo Odoo 18: `_("texto %s", arg)` con coma, nunca `%`.
- RN-05: precio, cantidad de cuotas e importe de cuota son inmutables una vez confirmada la venta.
- RN-06: los cobros no se borran, solo se anulan dejando registro.
- RN-08: toda operación relevante queda auditada — los modelos principales heredan `mail.thread` **y `cvi.audit.mixin`**.
- **Nunca llamar `message_post` directamente.** Toda entrada de auditoría va por `self._cvi_log(body)` (definido en `models/cvi_audit_mixin.py`). En Odoo 18 `message_post` levanta `UserError` cuando el partner del usuario actuante no tiene email, y los vendedores y cobradores de calle habitualmente no lo tienen: el helper hace el post normal si hay email y cae a `sudo()` con `author_id` explícito si no, preservando la atribución real. Verificado contra la base.
- Base de datos de pruebas: `calidad`. Contenedor Odoo: `odoo-odoo-1` (docker corre sin sudo).
- Todo comando `odoo` dentro del contenedor requiere `--no-http` (el puerto 8069 ya está tomado por el proceso principal).

---

## Estructura de archivos

```
collections_from_vendors_installments/
  __init__.py                          # from . import models, wizards
  __manifest__.py
  README.md                            # circuito operativo y configuración inicial
  models/
    __init__.py
    cvi_product_plan.py                # planes de cuotas de cada modelo de mueble
    cvi_audit_mixin.py                 # _cvi_log: auditoría RN-08 tolerante a usuarios sin email
    cvi_card.py                        # la tarjeta: venta en cuotas + máquina de estados
    cvi_installment.py                 # cuota: vencimiento, monto, residual, estado
    cvi_payment.py                     # cobro registrado por vendedor o cobrador
    cvi_allocation.py                  # imputación pago -> cuota
    product_template.py                # pestaña de planes en la ficha del mueble
    res_company.py                     # parámetros de negocio (HU-31)
    res_users.py                       # ubicación de stock del vendedor
    res_config_settings.py             # UI de los parámetros de negocio
  wizards/
    __init__.py
    cvi_vendor_delivery_wizard.py      # entrega y devolución de mercadería (HU-02, HU-04)
    cvi_route_wizard.py                # enrutamiento en lote (HU-11)
    cvi_reject_wizard.py               # rechazo con motivo (HU-13)
    cvi_transfer_wizard.py             # transferencia entre cobradores (HU-30)
  security/
    security.xml                       # res.groups + ir.rule por rol
    ir.model.access.csv
  data/
    ir_sequence.xml                    # secuencia de tarjetas y de cobros
    stock_location.xml                 # ubicación vista padre "Vendedores"
    ir_cron.xml                        # cron diario de cuotas vencidas
  views/
    cvi_card_views.xml
    cvi_installment_views.xml
    cvi_payment_views.xml
    cvi_wizard_views.xml
    stock_quant_views.xml              # reporte mercadería en poder de vendedores (HU-03)
    product_template_views.xml         # pestaña "Planes de cuotas" en el producto
    res_config_settings_views.xml
    menu_views.xml
  static/description/icon.png
  tests/
    __init__.py
    common.py                          # fixtures compartidos
    test_product_plan.py               # planes de cuotas por producto
    test_card.py                       # precio tomado del plan, día de cobro
    test_installment_schedule.py       # generación del calendario de cuotas
    test_card_confirm.py               # confirmación, comisión, inmutabilidad
    test_payment.py                    # imputación FIFO, parciales, anulación
    test_card_state.py                 # cierre automático, saldo
    test_vendor_stock.py               # entrega, devolución, picking de venta
    test_routing.py                    # enrutar, aceptar, rechazar, lote
    test_transfer.py                   # transferencia entre cobradores
    test_security.py                   # visibilidad por rol
    test_agenda.py                     # agenda de cobro del día
```

**Cómo correr los tests** (todas las tareas usan esta forma):

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -40
```

En la Task 1 (primera instalación) se usa `-i` en lugar de `-u`. Para correr un solo archivo de test:
`--test-tags /collections_from_vendors_installments:TestNombreDeClase`.

---

## Máquina de estados de `cvi.card`

| Estado | Significado | Transición de salida |
|---|---|---|
| `draft` | El vendedor está cargando la venta | `action_confirm()` → `sold`; `action_cancel()` → `cancel` |
| `sold` | Venta confirmada, primera cuota cobrada por el vendedor, sin cobrador responsable | `action_route()` → `routed`; `action_cancel()` → `cancel` |
| `routed` | Enviada a un cobrador, esperando su aceptación | `action_accept()` → `active`; `action_reject()` → `sold` |
| `active` | El cobrador aceptó y es responsable de la cobranza (RN-02) | automática → `done` al saldar |
| `done` | Saldada | — |
| `cancel` | Anulada | — |

`collector_id` es un único campo: en `routed` es el destinatario pendiente, en `active` el responsable. La responsabilidad la define el estado, no el campo.

---

## Task 1: Esqueleto del módulo, grupos de seguridad y parámetros de negocio

Cubre HU-31 (parámetros configurables) y la base de RN-07 (grupos por rol).

**Files:**
- Create: `collections_from_vendors_installments/__init__.py`
- Create: `collections_from_vendors_installments/__manifest__.py`
- Create: `collections_from_vendors_installments/models/__init__.py`
- Create: `collections_from_vendors_installments/models/res_company.py`
- Create: `collections_from_vendors_installments/models/res_config_settings.py`
- Create: `collections_from_vendors_installments/security/security.xml`
- Create: `collections_from_vendors_installments/security/ir.model.access.csv`
- Create: `collections_from_vendors_installments/views/res_config_settings_views.xml`
- Create: `collections_from_vendors_installments/tests/__init__.py`
- Create: `collections_from_vendors_installments/tests/common.py`
- Test: `collections_from_vendors_installments/tests/test_config.py`

**Interfaces:**
- Consumes: nada (primera tarea).
- Produces:
  - Grupos: `collections_from_vendors_installments.group_cvi_vendor`, `.group_cvi_collector`, `.group_cvi_manager`.
  - Campos en `res.company`: `cvi_default_installments` (Integer, default 12), `cvi_overdue_days` (Integer, default 0), `cvi_allowed_frequencies` (Selection `both`/`monthly`/`weekly`, default `both`).
  - Clase de test base `CviCommon(TransactionCase)` en `tests/common.py`, con atributos de clase `cls.company`, `cls.partner`, `cls.product`, `cls.warehouse`, `cls.vendor_user`, `cls.collector_user`.

- [ ] **Step 1: Crear el esqueleto de archivos vacíos e `__init__` del módulo**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
mkdir -p collections_from_vendors_installments/{models,wizards,security,data,views,tests,static/description}
```

`collections_from_vendors_installments/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import models
```

`collections_from_vendors_installments/models/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import res_company
from . import res_config_settings
```

- [ ] **Step 2: Escribir el manifest**

`collections_from_vendors_installments/__manifest__.py`:

```python
# -*- coding: utf-8 -*-
{
    "name": "Cobranza a vendedores y cuotas",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Venta domiciliaria en cuotas: entrega al vendedor, tarjeta, enrutamiento y cobranza",
    "description": """
        Soporta el circuito de venta domiciliaria financiada de una fábrica de muebles.

        El vendedor retira mercadería de fábrica, la vende en cuotas en el domicilio del
        cliente y cobra la primera cuota como comisión. Luego enruta la tarjeta a un
        cobrador, que la acepta y gestiona la cobranza de las cuotas restantes.

        No genera asientos contables ni comprobantes fiscales: usa modelos propios
        (prefijo cvi.). El stock en poder de cada vendedor se lleva con ubicaciones
        internas nativas de Odoo, una por vendedor.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "stock", "product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": True,
}
```

- [ ] **Step 3: Escribir el test que falla**

`collections_from_vendors_installments/tests/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import test_config
```

`collections_from_vendors_installments/tests/common.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CviCommon(TransactionCase):
    """Fixtures compartidos por todos los tests del módulo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        # En DBs compartidas (p.ej. `calidad`) main_company puede estar archivada por
        # datos ajenos al módulo. Si está inactiva, el company_ids de un res.users nuevo
        # no la reconoce como empresa permitida y rompe la creación de usuarios de test.
        # Se reactiva dentro de la transacción; el rollback lo revierte.
        cls.company.sudo().active = True
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.groups_id = [
            (4, cls.env.ref("collections_from_vendors_installments.group_cvi_manager").id)
        ]
        cls.partner = cls.env["res.partner"].create({
            "name": "Cliente CVI Test",
            "vat": "20111111112",
            "company_id": False,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Ropero 3 puertas",
            "type": "consu",
            "is_storable": True,
            # Precio de contado, informativo: el módulo no lo usa para nada. Los planes
            # de cuotas llevan su propio importe, con el interés ya incluido.
            "list_price": 95000.0,
        })
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.vendor_user = cls.env["res.users"].create({
            "name": "Vendedor Test",
            "login": "cvi_vendor_test",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                cls.env.ref("base.group_user").id,
            ])],
        })
        cls.collector_user = cls.env["res.users"].create({
            "name": "Cobrador Test",
            "login": "cvi_collector_test",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                cls.env.ref("base.group_user").id,
            ])],
        })
```

`collections_from_vendors_installments/tests/test_config.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviConfig(CviCommon):

    def test_default_installments_is_twelve(self):
        """La cantidad de cuotas por defecto arranca en 12 (HU-05)."""
        self.assertEqual(self.company.cvi_default_installments, 12)

    def test_overdue_days_defaults_to_zero(self):
        """Sin tolerancia configurada, una cuota vence al día siguiente del vencimiento."""
        self.assertEqual(self.company.cvi_overdue_days, 0)

    def test_allowed_frequencies_defaults_to_both(self):
        """Por defecto se permiten mensual y semanal (HU-06)."""
        self.assertEqual(self.company.cvi_allowed_frequencies, "both")

    def test_settings_writes_through_to_company(self):
        """Cambiar el ajuste en Configuración escribe en la empresa (HU-31)."""
        settings = self.env["res.config.settings"].create({
            "cvi_default_installments": 18,
            "cvi_overdue_days": 5,
            "cvi_allowed_frequencies": "monthly",
        })
        settings.execute()
        self.assertEqual(self.company.cvi_default_installments, 18)
        self.assertEqual(self.company.cvi_overdue_days, 5)
        self.assertEqual(self.company.cvi_allowed_frequencies, "monthly")
```

- [ ] **Step 4: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -i collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -40
```

Esperado: FALLA en la instalación, porque `security/security.xml` todavía no existe y el manifest lo referencia.

- [ ] **Step 5: Escribir los grupos y las reglas de acceso**

`collections_from_vendors_installments/security/security.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="module_category_cvi" model="ir.module.category">
            <field name="name">Venta en cuotas</field>
            <field name="description">Venta domiciliaria financiada y cobranza</field>
            <field name="sequence">20</field>
        </record>

        <record id="group_cvi_vendor" model="res.groups">
            <field name="name">Vendedor</field>
            <field name="category_id" ref="module_category_cvi"/>
            <field name="comment">Retira mercadería, vende en el domicilio, cobra la primera cuota y enruta la tarjeta. Solo ve sus propias ventas.</field>
        </record>

        <record id="group_cvi_collector" model="res.groups">
            <field name="name">Cobrador</field>
            <field name="category_id" ref="module_category_cvi"/>
            <field name="comment">Acepta tarjetas enrutadas y cobra las cuotas. Solo ve su propia cartera.</field>
        </record>

        <record id="group_cvi_manager" model="res.groups">
            <field name="name">Administrador de cobranzas</field>
            <field name="category_id" ref="module_category_cvi"/>
            <field name="comment">Configura el módulo, transfiere carteras y ve toda la operación.</field>
            <field name="implied_ids" eval="[(4, ref('group_cvi_vendor')), (4, ref('group_cvi_collector')), (4, ref('stock.group_stock_user'))]"/>
        </record>
    </data>
</odoo>
```

> Nota para quien implementa: el administrador **sí** puede implicar a vendedor y cobrador. Las reglas de esos grupos son restricciones por dominio (`vendor_id = uid`) y combinan con OR contra la regla del administrador (`[(1,'=',1)]`), que gana. Esto es lo contrario del patrón de `pos_user_readonly`, donde el grupo restringido nunca debe implicar al privilegiado.

`collections_from_vendors_installments/security/ir.model.access.csv`:

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
```

> El archivo arranca solo con el encabezado: todavía no hay modelos propios. Las tasks siguientes le van agregando una fila por (modelo, grupo). Odoo acepta un CSV con solo encabezado.

- [ ] **Step 6: Escribir los parámetros de negocio en `res.company`**

`collections_from_vendors_installments/models/res_company.py`:

```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    cvi_default_installments = fields.Integer(
        string="Cuotas por defecto",
        default=12,
        help="Cantidad de cuotas que se propone al cargar una venta nueva. El vendedor puede cambiarla.",
    )
    cvi_overdue_days = fields.Integer(
        string="Días de tolerancia de mora",
        default=0,
        help="Días de atraso que se toleran antes de marcar una cuota como vencida.",
    )
    cvi_allowed_frequencies = fields.Selection(
        selection=[
            ("both", "Mensual y semanal"),
            ("monthly", "Solo mensual"),
            ("weekly", "Solo semanal"),
        ],
        string="Frecuencias permitidas",
        default="both",
        required=True,
    )
```

- [ ] **Step 7: Escribir el espejo en `res.config.settings`**

`collections_from_vendors_installments/models/res_config_settings.py`:

```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cvi_default_installments = fields.Integer(
        related="company_id.cvi_default_installments",
        readonly=False,
    )
    cvi_overdue_days = fields.Integer(
        related="company_id.cvi_overdue_days",
        readonly=False,
    )
    cvi_allowed_frequencies = fields.Selection(
        related="company_id.cvi_allowed_frequencies",
        readonly=False,
    )
```

- [ ] **Step 8: Escribir la vista de configuración**

`collections_from_vendors_installments/views/res_config_settings_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="res_config_settings_view_form_cvi" model="ir.ui.view">
        <field name="name">res.config.settings.view.form.inherit.cvi</field>
        <field name="model">res.config.settings</field>
        <field name="inherit_id" ref="base.res_config_settings_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//form" position="inside">
                <app data-string="Venta en cuotas" string="Venta en cuotas"
                     name="collections_from_vendors_installments"
                     groups="collections_from_vendors_installments.group_cvi_manager">
                    <block title="Parámetros de venta" name="cvi_sale_block">
                        <setting string="Cuotas por defecto"
                                 help="Cantidad de cuotas propuesta al cargar una venta nueva">
                            <field name="cvi_default_installments"/>
                        </setting>
                        <setting string="Frecuencias permitidas"
                                 help="Qué frecuencias de cobro puede elegir el vendedor">
                            <field name="cvi_allowed_frequencies"/>
                        </setting>
                    </block>
                    <block title="Cobranza" name="cvi_collection_block">
                        <setting string="Días de tolerancia de mora"
                                 help="Días de atraso tolerados antes de marcar una cuota como vencida">
                            <field name="cvi_overdue_days"/>
                        </setting>
                    </block>
                </app>
            </xpath>
        </field>
    </record>
</odoo>
```

- [ ] **Step 9: Instalar y correr los tests**

```bash
docker exec odoo-odoo-1 odoo -d calidad -i collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -40
```

Esperado: `0 failed, 0 error(s)` y los 4 tests de `TestCviConfig` en verde.

- [ ] **Step 10: Commit**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
git checkout -b feat/collections-from-vendors-installments
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): esqueleto, grupos por rol y parámetros de negocio"
```

---

## Task 2: Planes de cuotas por producto

El precio de una venta no se carga a mano: sale del plan de cuotas definido en la ficha
del mueble. Cada producto lleva su propia tabla de planes con los valores exactos.

**Files:**
- Create: `collections_from_vendors_installments/models/cvi_product_plan.py`
- Create: `collections_from_vendors_installments/models/product_template.py`
- Create: `collections_from_vendors_installments/views/product_template_views.xml`
- Modify: `collections_from_vendors_installments/models/__init__.py`
- Modify: `collections_from_vendors_installments/__manifest__.py`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_product_plan.py`

**Interfaces:**
- Consumes: grupos `group_cvi_vendor`, `group_cvi_collector`, `group_cvi_manager` y `CviCommon` (Task 1).
- Produces:
  - Modelo `cvi.product.plan` con `product_tmpl_id` (Many2one `product.template`), `sequence` (Integer), `name` (Char), `installment_count` (Integer), `installment_amount` (Monetary), `frequency` (Selection `monthly`/`weekly`), `amount_total` (Monetary compute store), `active` (Boolean), `company_id`, `currency_id`.
  - Campos en `product.template`: `cvi_plan_ids` (One2many), `cvi_plan_count` (Integer compute).
  - Constante de módulo `FREQUENCY_SELECTION` en `cvi_product_plan.py`, reutilizada por `cvi.card` en la Task 3. El día de la semana **no** vive acá: un plan define la modalidad (mensual o semanal), no el día concreto de cobro, que el vendedor elige en cada venta. Su `WEEKDAY_SELECTION` es local a `cvi_card.py`.

**Modelo de precios** (fijado acá): el plan define **cantidad de cuotas**, **importe de
cuota** y **modalidad** (mensual o semanal); el total es cuotas × importe, calculado,
nunca cargado a mano.

El importe de cuota **incluye el interés** y por eso no es una división exacta de ningún
precio. Un mueble de $100.000 al contado se carga así:

| Plan | Cuotas | Importe | Total | Recargo real |
|---|---|---|---|---|
| 6 cuotas | 6 | 22.000 | 132.000 | 32% |
| 12 cuotas | 12 | 13.500 | 162.000 | 62% |
| 20 semanas | 20 | 7.000 | 140.000 | 40% |

**El `list_price` del producto no interviene en ningún cálculo del módulo.** No se lee,
no se valida contra él, no se deriva nada de él. Cada fila de la tabla es una opción
cerrada que el administrador carga a mano y el vendedor solo elige. No hay coeficientes,
tasas ni fórmulas que mantener.

Las dos modalidades conviven en la misma tabla: un mueble puede tener planes mensuales y
planes semanales a la vez, y elegir el plan es lo que define cuál se aplica.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_product_plan.py`:

```python
# -*- coding: utf-8 -*-
import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviProductPlan(CviCommon):

    def setUp(self):
        super().setUp()
        # Mueble propio de esta clase: `cls.product` del fixture ya trae tres planes
        # cargados, y estos tests cuentan y nombran planes desde cero.
        self.furniture = self.env["product.product"].create({
            "name": "Cómoda 4 cajones",
            "type": "consu",
            "is_storable": True,
            "list_price": 90000.0,
        })

    def _plan(self, **kwargs):
        """Plan de cuotas del mueble de test, sobreescribible."""
        vals = {
            "product_tmpl_id": self.furniture.product_tmpl_id.id,
            "name": "12 cuotas",
            "installment_count": 12,
            "installment_amount": 13500.0,
            "frequency": "monthly",
        }
        vals.update(kwargs)
        return self.env["cvi.product.plan"].create(vals)

    def test_total_is_count_times_amount(self):
        """El total del plan se calcula: cantidad de cuotas por importe de cuota."""
        plan = self._plan(installment_count=12, installment_amount=13500.0)
        self.assertEqual(plan.amount_total, 162000.0)

    def test_total_updates_when_amount_changes(self):
        """Cambiar el importe de cuota recalcula el total del plan."""
        plan = self._plan(installment_count=12, installment_amount=13500.0)
        plan.installment_amount = 15000.0
        self.assertEqual(plan.amount_total, 180000.0)

    def test_weekly_plan_is_supported(self):
        """Un plan puede ser semanal en vez de mensual."""
        plan = self._plan(name="20 semanas", installment_count=20,
                          installment_amount=7000.0, frequency="weekly")
        self.assertEqual(plan.frequency, "weekly")
        self.assertEqual(plan.amount_total, 140000.0)

    def test_both_modalities_coexist_on_the_same_product(self):
        """Un mismo mueble ofrece planes mensuales y semanales a la vez."""
        self._plan(name="12 cuotas", frequency="monthly")
        self._plan(name="20 semanas", installment_count=20,
                   installment_amount=7000.0, frequency="weekly")
        frequencies = self.furniture.product_tmpl_id.cvi_plan_ids.mapped("frequency")
        self.assertEqual(set(frequencies), {"monthly", "weekly"})

    def test_installment_amount_is_not_a_division_of_the_list_price(self):
        """El importe de cuota lleva el interés adentro: no divide ningún precio.

        El mueble vale $90.000 de contado y el plan de 6 cuotas suma $132.000. El módulo
        acepta esa diferencia sin chistar porque el recargo es parte del importe cargado.
        """
        self.assertEqual(self.furniture.list_price, 90000.0)
        plan = self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self.assertEqual(plan.amount_total, 132000.0)
        self.assertGreater(plan.amount_total, self.furniture.list_price)

    def test_list_price_change_does_not_touch_the_plans(self):
        """Cambiar el precio de lista del mueble no altera los planes ya cargados."""
        plan = self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self.furniture.list_price = 150000.0
        self.assertEqual(plan.installment_amount, 22000.0)
        self.assertEqual(plan.amount_total, 132000.0)

    def test_product_lists_its_plans(self):
        """Los planes cuelgan de la ficha del mueble (HU-05)."""
        self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self._plan(name="12 cuotas", installment_count=12, installment_amount=13500.0)
        template = self.furniture.product_tmpl_id
        self.assertEqual(len(template.cvi_plan_ids), 2)
        self.assertEqual(template.cvi_plan_count, 2)

    def test_plan_count_ignores_archived_plans(self):
        """Un plan archivado deja de ofrecerse y no se cuenta."""
        plan = self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self._plan(name="12 cuotas")
        plan.active = False
        self.assertEqual(self.furniture.product_tmpl_id.cvi_plan_count, 1)

    def test_installment_count_must_be_positive(self):
        """No existe un plan de cero cuotas."""
        with self.assertRaises(ValidationError):
            self._plan(installment_count=0)

    def test_installment_amount_must_be_positive(self):
        """No existe un plan con cuota de importe cero."""
        with self.assertRaises(ValidationError):
            self._plan(installment_amount=0.0)

    def test_plan_name_is_unique_per_product(self):
        """Un mismo mueble no puede tener dos planes con el mismo nombre."""
        self._plan(name="12 cuotas")
        with self.assertRaises(psycopg2.errors.UniqueViolation), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self._plan(name="12 cuotas", installment_amount=14000.0)

    def test_same_plan_name_allowed_on_another_product(self):
        """Dos muebles distintos sí pueden tener un plan llamado igual."""
        self._plan(name="12 cuotas")
        other = self.env["product.product"].create({
            "name": "Mesa de luz", "type": "consu", "is_storable": True,
        })
        plan = self._plan(name="12 cuotas", product_tmpl_id=other.product_tmpl_id.id,
                          installment_amount=4000.0)
        self.assertEqual(plan.amount_total, 48000.0)

    def test_display_name_shows_the_installment_amount(self):
        """El plan se muestra con su importe, para elegirlo de un vistazo en la calle."""
        plan = self._plan(name="12 cuotas", installment_count=12, installment_amount=13500.0)
        self.assertIn("13.500", plan.display_name.replace(",", "."))
        self.assertIn("12 cuotas", plan.display_name)
```

Registrar en `tests/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import test_config
from . import test_product_plan
```

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviProductPlan \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `KeyError: 'cvi.product.plan'`.

- [ ] **Step 3: Escribir el modelo `cvi.product.plan`**

`collections_from_vendors_installments/models/cvi_product_plan.py`:

```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

FREQUENCY_SELECTION = [
    ("monthly", "Mensual"),
    ("weekly", "Semanal"),
]


class CviProductPlan(models.Model):
    _name = "cvi.product.plan"
    _description = "Plan de cuotas de un modelo de mueble"
    _order = "product_tmpl_id, sequence, installment_count"

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Modelo de mueble",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Orden", default=10)
    name = fields.Char(
        string="Plan",
        required=True,
        help="Cómo lo nombra el vendedor en la calle: '12 cuotas', '20 semanas'.",
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
        help="Un plan archivado deja de ofrecerse en ventas nuevas, "
             "pero las tarjetas ya vendidas con él no se tocan.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id", string="Moneda", readonly=True
    )
    installment_count = fields.Integer(string="Cantidad de cuotas", required=True)
    installment_amount = fields.Monetary(
        string="Importe de cuota", required=True, currency_field="currency_id"
    )
    frequency = fields.Selection(
        selection=FREQUENCY_SELECTION,
        string="Frecuencia",
        default="monthly",
        required=True,
    )
    amount_total = fields.Monetary(
        string="Precio total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
        help="Cantidad de cuotas por importe de cuota. El recargo por financiación "
             "ya está incluido en el importe de cada plan.",
    )

    _sql_constraints = [
        (
            "name_unique_per_product",
            "UNIQUE(product_tmpl_id, name)",
            "Ese modelo de mueble ya tiene un plan con ese nombre.",
        ),
    ]

    @api.depends("installment_count", "installment_amount")
    def _compute_amount_total(self):
        """El total de un plan es siempre cuotas por importe: nunca se carga a mano."""
        for plan in self:
            plan.amount_total = plan.installment_count * plan.installment_amount

    @api.constrains("installment_count", "installment_amount")
    def _check_plan_values(self):
        """Un plan sin cuotas o con cuota de importe cero no es vendible."""
        for plan in self:
            if plan.installment_count < 1:
                raise ValidationError(_(
                    "El plan %s debe tener al menos una cuota.", plan.name
                ))
            if plan.installment_amount <= 0:
                raise ValidationError(_(
                    "El importe de cuota del plan %s debe ser mayor a cero.", plan.name
                ))

    @api.depends("name", "installment_count", "installment_amount", "currency_id")
    def _compute_display_name(self):
        """Se muestra con el importe, para que el vendedor elija de un vistazo."""
        for plan in self:
            amount = plan.currency_id.format(plan.installment_amount)
            plan.display_name = _(
                "%(name)s de %(amount)s", name=plan.name, amount=amount
            )
```

> `currency_id.format(...)` es el helper de `res.currency` de Odoo 18 para texto legible.
> Si en el entorno no existiera, sustituirlo por `formatLang(self.env, plan.installment_amount, currency_obj=plan.currency_id)` importando `from odoo.tools import formatLang`.

- [ ] **Step 4: Escribir la extensión de `product.template`**

`collections_from_vendors_installments/models/product_template.py`:

```python
# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cvi_plan_ids = fields.One2many(
        "cvi.product.plan",
        "product_tmpl_id",
        string="Planes de cuotas",
        help="Cómo se vende este mueble en la calle: un plan por cada combinación "
             "de cantidad de cuotas e importe.",
    )
    cvi_plan_count = fields.Integer(
        string="Planes de cuotas", compute="_compute_cvi_plan_count"
    )

    @api.depends("cvi_plan_ids")
    def _compute_cvi_plan_count(self):
        """Cuántos planes activos tiene el mueble, para el botón de la ficha."""
        for template in self:
            template.cvi_plan_count = len(template.cvi_plan_ids)
```

- [ ] **Step 5: Escribir la pestaña en la ficha del producto**

`collections_from_vendors_installments/views/product_template_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_product_template_form_cvi_plans" model="ir.ui.view">
        <field name="name">product.template.form.inherit.cvi.plans</field>
        <field name="model">product.template</field>
        <field name="inherit_id" ref="product.product_template_form_view"/>
        <field name="arch" type="xml">
            <xpath expr="//notebook" position="inside">
                <page string="Planes de cuotas" name="cvi_plans"
                      groups="collections_from_vendors_installments.group_cvi_manager">
                    <field name="cvi_plan_ids">
                        <list editable="bottom">
                            <field name="sequence" widget="handle"/>
                            <field name="name"/>
                            <field name="installment_count"/>
                            <field name="installment_amount"/>
                            <field name="frequency"/>
                            <field name="amount_total" readonly="1"/>
                            <field name="active" column_invisible="True"/>
                            <field name="company_id" column_invisible="True"/>
                            <field name="currency_id" column_invisible="True"/>
                        </list>
                    </field>
                    <p class="text-muted">
                        El precio total de cada plan se calcula solo: cantidad de cuotas por
                        importe de cuota. El interés va incluido en el importe de la cuota,
                        así que el total no es una división del precio de contado. El precio
                        de lista del producto no interviene en el cálculo.
                    </p>
                </page>
            </xpath>
        </field>
    </record>
</odoo>
```

- [ ] **Step 6: Registrar el modelo, la vista y los accesos**

`models/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import cvi_product_plan
from . import product_template
from . import res_company
from . import res_config_settings
```

`__manifest__.py` — lista `data`:

```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
    ],
```

`security/ir.model.access.csv` — el vendedor y el cobrador leen los planes; solo el
administrador los define:

```csv
access_cvi_product_plan_vendor,cvi.product.plan vendedor,model_cvi_product_plan,collections_from_vendors_installments.group_cvi_vendor,1,0,0,0
access_cvi_product_plan_collector,cvi.product.plan cobrador,model_cvi_product_plan,collections_from_vendors_installments.group_cvi_collector,1,0,0,0
access_cvi_product_plan_manager,cvi.product.plan administrador,model_cvi_product_plan,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
```

- [ ] **Step 7: Agregar planes al fixture de tests**

Todas las tasks siguientes venden con un plan. Agregar al final de `setUpClass` en
`tests/common.py`, después de crear `cls.product`:

```python
        cls.plan_12 = cls.env["cvi.product.plan"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "name": "12 cuotas",
            "installment_count": 12,
            "installment_amount": 10000.0,
            "frequency": "monthly",
        })
        cls.plan_3 = cls.env["cvi.product.plan"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "name": "3 cuotas",
            "installment_count": 3,
            "installment_amount": 10000.0,
            "frequency": "monthly",
        })
        cls.plan_weekly = cls.env["cvi.product.plan"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "name": "4 semanas",
            "installment_count": 4,
            "installment_amount": 5000.0,
            "frequency": "weekly",
        })
```

> `cls.plan_12` da un total de $120.000, `cls.plan_3` de $30.000 y `cls.plan_weekly` de
> $20.000. Esos importes son los que usan los tests de las tasks siguientes.
>
> Fijate que ninguno coincide con el `list_price` del producto ($95.000): **el precio de
> lista no interviene en ningún cálculo**. El importe de cuota lo carga el administrador
> con el interés ya adentro, y el total sale de multiplicar. Si el implementador siente
> la tentación de derivar el precio del `list_price`, está resolviendo otro problema.

- [ ] **Step 8: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 10 tests de `TestCviProductPlan` en verde.

- [ ] **Step 9: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): planes de cuotas por modelo de mueble"
```

---

## Task 3: Modelo `cvi.card` — la tarjeta de venta

Cubre HU-05 (registrar la venta eligiendo el plan del mueble) y la parte de carga de HU-06.

**Files:**
- Create: `collections_from_vendors_installments/models/cvi_card.py`
- Create: `collections_from_vendors_installments/data/ir_sequence.xml`
- Modify: `collections_from_vendors_installments/models/__init__.py`
- Modify: `collections_from_vendors_installments/__manifest__.py`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_card.py`

**Interfaces:**
- Consumes: `res.company.cvi_default_installments`, `.cvi_allowed_frequencies` y grupos (Task 1); `cvi.product.plan` con `product_tmpl_id`, `installment_count`, `installment_amount`, `frequency`, `amount_total`, y el fixture `cls.plan_12` / `cls.plan_3` / `cls.plan_weekly` (Task 2).
- Produces: modelo `cvi.card` con campos `name` (Char), `partner_id`, `vendor_id`, `collector_id` (Many2one `res.users`), `product_id`, `product_tmpl_id` (related), `plan_id` (Many2one `cvi.product.plan`), `quantity` (Float), `installment_count` (Integer compute store editable), `installment_amount` (Monetary compute store editable), `frequency` (Selection compute store editable), `amount_total` (Monetary compute store), `charge_day_month` (Integer), `charge_day_week` (Selection `'0'`..`'6'`), `charge_day_display` (Char compute), `date_sale` (Date), `state` (Selection `draft`/`sold`/`routed`/`active`/`done`/`cancel`), `company_id`, `currency_id`. Secuencia `cvi.card` con prefijo `TARJ/`.

**Cómo se fija el precio** (fijado acá): el vendedor elige el mueble y después uno de los
planes cargados en su ficha. Elegir el plan completa cantidad de cuotas, importe de cuota
y frecuencia; el precio total es el producto de los dos primeros. Esos tres campos son
editables **solo por el administrador**: si un vendedor los cambia respecto del plan, la
validación lo rechaza.

> **Un compute por campo, y no se fusionan.** `installment_count`, `installment_amount` y
> `frequency` se copian del plan con tres métodos `@api.depends("plan_id")` separados, uno
> por campo. Es obligatorio: la protección de Odoo para campos `compute + store +
> readonly=False` pasados explícitos en `create()` se aplica **al método compute entero**,
> no al campo. Con un solo método que calcule los tres, pasar `installment_amount` explícito
> (el override del administrador) saltea el método completo y deja `installment_count` en 0
> y `frequency` en False — `amount_total` termina en 0. Verificado contra la base real.
> No los unifiques ni metas un helper compartido.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_card.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCard(CviCommon):

    def _card(self, **kwargs):
        """Tarjeta en borrador con valores mínimos, sobreescribibles."""
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_sequence_is_assigned_on_create(self):
        """Al crear, la tarjeta recibe una referencia de la secuencia."""
        card = self._card()
        self.assertTrue(card.name.startswith("TARJ/"))
        self.assertNotEqual(card.name, "Nuevo")

    def test_new_card_starts_in_draft(self):
        """Una tarjeta nueva arranca en borrador."""
        self.assertEqual(self._card().state, "draft")

    def test_plan_fills_installment_count(self):
        """Elegir el plan completa la cantidad de cuotas (HU-05)."""
        self.assertEqual(self._card(plan_id=self.plan_12.id).installment_count, 12)

    def test_plan_fills_installment_amount(self):
        """Elegir el plan completa el importe de cuota, que no se carga a mano (HU-05)."""
        self.assertEqual(self._card(plan_id=self.plan_12.id).installment_amount, 10000.0)

    def test_plan_fills_frequency(self):
        """La frecuencia de cobro viene con el plan, no se elige aparte (HU-06)."""
        card = self._card(plan_id=self.plan_weekly.id, charge_day_week="2",
                          charge_day_month=0)
        self.assertEqual(card.frequency, "weekly")

    def test_total_is_derived_from_the_plan(self):
        """El precio total sale de cantidad de cuotas por importe: 12 x 10.000."""
        self.assertEqual(self._card(plan_id=self.plan_12.id).amount_total, 120000.0)

    def test_changing_the_plan_repricing_the_card(self):
        """Cambiar de plan reescribe cuotas, importe y total."""
        card = self._card(plan_id=self.plan_12.id)
        card.plan_id = self.plan_3.id
        self.assertEqual(card.installment_count, 3)
        self.assertEqual(card.installment_amount, 10000.0)
        self.assertEqual(card.amount_total, 30000.0)

    def test_plan_of_another_product_is_rejected(self):
        """No se puede vender un mueble con el plan de otro mueble."""
        other = self.env["product.product"].create({
            "name": "Mesa de luz", "type": "consu", "is_storable": True,
        })
        other_plan = self.env["cvi.product.plan"].create({
            "product_tmpl_id": other.product_tmpl_id.id,
            "name": "6 cuotas",
            "installment_count": 6,
            "installment_amount": 4000.0,
            "frequency": "monthly",
        })
        with self.assertRaises(ValidationError):
            self._card(product_id=self.product.id, plan_id=other_plan.id)

    def test_manager_can_override_the_plan_amount(self):
        """El administrador puede vender con un importe distinto al del plan."""
        card = self._card(plan_id=self.plan_12.id, installment_amount=11000.0)
        self.assertEqual(card.installment_amount, 11000.0)
        self.assertEqual(card.amount_total, 132000.0)

    def test_vendor_cannot_override_the_plan_amount(self):
        """Un vendedor no puede cambiar el precio que fija el plan."""
        with self.assertRaises(ValidationError):
            self.env["cvi.card"].with_user(self.vendor_user).create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "plan_id": self.plan_12.id,
                "date_sale": "2026-01-15",
                "charge_day_month": 10,
                "installment_amount": 8000.0,
            })

    def test_vendor_cannot_override_the_installment_count(self):
        """Un vendedor tampoco puede cambiar en cuántas cuotas vende."""
        with self.assertRaises(ValidationError):
            self.env["cvi.card"].with_user(self.vendor_user).create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "plan_id": self.plan_12.id,
                "date_sale": "2026-01-15",
                "charge_day_month": 10,
                "installment_count": 24,
            })

    def test_vendor_selling_at_the_plan_price_is_accepted(self):
        """Vendiendo al precio del plan, el vendedor carga la venta sin problemas."""
        card = self.env["cvi.card"].with_user(self.vendor_user).create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
        })
        self.assertEqual(card.amount_total, 120000.0)

    def test_charge_day_display_monthly(self):
        """Con frecuencia mensual el día de cobro se muestra como día del mes."""
        card = self._card(plan_id=self.plan_12.id, charge_day_month=10)
        self.assertEqual(card.charge_day_display, "Día 10 de cada mes")

    def test_charge_day_display_weekly(self):
        """Con frecuencia semanal el día de cobro se muestra como día de la semana."""
        card = self._card(plan_id=self.plan_weekly.id, charge_day_week="2",
                          charge_day_month=0)
        self.assertEqual(card.charge_day_display, "Todos los miércoles")

    def test_charge_day_month_out_of_range_is_rejected(self):
        """Un día del mes fuera de 1..31 no se acepta."""
        with self.assertRaises(ValidationError):
            self._card(plan_id=self.plan_12.id, charge_day_month=45)

    def test_frequency_not_allowed_by_company_is_rejected(self):
        """Si la empresa solo permite mensual, un plan semanal no se puede vender (HU-31)."""
        self.company.cvi_allowed_frequencies = "monthly"
        with self.assertRaises(ValidationError):
            self._card(plan_id=self.plan_weekly.id, charge_day_week="2",
                       charge_day_month=0)
```

Y registrar el archivo en `tests/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import test_config
from . import test_product_plan
from . import test_card
```

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviCard \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `KeyError: 'cvi.card'` — el modelo no existe.

- [ ] **Step 3: Escribir el modelo `cvi.card`**

`collections_from_vendors_installments/models/cvi_card.py`:

```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .cvi_product_plan import FREQUENCY_SELECTION

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("sold", "Vendida"),
    ("routed", "Enrutada"),
    ("active", "En cobranza"),
    ("done", "Finalizada"),
    ("cancel", "Anulada"),
]

WEEKDAY_SELECTION = [
    ("0", "Lunes"),
    ("1", "Martes"),
    ("2", "Miércoles"),
    ("3", "Jueves"),
    ("4", "Viernes"),
    ("5", "Sábado"),
    ("6", "Domingo"),
]

WEEKDAY_PLURAL = {
    "0": "lunes",
    "1": "martes",
    "2": "miércoles",
    "3": "jueves",
    "4": "viernes",
    "5": "sábados",
    "6": "domingos",
}


class CviCard(models.Model):
    _name = "cvi.card"
    _description = "Tarjeta de venta domiciliaria en cuotas"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_sale desc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("Nuevo"),
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Moneda",
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Cliente",
        required=True,
        tracking=True,
        index=True,
    )
    vendor_id = fields.Many2one(
        "res.users",
        string="Vendedor",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
    )
    collector_id = fields.Many2one(
        "res.users",
        string="Cobrador",
        tracking=True,
        index=True,
        copy=False,
        help="En estado Enrutada es el destinatario pendiente de aceptar; "
             "en En cobranza es el responsable de la cobranza.",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Modelo de mueble",
        required=True,
        domain="[('is_storable', '=', True)]",
    )
    product_tmpl_id = fields.Many2one(
        related="product_id.product_tmpl_id", string="Ficha del mueble", readonly=True
    )
    plan_id = fields.Many2one(
        "cvi.product.plan",
        string="Plan de cuotas",
        required=True,
        tracking=True,
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        help="Los planes se definen en la ficha del mueble, pestaña Planes de cuotas.",
    )
    quantity = fields.Float(string="Cantidad", default=1.0, required=True)
    date_sale = fields.Date(
        string="Fecha de venta",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    installment_count = fields.Integer(
        string="Cantidad de cuotas",
        compute="_compute_installment_count",
        store=True,
        readonly=False,
        tracking=True,
    )
    installment_amount = fields.Monetary(
        string="Importe de cuota",
        compute="_compute_installment_amount",
        store=True,
        readonly=False,
        currency_field="currency_id",
        tracking=True,
    )
    frequency = fields.Selection(
        selection=FREQUENCY_SELECTION,
        string="Frecuencia",
        compute="_compute_frequency",
        store=True,
        readonly=False,
        tracking=True,
    )
    amount_total = fields.Monetary(
        string="Precio total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
        tracking=True,
        help="Cantidad de cuotas por importe de cuota. No se carga a mano.",
    )
    charge_day_month = fields.Integer(
        string="Día del mes",
        default=lambda self: fields.Date.context_today(self).day,
        help="Día de cobro cuando la frecuencia es mensual. Si el mes no llega a ese día, se cobra el último.",
    )
    charge_day_week = fields.Selection(
        selection=WEEKDAY_SELECTION,
        string="Día de la semana",
        default="0",
        help="Día de cobro cuando la frecuencia es semanal.",
    )
    charge_day_display = fields.Char(
        string="Día de cobro",
        compute="_compute_charge_day_display",
        store=True,
    )
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        default="draft",
        required=True,
        copy=False,
        tracking=True,
        index=True,
    )

    _sql_constraints = [
        (
            "amount_total_positive",
            "CHECK(amount_total > 0)",
            "El precio total de la venta debe ser mayor a cero.",
        ),
    ]

    @api.depends("plan_id")
    def _compute_installment_count(self):
        """Cantidad de cuotas del plan elegido (HU-05)."""
        for card in self:
            if card.plan_id:
                card.installment_count = card.plan_id.installment_count
            else:
                card.installment_count = card.company_id.cvi_default_installments

    @api.depends("plan_id")
    def _compute_installment_amount(self):
        """Importe de cuota del plan elegido, con el interés ya incluido (HU-05)."""
        for card in self:
            card.installment_amount = card.plan_id.installment_amount if card.plan_id else 0.0

    @api.depends("plan_id")
    def _compute_frequency(self):
        """Modalidad de cobro del plan elegido (HU-06)."""
        for card in self:
            card.frequency = card.plan_id.frequency if card.plan_id else "monthly"

    @api.depends("installment_count", "installment_amount")
    def _compute_amount_total(self):
        """El precio total de la venta es cuotas por importe: nunca se carga a mano."""
        for card in self:
            card.amount_total = card.installment_count * card.installment_amount

    @api.depends("frequency", "charge_day_month", "charge_day_week")
    def _compute_charge_day_display(self):
        """Texto legible del día de cobro, para listas y para el cobrador."""
        for card in self:
            if card.frequency == "weekly":
                day = WEEKDAY_PLURAL.get(card.charge_day_week, "")
                card.charge_day_display = _("Todos los %s", day) if day else ""
            else:
                card.charge_day_display = _("Día %s de cada mes", card.charge_day_month)

    @api.constrains("plan_id", "product_id")
    def _check_plan_belongs_to_product(self):
        """El plan elegido tiene que ser uno de los cargados en la ficha de ese mueble."""
        for card in self:
            if card.plan_id.product_tmpl_id != card.product_id.product_tmpl_id:
                raise ValidationError(_(
                    "El plan %(plan)s pertenece a %(plan_product)s, no a %(product)s.",
                    plan=card.plan_id.name,
                    plan_product=card.plan_id.product_tmpl_id.display_name,
                    product=card.product_id.display_name,
                ))

    @api.constrains("plan_id", "installment_count", "installment_amount", "frequency")
    def _check_plan_values(self):
        """Solo el administrador puede vender con valores distintos a los del plan (RN-05)."""
        if self.env.user.has_group(
            "collections_from_vendors_installments.group_cvi_manager"
        ):
            return
        for card in self:
            plan = card.plan_id
            currency = card.currency_id
            differs = (
                card.installment_count != plan.installment_count
                or currency.compare_amounts(
                    card.installment_amount, plan.installment_amount
                ) != 0
                or card.frequency != plan.frequency
            )
            if differs:
                raise ValidationError(_(
                    "El plan %(plan)s se vende en %(count)s cuotas de %(amount)s. "
                    "Solo un administrador puede vender con otros valores.",
                    plan=plan.name,
                    count=plan.installment_count,
                    amount=plan.installment_amount,
                ))

    @api.constrains("frequency", "charge_day_month", "charge_day_week")
    def _check_charge_day(self):
        """El día de cobro debe ser válido para la frecuencia del plan."""
        for card in self:
            if card.frequency == "monthly" and not 1 <= card.charge_day_month <= 31:
                raise ValidationError(_(
                    "El día de cobro mensual debe estar entre 1 y 31 (recibido: %s).",
                    card.charge_day_month,
                ))
            if card.frequency == "weekly" and not card.charge_day_week:
                raise ValidationError(_("Elegí el día de la semana en que se cobra."))

    @api.constrains("frequency", "company_id")
    def _check_frequency_allowed(self):
        """La frecuencia del plan tiene que estar habilitada en la configuración (HU-31)."""
        for card in self:
            allowed = card.company_id.cvi_allowed_frequencies
            if allowed != "both" and card.frequency != allowed:
                raise ValidationError(_(
                    "La empresa %(company)s solo permite ventas con frecuencia %(allowed)s.",
                    company=card.company_id.name,
                    allowed=dict(
                        card.company_id._fields["cvi_allowed_frequencies"].selection
                    )[allowed],
                ))

    @api.constrains("installment_count")
    def _check_installment_count(self):
        """No tiene sentido una venta con cero o menos cuotas."""
        for card in self:
            if card.installment_count < 1:
                raise ValidationError(_("La cantidad de cuotas debe ser al menos 1."))

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Al cambiar de mueble, el plan anterior deja de corresponder."""
        if self.plan_id.product_tmpl_id != self.product_id.product_tmpl_id:
            self.plan_id = False

    @api.onchange("frequency")
    def _onchange_frequency(self):
        """Al pasar a semanal, hay que elegir día de la semana en vez de día del mes."""
        if self.frequency == "weekly" and not self.charge_day_week:
            self.charge_day_week = str(fields.Date.context_today(self).weekday())

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia desde la secuencia al crear."""
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cvi.card") or _("Nuevo")
        return super().create(vals_list)
```

- [ ] **Step 4: Escribir la secuencia**

`collections_from_vendors_installments/data/ir_sequence.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="seq_cvi_card" model="ir.sequence">
        <field name="name">Tarjeta de venta en cuotas</field>
        <field name="code">cvi.card</field>
        <field name="prefix">TARJ/</field>
        <field name="padding">6</field>
        <field name="company_id" eval="False"/>
    </record>

    <record id="seq_cvi_payment" model="ir.sequence">
        <field name="name">Cobro de cuota</field>
        <field name="code">cvi.payment</field>
        <field name="prefix">COB/</field>
        <field name="padding">6</field>
        <field name="company_id" eval="False"/>
    </record>
</odoo>
```

- [ ] **Step 5: Registrar el modelo, la data y los accesos**

`models/__init__.py` — agregar `cvi_card` al principio:

```python
# -*- coding: utf-8 -*-
from . import cvi_product_plan
from . import cvi_card
from . import product_template
from . import res_company
from . import res_config_settings
```

`__manifest__.py` — reemplazar la lista `data` por:

```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
    ],
```

`security/ir.model.access.csv` — agregar estas filas:

```csv
access_cvi_card_vendor,cvi.card vendedor,model_cvi_card,collections_from_vendors_installments.group_cvi_vendor,1,1,1,0
access_cvi_card_collector,cvi.card cobrador,model_cvi_card,collections_from_vendors_installments.group_cvi_collector,1,1,0,0
access_cvi_card_manager,cvi.card administrador,model_cvi_card,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 16 tests de `TestCviCard` en verde.

- [ ] **Step 7: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): tarjeta de venta con precio tomado del plan del mueble"
```

---


## Task 4: Modelo `cvi.installment` y generación del calendario de cuotas

Cubre HU-06 (calendario automático) y la reprogramación de una cuota a pedido del cliente (contexto §1.3).

**Files:**
- Create: `collections_from_vendors_installments/models/cvi_installment.py`
- Create: `collections_from_vendors_installments/data/ir_cron.xml`
- Modify: `collections_from_vendors_installments/models/cvi_card.py` (agregar `installment_ids` y `_cvi_due_dates` / `_cvi_generate_installments`)
- Modify: `collections_from_vendors_installments/models/__init__.py`
- Modify: `collections_from_vendors_installments/__manifest__.py`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_installment_schedule.py`

**Interfaces:**
- Consumes: `cvi.card` con `date_sale`, `frequency`, `charge_day_month`, `charge_day_week`, `installment_count`, `amount_total`, `installment_amount` (Task 3); `res.company.cvi_overdue_days` (Task 1).
- Produces:
  - Modelo `cvi.installment` con `card_id`, `sequence` (Integer, Nº de cuota, 1-based), `date_due` (Date), `amount` (Monetary), `is_commission` (Boolean), `amount_paid` (Monetary compute store), `amount_residual` (Monetary compute store), `state` (Selection `pending`/`partial`/`paid`/`overdue`), `allocation_ids` (One2many, definido en Task 5), y related `partner_id`, `collector_id`, `company_id`, `currency_id`.
  - Método `cvi.installment.action_postpone(new_date)` → reprograma una cuota impaga.
  - Método `cvi.installment._cron_update_overdue()` → recalcula vencidas, invocado por cron diario.
  - Método `cvi.card._cvi_due_dates(count)` → `list[date]` con los vencimientos de las cuotas de cobranza.
  - Método `cvi.card._cvi_generate_installments()` → crea las N cuotas; la cuota 1 vence el día de la venta y lleva `is_commission=True`.

**Reglas del calendario** (fijadas acá, no negociables por el implementador):
- La cuota 1 vence el mismo día de la venta y es la comisión del vendedor (RN-01).
- Frecuencia mensual: la cuota 2 vence el `charge_day_month` del **mes siguiente** al de la venta; las siguientes, mes a mes. Si el mes no llega a ese día (ej. 31 en febrero), vence el último día del mes.
- Frecuencia semanal: la cuota 2 vence en la **primera ocurrencia estrictamente posterior** a la fecha de venta del `charge_day_week`; las siguientes, cada 7 días.
- Montos: todas las cuotas valen `installment_amount`, el importe que fija el plan. No hay resto que repartir: el precio total de la tarjeta *es* cuotas por importe.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_installment_schedule.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviInstallmentSchedule(CviCommon):

    def _card(self, count=12, amount=10000.0, frequency="monthly", **kwargs):
        """Tarjeta en borrador con un plan creado a medida para el caso bajo prueba.

        Cada test necesita una combinación distinta de cantidad de cuotas y frecuencia,
        así que el plan se arma acá en vez de usar los del fixture compartido.
        """
        plan = self.env["cvi.product.plan"].create({
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "name": "Plan %s x %s %s" % (count, amount, frequency),
            "installment_count": count,
            "installment_amount": amount,
            "frequency": frequency,
        })
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": plan.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_generates_exactly_n_installments(self):
        """Se generan tantas cuotas como indica el plan elegido."""
        card = self._card(count=12)
        card._cvi_generate_installments()
        self.assertEqual(len(card.installment_ids), 12)

    def test_first_installment_due_on_sale_date(self):
        """La cuota 1 vence el día de la venta: la cobra el vendedor en el acto (RN-01)."""
        card = self._card(date_sale="2026-01-15")
        card._cvi_generate_installments()
        first = card.installment_ids.filtered(lambda i: i.sequence == 1)
        self.assertEqual(str(first.date_due), "2026-01-15")
        self.assertTrue(first.is_commission)

    def test_only_first_installment_is_commission(self):
        """Solo la cuota 1 es comisión del vendedor."""
        card = self._card(count=12)
        card._cvi_generate_installments()
        commissions = card.installment_ids.filtered("is_commission")
        self.assertEqual(len(commissions), 1)
        self.assertEqual(commissions.sequence, 1)

    def test_monthly_second_installment_falls_next_month_on_charge_day(self):
        """Venta el 15/01 con día de cobro 10: la cuota 2 vence el 10/02."""
        card = self._card(count=3, date_sale="2026-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-02-10")

    def test_monthly_clamps_to_last_day_of_short_month(self):
        """Día de cobro 31 en febrero: vence el 28 (2026 no es bisiesto)."""
        card = self._card(count=3, date_sale="2026-01-15", charge_day_month=31)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-02-28")

    def test_monthly_installments_advance_one_month_each(self):
        """Las cuotas mensuales avanzan mes a mes sobre el mismo día."""
        card = self._card(count=4, date_sale="2026-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        dues = card.installment_ids.sorted("sequence").mapped("date_due")
        self.assertEqual(
            [str(d) for d in dues],
            ["2026-01-15", "2026-02-10", "2026-03-10", "2026-04-10"],
        )

    def test_weekly_second_installment_is_next_occurrence(self):
        """Venta el jueves 15/01/2026 con cobro los miércoles: la cuota 2 vence el 21/01."""
        card = self._card(
            count=3, frequency="weekly", date_sale="2026-01-15", charge_day_week="2"
        )
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-01-21")

    def test_weekly_same_weekday_as_sale_skips_to_next_week(self):
        """Si el día de cobro es el mismo día de la semana que la venta, salta 7 días."""
        card = self._card(
            count=3, frequency="weekly", date_sale="2026-01-15", charge_day_week="3"
        )
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-01-22")

    def test_weekly_installments_advance_seven_days(self):
        """Las cuotas semanales avanzan de a 7 días."""
        card = self._card(
            count=4, frequency="weekly", date_sale="2026-01-15", charge_day_week="2"
        )
        card._cvi_generate_installments()
        dues = card.installment_ids.sorted("sequence").mapped("date_due")
        self.assertEqual(
            [str(d) for d in dues],
            ["2026-01-15", "2026-01-21", "2026-01-28", "2026-02-04"],
        )

    def test_every_installment_is_worth_the_plan_amount(self):
        """Todas las cuotas valen lo que dice el plan: no hay resto que repartir."""
        card = self._card(count=3, amount=33333.33)
        card._cvi_generate_installments()
        amounts = card.installment_ids.sorted("sequence").mapped("amount")
        self.assertEqual(amounts, [33333.33, 33333.33, 33333.33])

    def test_installment_amounts_sum_to_total(self):
        """La suma de las cuotas iguala exactamente el precio total de la tarjeta."""
        card = self._card(count=3, amount=33333.33)
        card._cvi_generate_installments()
        self.assertEqual(
            sum(card.installment_ids.mapped("amount")), card.amount_total
        )

    def test_regenerating_replaces_previous_schedule(self):
        """Regenerar el calendario en borrador reemplaza las cuotas anteriores."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        card.plan_id = self.plan_12
        card._cvi_generate_installments()
        self.assertEqual(len(card.installment_ids), 12)

    def test_installment_starts_pending(self):
        """Una cuota recién generada está pendiente y su residual es el monto total."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "pending")
        self.assertEqual(second.amount_paid, 0.0)
        self.assertEqual(second.amount_residual, second.amount)

    def test_postpone_moves_due_date(self):
        """El cliente pide correr la próxima fecha de cobro y la cuota se reprograma."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        second.action_postpone("2026-02-20")
        self.assertEqual(str(second.date_due), "2026-02-20")

    def test_postpone_before_sale_date_is_rejected(self):
        """No se puede reprogramar una cuota a antes de la fecha de venta."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        with self.assertRaises(UserError):
            second.action_postpone("2026-01-01")

    def test_overdue_when_past_due_without_tolerance(self):
        """Sin tolerancia, una cuota impaga vencida ayer figura como vencida."""
        self.company.cvi_overdue_days = 0
        card = self._card(count=3, date_sale="2020-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "overdue")

    def test_tolerance_days_delay_overdue_flag(self):
        """Con 10000 días de tolerancia, la misma cuota vieja sigue pendiente."""
        self.company.cvi_overdue_days = 10000
        card = self._card(count=3, date_sale="2020-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "pending")
```

Registrar en `tests/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import test_config
from . import test_product_plan
from . import test_card
from . import test_installment_schedule
```

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviInstallmentSchedule \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `KeyError: 'cvi.installment'`.

- [ ] **Step 3: Escribir el modelo `cvi.installment`**

`collections_from_vendors_installments/models/cvi_installment.py`:

```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("pending", "Pendiente"),
    ("partial", "Parcial"),
    ("paid", "Pagada"),
    ("overdue", "Vencida"),
]


class CviInstallment(models.Model):
    _name = "cvi.installment"
    _description = "Cuota de una tarjeta de venta en cuotas"
    _order = "date_due, card_id, sequence, id"

    card_id = fields.Many2one(
        "cvi.card",
        string="Tarjeta",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_id = fields.Many2one(
        related="card_id.partner_id", store=True, index=True, string="Cliente"
    )
    collector_id = fields.Many2one(
        related="card_id.collector_id", store=True, index=True, string="Cobrador"
    )
    company_id = fields.Many2one(related="card_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="card_id.currency_id", readonly=True)
    sequence = fields.Integer(string="Nº de cuota", default=1, required=True)
    date_due = fields.Date(string="Vencimiento", required=True, index=True)
    amount = fields.Monetary(
        string="Monto", required=True, currency_field="currency_id"
    )
    is_commission = fields.Boolean(
        string="Comisión del vendedor",
        default=False,
        help="La primera cuota la cobra el vendedor y constituye su comisión (RN-01). "
             "No forma parte de la cobranza del cobrador.",
    )
    allocation_ids = fields.One2many(
        "cvi.allocation", "installment_id", string="Imputaciones"
    )
    amount_paid = fields.Monetary(
        string="Cobrado",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_residual = fields.Monetary(
        string="Residual",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        compute="_compute_state",
        store=True,
        index=True,
        default="pending",
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto de la cuota debe ser mayor a cero.",
        ),
    ]

    @api.depends("amount", "allocation_ids.amount", "allocation_ids.payment_id.state")
    def _compute_amounts(self):
        """Cobrado = imputaciones de cobros publicados. Residual nunca es negativo."""
        for installment in self:
            paid = sum(
                installment.allocation_ids
                .filtered(lambda a: a.payment_id.state == "posted")
                .mapped("amount")
            )
            installment.amount_paid = paid
            installment.amount_residual = max(installment.amount - paid, 0.0)

    @api.depends("amount", "amount_paid", "amount_residual", "date_due", "company_id.cvi_overdue_days")
    def _compute_state(self):
        """Estado de la cuota. Solo es pagada cuando el residual llega a cero."""
        today = fields.Date.context_today(self)
        for installment in self:
            rounding = installment.currency_id.rounding or 0.01
            tolerance = installment.company_id.cvi_overdue_days or 0
            if float_is_zero(installment.amount_residual, precision_rounding=rounding):
                installment.state = "paid"
            elif installment.date_due and (today - installment.date_due).days > tolerance:
                installment.state = "overdue"
            elif installment.amount_paid > 0:
                installment.state = "partial"
            else:
                installment.state = "pending"

    def action_postpone(self, new_date):
        """Corre el vencimiento de una cuota impaga a pedido del cliente.

        El vendedor fija el día de cobro al vender, pero el cliente puede pedir mover una
        fecha puntual. Solo mueve esta cuota; el resto del calendario queda igual.
        """
        self.ensure_one()
        if self.state == "paid":
            raise UserError(_("La cuota %s ya está pagada: no se puede reprogramar.", self.sequence))
        new_date = fields.Date.to_date(new_date)
        if new_date < self.card_id.date_sale:
            raise UserError(_(
                "No se puede reprogramar la cuota a %(new)s: es anterior a la fecha de venta (%(sale)s).",
                new=new_date,
                sale=self.card_id.date_sale,
            ))
        old_date = self.date_due
        self.date_due = new_date
        self.card_id._cvi_log(_(
            "Cuota %(seq)s reprogramada de %(old)s a %(new)s.",
            seq=self.sequence, old=old_date, new=new_date,
        ))
        return True

    @api.model
    def _cron_update_overdue(self):
        """Cron diario: recalcula el estado de las cuotas impagas ya vencidas (HU-23 parcial).

        El estado es computado y almacenado pero depende de la fecha de hoy, que no es un
        campo. Este cron fuerza el recálculo invalidando la caché de las candidatas.
        """
        today = fields.Date.context_today(self)
        candidates = self.search([
            ("date_due", "<", today),
            ("state", "in", ("pending", "partial")),
            ("card_id.state", "not in", ("draft", "cancel")),
        ])
        candidates.invalidate_recordset(["state"])
        candidates._compute_state()
        _logger.info("Cron de cuotas vencidas: %s cuotas revisadas", len(candidates))
        return True
```

- [ ] **Step 4: Agregar la generación del calendario a `cvi.card`**

En `models/cvi_card.py`, agregar al principio del archivo, junto a los imports:

```python
import calendar
from datetime import date

from dateutil.relativedelta import relativedelta
```

Agregar el campo `installment_ids` después de `state`:

```python
    installment_ids = fields.One2many(
        "cvi.installment", "card_id", string="Cuotas", copy=False
    )
```

Y agregar estos dos métodos al final de la clase:

```python
    def _cvi_due_dates(self, count):
        """Vencimientos de las `count` cuotas de cobranza (las que cobra el cobrador).

        La cuota 1 no entra acá: vence el día de la venta porque la cobra el vendedor.
        Mensual: la primera cae el día de cobro del mes SIGUIENTE al de la venta,
        recortada al último día si el mes no llega (31 en febrero -> 28).
        Semanal: la primera cae en la próxima ocurrencia estricta del día elegido.
        """
        self.ensure_one()
        dates = []
        if self.frequency == "weekly":
            target = int(self.charge_day_week)
            delta = (target - self.date_sale.weekday()) % 7 or 7
            current = self.date_sale + relativedelta(days=delta)
            for _index in range(count):
                dates.append(current)
                current = current + relativedelta(days=7)
        else:
            cursor = self.date_sale + relativedelta(months=1)
            for _index in range(count):
                last_day = calendar.monthrange(cursor.year, cursor.month)[1]
                dates.append(
                    date(cursor.year, cursor.month, min(self.charge_day_month, last_day))
                )
                cursor = cursor + relativedelta(months=1)
        return dates

    def _cvi_generate_installments(self):
        """Genera el calendario completo de cuotas, reemplazando el anterior si existe.

        La cuota 1 es la comisión del vendedor y vence el día de la venta (RN-01).
        Todas las cuotas valen lo mismo: el importe que fija el plan. No hay resto que
        repartir, porque el precio total de la tarjeta es cuotas por importe.
        """
        self.ensure_one()
        self.installment_ids.unlink()
        due_dates = [self.date_sale] + self._cvi_due_dates(self.installment_count - 1)
        vals_list = [{
            "card_id": self.id,
            "sequence": index,
            "date_due": due,
            "amount": self.installment_amount,
            "is_commission": index == 1,
        } for index, due in enumerate(due_dates, start=1)]
        self.env["cvi.installment"].create(vals_list)
        return True
```

- [ ] **Step 5: Escribir el cron y registrar todo**

`collections_from_vendors_installments/data/ir_cron.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="cron_cvi_update_overdue" model="ir.cron">
        <field name="name">Venta en cuotas: marcar cuotas vencidas</field>
        <field name="model_id" ref="model_cvi_installment"/>
        <field name="state">code</field>
        <field name="code">model._cron_update_overdue()</field>
        <field name="interval_number">1</field>
        <field name="interval_type">days</field>
        <field name="active" eval="True"/>
    </record>
</odoo>
```

`models/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import cvi_card
from . import cvi_installment
from . import res_company
from . import res_config_settings
```

`__manifest__.py` — lista `data`:

```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
    ],
```

`security/ir.model.access.csv` — agregar:

```csv
access_cvi_installment_vendor,cvi.installment vendedor,model_cvi_installment,collections_from_vendors_installments.group_cvi_vendor,1,1,1,0
access_cvi_installment_collector,cvi.installment cobrador,model_cvi_installment,collections_from_vendors_installments.group_cvi_collector,1,1,0,0
access_cvi_installment_manager,cvi.installment administrador,model_cvi_installment,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`. Los tests de `TestCviInstallmentSchedule` referencian `cvi.allocation` a través de `allocation_ids`; ese modelo se crea en la Task 5, así que **el módulo no cargará** hasta entonces si `cvi.allocation` no existe. Para no romper la secuencia, esta task incluye el modelo mínimo en el paso siguiente.

- [ ] **Step 7: Crear el modelo `cvi.allocation` mínimo para que `allocation_ids` resuelva**

`collections_from_vendors_installments/models/cvi_allocation.py`:

```python
# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CviAllocation(models.Model):
    _name = "cvi.allocation"
    _description = "Imputación de un cobro sobre una cuota"
    _order = "installment_id, id"

    payment_id = fields.Many2one(
        "cvi.payment", string="Cobro", required=True, ondelete="cascade", index=True
    )
    installment_id = fields.Many2one(
        "cvi.installment", string="Cuota", required=True, ondelete="cascade", index=True
    )
    card_id = fields.Many2one(
        related="installment_id.card_id", store=True, index=True, string="Tarjeta"
    )
    currency_id = fields.Many2one(related="installment_id.currency_id", readonly=True)
    amount = fields.Monetary(
        string="Monto imputado", required=True, currency_field="currency_id"
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto imputado debe ser mayor a cero.",
        ),
    ]
```

Registrar en `models/__init__.py` (después de `cvi_installment`, antes de `res_company`):

```python
from . import cvi_allocation
```

Agregar accesos en `security/ir.model.access.csv`:

```csv
access_cvi_allocation_vendor,cvi.allocation vendedor,model_cvi_allocation,collections_from_vendors_installments.group_cvi_vendor,1,0,0,0
access_cvi_allocation_collector,cvi.allocation cobrador,model_cvi_allocation,collections_from_vendors_installments.group_cvi_collector,1,1,1,0
access_cvi_allocation_manager,cvi.allocation administrador,model_cvi_allocation,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
```

> `cvi.allocation.payment_id` apunta a `cvi.payment`, que se crea en la Task 5. Para que este paso cargue, la Task 5 debe ejecutarse a continuación sin interrupciones; si se corre el módulo ahora fallará con `Many2one field payment_id: unknown comodel cvi.payment`. **Por eso el modelo `cvi.payment` mínimo también se crea en esta task**, en el paso 8.

- [ ] **Step 8: Crear el modelo `cvi.payment` mínimo (solo estructura; la lógica va en la Task 5)**

`collections_from_vendors_installments/models/cvi_payment.py`:

```python
# -*- coding: utf-8 -*-
from odoo import _, fields, models

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("posted", "Registrado"),
    ("cancel", "Anulado"),
]


class CviPayment(models.Model):
    _name = "cvi.payment"
    _description = "Cobro de cuotas de una tarjeta"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        default=lambda self: _("Nuevo"),
    )
    card_id = fields.Many2one(
        "cvi.card", string="Tarjeta", required=True, ondelete="restrict", index=True
    )
    partner_id = fields.Many2one(
        related="card_id.partner_id", store=True, index=True, string="Cliente"
    )
    company_id = fields.Many2one(related="card_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="card_id.currency_id", readonly=True)
    date = fields.Date(
        string="Fecha", required=True, default=fields.Date.context_today, index=True
    )
    amount = fields.Monetary(
        string="Monto cobrado", required=True, currency_field="currency_id"
    )
    user_id = fields.Many2one(
        "res.users", string="Cobrado por", required=True,
        default=lambda self: self.env.user, readonly=True, index=True,
    )
    is_commission = fields.Boolean(
        string="Comisión del vendedor", default=False,
        help="Marca el cobro de la primera cuota, que hace el vendedor (RN-01).",
    )
    state = fields.Selection(
        selection=STATE_SELECTION, string="Estado", default="draft",
        required=True, copy=False, tracking=True, index=True,
    )
    allocation_ids = fields.One2many(
        "cvi.allocation", "payment_id", string="Imputaciones"
    )
    note = fields.Char(string="Observación")

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto cobrado debe ser mayor a cero.",
        ),
    ]
```

Registrar en `models/__init__.py` — el orden final del archivo queda:

```python
# -*- coding: utf-8 -*-
from . import cvi_card
from . import cvi_installment
from . import cvi_payment
from . import cvi_allocation
from . import res_company
from . import res_config_settings
```

Agregar accesos en `security/ir.model.access.csv`:

```csv
access_cvi_payment_vendor,cvi.payment vendedor,model_cvi_payment,collections_from_vendors_installments.group_cvi_vendor,1,1,1,0
access_cvi_payment_collector,cvi.payment cobrador,model_cvi_payment,collections_from_vendors_installments.group_cvi_collector,1,1,1,0
access_cvi_payment_manager,cvi.payment administrador,model_cvi_payment,collections_from_vendors_installments.group_cvi_manager,1,1,1,0
```

> `perm_unlink` es 0 para todos los roles, incluido el administrador: RN-06 exige que un cobro no se borre, solo se anule.

- [ ] **Step 9: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 17 tests de `TestCviInstallmentSchedule` en verde.

- [ ] **Step 10: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): cuotas, calendario por frecuencia y cron de vencidas"
```

---

## Task 5: Cobros con imputación FIFO y anulación

Cubre HU-15 (registrar el cobro, parcial y multi-cuota) y RN-06 (los cobros no se borran, se anulan).

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_payment.py` (agregar `create`, `action_post`, `action_cancel`, `_cvi_allocate`)
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_payment.py`

**Interfaces:**
- Consumes: `cvi.card` (Task 3), `cvi.installment` con `amount_residual`, `state`, `is_commission`, `sequence`, `date_due` (Task 4), `cvi.allocation` con `payment_id`, `installment_id`, `amount` (Task 4).
- Produces:
  - `cvi.payment.action_post()` → publica el cobro e imputa FIFO sobre las cuotas impagas de la tarjeta.
  - `cvi.payment.action_cancel()` → anula un cobro publicado, borra sus imputaciones y deja registro en el chatter de la tarjeta.
  - `cvi.payment._cvi_allocate()` → helper interno que reparte `amount` sobre las cuotas; devuelve el sobrante no imputado (`float`).

**Reglas de imputación** (fijadas acá):
- Se imputa sobre las cuotas de la tarjeta con `amount_residual > 0`, ordenadas por `date_due`, luego `sequence` (FIFO por vencimiento).
- Un cobro de comisión (`is_commission=True`) solo imputa sobre cuotas con `is_commission=True`; un cobro normal solo sobre cuotas con `is_commission=False`. Así el cobrador nunca ve como pendiente la cuota del vendedor (HU-09).
- Si el monto cobrado supera el residual total imputable, se rechaza con `UserError`: no se aceptan pagos en exceso.
- Un cobro parcial imputa lo que alcanza y deja la cuota en `partial`.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_payment.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviPayment(CviCommon):

    def setUp(self):
        super().setUp()
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_12.id,
            "charge_day_month": 10,
        })
        self.card._cvi_generate_installments()

    def _pay(self, amount, **kwargs):
        """Cobro publicado sobre la tarjeta de test."""
        vals = {"card_id": self.card.id, "amount": amount, "date": "2026-02-10"}
        vals.update(kwargs)
        payment = self.env["cvi.payment"].create(vals)
        payment.action_post()
        return payment

    def _installment(self, sequence):
        return self.card.installment_ids.filtered(lambda i: i.sequence == sequence)

    def test_payment_gets_sequence_reference(self):
        """El cobro recibe una referencia de la secuencia."""
        payment = self._pay(10000.0)
        self.assertTrue(payment.name.startswith("COB/"))

    def test_posting_sets_state_posted(self):
        """Publicar un cobro lo deja en estado Registrado."""
        self.assertEqual(self._pay(10000.0).state, "posted")

    def test_exact_installment_payment_marks_it_paid(self):
        """Un cobro por el importe exacto de una cuota la deja pagada."""
        self._pay(10000.0)
        self.assertEqual(self._installment(2).state, "paid")
        self.assertEqual(self._installment(2).amount_residual, 0.0)

    def test_partial_payment_leaves_installment_partial(self):
        """Un cobro por menos del importe deja la cuota parcial con residual."""
        self._pay(4000.0)
        second = self._installment(2)
        self.assertEqual(second.state, "partial")
        self.assertEqual(second.amount_paid, 4000.0)
        self.assertEqual(second.amount_residual, 6000.0)

    def test_payment_covers_multiple_installments(self):
        """Un cobro grande cubre varias cuotas de una sola vez."""
        self._pay(25000.0)
        self.assertEqual(self._installment(2).state, "paid")
        self.assertEqual(self._installment(3).state, "paid")
        self.assertEqual(self._installment(4).state, "partial")
        self.assertEqual(self._installment(4).amount_paid, 5000.0)

    def test_allocation_is_fifo_by_due_date(self):
        """La imputación arranca por la cuota de cobranza más vieja impaga."""
        self._pay(10000.0)
        allocated = self._pay(10000.0).allocation_ids
        self.assertEqual(len(allocated), 1)
        self.assertEqual(allocated.installment_id.sequence, 3)

    def test_commission_payment_only_hits_commission_installment(self):
        """El cobro de comisión imputa sobre la cuota 1, no sobre las de cobranza."""
        payment = self._pay(10000.0, is_commission=True, date="2026-01-15")
        self.assertEqual(payment.allocation_ids.installment_id.sequence, 1)
        self.assertEqual(self._installment(1).state, "paid")
        self.assertEqual(self._installment(2).state, "pending")

    def test_regular_payment_never_hits_commission_installment(self):
        """Un cobro normal saltea la cuota del vendedor aunque esté impaga (HU-09)."""
        payment = self._pay(10000.0)
        self.assertEqual(payment.allocation_ids.installment_id.sequence, 2)
        self.assertEqual(self._installment(1).state, "pending")

    def test_overpayment_is_rejected(self):
        """No se acepta un cobro que supera lo que la tarjeta adeuda."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 999999.0, "date": "2026-02-10",
        })
        with self.assertRaises(UserError):
            payment.action_post()

    def test_posting_twice_is_rejected(self):
        """Un cobro ya publicado no se vuelve a publicar."""
        payment = self._pay(10000.0)
        with self.assertRaises(UserError):
            payment.action_post()

    def test_cancel_releases_the_installment(self):
        """Anular un cobro devuelve la cuota a pendiente (RN-06)."""
        payment = self._pay(10000.0)
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")
        self.assertFalse(payment.allocation_ids)
        self.assertEqual(self._installment(2).amount_paid, 0.0)

    def test_cancelled_payment_keeps_its_record(self):
        """El cobro anulado sigue existiendo con su monto y su usuario (RN-06)."""
        payment = self._pay(10000.0)
        payment.action_cancel()
        self.assertTrue(payment.exists())
        self.assertEqual(payment.amount, 10000.0)
        self.assertEqual(payment.user_id, self.env.user)

    def test_payment_cannot_be_deleted(self):
        """Un cobro publicado no se puede borrar, ni siquiera por el administrador."""
        payment = self._pay(10000.0)
        with self.assertRaises(UserError):
            payment.unlink()

    def test_draft_payment_can_be_deleted(self):
        """Un cobro en borrador (todavía sin publicar) sí se puede descartar."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 5000.0, "date": "2026-02-10",
        })
        payment.unlink()
        self.assertFalse(payment.exists())

    def test_payment_records_who_charged(self):
        """Queda registrado quién cobró y cuándo (RN-06, RN-08)."""
        payment = self._pay(10000.0)
        self.assertEqual(payment.user_id, self.env.user)
        self.assertEqual(str(payment.date), "2026-02-10")
```

Registrar en `tests/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import test_config
from . import test_product_plan
from . import test_card
from . import test_installment_schedule
from . import test_payment
```

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviPayment \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `AttributeError: 'cvi.payment' object has no attribute 'action_post'`.

- [ ] **Step 3: Escribir la lógica de cobro**

En `models/cvi_payment.py`, cambiar la línea de imports por:

```python
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero
```

y agregar estos métodos al final de la clase `CviPayment`:

```python
    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia desde la secuencia al crear."""
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cvi.payment") or _("Nuevo")
        return super().create(vals_list)

    def unlink(self):
        """Un cobro publicado o anulado nunca se borra: queda como registro (RN-06)."""
        if any(payment.state != "draft" for payment in self):
            raise UserError(_(
                "Un cobro registrado no se puede eliminar. Anulalo con el botón Anular "
                "para que quede constancia."
            ))
        return super().unlink()

    def _cvi_target_installments(self):
        """Cuotas candidatas a recibir esta imputación, en orden FIFO por vencimiento.

        Un cobro de comisión solo toca la cuota del vendedor; un cobro normal solo toca
        las cuotas de cobranza. Así el cobrador nunca ve la comisión como pendiente (HU-09).
        """
        self.ensure_one()
        return self.card_id.installment_ids.filtered(
            lambda i: i.amount_residual > 0 and i.is_commission == self.is_commission
        ).sorted(lambda i: (i.date_due, i.sequence))

    def _cvi_allocate(self):
        """Reparte el monto del cobro sobre las cuotas candidatas. Devuelve el sobrante."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        remaining = self.amount
        vals_list = []
        for installment in self._cvi_target_installments():
            if float_is_zero(remaining, precision_rounding=rounding):
                break
            applied = min(remaining, installment.amount_residual)
            vals_list.append({
                "payment_id": self.id,
                "installment_id": installment.id,
                "amount": applied,
            })
            remaining -= applied
        if vals_list:
            self.env["cvi.allocation"].create(vals_list)
        return remaining

    def action_post(self):
        """Publica el cobro e imputa su monto sobre las cuotas impagas (HU-15)."""
        for payment in self:
            if payment.state != "draft":
                raise UserError(_(
                    "El cobro %s ya fue registrado: no se puede volver a registrar.",
                    payment.name,
                ))
            payment.state = "posted"
            leftover = payment._cvi_allocate()
            rounding = payment.currency_id.rounding or 0.01
            if float_compare(leftover, 0.0, precision_rounding=rounding) > 0:
                raise UserError(_(
                    "El cobro de %(amount)s supera lo que adeuda la tarjeta %(card)s: "
                    "sobran %(left)s sin imputar.",
                    amount=payment.amount,
                    card=payment.card_id.name,
                    left=leftover,
                ))
            payment.card_id._cvi_log(_(
                "Cobro %(name)s por %(amount)s registrado por %(user)s.",
                name=payment.name, amount=payment.amount, user=payment.user_id.name,
            ))
        return True

    def action_cancel(self):
        """Anula el cobro y libera las cuotas que había imputado (RN-06)."""
        for payment in self:
            if payment.state != "posted":
                raise UserError(_(
                    "Solo se puede anular un cobro registrado (el cobro %s está en estado %s).",
                    payment.name, payment.state,
                ))
            payment.allocation_ids.unlink()
            payment.state = "cancel"
            payment.card_id._cvi_log(_(
                "Cobro %(name)s por %(amount)s ANULADO por %(user)s.",
                name=payment.name, amount=payment.amount, user=self.env.user.name,
            ))
        return True
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 15 tests de `TestCviPayment` en verde.

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): cobros con imputación FIFO, parciales y anulación"
```

---

## Task 6: Confirmar la venta — comisión del vendedor y campos inmutables

Cubre HU-09 (cobro de la primera cuota como comisión) y RN-05 (precio, cuotas e importe congelados tras confirmar).

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_card.py` (agregar `action_confirm`, `action_cancel`, `write`)
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_card_confirm.py`

**Interfaces:**
- Consumes: `cvi.card._cvi_generate_installments()` (Task 4), `cvi.payment.action_post()` y el flag `is_commission` (Task 5).
- Produces:
  - `cvi.card.action_confirm()` → genera el calendario, crea y publica el cobro de comisión de la cuota 1, pasa a `sold` (o a `routed` si ya tiene `collector_id`).
  - `cvi.card.action_cancel()` → pasa a `cancel` desde `draft` o `sold`.
  - Constante de módulo `CVI_FROZEN_FIELDS = ("plan_id", "installment_count", "installment_amount", "frequency", "product_id", "quantity")` en `cvi_card.py`. `amount_total` no hace falta: es computado a partir de dos campos ya congelados.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_card_confirm.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCardConfirm(CviCommon):

    def _card(self, **kwargs):
        """Tarjeta en borrador con valores mínimos, sobreescribibles."""
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_12.id,
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_confirm_moves_card_to_sold(self):
        """Confirmar una venta sin cobrador la deja Vendida."""
        card = self._card()
        card.action_confirm()
        self.assertEqual(card.state, "sold")

    def test_confirm_generates_the_schedule(self):
        """Confirmar genera el calendario completo de cuotas del plan (HU-06)."""
        card = self._card(plan_id=self.plan_12.id)
        card.action_confirm()
        self.assertEqual(len(card.installment_ids), 12)

    def test_confirm_charges_the_first_installment(self):
        """La primera cuota queda cobrada por el vendedor al confirmar (HU-09, RN-01)."""
        card = self._card()
        card.action_confirm()
        first = card.installment_ids.filtered(lambda i: i.sequence == 1)
        self.assertEqual(first.state, "paid")

    def test_commission_payment_is_flagged_and_attributed_to_vendor(self):
        """El cobro de la comisión se identifica por separado y queda a nombre del vendedor."""
        card = self._card()
        card.action_confirm()
        commission = card.payment_ids.filtered("is_commission")
        self.assertEqual(len(commission), 1)
        self.assertEqual(commission.amount, card.installment_amount)
        self.assertEqual(commission.user_id, self.vendor_user)
        self.assertEqual(commission.state, "posted")

    def test_second_installment_stays_pending_after_confirm(self):
        """Confirmar no toca las cuotas de cobranza: siguen pendientes para el cobrador."""
        card = self._card()
        card.action_confirm()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "pending")

    def test_confirm_with_collector_goes_straight_to_routed(self):
        """Si el vendedor eligió cobrador al cargar la venta, la tarjeta queda enrutada (HU-10)."""
        card = self._card(collector_id=self.collector_user.id)
        card.action_confirm()
        self.assertEqual(card.state, "routed")

    def test_confirming_twice_is_rejected(self):
        """Una tarjeta ya confirmada no se vuelve a confirmar."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.action_confirm()

    def test_plan_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar el plan, que es lo que fija el precio (RN-05)."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.plan_id = self.plan_3.id

    def test_price_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar el importe de cuota (RN-05)."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.installment_amount = 20000.0

    def test_installment_count_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar la cantidad de cuotas (RN-05)."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.installment_count = 6

    def test_product_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar el modelo de mueble vendido (RN-05)."""
        card = self._card()
        card.action_confirm()
        other = self.env["product.product"].create({
            "name": "Mesa de luz", "type": "consu", "is_storable": True,
        })
        with self.assertRaises(UserError):
            card.product_id = other.id

    def test_collector_can_still_be_changed_after_confirm(self):
        """El cobrador sí se puede cambiar tras confirmar: es el enrutamiento (HU-11, HU-30)."""
        card = self._card()
        card.action_confirm()
        card.collector_id = self.collector_user.id
        self.assertEqual(card.collector_id, self.collector_user)

    def test_plan_can_be_changed_while_draft(self):
        """En borrador el vendedor todavía puede cambiar de plan y reprecia la venta."""
        card = self._card()
        card.plan_id = self.plan_3.id
        self.assertEqual(card.installment_count, 3)
        self.assertEqual(card.amount_total, 30000.0)

    def test_cancel_from_draft(self):
        """Una tarjeta en borrador se puede anular."""
        card = self._card()
        card.action_cancel()
        self.assertEqual(card.state, "cancel")

    def test_cancel_from_sold(self):
        """Una tarjeta vendida sin cobrar cuotas de cobranza se puede anular."""
        card = self._card()
        card.action_confirm()
        card.action_cancel()
        self.assertEqual(card.state, "cancel")
```

Registrar en `tests/__init__.py` agregando `from . import test_card_confirm`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviCardConfirm \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `AttributeError: 'cvi.card' object has no attribute 'action_confirm'`.

- [ ] **Step 3: Escribir la confirmación y el congelamiento de campos**

En `models/cvi_card.py`, agregar el import de `UserError` (la línea de excepciones queda así):

```python
from odoo.exceptions import UserError, ValidationError
```

Agregar debajo de `WEEKDAY_PLURAL` la constante:

```python
CVI_FROZEN_FIELDS = (
    "plan_id",
    "installment_count",
    "installment_amount",
    "frequency",
    "product_id",
    "quantity",
)
```

Agregar el campo `payment_ids` junto a `installment_ids`:

```python
    payment_ids = fields.One2many(
        "cvi.payment", "card_id", string="Cobros", copy=False
    )
```

Y agregar estos métodos al final de la clase:

```python
    def write(self, vals):
        """Congela precio, cuotas y mercadería una vez confirmada la venta (RN-05)."""
        frozen = [name for name in CVI_FROZEN_FIELDS if name in vals]
        if frozen:
            locked = self.filtered(lambda c: c.state not in ("draft", "cancel"))
            if locked:
                labels = ", ".join(self._fields[name].string for name in frozen)
                raise UserError(_(
                    "No se puede modificar %(fields)s en la tarjeta %(card)s: "
                    "la venta ya está confirmada.",
                    fields=labels,
                    card=locked[0].name,
                ))
        return super().write(vals)

    def _cvi_charge_commission(self):
        """Registra el cobro de la primera cuota, que se lleva el vendedor (RN-01, HU-09)."""
        self.ensure_one()
        first = self.installment_ids.filtered(lambda i: i.is_commission)
        payment = self.env["cvi.payment"].create({
            "card_id": self.id,
            "date": self.date_sale,
            "amount": first.amount,
            "user_id": self.vendor_id.id,
            "is_commission": True,
            "note": _("Primera cuota cobrada por el vendedor (comisión)."),
        })
        payment.action_post()
        return payment

    def action_confirm(self):
        """Confirma la venta: genera las cuotas y cobra la primera como comisión."""
        for card in self:
            if card.state != "draft":
                raise UserError(_(
                    "La tarjeta %(card)s ya fue confirmada (estado: %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            card._cvi_generate_installments()
            card._cvi_charge_commission()
            card.state = "routed" if card.collector_id else "sold"
            card._cvi_log(_(
                "Venta confirmada por %(user)s: %(count)s cuotas de %(amount)s.",
                user=card.vendor_id.name,
                count=card.installment_count,
                amount=card.installment_amount,
            ))
        return True

    def action_cancel(self):
        """Anula la tarjeta. Solo desde borrador o vendida, antes de entrar en cobranza."""
        for card in self:
            if card.state not in ("draft", "sold"):
                raise UserError(_(
                    "La tarjeta %(card)s no se puede anular en estado %(state)s.",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            card.state = "cancel"
            card._cvi_log(_("Tarjeta anulada por %s.", self.env.user.name))
        return True
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 14 tests de `TestCviCardConfirm` en verde.

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): confirmación de venta, comisión del vendedor y campos congelados"
```

---

## Task 7: Saldo de la tarjeta y cierre automático

Cubre HU-16 (estado de la tarjeta: pagadas, pendientes, vencidas, saldo) y HU-17 (cierre automático al saldar).

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_card.py` (agregar campos computados de saldo y el cierre automático)
- Modify: `collections_from_vendors_installments/models/cvi_payment.py` (invocar el cierre desde `action_post` y `action_cancel`)
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_card_state.py`

**Interfaces:**
- Consumes: `cvi.installment.amount_paid`, `.amount_residual`, `.state`, `.is_commission` (Task 4); `cvi.card.state` (Task 3).
- Produces, en `cvi.card`:
  - `amount_paid` (Monetary compute store) — total cobrado, incluida la comisión.
  - `amount_residual` (Monetary compute store) — lo que falta cobrar.
  - `paid_installment_count`, `pending_installment_count`, `overdue_installment_count` (Integer compute store).
  - `next_due_date` (Date compute store) — vencimiento de la cuota de cobranza impaga más próxima.
  - `_cvi_check_settlement()` — pasa a `done` cuando el residual llega a cero, y de `done` vuelve a `active` si se anula un cobro.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_card_state.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCardState(CviCommon):

    def setUp(self):
        super().setUp()
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _pay(self, amount):
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": amount, "date": "2026-02-10",
        })
        payment.action_post()
        return payment

    def test_amount_paid_includes_commission(self):
        """Tras confirmar, lo cobrado es la comisión de la primera cuota."""
        self.assertEqual(self.card.amount_paid, 10000.0)

    def test_amount_residual_is_what_is_left(self):
        """El residual de la tarjeta es el total menos lo cobrado."""
        self.assertEqual(self.card.amount_residual, 20000.0)

    def test_counts_after_confirm(self):
        """Con la comisión cobrada: 1 cuota pagada, 2 pendientes (HU-16)."""
        self.assertEqual(self.card.paid_installment_count, 1)
        self.assertEqual(self.card.pending_installment_count, 2)

    def test_next_due_date_is_next_unpaid_collection_installment(self):
        """La próxima fecha de cobro es la de la cuota 2 (la 1 ya está cobrada)."""
        self.assertEqual(str(self.card.next_due_date), "2026-02-10")

    def test_paying_advances_the_next_due_date(self):
        """Al cobrar la cuota 2, la próxima fecha pasa a la de la cuota 3."""
        self._pay(10000.0)
        self.assertEqual(str(self.card.next_due_date), "2026-03-10")

    def test_partial_payment_updates_balance(self):
        """Un cobro parcial actualiza el saldo de la tarjeta al instante (HU-15)."""
        self._pay(4000.0)
        self.assertEqual(self.card.amount_paid, 14000.0)
        self.assertEqual(self.card.amount_residual, 16000.0)

    def test_card_closes_when_fully_paid(self):
        """Al cubrirse el total, la tarjeta pasa sola a Finalizada (HU-17)."""
        self._pay(20000.0)
        self.assertEqual(self.card.amount_residual, 0.0)
        self.assertEqual(self.card.state, "done")

    def test_card_does_not_close_while_residual_remains(self):
        """Mientras quede residual, la tarjeta sigue en cobranza."""
        self._pay(19999.0)
        self.assertEqual(self.card.state, "active")

    def test_cancelling_a_payment_reopens_a_closed_card(self):
        """Anular un cobro sobre una tarjeta saldada la devuelve a cobranza."""
        payment = self._pay(20000.0)
        self.assertEqual(self.card.state, "done")
        payment.action_cancel()
        self.assertEqual(self.card.state, "active")
        self.assertEqual(self.card.amount_residual, 20000.0)

    def test_overdue_count_reflects_late_installments(self):
        """Las cuotas impagas ya vencidas se cuentan como vencidas (HU-16)."""
        self.company.cvi_overdue_days = 0
        old = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        old.action_confirm()
        self.assertEqual(old.overdue_installment_count, 2)
```

Registrar en `tests/__init__.py` agregando `from . import test_card_state`.

> Estos tests usan `card.action_accept()`, que se implementa en la Task 8. Si la Task 8 todavía no está hecha, este archivo de test fallará por `AttributeError`. **Ejecutar la Task 8 antes que la 6 no es necesario**: el paso 3 de esta task agrega un `action_accept()` mínimo que solo cambia el estado, y la Task 8 lo completa con las validaciones de rol.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviCardState \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `AttributeError: 'cvi.card' object has no attribute 'action_accept'`.

- [ ] **Step 3: Escribir los campos de saldo, el cierre automático y el `action_accept` mínimo**

En `models/cvi_card.py`, agregar el import de `float_is_zero`:

```python
from odoo.tools import float_is_zero
```

Agregar estos campos después de `payment_ids`:

```python
    amount_paid = fields.Monetary(
        string="Cobrado",
        compute="_compute_balance",
        store=True,
        currency_field="currency_id",
    )
    amount_residual = fields.Monetary(
        string="Saldo",
        compute="_compute_balance",
        store=True,
        currency_field="currency_id",
    )
    paid_installment_count = fields.Integer(
        string="Cuotas pagadas", compute="_compute_balance", store=True
    )
    pending_installment_count = fields.Integer(
        string="Cuotas pendientes", compute="_compute_balance", store=True
    )
    overdue_installment_count = fields.Integer(
        string="Cuotas vencidas", compute="_compute_balance", store=True
    )
    next_due_date = fields.Date(
        string="Próximo vencimiento", compute="_compute_balance", store=True, index=True
    )
```

Y estos métodos al final de la clase:

```python
    @api.depends(
        "amount_total",
        "installment_ids.amount_paid",
        "installment_ids.amount_residual",
        "installment_ids.state",
        "installment_ids.date_due",
    )
    def _compute_balance(self):
        """Resume el estado de cobranza de la tarjeta a partir de sus cuotas (HU-16)."""
        for card in self:
            installments = card.installment_ids
            card.amount_paid = sum(installments.mapped("amount_paid"))
            card.amount_residual = sum(installments.mapped("amount_residual"))
            card.paid_installment_count = len(
                installments.filtered(lambda i: i.state == "paid")
            )
            card.pending_installment_count = len(
                installments.filtered(lambda i: i.state in ("pending", "partial"))
            )
            card.overdue_installment_count = len(
                installments.filtered(lambda i: i.state == "overdue")
            )
            upcoming = installments.filtered(
                lambda i: not i.is_commission and i.amount_residual > 0
            ).sorted("date_due")
            card.next_due_date = upcoming[0].date_due if upcoming else False

    def _cvi_check_settlement(self):
        """Cierra la tarjeta al saldarse y la reabre si un cobro se anula (HU-17)."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        settled = float_is_zero(self.amount_residual, precision_rounding=rounding)
        if settled and self.state in ("sold", "routed", "active"):
            self.state = "done"
            self._cvi_log(_("Tarjeta saldada: pasa a Finalizada."))
        elif not settled and self.state == "done":
            self.state = "active"
            self._cvi_log(_(
                "La tarjeta vuelve a cobranza: quedó saldo pendiente tras anular un cobro."
            ))

    def action_accept(self):
        """El cobrador acepta la tarjeta enrutada y se hace responsable (RN-02, HU-12)."""
        for card in self:
            if card.state != "routed":
                raise UserError(_(
                    "Solo se puede aceptar una tarjeta enrutada (la tarjeta %(card)s "
                    "está en estado %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            card.state = "active"
            card._cvi_log(_(
                "Tarjeta aceptada por %s: se hace responsable de la cobranza.",
                card.collector_id.name,
            ))
        return True
```

> `_cvi_check_settlement()` **no** se llama desde el compute: escribir `state` dentro de un
> método computado es frágil (durante `create` el registro puede tener un `NewId`, y Odoo
> puede reordenar los recomputes). Se lo invoca explícitamente desde el cobro, que es el
> único evento que cambia el saldo. Eso se conecta en el paso siguiente.

- [ ] **Step 4: Conectar el cierre automático al registro y a la anulación de cobros**

En `models/cvi_payment.py`, agregar la llamada al final del `for` de `action_post`, después del `_cvi_log`:

```python
            payment.card_id._cvi_check_settlement()
```

Y lo mismo al final del `for` de `action_cancel`, después de su `_cvi_log`:

```python
            payment.card_id._cvi_check_settlement()
```

> En `action_post` la llamada llega también desde `_cvi_charge_commission()` al confirmar la
> venta, pero ahí la tarjeta todavía está en `draft`, y `_cvi_check_settlement()` solo actúa
> sobre `sold`, `routed`, `active` y `done`. No hay efecto colateral.

- [ ] **Step 5: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 10 tests de `TestCviCardState` en verde.

- [ ] **Step 6: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): saldo de la tarjeta y cierre automático al saldar"
```

---

## Task 8: Enrutamiento de la tarjeta al cobrador — enviar, aceptar, rechazar

Cubre HU-10 (enrutar al momento de la venta), HU-12 (aceptar) y HU-13 (rechazar con motivo).

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_card.py` (agregar `reject_reason`, `action_route`, completar `action_accept`, agregar `action_reject`)
- Create: `collections_from_vendors_installments/wizards/__init__.py`
- Create: `collections_from_vendors_installments/wizards/cvi_reject_wizard.py`
- Modify: `collections_from_vendors_installments/__init__.py`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_routing.py`

**Interfaces:**
- Consumes: `cvi.card.state`, `collector_id` (Task 3); `action_confirm()` (Task 6); `action_accept()` mínimo (Task 7).
- Produces:
  - Campo `cvi.card.reject_reason` (Char) — motivo del último rechazo, visible para el vendedor.
  - `cvi.card.action_route()` → `sold` → `routed`, requiere `collector_id`.
  - `cvi.card.action_accept()` completo → solo el cobrador destinatario (o un administrador) puede aceptar.
  - `cvi.card.action_reject(reason)` → `routed` → `sold`, limpia `collector_id` y guarda el motivo.
  - `cvi.card.action_open_reject_wizard()` → abre el wizard de rechazo.
  - Modelo transitorio `cvi.reject.wizard` con `card_ids` (Many2many) y `reason` (Char required) y método `action_confirm_reject()`.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_routing.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviRouting(CviCommon):

    def _confirmed_card(self, **kwargs):
        """Tarjeta confirmada (estado Vendida) sin cobrador asignado."""
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        card = self.env["cvi.card"].create(vals)
        card.action_confirm()
        return card

    def test_route_moves_card_to_routed(self):
        """Asignar un cobrador y enrutar deja la tarjeta a la espera de aceptación (HU-10)."""
        card = self._confirmed_card()
        card.collector_id = self.collector_user.id
        card.action_route()
        self.assertEqual(card.state, "routed")

    def test_route_without_collector_is_rejected(self):
        """No se puede enrutar sin elegir a quién."""
        card = self._confirmed_card()
        with self.assertRaises(UserError):
            card.action_route()

    def test_routed_card_is_not_in_active_portfolio(self):
        """Mientras no acepte, la tarjeta no está en la cartera activa del cobrador (RN-02)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_route() if card.state == "sold" else None
        self.assertEqual(card.state, "routed")
        active = self.env["cvi.card"].search([
            ("collector_id", "=", self.collector_user.id), ("state", "=", "active"),
        ])
        self.assertNotIn(card, active)

    def test_accept_moves_card_to_active(self):
        """Aceptar pone la tarjeta en la cartera activa del cobrador (HU-12)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.with_user(self.collector_user).action_accept()
        self.assertEqual(card.state, "active")

    def test_only_the_target_collector_can_accept(self):
        """Otro cobrador no puede aceptar una tarjeta que no le fue enrutada."""
        other = self.env["res.users"].create({
            "name": "Otro Cobrador",
            "login": "cvi_collector_other",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        card = self._confirmed_card(collector_id=self.collector_user.id)
        with self.assertRaises(UserError):
            card.with_user(other).action_accept()

    def test_manager_can_accept_on_behalf_of_collector(self):
        """El administrador puede aceptar por el cobrador (traspasos de oficina)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_accept()
        self.assertEqual(card.state, "active")

    def test_accepting_a_non_routed_card_is_rejected(self):
        """No se puede aceptar una tarjeta que no está enrutada."""
        card = self._confirmed_card()
        with self.assertRaises(UserError):
            card.action_accept()

    def test_reject_returns_card_to_vendor(self):
        """Rechazar devuelve la tarjeta al vendedor y libera el cobrador (HU-13)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_reject("Zona que no recorro")
        self.assertEqual(card.state, "sold")
        self.assertFalse(card.collector_id)

    def test_reject_stores_the_reason(self):
        """El motivo del rechazo queda visible para el vendedor (HU-13)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_reject("Zona que no recorro")
        self.assertEqual(card.reject_reason, "Zona que no recorro")

    def test_reject_without_reason_is_rejected(self):
        """El motivo es obligatorio al rechazar."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        with self.assertRaises(UserError):
            card.action_reject("")

    def test_rejecting_a_non_routed_card_is_rejected(self):
        """Solo se rechaza una tarjeta enrutada."""
        card = self._confirmed_card()
        with self.assertRaises(UserError):
            card.action_reject("No corresponde")

    def test_reject_wizard_rejects_all_selected_cards(self):
        """El wizard de rechazo aplica el mismo motivo a todas las tarjetas elegidas."""
        cards = self._confirmed_card(collector_id=self.collector_user.id)
        cards |= self._confirmed_card(collector_id=self.collector_user.id)
        wizard = self.env["cvi.reject.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "reason": "Ruta discontinuada",
        })
        wizard.action_confirm_reject()
        self.assertEqual(set(cards.mapped("state")), {"sold"})
        self.assertEqual(set(cards.mapped("reject_reason")), {"Ruta discontinuada"})

    def test_rerouting_after_reject_clears_the_reason(self):
        """Al volver a enrutar, el motivo del rechazo anterior se limpia."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_reject("Zona que no recorro")
        card.collector_id = self.collector_user.id
        card.action_route()
        self.assertFalse(card.reject_reason)
```

Registrar en `tests/__init__.py` agregando `from . import test_routing`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviRouting \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `AttributeError: 'cvi.card' object has no attribute 'action_route'`.

- [ ] **Step 3: Agregar el campo de motivo y los métodos de enrutamiento**

En `models/cvi_card.py`, agregar el campo después de `state`:

```python
    reject_reason = fields.Char(
        string="Motivo del rechazo",
        readonly=True,
        copy=False,
        help="Motivo por el que el cobrador devolvió la tarjeta al vendedor.",
    )
```

Reemplazar el `action_accept()` que dejó la Task 7 por esta versión completa, y agregar `action_route` y `action_reject`:

```python
    def action_route(self):
        """Envía la tarjeta al cobrador elegido, a la espera de que la acepte (HU-10)."""
        for card in self:
            if card.state != "sold":
                raise UserError(_(
                    "Solo se puede enrutar una tarjeta vendida (la tarjeta %(card)s "
                    "está en estado %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            if not card.collector_id:
                raise UserError(_(
                    "Elegí a qué cobrador enviar la tarjeta %s antes de enrutarla.",
                    card.name,
                ))
            card.state = "routed"
            card.reject_reason = False
            card._cvi_log(_(
                "Tarjeta enrutada a %(collector)s por %(user)s.",
                collector=card.collector_id.name, user=self.env.user.name,
            ))
        return True

    def action_accept(self):
        """El cobrador acepta la tarjeta enrutada y se hace responsable (RN-02, HU-12)."""
        is_manager = self.env.user.has_group(
            "collections_from_vendors_installments.group_cvi_manager"
        )
        for card in self:
            if card.state != "routed":
                raise UserError(_(
                    "Solo se puede aceptar una tarjeta enrutada (la tarjeta %(card)s "
                    "está en estado %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            if not is_manager and card.collector_id != self.env.user:
                raise UserError(_(
                    "La tarjeta %(card)s fue enrutada a %(collector)s: no la podés aceptar.",
                    card=card.name, collector=card.collector_id.name,
                ))
            card.state = "active"
            card._cvi_log(_(
                "Tarjeta aceptada por %s: se hace responsable de la cobranza.",
                card.collector_id.name,
            ))
        return True

    def action_reject(self, reason):
        """El cobrador devuelve la tarjeta al vendedor indicando un motivo (HU-13)."""
        if not reason or not reason.strip():
            raise UserError(_("Indicá el motivo del rechazo."))
        for card in self:
            if card.state != "routed":
                raise UserError(_(
                    "Solo se puede rechazar una tarjeta enrutada (la tarjeta %(card)s "
                    "está en estado %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            previous = card.collector_id
            card.state = "sold"
            card.collector_id = False
            card.reject_reason = reason.strip()
            card._cvi_log(_(
                "Tarjeta RECHAZADA por %(collector)s: %(reason)s. Vuelve al vendedor %(vendor)s.",
                collector=previous.name, reason=card.reject_reason, vendor=card.vendor_id.name,
            ))
        return True

    def action_open_reject_wizard(self):
        """Abre el wizard que pide el motivo antes de rechazar (HU-13)."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Rechazar tarjetas"),
            "res_model": "cvi.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_card_ids": [(6, 0, self.ids)]},
        }
```

- [ ] **Step 4: Escribir el wizard de rechazo**

`collections_from_vendors_installments/wizards/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import cvi_reject_wizard
```

`collections_from_vendors_installments/wizards/cvi_reject_wizard.py`:

```python
# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class CviRejectWizard(models.TransientModel):
    _name = "cvi.reject.wizard"
    _description = "Rechazo de tarjetas enrutadas"

    card_ids = fields.Many2many(
        "cvi.card",
        string="Tarjetas",
        required=True,
        domain="[('state', '=', 'routed')]",
    )
    reason = fields.Char(string="Motivo del rechazo", required=True)

    def action_confirm_reject(self):
        """Aplica el mismo motivo de rechazo a todas las tarjetas seleccionadas."""
        self.ensure_one()
        if not self.card_ids:
            raise UserError(_("Seleccioná al menos una tarjeta para rechazar."))
        self.card_ids.action_reject(self.reason)
        return {"type": "ir.actions.act_window_close"}
```

Actualizar `collections_from_vendors_installments/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import models
from . import wizards
```

Agregar en `security/ir.model.access.csv`:

```csv
access_cvi_reject_wizard_collector,cvi.reject.wizard cobrador,model_cvi_reject_wizard,collections_from_vendors_installments.group_cvi_collector,1,1,1,1
access_cvi_reject_wizard_manager,cvi.reject.wizard administrador,model_cvi_reject_wizard,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 13 tests de `TestCviRouting` en verde.

- [ ] **Step 6: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): enrutamiento de tarjetas con aceptación y rechazo motivado"
```

---

## Task 9: Enrutamiento en lote

> **Helper de dominio por grupo.** Los tres wizards de este plan (enrutamiento en lote,
> transferencia y entrega de mercadería) restringen un `Many2one` a `res.users` por grupo.
> Resolver el grupo con `self.env.ref("...")` a secas dentro del `domain=lambda` revienta
> con `ValueError` no capturado si el xmlid no resuelve (base a medio actualizar, datos sin
> cargar), y rompe el formulario entero en vez de degradar. Definí el helper UNA vez, en
> `wizards/cvi_wizard_mixin.py`, y usalo en los tres:
>
> ```python
> # -*- coding: utf-8 -*-
> from odoo import models
>
>
> class CviWizardMixin(models.AbstractModel):
>     _name = "cvi.wizard.mixin"
>     _description = "Utilidades compartidas por los asistentes del módulo"
>
>     def _cvi_group_domain(self, group_name):
>         """Dominio que restringe un campo de usuarios a los de un grupo del módulo.
>
>         Si el xmlid del grupo no resuelve (base a medio actualizar), devuelve un dominio
>         vacío en vez de romper el formulario con un ValueError.
>         """
>         group = self.env.ref(
>             "collections_from_vendors_installments.%s" % group_name,
>             raise_if_not_found=False,
>         )
>         return [("groups_id", "in", group.id)] if group else []
> ```
>
> Cada wizard hereda con `_inherit = ["cvi.wizard.mixin"]` y declara el campo como
> `domain=lambda self: self._cvi_group_domain("group_cvi_collector")`.

Cubre HU-11 (seleccionar varias tarjetas y enviarlas juntas a un cobrador) y RNF-05 (100+ tarjetas en una sola operación).

**Files:**
- Create: `collections_from_vendors_installments/wizards/cvi_route_wizard.py`
- Modify: `collections_from_vendors_installments/wizards/__init__.py`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_route_batch.py`

**Interfaces:**
- Consumes: `cvi.card.action_route()`, `cvi.card.collector_id`, `cvi.card.state` (Task 8).
- Produces: modelo transitorio `cvi.route.wizard` con `card_ids` (Many2many `cvi.card`), `collector_id` (Many2one `res.users`, required) y `card_count` (Integer compute); método `action_confirm_route()` que asigna el cobrador y enruta en una sola escritura.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_route_batch.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviRouteBatch(CviCommon):

    def _confirmed_cards(self, how_many):
        """`how_many` tarjetas confirmadas sin cobrador asignado."""
        cards = self.env["cvi.card"]
        for _index in range(how_many):
            card = self.env["cvi.card"].create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "date_sale": "2026-01-15",
                "plan_id": self.plan_3.id,
                "charge_day_month": 10,
            })
            card.action_confirm()
            cards |= card
        return cards

    def test_batch_routes_every_selected_card(self):
        """Enviar 5 tarjetas juntas las deja todas enrutadas al mismo cobrador (HU-11)."""
        cards = self._confirmed_cards(5)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        wizard.action_confirm_route()
        self.assertEqual(set(cards.mapped("state")), {"routed"})
        self.assertEqual(set(cards.mapped("collector_id")), {self.collector_user})

    def test_card_count_reflects_selection(self):
        """El wizard muestra cuántas tarjetas se van a enviar."""
        cards = self._confirmed_cards(3)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        self.assertEqual(wizard.card_count, 3)

    def test_batch_of_one_hundred_cards(self):
        """El enrutamiento masivo resuelve 100 tarjetas en una sola operación (RNF-05)."""
        cards = self._confirmed_cards(100)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        wizard.action_confirm_route()
        self.assertEqual(len(cards.filtered(lambda c: c.state == "routed")), 100)

    def test_empty_selection_is_rejected(self):
        """No se puede confirmar el envío sin tarjetas seleccionadas."""
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, [])],
            "collector_id": self.collector_user.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_route()

    def test_already_routed_card_is_rejected(self):
        """Una tarjeta ya enrutada no se puede volver a enviar desde el wizard."""
        cards = self._confirmed_cards(1)
        cards.collector_id = self.collector_user.id
        cards.action_route()
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_route()

    def test_routed_cards_appear_as_pending_for_the_collector(self):
        """Tras el envío, las tarjetas figuran en Pendientes de aceptar del cobrador (HU-12)."""
        cards = self._confirmed_cards(4)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        wizard.action_confirm_route()
        pending = self.env["cvi.card"].search([
            ("collector_id", "=", self.collector_user.id), ("state", "=", "routed"),
        ])
        self.assertEqual(len(pending & cards), 4)
```

Registrar en `tests/__init__.py` agregando `from . import test_route_batch`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviRouteBatch \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `KeyError: 'cvi.route.wizard'`.

- [ ] **Step 3: Escribir el wizard de enrutamiento en lote**

`collections_from_vendors_installments/wizards/cvi_route_wizard.py`:

```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CviRouteWizard(models.TransientModel):
    _name = "cvi.route.wizard"
    _description = "Enrutamiento en lote de tarjetas a un cobrador"

    card_ids = fields.Many2many(
        "cvi.card",
        string="Tarjetas a enviar",
        domain="[('state', '=', 'sold')]",
    )
    collector_id = fields.Many2one(
        "res.users",
        string="Cobrador",
        required=True,
        domain=lambda self: self._cvi_group_domain("group_cvi_collector"),
    )
    card_count = fields.Integer(string="Tarjetas seleccionadas", compute="_compute_card_count")

    @api.depends("card_ids")
    def _compute_card_count(self):
        """Cuántas tarjetas se van a enviar, para confirmarlo antes de ejecutar."""
        for wizard in self:
            wizard.card_count = len(wizard.card_ids)

    def action_confirm_route(self):
        """Asigna el cobrador y enruta todas las tarjetas en una sola operación (HU-11).

        La asignación del cobrador se hace con un único write sobre todo el recordset,
        y el cambio de estado en un solo recorrido, para que 100+ tarjetas no degraden (RNF-05).
        """
        self.ensure_one()
        if not self.card_ids:
            raise UserError(_("Seleccioná al menos una tarjeta para enviar."))
        wrong_state = self.card_ids.filtered(lambda c: c.state != "sold")
        if wrong_state:
            raise UserError(_(
                "Estas tarjetas no están en estado Vendida y no se pueden enviar: %s",
                ", ".join(wrong_state.mapped("name")),
            ))
        self.card_ids.write({"collector_id": self.collector_id.id})
        self.card_ids.action_route()
        return {"type": "ir.actions.act_window_close"}
```

Actualizar `wizards/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import cvi_reject_wizard
from . import cvi_route_wizard
```

Agregar en `security/ir.model.access.csv`:

```csv
access_cvi_route_wizard_vendor,cvi.route.wizard vendedor,model_cvi_route_wizard,collections_from_vendors_installments.group_cvi_vendor,1,1,1,1
access_cvi_route_wizard_manager,cvi.route.wizard administrador,model_cvi_route_wizard,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 6 tests de `TestCviRouteBatch` en verde.

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): enrutamiento en lote de tarjetas a un cobrador"
```

---

## Task 10: Transferencia de tarjetas entre cobradores

Cubre HU-30 (transferir individual o masivamente, con registro) y RN-04 (solo el administrador puede hacerlo).

**Files:**
- Create: `collections_from_vendors_installments/wizards/cvi_transfer_wizard.py`
- Modify: `collections_from_vendors_installments/wizards/__init__.py`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_transfer.py`

**Interfaces:**
- Consumes: `cvi.card.collector_id`, `cvi.card.state`, `cvi.card._cvi_log` (Tasks 3 y 8); grupo `group_cvi_manager` (Task 1).
- Produces: modelo transitorio `cvi.transfer.wizard` con `card_ids` (Many2many), `collector_dest_id` (Many2one `res.users`, required), `reason` (Char required), `card_count` (Integer compute); método `action_confirm_transfer()`.

**Regla:** la transferencia mantiene el estado `active` de la tarjeta — el cobrador destino la recibe ya aceptada, porque es una decisión de la administración, no un ofrecimiento.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_transfer.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviTransfer(CviCommon):

    def setUp(self):
        super().setUp()
        self.collector_dest = self.env["res.users"].create({
            "name": "Cobrador Destino",
            "login": "cvi_collector_dest",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def _active_cards(self, how_many):
        """`how_many` tarjetas en cobranza a cargo de `self.collector_user`."""
        cards = self.env["cvi.card"]
        for _index in range(how_many):
            card = self.env["cvi.card"].create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "date_sale": "2026-01-15",
                "plan_id": self.plan_3.id,
                "charge_day_month": 10,
                "collector_id": self.collector_user.id,
            })
            card.action_confirm()
            card.action_accept()
            cards |= card
        return cards

    def _wizard(self, cards, reason="Reorganización de rutas"):
        return self.env["cvi.transfer.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_dest_id": self.collector_dest.id,
            "reason": reason,
        })

    def test_transfer_moves_cards_to_destination(self):
        """La tarjeta pasa a la cartera del cobrador destino (HU-30)."""
        cards = self._active_cards(1)
        self._wizard(cards).action_confirm_transfer()
        self.assertEqual(cards.collector_id, self.collector_dest)

    def test_transferred_card_stays_active(self):
        """La tarjeta transferida sigue en cobranza: no vuelve a pendiente de aceptar."""
        cards = self._active_cards(1)
        self._wizard(cards).action_confirm_transfer()
        self.assertEqual(cards.state, "active")

    def test_origin_collector_no_longer_sees_the_card(self):
        """El cobrador de origen deja de tener la tarjeta en su cartera (HU-30)."""
        cards = self._active_cards(1)
        self._wizard(cards).action_confirm_transfer()
        origin_portfolio = self.env["cvi.card"].search([
            ("collector_id", "=", self.collector_user.id), ("state", "=", "active"),
        ])
        self.assertNotIn(cards, origin_portfolio)

    def test_transfer_is_logged_with_reason_and_users(self):
        """Queda registrada la transferencia con origen, destino y motivo (HU-30, RN-08)."""
        cards = self._active_cards(1)
        self._wizard(cards, "Cambio de zona").action_confirm_transfer()
        body = cards.message_ids[0].body
        self.assertIn("Cambio de zona", body)
        self.assertIn(self.collector_user.name, body)
        self.assertIn(self.collector_dest.name, body)

    def test_mass_transfer(self):
        """Se pueden transferir varias tarjetas de una sola vez (HU-30)."""
        cards = self._active_cards(10)
        self._wizard(cards).action_confirm_transfer()
        self.assertEqual(set(cards.mapped("collector_id")), {self.collector_dest})

    def test_reason_is_required(self):
        """No se transfiere sin motivo."""
        cards = self._active_cards(1)
        with self.assertRaises(UserError):
            self._wizard(cards, "   ").action_confirm_transfer()

    def test_transfer_to_same_collector_is_rejected(self):
        """No tiene sentido transferir una tarjeta al cobrador que ya la tiene."""
        cards = self._active_cards(1)
        wizard = self.env["cvi.transfer.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_dest_id": self.collector_user.id,
            "reason": "Sin cambio",
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_transfer()

    def test_draft_card_cannot_be_transferred(self):
        """Solo se transfieren tarjetas ya en cobranza o enrutadas."""
        card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        with self.assertRaises(UserError):
            self._wizard(card).action_confirm_transfer()

    def test_collector_cannot_use_the_transfer_wizard(self):
        """Un cobrador no puede transferir tarjetas: es potestad del administrador (RN-04)."""
        cards = self._active_cards(1)
        with self.assertRaises(AccessError):
            self.env["cvi.transfer.wizard"].with_user(self.collector_user).create({
                "card_ids": [(6, 0, cards.ids)],
                "collector_dest_id": self.collector_dest.id,
                "reason": "Intento no autorizado",
            })
```

Registrar en `tests/__init__.py` agregando `from . import test_transfer`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviTransfer \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `KeyError: 'cvi.transfer.wizard'`.

- [ ] **Step 3: Escribir el wizard de transferencia**

`collections_from_vendors_installments/wizards/cvi_transfer_wizard.py`:

```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CviTransferWizard(models.TransientModel):
    _name = "cvi.transfer.wizard"
    _description = "Transferencia de tarjetas entre cobradores"

    card_ids = fields.Many2many(
        "cvi.card",
        string="Tarjetas a transferir",
        domain="[('state', 'in', ('routed', 'active'))]",
    )
    collector_dest_id = fields.Many2one(
        "res.users",
        string="Cobrador destino",
        required=True,
        domain=lambda self: self._cvi_group_domain("group_cvi_collector"),
    )
    reason = fields.Char(string="Motivo de la transferencia", required=True)
    card_count = fields.Integer(string="Tarjetas seleccionadas", compute="_compute_card_count")

    @api.depends("card_ids")
    def _compute_card_count(self):
        """Cuántas tarjetas se van a transferir."""
        for wizard in self:
            wizard.card_count = len(wizard.card_ids)

    def action_confirm_transfer(self):
        """Pasa las tarjetas al cobrador destino dejando registro de la operación (HU-30).

        La tarjeta transferida conserva su estado: es una decisión de la administración,
        no un ofrecimiento que el cobrador destino deba aceptar.
        """
        self.ensure_one()
        if not self.card_ids:
            raise UserError(_("Seleccioná al menos una tarjeta para transferir."))
        if not self.reason or not self.reason.strip():
            raise UserError(_("Indicá el motivo de la transferencia."))
        wrong_state = self.card_ids.filtered(lambda c: c.state not in ("routed", "active"))
        if wrong_state:
            raise UserError(_(
                "Estas tarjetas no están en cobranza y no se pueden transferir: %s",
                ", ".join(wrong_state.mapped("name")),
            ))
        same = self.card_ids.filtered(lambda c: c.collector_id == self.collector_dest_id)
        if same:
            raise UserError(_(
                "Estas tarjetas ya están a cargo de %(collector)s: %(cards)s",
                collector=self.collector_dest_id.name,
                cards=", ".join(same.mapped("name")),
            ))
        reason = self.reason.strip()
        for card in self.card_ids:
            origin = card.collector_id
            card.collector_id = self.collector_dest_id
            card._cvi_log(_(
                "Tarjeta transferida de %(origin)s a %(dest)s por %(user)s. Motivo: %(reason)s",
                origin=origin.name or _("sin cobrador"),
                dest=self.collector_dest_id.name,
                user=self.env.user.name,
                reason=reason,
            ))
        return {"type": "ir.actions.act_window_close"}
```

Actualizar `wizards/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import cvi_reject_wizard
from . import cvi_route_wizard
from . import cvi_transfer_wizard
```

Agregar en `security/ir.model.access.csv` — **solo el administrador** (RN-04):

```csv
access_cvi_transfer_wizard_manager,cvi.transfer.wizard administrador,model_cvi_transfer_wizard,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 9 tests de `TestCviTransfer` en verde.

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): transferencia de tarjetas entre cobradores con registro"
```

---

## Task 11: Stock en poder del vendedor — ubicación, entrega y devolución

Cubre HU-01 (ingreso de producción), HU-02 (entrega de mercadería a un vendedor) y HU-04 (devolución de lo no vendido).

**HU-01 no requiere código.** El ingreso de producción se hace con el Inventario nativo de Odoo: un albarán de entrada (o un ajuste de inventario) que suma cantidad por modelo de mueble en `WH/Stock`. No se pide ni genera código individual por unidad porque los productos se crean sin seguimiento (`tracking = 'none'`, el default). Se verifica con un test, y se documenta en el README en la Task 16.

**Files:**
- Create: `collections_from_vendors_installments/models/res_users.py`
- Create: `collections_from_vendors_installments/models/stock_location.py`
- Create: `collections_from_vendors_installments/data/stock_location.xml`
- Create: `collections_from_vendors_installments/wizards/cvi_vendor_delivery_wizard.py`
- Modify: `collections_from_vendors_installments/models/__init__.py`
- Modify: `collections_from_vendors_installments/wizards/__init__.py`
- Modify: `collections_from_vendors_installments/__manifest__.py`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_vendor_stock.py`

**Interfaces:**
- Consumes: grupos de la Task 1; nada de las tasks 3-10.
- Produces:
  - XMLID `collections_from_vendors_installments.stock_location_vendors` — ubicación vista "Vendedores".
  - Campo `stock.location.cvi_is_vendor_location` (Boolean, index) — marca las ubicaciones que son de un vendedor, sin depender de la jerarquía.
  - Campo `res.users.cvi_stock_location_id` (Many2one `stock.location`, readonly).
  - Método `res.users._cvi_get_location()` → devuelve la ubicación interna del vendedor, creándola la primera vez.
  - Modelo transitorio `cvi.vendor.delivery.wizard` con `vendor_id`, `direction` (Selection `out`/`in`), `line_ids` (One2many a `cvi.vendor.delivery.line`), método `action_confirm_delivery()` → devuelve el `stock.picking` validado.
  - Modelo transitorio `cvi.vendor.delivery.line` con `wizard_id`, `product_id`, `quantity`.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_vendor_stock.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviVendorStock(CviCommon):

    def setUp(self):
        super().setUp()
        self.stock_location = self.warehouse.lot_stock_id

    def _receive(self, quantity, product=None):
        """Ingresa producción a WH/Stock por ajuste de inventario (HU-01)."""
        product = product or self.product
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": quantity,
        })
        quant.action_apply_inventory()
        return quant

    def _available(self, location, product=None):
        """Cantidad disponible de un producto en una ubicación."""
        product = product or self.product
        return self.env["stock.quant"]._get_available_quantity(product, location)

    def _deliver(self, quantity, direction="out", vendor=None):
        """Corre el wizard de entrega/devolución de mercadería."""
        wizard = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": (vendor or self.vendor_user).id,
            "direction": direction,
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": quantity})],
        })
        return wizard.action_confirm_delivery()

    def test_production_intake_increases_factory_stock(self):
        """Ingresar producción actualiza el stock disponible de fábrica (HU-01)."""
        before = self._available(self.stock_location)
        self._receive(10)
        self.assertEqual(self._available(self.stock_location), before + 10)

    def test_product_has_no_individual_tracking(self):
        """Los muebles no se identifican por unidad: sin lotes ni series (HU-01)."""
        self.assertEqual(self.product.tracking, "none")

    def test_vendor_location_is_created_on_demand(self):
        """La ubicación del vendedor se crea la primera vez que se la necesita."""
        self.assertFalse(self.vendor_user.cvi_stock_location_id)
        location = self.vendor_user._cvi_get_location()
        self.assertTrue(location)
        self.assertEqual(location.usage, "internal")
        self.assertEqual(self.vendor_user.cvi_stock_location_id, location)

    def test_vendor_location_is_reused(self):
        """La segunda llamada devuelve la misma ubicación, no crea otra."""
        first = self.vendor_user._cvi_get_location()
        second = self.vendor_user._cvi_get_location()
        self.assertEqual(first, second)

    def test_vendor_location_hangs_from_vendors_parent(self):
        """La ubicación del vendedor cuelga de la ubicación vista Vendedores."""
        parent = self.env.ref("collections_from_vendors_installments.stock_location_vendors")
        self.assertEqual(self.vendor_user._cvi_get_location().location_id, parent)

    def test_delivery_moves_stock_from_factory_to_vendor(self):
        """Entregar mercadería la pasa de fábrica al vendedor (HU-02)."""
        self._receive(10)
        self._deliver(3)
        vendor_location = self.vendor_user._cvi_get_location()
        self.assertEqual(self._available(vendor_location), 3)

    def test_delivery_reduces_factory_stock(self):
        """Lo entregado deja de estar disponible en fábrica (HU-02)."""
        self._receive(10)
        before = self._available(self.stock_location)
        self._deliver(3)
        self.assertEqual(self._available(self.stock_location), before - 3)

    def test_delivery_produces_a_validated_picking(self):
        """La entrega genera un albarán hecho, que sirve de constancia (HU-02, RN-08)."""
        self._receive(10)
        picking = self._deliver(3)
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.location_dest_id, self.vendor_user._cvi_get_location())

    def test_delivering_more_than_available_is_rejected(self):
        """No se puede entregar más unidades de las disponibles en fábrica (HU-02)."""
        self._receive(2)
        with self.assertRaises(UserError):
            self._deliver(5)

    def test_delivery_without_lines_is_rejected(self):
        """No se confirma una entrega vacía."""
        wizard = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": self.vendor_user.id,
            "direction": "out",
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_delivery()

    def test_zero_quantity_line_is_rejected(self):
        """Una línea con cantidad cero o negativa no es una entrega válida."""
        with self.assertRaises(UserError):
            self._deliver(0)

    def test_return_moves_stock_back_to_factory(self):
        """La devolución del vendedor reingresa el stock a fábrica (HU-04)."""
        self._receive(10)
        self._deliver(4)
        vendor_location = self.vendor_user._cvi_get_location()
        self._deliver(4, direction="in")
        self.assertEqual(self._available(vendor_location), 0)

    def test_return_increases_factory_stock(self):
        """Lo devuelto vuelve a estar disponible en fábrica (HU-04)."""
        self._receive(10)
        self._deliver(4)
        before = self._available(self.stock_location)
        self._deliver(4, direction="in")
        self.assertEqual(self._available(self.stock_location), before + 4)

    def test_returning_more_than_the_vendor_holds_is_rejected(self):
        """El vendedor no puede devolver más de lo que tiene a cargo (HU-04)."""
        self._receive(10)
        self._deliver(2)
        with self.assertRaises(UserError):
            self._deliver(5, direction="in")
```

Registrar en `tests/__init__.py` agregando `from . import test_vendor_stock`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviVendorStock \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `ValueError: External ID not found: collections_from_vendors_installments.stock_location_vendors`.

- [ ] **Step 3: Escribir la ubicación vista padre**

`collections_from_vendors_installments/data/stock_location.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="stock_location_vendors" model="stock.location">
            <field name="name">Vendedores</field>
            <field name="usage">view</field>
            <field name="location_id" ref="stock.stock_location_locations"/>
            <field name="comment">Ubicación padre de la mercadería en poder de cada vendedor.</field>
        </record>
    </data>
</odoo>
```

- [ ] **Step 4: Escribir el campo marcador en `stock.location`**

`collections_from_vendors_installments/models/stock_location.py`:

```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    cvi_is_vendor_location = fields.Boolean(
        string="Es ubicación de un vendedor",
        default=False,
        index=True,
        copy=False,
        help="Marca las ubicaciones que representan la mercadería que un vendedor "
             "tiene en la calle. Es lo que filtra el reporte de mercadería en la calle.",
    )
```

- [ ] **Step 5: Escribir la ubicación por vendedor en `res.users`**

`collections_from_vendors_installments/models/res_users.py`:

```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    cvi_stock_location_id = fields.Many2one(
        "stock.location",
        string="Ubicación de mercadería",
        readonly=True,
        copy=False,
        help="Ubicación interna donde vive la mercadería que este vendedor tiene en la calle. "
             "Se crea sola la primera vez que se le entrega mercadería.",
    )

    def _cvi_get_location(self):
        """Devuelve la ubicación de stock del vendedor, creándola si todavía no existe.

        Se crea on-demand para no obligar a configurar una ubicación por usuario antes
        de empezar a operar.
        """
        self.ensure_one()
        if self.cvi_stock_location_id:
            return self.cvi_stock_location_id
        parent = self.env.ref("collections_from_vendors_installments.stock_location_vendors")
        location = self.env["stock.location"].sudo().create({
            "name": self.name,
            "usage": "internal",
            "location_id": parent.id,
            "company_id": self.company_id.id,
            "cvi_is_vendor_location": True,
        })
        self.sudo().cvi_stock_location_id = location
        return location
```

- [ ] **Step 6: Escribir el wizard de entrega y devolución**

`collections_from_vendors_installments/wizards/cvi_vendor_delivery_wizard.py`:

```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CviVendorDeliveryWizard(models.TransientModel):
    _name = "cvi.vendor.delivery.wizard"
    _description = "Entrega y devolución de mercadería de vendedores"

    vendor_id = fields.Many2one(
        "res.users",
        string="Vendedor",
        required=True,
        domain=lambda self: self._cvi_group_domain("group_cvi_vendor"),
    )
    direction = fields.Selection(
        selection=[("out", "Entrega al vendedor"), ("in", "Devolución a fábrica")],
        string="Operación",
        default="out",
        required=True,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Almacén",
        required=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    line_ids = fields.One2many(
        "cvi.vendor.delivery.line", "wizard_id", string="Modelos y cantidades"
    )

    def _cvi_locations(self):
        """Ubicaciones origen y destino según la dirección de la operación."""
        self.ensure_one()
        factory = self.warehouse_id.lot_stock_id
        vendor = self.vendor_id._cvi_get_location()
        if self.direction == "out":
            return factory, vendor
        return vendor, factory

    def _cvi_check_availability(self, source):
        """Verifica que haya suficiente stock en el origen antes de mover nada (HU-02, HU-04)."""
        self.ensure_one()
        quant_model = self.env["stock.quant"]
        for line in self.line_ids:
            available = quant_model._get_available_quantity(line.product_id, source)
            if line.quantity > available:
                raise UserError(_(
                    "No hay suficiente stock de %(product)s en %(location)s: "
                    "pedís %(asked)s y hay %(available)s.",
                    product=line.product_id.display_name,
                    location=source.display_name,
                    asked=line.quantity,
                    available=available,
                ))

    def action_confirm_delivery(self):
        """Crea y valida el albarán que mueve la mercadería, y lo devuelve (HU-02, HU-04)."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Cargá al menos un modelo y su cantidad."))
        invalid = self.line_ids.filtered(lambda line: line.quantity <= 0)
        if invalid:
            raise UserError(_(
                "Estas líneas tienen cantidad cero o negativa: %s",
                ", ".join(invalid.mapped("product_id.display_name")),
            ))
        source, destination = self._cvi_locations()
        self._cvi_check_availability(source)
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse_id.int_type_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "partner_id": self.vendor_id.partner_id.id,
            "origin": _("Mercadería de %s", self.vendor_id.name),
            "move_ids": [(0, 0, {
                "name": line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.quantity,
                "product_uom": line.product_id.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
            }) for line in self.line_ids],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        _logger.info(
            "Mercadería %s: albarán %s de %s a %s",
            self.direction, picking.name, source.complete_name, destination.complete_name,
        )
        return picking


class CviVendorDeliveryLine(models.TransientModel):
    _name = "cvi.vendor.delivery.line"
    _description = "Línea de entrega o devolución de mercadería"

    wizard_id = fields.Many2one(
        "cvi.vendor.delivery.wizard", string="Operación", required=True, ondelete="cascade"
    )
    product_id = fields.Many2one(
        "product.product",
        string="Modelo de mueble",
        required=True,
        domain="[('is_storable', '=', True)]",
    )
    quantity = fields.Float(string="Cantidad", default=1.0, required=True)
```

- [ ] **Step 7: Registrar el modelo, el wizard, la data y los accesos**

`models/__init__.py` — agregar `from . import res_users` después de `res_company`:

```python
# -*- coding: utf-8 -*-
from . import cvi_card
from . import cvi_installment
from . import cvi_payment
from . import cvi_allocation
from . import res_company
from . import res_users
from . import stock_location
from . import res_config_settings
```

`wizards/__init__.py`:

```python
# -*- coding: utf-8 -*-
from . import cvi_reject_wizard
from . import cvi_route_wizard
from . import cvi_transfer_wizard
from . import cvi_vendor_delivery_wizard
```

`__manifest__.py` — lista `data`:

```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/stock_location.xml",
        "data/ir_cron.xml",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
    ],
```

`security/ir.model.access.csv` — agregar:

```csv
access_cvi_vendor_delivery_wizard_manager,cvi.vendor.delivery.wizard administrador,model_cvi_vendor_delivery_wizard,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
access_cvi_vendor_delivery_line_manager,cvi.vendor.delivery.line administrador,model_cvi_vendor_delivery_line,collections_from_vendors_installments.group_cvi_manager,1,1,1,1
access_cvi_vendor_delivery_wizard_stock,cvi.vendor.delivery.wizard depósito,model_cvi_vendor_delivery_wizard,stock.group_stock_user,1,1,1,1
access_cvi_vendor_delivery_line_stock,cvi.vendor.delivery.line depósito,model_cvi_vendor_delivery_line,stock.group_stock_user,1,1,1,1
```

- [ ] **Step 8: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 14 tests de `TestCviVendorStock` en verde.

- [ ] **Step 9: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): ubicación por vendedor, entrega y devolución de mercadería"
```

---

## Task 12: Descuento de stock al vender y reporte de mercadería en la calle

Cubre HU-03 (consultar qué mercadería tiene cada vendedor sin vender) y cierra el circuito de stock: al confirmar la venta, el mueble sale del vendedor hacia el cliente.

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_card.py` (agregar `picking_id` y `_cvi_create_sale_picking`, llamarlo desde `action_confirm`)
- Create: `collections_from_vendors_installments/views/stock_quant_views.xml`
- Modify: `collections_from_vendors_installments/__manifest__.py`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_sale_picking.py`

**Interfaces:**
- Consumes: `res.users._cvi_get_location()` (Task 11); `cvi.card.action_confirm()` (Task 6); `cvi.card.product_id`, `quantity`, `vendor_id` (Task 3).
- Produces:
  - Campo `cvi.card.picking_id` (Many2one `stock.picking`, readonly) — albarán que descontó el mueble del vendedor.
  - Método `cvi.card._cvi_create_sale_picking()` → crea y valida el albarán de salida hacia Clientes; devuelve el picking.
  - Acción de ventana `collections_from_vendors_installments.action_cvi_vendor_stock` sobre `stock.quant`, filtrada a las ubicaciones de vendedores y agrupada por ubicación (HU-03).

**Regla:** el descuento de stock ocurre en `action_confirm()`, después de generar las cuotas y cobrar la comisión. Si el vendedor no tiene el mueble a cargo, la confirmación falla y no se crea ninguna cuota (todo dentro de la misma transacción).

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_sale_picking.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSalePicking(CviCommon):

    def setUp(self):
        super().setUp()
        self.stock_location = self.warehouse.lot_stock_id
        self.vendor_location = self.vendor_user._cvi_get_location()

    def _stock_vendor(self, quantity):
        """Deja `quantity` unidades del mueble en poder del vendedor."""
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.vendor_location.id,
            "inventory_quantity": quantity,
        })
        quant.action_apply_inventory()

    def _available(self, location):
        return self.env["stock.quant"]._get_available_quantity(self.product, location)

    def _card(self, **kwargs):
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "quantity": 1.0,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_confirming_creates_a_validated_picking(self):
        """Confirmar la venta genera el albarán que saca el mueble del vendedor."""
        self._stock_vendor(2)
        card = self._card()
        card.action_confirm()
        self.assertTrue(card.picking_id)
        self.assertEqual(card.picking_id.state, "done")

    def test_sale_reduces_vendor_stock(self):
        """El mueble vendido deja de figurar a cargo del vendedor (HU-03)."""
        self._stock_vendor(2)
        card = self._card(quantity=1.0)
        card.action_confirm()
        self.assertEqual(self._available(self.vendor_location), 1)

    def test_sale_picking_goes_to_customer_location(self):
        """El albarán de venta lleva el mueble a la ubicación de clientes."""
        self._stock_vendor(2)
        card = self._card()
        card.action_confirm()
        customers = self.env.ref("stock.stock_location_customers")
        self.assertEqual(card.picking_id.location_dest_id, customers)

    def test_selling_without_stock_is_rejected(self):
        """El vendedor no puede vender un mueble que no retiró de fábrica."""
        card = self._card()
        with self.assertRaises(UserError):
            card.action_confirm()

    def test_failed_confirm_leaves_no_installments(self):
        """Si el descuento de stock falla, la tarjeta no queda con cuotas a medias."""
        card = self._card()
        with self.assertRaises(UserError):
            card.action_confirm()
        self.assertEqual(card.state, "draft")

    def test_multiple_units_are_discounted(self):
        """Una venta de 2 unidades descuenta 2 del stock del vendedor."""
        self._stock_vendor(5)
        card = self._card(quantity=2.0)
        card.action_confirm()
        self.assertEqual(self._available(self.vendor_location), 3)

    def _report_quants(self):
        """Lo que lista el reporte de mercadería en la calle (mismo dominio que la acción)."""
        return self.env["stock.quant"].search([
            ("location_id.cvi_is_vendor_location", "=", True),
        ])

    def test_vendor_location_is_marked_as_such(self):
        """La ubicación del vendedor queda marcada, que es lo que filtra el reporte."""
        self.assertTrue(self.vendor_location.cvi_is_vendor_location)

    def test_vendor_stock_report_shows_remaining_units(self):
        """El reporte de mercadería en la calle muestra retirado menos vendido (HU-03)."""
        self._stock_vendor(5)
        card = self._card(quantity=2.0)
        card.action_confirm()
        vendor_quants = self._report_quants().filtered(
            lambda q: q.location_id == self.vendor_location
            and q.product_id == self.product
        )
        self.assertEqual(sum(vendor_quants.mapped("quantity")), 3)

    def test_report_excludes_factory_stock(self):
        """El reporte solo mira ubicaciones de vendedores, no el stock de fábrica."""
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": 7,
        })
        quant.action_apply_inventory()
        self.assertNotIn(self.stock_location, self._report_quants().mapped("location_id"))

    def test_report_action_uses_the_same_domain(self):
        """La acción del menú filtra por el mismo marcador que verifican estos tests."""
        action = self.env.ref(
            "collections_from_vendors_installments.action_cvi_vendor_stock"
        )
        self.assertIn("cvi_is_vendor_location", action.domain)
```

Registrar en `tests/__init__.py` agregando `from . import test_sale_picking`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSalePicking \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `AttributeError: 'cvi.card' object has no attribute 'picking_id'`.

- [ ] **Step 3: Agregar el albarán de venta a `cvi.card`**

En `models/cvi_card.py`, agregar el campo después de `reject_reason`:

```python
    picking_id = fields.Many2one(
        "stock.picking",
        string="Albarán de venta",
        readonly=True,
        copy=False,
        help="Albarán que descontó el mueble del stock del vendedor al confirmar la venta.",
    )
```

Agregar este método antes de `action_confirm`:

```python
    def _cvi_create_sale_picking(self):
        """Descuenta el mueble vendido del stock del vendedor hacia el cliente.

        Usa el tipo de operación de salida del almacén forzando la ubicación origen a la
        del vendedor: la mercadería sale de la calle, no del depósito.
        """
        self.ensure_one()
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if not warehouse:
            raise UserError(_(
                "No hay un almacén configurado para la empresa %s.", self.company_id.name
            ))
        source = self.vendor_id._cvi_get_location()
        destination = self.env.ref("stock.stock_location_customers")
        available = self.env["stock.quant"]._get_available_quantity(self.product_id, source)
        if self.quantity > available:
            raise UserError(_(
                "%(vendor)s no tiene %(asked)s unidades de %(product)s a cargo "
                "(disponibles: %(available)s). Registrá la entrega de mercadería primero.",
                vendor=self.vendor_id.name,
                asked=self.quantity,
                product=self.product_id.display_name,
                available=available,
            ))
        picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.out_type_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "partner_id": self.partner_id.id,
            "origin": self.name,
            "move_ids": [(0, 0, {
                "name": self.product_id.display_name,
                "product_id": self.product_id.id,
                "product_uom_qty": self.quantity,
                "product_uom": self.product_id.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        self.picking_id = picking
        return picking
```

En `action_confirm`, agregar la llamada **antes** de generar las cuotas, para que una falta de stock aborte la operación completa sin dejar cuotas huérfanas. El cuerpo del `for` queda así:

```python
        for card in self:
            if card.state != "draft":
                raise UserError(_(
                    "La tarjeta %(card)s ya fue confirmada (estado: %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            card._cvi_create_sale_picking()
            card._cvi_generate_installments()
            card._cvi_charge_commission()
            card.state = "routed" if card.collector_id else "sold"
            card._cvi_log(_(
                "Venta confirmada por %(user)s: %(count)s cuotas de %(amount)s.",
                user=card.vendor_id.name,
                count=card.installment_count,
                amount=card.installment_amount,
            ))
```

> Las tasks 6 a 10 escribieron tests que confirman tarjetas sin stock. Al agregar este descuento, esos tests fallarán. **Corregirlos en este mismo paso**: en `tests/common.py`, agregar al final de `setUpClass` un stock inicial generoso en la ubicación del vendedor, para que cualquier test que confirme una tarjeta tenga mercadería disponible:
>
> ```python
>         cls.vendor_location = cls.vendor_user._cvi_get_location()
>         cls.env["stock.quant"].with_context(inventory_mode=True).create({
>             "product_id": cls.product.id,
>             "location_id": cls.vendor_location.id,
>             "inventory_quantity": 500,
>         }).action_apply_inventory()
> ```
>
> El test `test_selling_without_stock_is_rejected` de esta task necesita un vendedor **sin** stock: crear en su `setUp` un usuario vendedor aparte para ese caso. Reemplazar ese test por:
>
> ```python
>     def test_selling_without_stock_is_rejected(self):
>         """El vendedor no puede vender un mueble que no retiró de fábrica."""
>         broke_vendor = self.env["res.users"].create({
>             "name": "Vendedor Sin Stock",
>             "login": "cvi_vendor_nostock",
>             "company_id": self.company.id,
>             "company_ids": [(6, 0, [self.company.id])],
>             "groups_id": [(6, 0, [
>                 self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
>                 self.env.ref("base.group_user").id,
>             ])],
>         })
>         card = self._card(vendor_id=broke_vendor.id)
>         with self.assertRaises(UserError):
>             card.action_confirm()
> ```
>
> Y `test_failed_confirm_leaves_no_installments` de la misma forma, usando `broke_vendor`.

- [ ] **Step 4: Escribir el reporte de mercadería en poder de vendedores**

`collections_from_vendors_installments/views/stock_quant_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cvi_vendor_stock_list" model="ir.ui.view">
        <field name="name">cvi.vendor.stock.list</field>
        <field name="model">stock.quant</field>
        <field name="arch" type="xml">
            <list string="Mercadería en poder de vendedores" create="false" edit="false">
                <field name="location_id" string="Vendedor"/>
                <field name="product_id" string="Modelo"/>
                <field name="quantity" string="En la calle" sum="Total"/>
                <field name="company_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_cvi_vendor_stock_search" model="ir.ui.view">
        <field name="name">cvi.vendor.stock.search</field>
        <field name="model">stock.quant</field>
        <field name="arch" type="xml">
            <search string="Mercadería en la calle">
                <field name="location_id" string="Vendedor"/>
                <field name="product_id" string="Modelo"/>
                <filter name="filter_with_stock" string="Con unidades"
                        domain="[('quantity', '&gt;', 0)]"/>
                <group expand="1" string="Agrupar por">
                    <filter name="group_by_location" string="Vendedor"
                            context="{'group_by': 'location_id'}"/>
                    <filter name="group_by_product" string="Modelo"
                            context="{'group_by': 'product_id'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_cvi_vendor_stock" model="ir.actions.act_window">
        <field name="name">Mercadería en poder de vendedores</field>
        <field name="res_model">stock.quant</field>
        <field name="view_mode">list</field>
        <field name="search_view_id" ref="view_cvi_vendor_stock_search"/>
        <field name="domain">[('location_id.cvi_is_vendor_location', '=', True)]</field>
        <field name="context">{'search_default_filter_with_stock': 1, 'search_default_group_by_location': 1}</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Ningún vendedor tiene mercadería en la calle</p>
            <p>Acá ves lo que cada vendedor retiró de fábrica y todavía no vendió ni devolvió.</p>
        </field>
    </record>
</odoo>
```

Agregar el archivo a la lista `data` del manifest, después de `views/res_config_settings_views.xml`:

```python
        "views/stock_quant_views.xml",
```

> El `list` de la vista debe usar `view_mode">list` (Odoo 18 renombró `tree` a `list`).

- [ ] **Step 5: Correr toda la suite y verificar que pasa**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -40
```

Esperado: `0 failed, 0 error(s)` en **todos** los archivos de test, incluidos los de las tasks anteriores tras el ajuste de `common.py`.

- [ ] **Step 6: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): descuento de stock al vender y reporte de mercadería en la calle"
```

---

## Task 13: Visibilidad por rol

Cubre RN-07 (cada rol ve exclusivamente su información) y la parte multi-empresa de RN-08.

**Files:**
- Modify: `collections_from_vendors_installments/security/security.xml`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_security.py`

**Interfaces:**
- Consumes: grupos de la Task 1; `cvi.card.vendor_id`, `.collector_id`, `.company_id` (Task 3); `cvi.installment.collector_id`, `.company_id` (Task 4); `cvi.payment.user_id`, `.card_id` (Task 4).
- Produces: reglas `ir.rule` sobre `cvi.card`, `cvi.installment` y `cvi.payment` que restringen por rol, más reglas globales de empresa sobre los tres modelos.

**Reglas de visibilidad:**
- Vendedor: sus propias tarjetas (`vendor_id = user.id`) y las cuotas y cobros de esas tarjetas.
- Cobrador: las tarjetas donde figura como `collector_id`, sin importar el estado (así ve tanto las pendientes de aceptar como su cartera activa).
- Administrador: todo (`[(1, '=', 1)]`).
- Todos: solo registros de sus empresas permitidas.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_security.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSecurity(CviCommon):

    def setUp(self):
        super().setUp()
        self.other_vendor = self.env["res.users"].create({
            "name": "Vendedor Ajeno",
            "login": "cvi_vendor_other_sec",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.other_vendor._cvi_get_location()
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.other_vendor.cvi_stock_location_id.id,
            "inventory_quantity": 50,
        }).action_apply_inventory()
        self.my_card = self._card(self.vendor_user)
        self.other_card = self._card(self.other_vendor)

    def _card(self, vendor):
        """Tarjeta confirmada del vendedor indicado."""
        card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": vendor.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        card.action_confirm()
        return card

    def test_vendor_sees_only_own_cards(self):
        """Un vendedor solo ve sus propias ventas (RN-07)."""
        visible = self.env["cvi.card"].with_user(self.vendor_user).search([])
        self.assertIn(self.my_card, visible)
        self.assertNotIn(self.other_card, visible)

    def test_vendor_sees_installments_of_own_cards_only(self):
        """Un vendedor solo ve las cuotas de sus propias ventas."""
        visible = self.env["cvi.installment"].with_user(self.vendor_user).search([])
        self.assertEqual(set(visible.mapped("card_id")), {self.my_card})

    def test_collector_sees_only_assigned_cards(self):
        """Un cobrador solo ve las tarjetas que le fueron enrutadas (RN-07)."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        visible = self.env["cvi.card"].with_user(self.collector_user).search([])
        self.assertIn(self.my_card, visible)
        self.assertNotIn(self.other_card, visible)

    def test_collector_sees_routed_cards_before_accepting(self):
        """El cobrador ve las tarjetas pendientes de aceptar (HU-12)."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        pending = self.env["cvi.card"].with_user(self.collector_user).search([
            ("state", "=", "routed"),
        ])
        self.assertIn(self.my_card, pending)

    def test_collector_stops_seeing_transferred_cards(self):
        """Al transferir la tarjeta, el cobrador de origen deja de verla (HU-30)."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        self.my_card.action_accept()
        dest = self.env["res.users"].create({
            "name": "Cobrador Nuevo",
            "login": "cvi_collector_new_sec",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.my_card.collector_id = dest.id
        visible = self.env["cvi.card"].with_user(self.collector_user).search([])
        self.assertNotIn(self.my_card, visible)

    def test_collector_does_not_see_unrouted_cards(self):
        """Una tarjeta sin cobrador no aparece en la cartera de nadie."""
        visible = self.env["cvi.card"].with_user(self.collector_user).search([])
        self.assertNotIn(self.my_card, visible)

    def test_manager_sees_everything(self):
        """El administrador ve todas las tarjetas, de todos los vendedores (RN-07)."""
        visible = self.env["cvi.card"].search([])
        self.assertIn(self.my_card, visible)
        self.assertIn(self.other_card, visible)

    def test_collector_sees_payments_of_own_portfolio_only(self):
        """Un cobrador solo ve los cobros de las tarjetas de su cartera."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        self.my_card.action_accept()
        visible = self.env["cvi.payment"].with_user(self.collector_user).search([])
        self.assertEqual(set(visible.mapped("card_id")), {self.my_card})
```

Registrar en `tests/__init__.py` agregando `from . import test_security`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSecurity \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA en `test_vendor_sees_only_own_cards` — sin reglas, el vendedor ve todo.

- [ ] **Step 3: Escribir las reglas de registro**

En `security/security.xml`, agregar dentro del mismo `<data noupdate="1">`, después de los grupos:

```xml
        <!-- Multi-empresa: nadie ve registros de empresas que no le corresponden -->
        <record id="rule_cvi_card_company" model="ir.rule">
            <field name="name">Tarjeta: multi-empresa</field>
            <field name="model_id" ref="model_cvi_card"/>
            <field name="domain_force">[('company_id', 'in', company_ids)]</field>
            <field name="global" eval="True"/>
        </record>

        <record id="rule_cvi_installment_company" model="ir.rule">
            <field name="name">Cuota: multi-empresa</field>
            <field name="model_id" ref="model_cvi_installment"/>
            <field name="domain_force">[('company_id', 'in', company_ids)]</field>
            <field name="global" eval="True"/>
        </record>

        <record id="rule_cvi_payment_company" model="ir.rule">
            <field name="name">Cobro: multi-empresa</field>
            <field name="model_id" ref="model_cvi_payment"/>
            <field name="domain_force">[('company_id', 'in', company_ids)]</field>
            <field name="global" eval="True"/>
        </record>

        <!-- RN-07: cada rol ve exclusivamente su propia información -->
        <record id="rule_cvi_card_vendor" model="ir.rule">
            <field name="name">Tarjeta: el vendedor ve sus ventas</field>
            <field name="model_id" ref="model_cvi_card"/>
            <field name="domain_force">[('vendor_id', '=', user.id)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_vendor'))]"/>
        </record>

        <record id="rule_cvi_card_collector" model="ir.rule">
            <field name="name">Tarjeta: el cobrador ve su cartera</field>
            <field name="model_id" ref="model_cvi_card"/>
            <field name="domain_force">[('collector_id', '=', user.id)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_collector'))]"/>
        </record>

        <record id="rule_cvi_card_manager" model="ir.rule">
            <field name="name">Tarjeta: el administrador ve todo</field>
            <field name="model_id" ref="model_cvi_card"/>
            <field name="domain_force">[(1, '=', 1)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_manager'))]"/>
        </record>

        <record id="rule_cvi_installment_vendor" model="ir.rule">
            <field name="name">Cuota: el vendedor ve las de sus ventas</field>
            <field name="model_id" ref="model_cvi_installment"/>
            <field name="domain_force">[('card_id.vendor_id', '=', user.id)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_vendor'))]"/>
        </record>

        <record id="rule_cvi_installment_collector" model="ir.rule">
            <field name="name">Cuota: el cobrador ve las de su cartera</field>
            <field name="model_id" ref="model_cvi_installment"/>
            <field name="domain_force">[('card_id.collector_id', '=', user.id)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_collector'))]"/>
        </record>

        <record id="rule_cvi_installment_manager" model="ir.rule">
            <field name="name">Cuota: el administrador ve todo</field>
            <field name="model_id" ref="model_cvi_installment"/>
            <field name="domain_force">[(1, '=', 1)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_manager'))]"/>
        </record>

        <record id="rule_cvi_payment_vendor" model="ir.rule">
            <field name="name">Cobro: el vendedor ve los de sus ventas</field>
            <field name="model_id" ref="model_cvi_payment"/>
            <field name="domain_force">[('card_id.vendor_id', '=', user.id)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_vendor'))]"/>
        </record>

        <record id="rule_cvi_payment_collector" model="ir.rule">
            <field name="name">Cobro: el cobrador ve los de su cartera</field>
            <field name="model_id" ref="model_cvi_payment"/>
            <field name="domain_force">[('card_id.collector_id', '=', user.id)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_collector'))]"/>
        </record>

        <record id="rule_cvi_payment_manager" model="ir.rule">
            <field name="name">Cobro: el administrador ve todo</field>
            <field name="model_id" ref="model_cvi_payment"/>
            <field name="domain_force">[(1, '=', 1)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_manager'))]"/>
        </record>
```

> Las reglas por grupo combinan con **OR**: un usuario que sea vendedor y cobrador a la vez ve sus ventas *más* su cartera, que es exactamente lo que la operación necesita. La regla del administrador (`[(1,'=',1)]`) gana sobre las demás por la misma razón — y por eso `group_cvi_manager` puede implicar a los otros dos sin romper nada.

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -40
```

Esperado: `0 failed, 0 error(s)`, con los 8 tests de `TestCviSecurity` en verde y el resto de la suite sin regresiones.

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): visibilidad por rol con reglas de registro"
```

---

## Task 14: Agenda de cobro del día

Cubre HU-14 (ver qué clientes hay que cobrar hoy, con dirección, saldo y ubicación en el mapa).

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_installment.py` (agregar `street`, `map_url`, `card_residual`, `action_open_map`)
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_agenda.py`

**Interfaces:**
- Consumes: `cvi.installment.date_due`, `.state`, `.card_id`, `.partner_id` (Task 4); `cvi.card.amount_residual`, `.state` (Task 7).
- Produces, en `cvi.installment`:
  - `street` (Char related `partner_id.street`, store) — dirección del cliente.
  - `card_residual` (Monetary related `card_id.amount_residual`) — saldo total de la tarjeta.
  - `map_url` (Char compute) — link de Google Maps armado con la dirección del cliente.
  - `action_open_map()` → `ir.actions.act_url` que abre el mapa en una pestaña nueva.
  - Acción de ventana `collections_from_vendors_installments.action_cvi_agenda` — cuotas a cobrar hasta hoy, de la cartera activa del usuario (definida en la Task 15 junto al resto de las vistas; acá solo el modelo).

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_agenda.py`:

```python
# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviAgenda(CviCommon):

    def setUp(self):
        super().setUp()
        self.partner.write({
            "street": "Av. Siempreviva 742",
            "city": "Rosario",
        })
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _agenda(self):
        """Cuotas que el cobrador tiene que cobrar hasta hoy (HU-14)."""
        today = fields.Date.context_today(self.env.user)
        return self.env["cvi.installment"].search([
            ("card_id.collector_id", "=", self.collector_user.id),
            ("card_id.state", "=", "active"),
            ("state", "in", ("pending", "partial", "overdue")),
            ("date_due", "<=", today),
        ])

    def test_agenda_lists_due_installments(self):
        """La agenda muestra las cuotas vencidas o que vencen hoy."""
        agenda = self._agenda()
        self.assertEqual(len(agenda), 2)
        self.assertEqual(set(agenda.mapped("sequence")), {2, 3})

    def test_agenda_excludes_the_commission_installment(self):
        """La cuota que cobró el vendedor no aparece en la agenda del cobrador (HU-09)."""
        agenda = self._agenda()
        self.assertNotIn(1, agenda.mapped("sequence"))

    def test_agenda_excludes_paid_installments(self):
        """Una cuota ya cobrada sale de la agenda."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 10000.0,
        })
        payment.action_post()
        self.assertNotIn(2, self._agenda().mapped("sequence"))

    def test_installment_exposes_customer_address(self):
        """Cada línea de la agenda trae la dirección del cliente (HU-14)."""
        installment = self._agenda()[0]
        self.assertEqual(installment.street, "Av. Siempreviva 742")

    def test_installment_exposes_card_balance(self):
        """El cobrador ve el saldo total de la tarjeta desde la agenda (HU-14)."""
        installment = self._agenda()[0]
        self.assertEqual(installment.card_residual, self.card.amount_residual)

    def test_map_url_is_built_from_the_address(self):
        """El link al mapa se arma con la dirección del cliente (HU-14)."""
        installment = self._agenda()[0]
        self.assertIn("google.com/maps", installment.map_url)
        self.assertIn("Siempreviva", installment.map_url)

    def test_map_url_is_empty_without_address(self):
        """Sin dirección cargada no se ofrece un link roto."""
        self.partner.write({"street": False, "city": False, "zip": False})
        installment = self._agenda()[0]
        self.assertFalse(installment.map_url)

    def test_open_map_returns_url_action(self):
        """El botón del mapa devuelve una acción que abre el link (HU-14)."""
        installment = self._agenda()[0]
        action = installment.action_open_map()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["target"], "new")
```

Registrar en `tests/__init__.py` agregando `from . import test_agenda`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviAgenda \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `ValueError: Invalid field 'street' on model 'cvi.installment'`.

- [ ] **Step 3: Agregar los campos de agenda a `cvi.installment`**

En `models/cvi_installment.py`, agregar el import de `url_encode`:

```python
from werkzeug.urls import url_encode
```

Agregar estos campos después de `collector_id`:

```python
    street = fields.Char(
        related="partner_id.street", store=True, string="Dirección"
    )
    city = fields.Char(related="partner_id.city", store=True, string="Ciudad")
    phone = fields.Char(related="partner_id.phone", string="Teléfono")
    card_residual = fields.Monetary(
        related="card_id.amount_residual",
        string="Saldo de la tarjeta",
        currency_field="currency_id",
    )
    card_state = fields.Selection(
        related="card_id.state", store=True, string="Estado de la tarjeta"
    )
    map_url = fields.Char(string="Mapa", compute="_compute_map_url")
```

Y estos métodos al final de la clase:

```python
    @api.depends("partner_id.street", "partner_id.city", "partner_id.zip")
    def _compute_map_url(self):
        """Link a Google Maps con la dirección del cliente, para armar el recorrido (HU-14)."""
        for installment in self:
            partner = installment.partner_id
            parts = [partner.street, partner.city, partner.zip]
            address = ", ".join(part for part in parts if part)
            if address:
                query = url_encode({"api": "1", "query": address})
                installment.map_url = "https://www.google.com/maps/search/?%s" % query
            else:
                installment.map_url = False

    def action_open_map(self):
        """Abre la ubicación del cliente en el mapa, en una pestaña nueva (HU-14)."""
        self.ensure_one()
        if not self.map_url:
            raise UserError(_(
                "El cliente %s no tiene dirección cargada.", self.partner_id.display_name
            ))
        return {
            "type": "ir.actions.act_url",
            "url": self.map_url,
            "target": "new",
        }
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: `0 failed, 0 error(s)`, con los 8 tests de `TestCviAgenda` en verde.

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): agenda de cobro con dirección, saldo y mapa"
```

---

## Task 15: Vistas, menús y flujo de pantallas

Cubre la parte de interfaz de HU-05 (formulario usable en celular), HU-11 (ver mis tarjetas sin cobrador y enviarlas), HU-12 (vista dedicada "Pendientes de aceptar"), HU-14 (agenda), HU-16 (estado de la tarjeta) y RNF-01 (pocos campos por pantalla).

**Files:**
- Create: `collections_from_vendors_installments/views/cvi_card_views.xml`
- Create: `collections_from_vendors_installments/views/cvi_installment_views.xml`
- Create: `collections_from_vendors_installments/views/cvi_payment_views.xml`
- Create: `collections_from_vendors_installments/views/cvi_wizard_views.xml`
- Create: `collections_from_vendors_installments/views/menu_views.xml`
- Modify: `collections_from_vendors_installments/__manifest__.py`

**Interfaces:**
- Consumes: todos los modelos, campos y métodos de las tasks 1 a 14.
- Produces: las acciones `action_cvi_card_my_sales`, `action_cvi_card_to_route`, `action_cvi_card_pending_accept`, `action_cvi_card_portfolio`, `action_cvi_card_all`, `action_cvi_agenda`, `action_cvi_payment`, `action_cvi_vendor_delivery`, `action_cvi_transfer`, y el menú raíz `menu_cvi_root`.

- [ ] **Step 1: Escribir las vistas de la tarjeta**

`collections_from_vendors_installments/views/cvi_card_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cvi_card_form" model="ir.ui.view">
        <field name="name">cvi.card.form</field>
        <field name="model">cvi.card</field>
        <field name="arch" type="xml">
            <form string="Tarjeta">
                <header>
                    <button name="action_confirm" type="object" string="Confirmar venta"
                            class="btn-primary" invisible="state != 'draft'"/>
                    <button name="action_route" type="object" string="Enviar al cobrador"
                            class="btn-primary" invisible="state != 'sold'"/>
                    <button name="action_accept" type="object" string="Aceptar"
                            class="btn-primary" invisible="state != 'routed'"
                            groups="collections_from_vendors_installments.group_cvi_collector"/>
                    <button name="action_open_reject_wizard" type="object" string="Rechazar"
                            invisible="state != 'routed'"
                            groups="collections_from_vendors_installments.group_cvi_collector"/>
                    <button name="action_cancel" type="object" string="Anular"
                            invisible="state not in ('draft', 'sold')"/>
                    <field name="state" widget="statusbar"
                           statusbar_visible="draft,sold,routed,active,done"/>
                </header>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <div class="alert alert-warning" role="alert" invisible="not reject_reason">
                        Rechazada por el cobrador: <field name="reject_reason" readonly="1"/>
                    </div>
                    <group>
                        <group string="Cliente">
                            <field name="partner_id" readonly="state != 'draft'"/>
                            <field name="date_sale" readonly="state != 'draft'"/>
                        </group>
                        <group string="Mercadería">
                            <field name="product_id" readonly="state != 'draft'"/>
                            <field name="product_tmpl_id" invisible="1"/>
                            <field name="quantity" readonly="state != 'draft'"/>
                            <field name="plan_id" readonly="state != 'draft'"
                                   options="{'no_create': True, 'no_open': True}"/>
                        </group>
                        <group string="Financiación">
                            <!-- El plan fija estos valores. Para el vendedor son de solo
                                 lectura; el administrador ve la versión editable. -->
                            <field name="installment_count" readonly="1"
                                   groups="!collections_from_vendors_installments.group_cvi_manager"/>
                            <field name="installment_amount" readonly="1"
                                   groups="!collections_from_vendors_installments.group_cvi_manager"/>
                            <field name="installment_count" readonly="state != 'draft'"
                                   groups="collections_from_vendors_installments.group_cvi_manager"/>
                            <field name="installment_amount" readonly="state != 'draft'"
                                   groups="collections_from_vendors_installments.group_cvi_manager"/>
                            <field name="amount_total" readonly="1"/>
                            <field name="currency_id" invisible="1"/>
                        </group>
                        <group string="Cobranza">
                            <field name="frequency" readonly="1"
                                   groups="!collections_from_vendors_installments.group_cvi_manager"/>
                            <field name="frequency" readonly="state != 'draft'"
                                   groups="collections_from_vendors_installments.group_cvi_manager"/>
                            <field name="charge_day_month" readonly="state != 'draft'"
                                   invisible="frequency != 'monthly'"/>
                            <field name="charge_day_week" readonly="state != 'draft'"
                                   invisible="frequency != 'weekly'"/>
                            <field name="vendor_id" readonly="state != 'draft'"/>
                            <field name="collector_id" readonly="state in ('done', 'cancel')"/>
                        </group>
                    </group>
                    <group string="Saldo" invisible="state == 'draft'">
                        <group>
                            <field name="amount_paid"/>
                            <field name="amount_residual"/>
                            <field name="next_due_date"/>
                        </group>
                        <group>
                            <field name="paid_installment_count"/>
                            <field name="pending_installment_count"/>
                            <field name="overdue_installment_count"/>
                        </group>
                    </group>
                    <notebook invisible="state == 'draft'">
                        <page string="Cuotas" name="installments">
                            <field name="installment_ids" readonly="1">
                                <list decoration-danger="state == 'overdue'"
                                      decoration-success="state == 'paid'">
                                    <field name="sequence"/>
                                    <field name="date_due"/>
                                    <field name="amount"/>
                                    <field name="amount_paid"/>
                                    <field name="amount_residual"/>
                                    <field name="is_commission"/>
                                    <field name="state"/>
                                    <field name="currency_id" column_invisible="True"/>
                                </list>
                            </field>
                        </page>
                        <page string="Cobros" name="payments">
                            <field name="payment_ids" readonly="1">
                                <list decoration-muted="state == 'cancel'">
                                    <field name="name"/>
                                    <field name="date"/>
                                    <field name="amount"/>
                                    <field name="user_id"/>
                                    <field name="is_commission"/>
                                    <field name="state"/>
                                    <field name="currency_id" column_invisible="True"/>
                                </list>
                            </field>
                        </page>
                        <page string="Albarán" name="picking">
                            <group>
                                <field name="picking_id"/>
                            </group>
                        </page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="view_cvi_card_list" model="ir.ui.view">
        <field name="name">cvi.card.list</field>
        <field name="model">cvi.card</field>
        <field name="arch" type="xml">
            <list string="Tarjetas" decoration-danger="overdue_installment_count > 0"
                  decoration-muted="state == 'cancel'">
                <field name="name"/>
                <field name="partner_id"/>
                <field name="product_id" optional="show"/>
                <field name="plan_id" optional="show"/>
                <field name="installment_amount"/>
                <field name="charge_day_display" optional="show"/>
                <field name="next_due_date"/>
                <field name="amount_residual" sum="Saldo total"/>
                <field name="vendor_id" optional="hide"/>
                <field name="collector_id" optional="show"/>
                <field name="state"/>
                <field name="overdue_installment_count" column_invisible="True"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_cvi_card_kanban" model="ir.ui.view">
        <field name="name">cvi.card.kanban</field>
        <field name="model">cvi.card</field>
        <field name="arch" type="xml">
            <kanban class="o_kanban_mobile" default_order="next_due_date">
                <field name="state"/>
                <field name="currency_id"/>
                <templates>
                    <t t-name="card">
                        <div class="row">
                            <div class="col-8">
                                <strong><field name="partner_id"/></strong>
                                <div class="text-muted">
                                    <field name="product_id"/> — <field name="plan_id"/>
                                </div>
                            </div>
                            <div class="col-4 text-end">
                                <field name="installment_amount" widget="monetary"/>
                            </div>
                        </div>
                        <div class="row mt-2">
                            <div class="col-7">
                                <field name="charge_day_display"/>
                            </div>
                            <div class="col-5 text-end">
                                <field name="state" widget="label_selection"
                                       options="{'classes': {'draft': 'default', 'done': 'success', 'cancel': 'danger'}}"/>
                            </div>
                        </div>
                    </t>
                </templates>
            </kanban>
        </field>
    </record>

    <record id="view_cvi_card_search" model="ir.ui.view">
        <field name="name">cvi.card.search</field>
        <field name="model">cvi.card</field>
        <field name="arch" type="xml">
            <search string="Tarjetas">
                <field name="name"/>
                <field name="partner_id"/>
                <field name="vendor_id"/>
                <field name="collector_id"/>
                <field name="product_id"/>
                <field name="plan_id"/>
                <filter name="filter_draft" string="Borrador" domain="[('state', '=', 'draft')]"/>
                <filter name="filter_sold" string="Vendidas" domain="[('state', '=', 'sold')]"/>
                <filter name="filter_routed" string="Enrutadas" domain="[('state', '=', 'routed')]"/>
                <filter name="filter_active" string="En cobranza" domain="[('state', '=', 'active')]"/>
                <filter name="filter_done" string="Finalizadas" domain="[('state', '=', 'done')]"/>
                <separator/>
                <filter name="filter_no_collector" string="Sin cobrador"
                        domain="[('collector_id', '=', False)]"/>
                <filter name="filter_overdue" string="Con cuotas vencidas"
                        domain="[('overdue_installment_count', '&gt;', 0)]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_by_vendor" string="Vendedor"
                            context="{'group_by': 'vendor_id'}"/>
                    <filter name="group_by_collector" string="Cobrador"
                            context="{'group_by': 'collector_id'}"/>
                    <filter name="group_by_state" string="Estado"
                            context="{'group_by': 'state'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_cvi_card_my_sales" model="ir.actions.act_window">
        <field name="name">Mis ventas</field>
        <field name="res_model">cvi.card</field>
        <field name="view_mode">kanban,list,form</field>
        <field name="search_view_id" ref="view_cvi_card_search"/>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Cargá tu primera venta</p>
            <p>Elegí el cliente, el mueble y en cuántas cuotas lo vendés.</p>
        </field>
    </record>

    <record id="action_cvi_card_to_route" model="ir.actions.act_window">
        <field name="name">Tarjetas sin cobrador</field>
        <field name="res_model">cvi.card</field>
        <field name="view_mode">list,kanban,form</field>
        <field name="search_view_id" ref="view_cvi_card_search"/>
        <field name="domain">[('state', '=', 'sold'), ('collector_id', '=', False)]</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">No tenés tarjetas para enviar</p>
            <p>Acá aparecen las ventas confirmadas que todavía no asignaste a un cobrador.</p>
        </field>
    </record>

    <record id="action_cvi_card_pending_accept" model="ir.actions.act_window">
        <field name="name">Pendientes de aceptar</field>
        <field name="res_model">cvi.card</field>
        <field name="view_mode">list,kanban,form</field>
        <field name="search_view_id" ref="view_cvi_card_search"/>
        <field name="domain">[('state', '=', 'routed')]</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">No tenés tarjetas para aceptar</p>
            <p>Cuando un vendedor te envíe tarjetas, aparecen acá para que las aceptes.</p>
        </field>
    </record>

    <record id="action_cvi_card_portfolio" model="ir.actions.act_window">
        <field name="name">Mi cartera</field>
        <field name="res_model">cvi.card</field>
        <field name="view_mode">list,kanban,form</field>
        <field name="search_view_id" ref="view_cvi_card_search"/>
        <field name="domain">[('state', '=', 'active')]</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Tu cartera está vacía</p>
            <p>Acá ves las tarjetas que aceptaste y estás cobrando.</p>
        </field>
    </record>

    <record id="action_cvi_card_all" model="ir.actions.act_window">
        <field name="name">Todas las tarjetas</field>
        <field name="res_model">cvi.card</field>
        <field name="view_mode">list,kanban,form</field>
        <field name="search_view_id" ref="view_cvi_card_search"/>
    </record>
</odoo>
```

- [ ] **Step 2: Escribir las vistas de cuotas y de cobros**

`collections_from_vendors_installments/views/cvi_installment_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cvi_installment_list" model="ir.ui.view">
        <field name="name">cvi.installment.list</field>
        <field name="model">cvi.installment</field>
        <field name="arch" type="xml">
            <list string="Cuotas" create="false"
                  decoration-danger="state == 'overdue'" decoration-success="state == 'paid'">
                <field name="partner_id"/>
                <field name="street" optional="show"/>
                <field name="phone" optional="show"/>
                <field name="sequence" string="Cuota"/>
                <field name="date_due"/>
                <field name="amount_residual" sum="A cobrar"/>
                <field name="card_residual" optional="show"/>
                <field name="state"/>
                <button name="action_open_map" type="object" icon="fa-map-marker"
                        title="Abrir en el mapa" invisible="not map_url"/>
                <field name="map_url" column_invisible="True"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_cvi_installment_search" model="ir.ui.view">
        <field name="name">cvi.installment.search</field>
        <field name="model">cvi.installment</field>
        <field name="arch" type="xml">
            <search string="Cuotas">
                <field name="partner_id"/>
                <field name="card_id"/>
                <field name="collector_id"/>
                <filter name="filter_due_today" string="Vencen hoy o antes"
                        domain="[('date_due', '&lt;=', context_today().strftime('%Y-%m-%d'))]"/>
                <filter name="filter_unpaid" string="Impagas"
                        domain="[('state', 'in', ('pending', 'partial', 'overdue'))]"/>
                <filter name="filter_overdue" string="Vencidas"
                        domain="[('state', '=', 'overdue')]"/>
                <filter name="filter_collection" string="De cobranza"
                        domain="[('is_commission', '=', False)]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_by_partner" string="Cliente"
                            context="{'group_by': 'partner_id'}"/>
                    <filter name="group_by_due" string="Vencimiento"
                            context="{'group_by': 'date_due'}"/>
                    <filter name="group_by_collector" string="Cobrador"
                            context="{'group_by': 'collector_id'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_cvi_agenda" model="ir.actions.act_window">
        <field name="name">Agenda de cobro</field>
        <field name="res_model">cvi.installment</field>
        <field name="view_mode">list,form</field>
        <field name="search_view_id" ref="view_cvi_installment_search"/>
        <field name="domain">[('card_state', '=', 'active'), ('is_commission', '=', False)]</field>
        <field name="context">{'search_default_filter_due_today': 1, 'search_default_filter_unpaid': 1}</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">No tenés cobros pendientes para hoy</p>
            <p>Acá aparecen las cuotas de tu cartera que vencen hoy o que quedaron atrasadas.</p>
        </field>
    </record>
</odoo>
```

`collections_from_vendors_installments/views/cvi_payment_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cvi_payment_form" model="ir.ui.view">
        <field name="name">cvi.payment.form</field>
        <field name="model">cvi.payment</field>
        <field name="arch" type="xml">
            <form string="Cobro">
                <header>
                    <button name="action_post" type="object" string="Registrar cobro"
                            class="btn-primary" invisible="state != 'draft'"/>
                    <button name="action_cancel" type="object" string="Anular"
                            invisible="state != 'posted'"
                            confirm="¿Anular este cobro? La cuota vuelve a quedar pendiente."/>
                    <field name="state" widget="statusbar" statusbar_visible="draft,posted"/>
                </header>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="card_id" readonly="state != 'draft'"/>
                            <field name="partner_id" readonly="1"/>
                            <field name="date" readonly="state != 'draft'"/>
                        </group>
                        <group>
                            <field name="amount" readonly="state != 'draft'"/>
                            <field name="user_id"/>
                            <field name="is_commission" readonly="1"/>
                            <field name="currency_id" invisible="1"/>
                        </group>
                    </group>
                    <group string="Observación">
                        <field name="note" nolabel="1" readonly="state != 'draft'"/>
                    </group>
                    <group string="Imputación" invisible="state == 'draft'">
                        <field name="allocation_ids" nolabel="1" readonly="1">
                            <list>
                                <field name="installment_id"/>
                                <field name="amount"/>
                                <field name="currency_id" column_invisible="True"/>
                            </list>
                        </field>
                    </group>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="view_cvi_payment_list" model="ir.ui.view">
        <field name="name">cvi.payment.list</field>
        <field name="model">cvi.payment</field>
        <field name="arch" type="xml">
            <list string="Cobros" decoration-muted="state == 'cancel'">
                <field name="name"/>
                <field name="date"/>
                <field name="partner_id"/>
                <field name="card_id" optional="show"/>
                <field name="amount" sum="Total cobrado"/>
                <field name="user_id"/>
                <field name="is_commission" optional="hide"/>
                <field name="state"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="action_cvi_payment" model="ir.actions.act_window">
        <field name="name">Cobros</field>
        <field name="res_model">cvi.payment</field>
        <field name="view_mode">list,form</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Todavía no registraste cobros</p>
            <p>Registrá lo que te paga el cliente: se imputa solo a las cuotas más viejas.</p>
        </field>
    </record>
</odoo>
```

- [ ] **Step 3: Escribir las vistas de los wizards**

`collections_from_vendors_installments/views/cvi_wizard_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cvi_route_wizard_form" model="ir.ui.view">
        <field name="name">cvi.route.wizard.form</field>
        <field name="model">cvi.route.wizard</field>
        <field name="arch" type="xml">
            <form string="Enviar tarjetas a un cobrador">
                <group>
                    <field name="collector_id"/>
                    <field name="card_count" readonly="1"/>
                </group>
                <field name="card_ids" nolabel="1">
                    <list>
                        <field name="name"/>
                        <field name="partner_id"/>
                        <field name="plan_id"/>
                        <field name="installment_amount"/>
                        <field name="charge_day_display"/>
                        <field name="currency_id" column_invisible="True"/>
                    </list>
                </field>
                <footer>
                    <button name="action_confirm_route" type="object" string="Enviar"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="action_cvi_route_wizard" model="ir.actions.act_window">
        <field name="name">Enviar al cobrador</field>
        <field name="res_model">cvi.route.wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
        <field name="binding_model_id" ref="model_cvi_card"/>
        <field name="binding_view_types">list</field>
        <field name="context">{'default_card_ids': active_ids}</field>
    </record>

    <record id="view_cvi_reject_wizard_form" model="ir.ui.view">
        <field name="name">cvi.reject.wizard.form</field>
        <field name="model">cvi.reject.wizard</field>
        <field name="arch" type="xml">
            <form string="Rechazar tarjetas">
                <group>
                    <field name="reason" placeholder="Por qué devolvés estas tarjetas"/>
                </group>
                <field name="card_ids" nolabel="1" readonly="1">
                    <list>
                        <field name="name"/>
                        <field name="partner_id"/>
                        <field name="vendor_id"/>
                    </list>
                </field>
                <footer>
                    <button name="action_confirm_reject" type="object" string="Rechazar"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="view_cvi_transfer_wizard_form" model="ir.ui.view">
        <field name="name">cvi.transfer.wizard.form</field>
        <field name="model">cvi.transfer.wizard</field>
        <field name="arch" type="xml">
            <form string="Transferir tarjetas entre cobradores">
                <group>
                    <field name="collector_dest_id"/>
                    <field name="reason" placeholder="Motivo de la transferencia"/>
                    <field name="card_count" readonly="1"/>
                </group>
                <field name="card_ids" nolabel="1">
                    <list>
                        <field name="name"/>
                        <field name="partner_id"/>
                        <field name="collector_id" string="Cobrador actual"/>
                        <field name="amount_residual"/>
                        <field name="currency_id" column_invisible="True"/>
                    </list>
                </field>
                <footer>
                    <button name="action_confirm_transfer" type="object" string="Transferir"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="action_cvi_transfer_wizard" model="ir.actions.act_window">
        <field name="name">Transferir a otro cobrador</field>
        <field name="res_model">cvi.transfer.wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
        <field name="binding_model_id" ref="model_cvi_card"/>
        <field name="binding_view_types">list</field>
        <field name="context">{'default_card_ids': active_ids}</field>
        <field name="groups_id" eval="[(4, ref('group_cvi_manager'))]"/>
    </record>

    <record id="view_cvi_vendor_delivery_wizard_form" model="ir.ui.view">
        <field name="name">cvi.vendor.delivery.wizard.form</field>
        <field name="model">cvi.vendor.delivery.wizard</field>
        <field name="arch" type="xml">
            <form string="Mercadería de vendedores">
                <group>
                    <group>
                        <field name="vendor_id"/>
                        <field name="direction" widget="radio"/>
                    </group>
                    <group>
                        <field name="warehouse_id"/>
                    </group>
                </group>
                <field name="line_ids" nolabel="1">
                    <list editable="bottom">
                        <field name="product_id"/>
                        <field name="quantity"/>
                    </list>
                </field>
                <footer>
                    <button name="action_confirm_delivery" type="object" string="Confirmar"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="action_cvi_vendor_delivery" model="ir.actions.act_window">
        <field name="name">Entrega y devolución de mercadería</field>
        <field name="res_model">cvi.vendor.delivery.wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
    </record>
</odoo>
```

- [ ] **Step 4: Escribir los menús**

`collections_from_vendors_installments/views/menu_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_cvi_root" name="Venta en cuotas" sequence="45"
              web_icon="collections_from_vendors_installments,static/description/icon.png"/>

    <menuitem id="menu_cvi_vendor" name="Vendedor" parent="menu_cvi_root" sequence="10"
              groups="collections_from_vendors_installments.group_cvi_vendor"/>
    <menuitem id="menu_cvi_my_sales" name="Mis ventas" parent="menu_cvi_vendor"
              action="action_cvi_card_my_sales" sequence="10"/>
    <menuitem id="menu_cvi_to_route" name="Sin cobrador" parent="menu_cvi_vendor"
              action="action_cvi_card_to_route" sequence="20"/>

    <menuitem id="menu_cvi_collector" name="Cobrador" parent="menu_cvi_root" sequence="20"
              groups="collections_from_vendors_installments.group_cvi_collector"/>
    <menuitem id="menu_cvi_agenda" name="Agenda de cobro" parent="menu_cvi_collector"
              action="action_cvi_agenda" sequence="10"/>
    <menuitem id="menu_cvi_pending_accept" name="Pendientes de aceptar" parent="menu_cvi_collector"
              action="action_cvi_card_pending_accept" sequence="20"/>
    <menuitem id="menu_cvi_portfolio" name="Mi cartera" parent="menu_cvi_collector"
              action="action_cvi_card_portfolio" sequence="30"/>
    <menuitem id="menu_cvi_payments" name="Cobros" parent="menu_cvi_collector"
              action="action_cvi_payment" sequence="40"/>

    <menuitem id="menu_cvi_stock" name="Depósito" parent="menu_cvi_root" sequence="30"
              groups="stock.group_stock_user"/>
    <menuitem id="menu_cvi_vendor_delivery" name="Entregar / recibir mercadería"
              parent="menu_cvi_stock" action="action_cvi_vendor_delivery" sequence="10"/>
    <menuitem id="menu_cvi_vendor_stock" name="Mercadería en la calle"
              parent="menu_cvi_stock" action="action_cvi_vendor_stock" sequence="20"/>

    <menuitem id="menu_cvi_admin" name="Administración" parent="menu_cvi_root" sequence="40"
              groups="collections_from_vendors_installments.group_cvi_manager"/>
    <menuitem id="menu_cvi_all_cards" name="Todas las tarjetas" parent="menu_cvi_admin"
              action="action_cvi_card_all" sequence="10"/>
    <menuitem id="menu_cvi_transfer" name="Transferir cartera" parent="menu_cvi_admin"
              action="action_cvi_transfer_wizard" sequence="20"/>

    <menuitem id="menu_cvi_config" name="Configuración" parent="menu_cvi_root" sequence="90"
              groups="collections_from_vendors_installments.group_cvi_manager"/>
    <menuitem id="menu_cvi_settings" name="Ajustes" parent="menu_cvi_config"
              action="base_setup.action_general_configuration" sequence="10"/>
</odoo>
```

- [ ] **Step 5: Registrar las vistas en el manifest**

`__manifest__.py` — la lista `data` final queda así:

```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/stock_location.xml",
        "data/ir_cron.xml",
        "views/cvi_card_views.xml",
        "views/cvi_installment_views.xml",
        "views/cvi_payment_views.xml",
        "views/cvi_wizard_views.xml",
        "views/stock_quant_views.xml",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
```

- [ ] **Step 6: Validar el XML localmente antes de actualizar**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/collections_from_vendors_installments
for f in views/*.xml data/*.xml security/*.xml; do
  python3 -c "import xml.dom.minidom as m, sys; m.parse('$f')" || echo "ROTO: $f"
done
python3 -c "import csv; rows=list(csv.reader(open('security/ir.model.access.csv'))); print('columnas:', {len(r) for r in rows})"
python3 -c "import ast; ast.parse(open('__manifest__.py').read()); print('manifest ok')"
```

Esperado: ningún "ROTO", `columnas: {8}` y `manifest ok`.

- [ ] **Step 7: Actualizar el módulo y correr toda la suite**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -40
```

Esperado: el módulo carga sin errores de vista y `0 failed, 0 error(s)`.

> El menú raíz referencia `static/description/icon.png`, que se crea en la Task 16. Odoo no falla si el archivo no existe todavía: muestra el menú sin icono.

- [ ] **Step 8: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): vistas móviles, agenda, wizards y menús por rol"
```

---

## Task 16: Icono, README y verificación de extremo a extremo

Cierra el MVP: icono del módulo, documentación operativa y un test de circuito completo que recorre el flujo del spec de punta a punta.

**Files:**
- Create: `collections_from_vendors_installments/static/description/icon.png`
- Create: `collections_from_vendors_installments/README.md`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_full_flow.py`

**Interfaces:**
- Consumes: todo lo construido en las tasks 1 a 15.
- Produces: `static/description/icon.png` (512×512, estilo Cyber-Glassmorphic 3D con glifo "C"), `README.md`, y la clase de test `TestCviFullFlow`.

- [ ] **Step 1: Escribir el test de circuito completo**

`collections_from_vendors_installments/tests/test_full_flow.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviFullFlow(CviCommon):
    """Recorre el circuito del spec: fábrica -> vendedor -> cliente -> cobrador -> saldada."""

    def test_full_circuit_from_factory_to_settled_card(self):
        stock_location = self.warehouse.lot_stock_id
        quant_model = self.env["stock.quant"]

        # 1. La fábrica ingresa producción (HU-01).
        quant_model.with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": stock_location.id,
            "inventory_quantity": 20,
        }).action_apply_inventory()

        # 2. El depósito entrega 3 muebles al vendedor (HU-02).
        delivery = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": self.vendor_user.id,
            "direction": "out",
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 3})],
        })
        picking = delivery.action_confirm_delivery()
        self.assertEqual(picking.state, "done")
        vendor_location = self.vendor_user.cvi_stock_location_id

        # 3. El vendedor carga la venta en el domicilio (HU-05, HU-06).
        card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "quantity": 1.0,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        card.action_confirm()
        self.assertEqual(card.state, "sold")
        self.assertEqual(len(card.installment_ids), 3)

        # 4. La primera cuota es la comisión del vendedor (HU-09, RN-01).
        first = card.installment_ids.filtered(lambda i: i.sequence == 1)
        self.assertEqual(first.state, "paid")
        self.assertTrue(card.payment_ids.filtered("is_commission"))

        # 5. El mueble salió del stock del vendedor (HU-03).
        self.assertEqual(
            quant_model._get_available_quantity(self.product, vendor_location),
            502,  # 500 del fixture + 3 entregados - 1 vendido
        )

        # 6. El vendedor enruta la tarjeta al cobrador (HU-10, HU-11).
        route = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, card.ids)],
            "collector_id": self.collector_user.id,
        })
        route.action_confirm_route()
        self.assertEqual(card.state, "routed")

        # 7. El cobrador la acepta y entra en su cartera (HU-12, RN-02).
        card.with_user(self.collector_user).action_accept()
        self.assertEqual(card.state, "active")

        # 8. Cobra la cuota 2 completa y parte de la 3 (HU-15).
        payment = self.env["cvi.payment"].create({
            "card_id": card.id, "amount": 14000.0, "date": "2026-02-10",
        })
        payment.action_post()
        self.assertEqual(card.amount_residual, 6000.0)
        self.assertEqual(
            card.installment_ids.filtered(lambda i: i.sequence == 2).state, "paid"
        )
        self.assertEqual(
            card.installment_ids.filtered(lambda i: i.sequence == 3).state, "partial"
        )

        # 9. Cobra el resto y la tarjeta se cierra sola (HU-17).
        rest = self.env["cvi.payment"].create({
            "card_id": card.id, "amount": 6000.0, "date": "2026-03-10",
        })
        rest.action_post()
        self.assertEqual(card.amount_residual, 0.0)
        self.assertEqual(card.state, "done")

        # 10. El vendedor devuelve a fábrica los 2 muebles que no vendió (HU-04).
        before = quant_model._get_available_quantity(self.product, stock_location)
        giveback = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": self.vendor_user.id,
            "direction": "in",
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 2})],
        })
        giveback.action_confirm_delivery()
        self.assertEqual(
            quant_model._get_available_quantity(self.product, stock_location), before + 2
        )
```

Registrar en `tests/__init__.py` agregando `from . import test_full_flow`.

- [ ] **Step 2: Correr el test de circuito completo**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviFullFlow \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: PASA. Si falla, el problema está en la integración entre tasks, no en el test: revisar el paso concreto que rompe antes de tocar la aserción.

- [ ] **Step 3: Generar el icono del módulo**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/collections_from_vendors_installments
cp ~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg /tmp/cvi-icon.svg
```

Editar `/tmp/cvi-icon.svg` y cambiar el contenido del elemento `<text>` (el glifo) por `C`. Dejar los acentos cian `#22e6ff` y magenta `#ff3df0` como están.

Renderizar con Chrome headless (ImageMagick descarta el `<text>` y los gradientes radiales — no usarlo):

```bash
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="/home/alexis/Documents/Github/prometeo-odoo-modules/collections_from_vendors_installments/static/description/icon.png" \
  "file:///tmp/cvi-icon.svg"
```

Verificar que el PNG salió con contenido:

```bash
python3 -c "import os; p='collections_from_vendors_installments/static/description/icon.png'; print(p, os.path.getsize(p), 'bytes')"
```

Esperado: más de 10000 bytes. Si sale muy chico, el glifo no se renderizó: revisar el SVG.

- [ ] **Step 4: Escribir el README**

`collections_from_vendors_installments/README.md`:

```markdown
# Cobranza a vendedores y cuotas

Venta domiciliaria financiada para una fábrica de muebles: el vendedor retira
mercadería, la vende en cuotas en el domicilio del cliente, cobra la primera
cuota como comisión y enruta la tarjeta a un cobrador que gestiona el resto.

## Circuito

1. **Ingreso de producción** — Inventario nativo de Odoo. Un albarán de entrada
   o un ajuste suma cantidad por modelo en `WH/Stock`. Los muebles no se
   identifican por unidad: los productos no llevan lote ni serie.
2. **Entrega al vendedor** — Venta en cuotas > Depósito > *Entregar / recibir
   mercadería*, con dirección "Entrega al vendedor". Genera un albarán interno
   de `WH/Stock` a `Vendedores/<nombre>`. La ubicación del vendedor se crea sola
   la primera vez.
3. **Venta** — Venta en cuotas > Vendedor > *Mis ventas*. Se carga el cliente,
   el modelo de mueble y uno de los planes de cuotas de ese mueble. El plan fija
   cantidad de cuotas, importe de cuota y frecuencia; el precio total sale de
   cuotas × importe. El vendedor no puede cambiarlos: solo un administrador
   vende con valores distintos al plan. Al confirmar:
   - se descuenta el mueble del stock del vendedor hacia Clientes,
   - se genera el calendario de cuotas,
   - se registra el cobro de la primera cuota a nombre del vendedor.
4. **Enrutamiento** — El cobrador se puede elegir al cargar la venta, o después
   desde *Sin cobrador* seleccionando varias tarjetas y usando la acción
   *Enviar al cobrador*. La tarjeta queda "Enrutada".
5. **Aceptación** — Venta en cuotas > Cobrador > *Pendientes de aceptar*. Recién
   al aceptar el cobrador se hace responsable y la tarjeta entra en su cartera.
   También puede rechazarla indicando un motivo: vuelve al vendedor.
6. **Cobranza** — *Agenda de cobro* lista las cuotas de la cartera que vencen hoy
   o quedaron atrasadas, con dirección, teléfono, saldo de la tarjeta y un botón
   que abre la ubicación en el mapa. Los cobros se registran desde *Cobros* o
   desde la tarjeta.
7. **Cierre** — Cuando el residual llega a cero, la tarjeta pasa sola a
   Finalizada y sale de la cartera activa.

## Planes de cuotas

Cada modelo de mueble lleva sus propios planes, en la ficha del producto,
pestaña *Planes de cuotas*. Un plan es: nombre, cantidad de cuotas, importe de
cuota y modalidad (mensual o semanal). El precio total se calcula solo:
cantidad × importe.

| Plan | Cuotas | Importe | Total |
|---|---|---|---|
| 6 cuotas | 6 | 22.000 | 132.000 |
| 12 cuotas | 12 | 13.500 | 162.000 |
| 20 semanas | 20 | 7.000 | 140.000 |

El importe de cada cuota ya incluye el interés, por eso el total no es una
división del precio de contado. **El precio de lista del producto no se usa para
nada**: cada plan es una opción cerrada que se carga a mano. No hay coeficientes
ni tasas que mantener.

Los planes mensuales y semanales conviven en la misma tabla; elegir el plan es lo
que define la modalidad de cobro. Un plan archivado deja de ofrecerse en ventas
nuevas, pero las tarjetas ya vendidas con él no se tocan.

Definir planes requiere ser administrador; vendedores y cobradores solo los leen.

## Imputación de cobros

Un cobro se imputa automáticamente sobre las cuotas impagas de la tarjeta,
ordenadas por vencimiento (FIFO). Soporta pago parcial y pago de varias cuotas
de una vez. Un cobro que supere el saldo de la tarjeta se rechaza.

La cuota de comisión del vendedor está separada: un cobro normal nunca la toca,
y el cobrador no la ve como pendiente.

## Calendario de cuotas

- La cuota 1 vence el día de la venta (la cobra el vendedor).
- **Mensual**: la cuota 2 vence el día de cobro elegido, del mes siguiente al de
  la venta. Si el mes no llega a ese día (31 en febrero), vence el último día.
- **Semanal**: la cuota 2 vence en la próxima ocurrencia del día de la semana
  elegido, siempre posterior a la venta.
- Todas las cuotas valen el importe que fija el plan.

Una cuota puntual se puede correr de fecha a pedido del cliente sin tocar el
resto del calendario; queda registrado en el historial de la tarjeta.

## Roles

| Grupo | Ve | Puede |
|---|---|---|
| Vendedor | Sus propias ventas | Cargar y confirmar ventas, enrutar tarjetas |
| Cobrador | Las tarjetas donde figura como cobrador | Aceptar, rechazar, registrar cobros |
| Administrador de cobranzas | Todo | Configurar, transferir carteras, anular cobros |

Un cobro registrado no se puede borrar: solo anular, y queda el registro.
Precio, cantidad de cuotas, importe y mercadería quedan congelados al confirmar
la venta.

## Configuración

Ajustes > Venta en cuotas:
- **Cuotas por defecto** (12) — se propone al cargar una venta nueva.
- **Frecuencias permitidas** — mensual, semanal o ambas.
- **Días de tolerancia de mora** — atraso tolerado antes de marcar una cuota
  como vencida. Un cron diario recalcula las vencidas.

## Fuera de alcance de esta versión

Etapa 2 (rendición de caja, supervisión, morosidad, retiro del mueble, clientes
problemáticos) y etapa 3 (geolocalización de la venta, fotos de DNI y vivienda,
tablero de indicadores) no están implementadas. Cuando se implementen, la
decisión tomada es que el sistema **advierte pero no bloquea** ante falta de GPS,
falta de foto o cliente con antecedentes.

## Tests

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http
```
```

- [ ] **Step 5: Correr la suite completa una última vez**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -50
```

Esperado: `0 failed, 0 error(s)` sobre las 12 clases de test del módulo. Copiar la línea de resumen de Odoo en el mensaje del commit final.

- [ ] **Step 6: Verificar la instalación limpia sobre una base nueva**

Una actualización acumulada puede ocultar errores que solo aparecen al instalar
de cero (orden de la `data`, XMLIDs faltantes):

```bash
docker exec odoo-postgres18-1 createdb -U odoo cvi_clean_test
docker exec odoo-odoo-1 odoo -d cvi_clean_test -i collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | tail -40
docker exec odoo-postgres18-1 dropdb -U odoo cvi_clean_test
```

Esperado: instala sin errores y los tests pasan. Si falla acá pero pasa en `calidad`,
el problema es orden de carga en la lista `data` del manifest.

- [ ] **Step 7: Commit final**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): icono, README y test de circuito completo"
```

---

## Cobertura del spec

| Historia | Task | Nota |
|---|---|---|
| HU-01 Ingreso de producción | 11 | Inventario nativo, sin código; verificado por test |
| HU-02 Entrega a un vendedor | 11 | Wizard con dirección "Entrega al vendedor" |
| HU-03 Mercadería en poder de vendedores | 12 | Vista sobre `stock.quant`, agrupada por vendedor |
| HU-04 Devolución de no vendido | 11 | Mismo wizard, dirección "Devolución a fábrica" |
| HU-05 Registrar venta en el domicilio | 2, 3, 15 | Planes por producto + tarjeta + form y kanban móviles |
| HU-06 Frecuencia y día de cobro | 2, 3, 4 | La frecuencia viene del plan; el vendedor fija el día y se genera el calendario |
| HU-09 Cobrar la primera cuota | 6 | Cobro de comisión al confirmar |
| HU-10 Enrutar al momento de la venta | 6, 8 | `collector_id` al confirmar → estado Enrutada |
| HU-11 Enrutar en lote | 9 | Wizard masivo, probado con 100 tarjetas |
| HU-12 Aceptar tarjetas | 8, 15 | `action_accept` + vista "Pendientes de aceptar" |
| HU-13 Rechazar con motivo | 8 | Wizard de rechazo |
| HU-14 Agenda de cobro del día | 14, 15 | Cuotas por vencimiento + dirección + mapa |
| HU-15 Registrar el cobro | 5 | FIFO, parcial y multi-cuota |
| HU-16 Estado de una tarjeta | 7, 15 | Contadores + pestañas de cuotas y cobros |
| HU-17 Cerrar tarjeta saldada | 7 | Cierre automático al residual cero |
| HU-30 Transferir entre cobradores | 10 | Wizard solo para administrador |
| HU-31 Configurar parámetros | 1 | Cuotas por defecto, frecuencias, tolerancia |
| RN-01 Primera cuota = comisión | 4, 6 | `is_commission` en cuota y cobro |
| RN-02 Responsabilidad al aceptar | 8 | Estado `active` solo tras aceptar |
| RN-03 Cobrador con varios vendedores | 9, 13 | Sin restricción por vendedor en la cartera |
| RN-04 Solo el admin transfiere | 10 | Acceso al wizard limitado al grupo manager |
| RN-05 Campos congelados | 3, 6 | El plan fija el precio y el vendedor no lo edita; tras confirmar, `write` bloquea `CVI_FROZEN_FIELDS` |
| RN-06 Cobros no se borran | 5 | `unlink` bloqueado + `action_cancel` |
| RN-07 Cada rol ve lo suyo | 13 | `ir.rule` por grupo |
| RN-08 Auditoría | 3, 4, 5 | `mail.thread` + `cvi.audit.mixin._cvi_log` en cada acción |
| RNF-01 Uso móvil | 15 | Kanban `o_kanban_mobile`, form por grupos cortos |
| RNF-05 Enrutamiento de 100+ | 9 | Un `write` sobre el recordset completo |

**Fuera del MVP, con plan propio pendiente:** HU-07, HU-08 (etapa 3: GPS y fotos), HU-18 a HU-29 (etapa 2: rendición, supervisión, morosidad, retiro, clientes problemáticos), HU-32 (etapa 3: tablero). RNF-02 (offline) queda descartado para el MVP; RNF-03 y RNF-04 aplican a la etapa 3.
