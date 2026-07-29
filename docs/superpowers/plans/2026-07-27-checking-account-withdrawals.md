# checking_account_withdrawals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un módulo Odoo 18 de cuenta corriente para retiros de mercadería a fiado, con cuotas, pagos, imputación FIFO, dashboard OWL y reporte PDF, sin tocar la contabilidad fiscal.

**Architecture:** Modelos propios con prefijo `caw.` (standalone, sin `account.move`). El estado del retiro nunca se escribe: es un `compute` con `store=True` que sube en cascada desde `caw.allocation` → `caw.installment` → `caw.withdrawal` → `caw.account`. El stock sale por un `stock.picking` propio. El dashboard replica la arquitectura de `account_management_metrics` (controller JSON con SQL parametrizado + componente OWL con Chart.js).

**Tech Stack:** Odoo 18.0, PostgreSQL, OWL 2, Chart.js (CDN vía `loadJS`), QWeb.

## Global Constraints

- Módulo en `/home/alexis/Documents/Github/prometeo-odoo-modules/checking_account_withdrawals/`, rama `cuentav2`.
- Versión del manifiesto: `18.0.1.0.0`. Licencia `LGPL-3`. Author `Alexis Medina`. Website `alexis.medn@gmail.com`.
- Odoo 18: las vistas lista usan `<list>`, **no** `<tree>`. Traducciones con `_("texto %s", arg)` (coma, no `%`).
- snake_case en todo. Docstring en español en cada método. Un archivo por modelo.
- Orden de `data` en el manifiesto: `security/*` → `data/` → `views/` → `report/`.
- Todos los modelos llevan `company_id` con `ir.rule` por compañía.
- Monetary siempre acompañado de `currency_id` (related de `company_id.currency_id`).
- **Nunca** implicar `stock.group_stock_user` dentro de `group_cc_user` (la OR-combination de `ir.rule` anularía las restricciones). Para operaciones privilegiadas, patrón sudo.
- **Los tests y upgrades corren SIEMPRE contra la DB `calidad`, NUNCA contra `prod`.**
- Comando de upgrade: `docker exec odoo-odoo-1 odoo -u checking_account_withdrawals -d calidad --stop-after-init --no-http`
- Comando de tests: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
- Validación local sin DB: `python3 -c "import ast; ast.parse(open('f.py').read())"` y `python3 -c "import xml.dom.minidom as m; m.parse('f.xml')"`.
- El spec de referencia es `docs/superpowers/specs/2026-07-27-checking-account-withdrawals-design.md`.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `__manifest__.py`, `__init__.py` | Declaración del módulo |
| `models/res_company.py` | Defaults del plan de cuotas y tipo de operación de stock |
| `models/res_partner.py` | `caw_enabled` + saldos agregados + smart button |
| `models/caw_account.py` | Cuenta corriente por partner+compañía, límite y saldos |
| `models/caw_withdrawal.py` | Retiro: total, estado derivado, picking, mora |
| `models/caw_withdrawal_line.py` | Línea del retiro |
| `models/caw_installment.py` | Cuota: residual y estado |
| `models/caw_payment.py` | Pago sobre la cuenta + imputación FIFO |
| `models/caw_allocation.py` | Imputación pago ↔ cuota |
| `wizards/caw_confirm_wizard.py` | Plan de cuotas + chequeo de límite al confirmar |
| `wizards/caw_allocate_wizard.py` | Imputación manual (Manager) |
| `controllers/dashboard_controller.py` | Endpoints JSON/CSV del dashboard |
| `security/security.xml`, `security/ir.model.access.csv` | Grupos, reglas y accesos |
| `data/ir_sequence.xml`, `data/ir_cron.xml` | Secuencias y cron de vencidas |
| `views/*.xml` | Formularios, listas, menús |
| `report/report_caw_statement*.xml` | Resumen de cuenta PDF |
| `static/src/{js,xml,css}/dashboard.*` | Dashboard OWL |
| `tests/test_*.py` | Los casos críticos de CC-31 y los de imputación |

---

### Task 1: Scaffold del módulo, grupos y accesos

**Files:**
- Create: `checking_account_withdrawals/__init__.py`
- Create: `checking_account_withdrawals/__manifest__.py`
- Create: `checking_account_withdrawals/models/__init__.py`
- Create: `checking_account_withdrawals/security/security.xml`
- Create: `checking_account_withdrawals/security/ir.model.access.csv`
- Delete: la carpeta vacía `cuenta_corriente_retiros/`

**Interfaces:**
- Consumes: nada.
- Produces: los xmlids `checking_account_withdrawals.group_cc_user` y `checking_account_withdrawals.group_cc_manager`, usados por todas las tareas siguientes.

- [ ] **Step 1: Borrar la carpeta vacía del intento anterior**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
rmdir cuenta_corriente_retiros/models cuenta_corriente_retiros
```

- [ ] **Step 2: Crear `__init__.py` raíz y de `models/`**

`checking_account_withdrawals/__init__.py`:
```python
from . import models
```

`checking_account_withdrawals/models/__init__.py` (vacío por ahora, se irá llenando):
```python
```

- [ ] **Step 3: Crear el manifiesto**

`checking_account_withdrawals/__manifest__.py`:
```python
# -*- coding: utf-8 -*-
{
    "name": "Cuenta Corriente - Retiros de mercadería",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Retiros a cuenta corriente con cuotas, pagos, imputación FIFO y dashboard",
    "description": """
        Permite que contactos habilitados retiren mercadería sin pagar en el momento,
        llevando una cuenta corriente propia con cuotas, pagos e imputaciones.

        No genera asientos contables ni comprobantes fiscales: usa modelos propios
        (prefijo caw.) y descuenta stock mediante un albarán de salida.

        El estado del retiro se deriva siempre del estado de sus cuotas: un retiro
        solo figura como pagado cuando TODAS sus cuotas están canceladas.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "stock", "product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "auto_install": False,
    "application": True,
}
```

- [ ] **Step 4: Crear los grupos y la categoría**

`checking_account_withdrawals/security/security.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="module_category_checking_account" model="ir.module.category">
        <field name="name">Cuenta Corriente</field>
        <field name="description">Gestión de retiros de mercadería a cuenta corriente</field>
        <field name="sequence">20</field>
    </record>

    <record id="group_cc_user" model="res.groups">
        <field name="name">Operador de Cuenta Corriente</field>
        <field name="category_id" ref="module_category_checking_account"/>
        <field name="comment">Puede crear retiros, registrar pagos y consultar saldos. No puede modificar límites de crédito, imputar manualmente ni cancelar retiros.</field>
    </record>

    <record id="group_cc_manager" model="res.groups">
        <field name="name">Manager de Cuenta Corriente</field>
        <field name="category_id" ref="module_category_checking_account"/>
        <field name="comment">Además de lo del Operador: define límites de crédito, imputa pagos manualmente, cancela retiros, anula pagos y fuerza retiros por encima del límite.</field>
        <field name="implied_ids" eval="[(4, ref('group_cc_user'))]"/>
    </record>
</odoo>
```

- [ ] **Step 5: Crear el CSV de accesos vacío (solo cabecera)**

`checking_account_withdrawals/security/ir.model.access.csv`:
```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
```

Las filas se agregan en cada tarea que crea un modelo. Un CSV con solo cabecera es válido.

- [ ] **Step 6: Validar sintaxis local**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/checking_account_withdrawals
python3 -c "import ast; ast.parse(open('__manifest__.py').read())"
python3 -c "import xml.dom.minidom as m; m.parse('security/security.xml')"
```
Esperado: sin salida (ningún error).

- [ ] **Step 7: Instalar el módulo en `calidad`**

```bash
docker exec odoo-odoo-1 odoo -i checking_account_withdrawals -d calidad --stop-after-init --no-http
```
Esperado: `Module checking_account_withdrawals: loading` sin ERROR ni traceback.

- [ ] **Step 8: Commit**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
git add -A checking_account_withdrawals cuenta_corriente_retiros
git commit -m "feat(checking_account_withdrawals): scaffold del módulo con grupos de seguridad"
```

---

### Task 2: Configuración por compañía, cuenta corriente y habilitación del partner

**Files:**
- Create: `checking_account_withdrawals/models/res_company.py`
- Create: `checking_account_withdrawals/models/caw_account.py`
- Create: `checking_account_withdrawals/models/res_partner.py`
- Create: `checking_account_withdrawals/tests/__init__.py`
- Create: `checking_account_withdrawals/tests/common.py`
- Create: `checking_account_withdrawals/tests/test_account.py`
- Modify: `checking_account_withdrawals/models/__init__.py`
- Modify: `checking_account_withdrawals/security/ir.model.access.csv`
- Modify: `checking_account_withdrawals/security/security.xml`

**Interfaces:**
- Consumes: `group_cc_user`, `group_cc_manager` (Task 1).
- Produces:
  - `res.company.caw_installment_count` (Integer), `caw_installment_days` (Integer), `caw_installment_period` (Selection `days`/`weeks`/`months`), `caw_cutoff_day` (Integer 0-28, 0 = sin día de corte), `caw_picking_type_id` (Many2one `stock.picking.type`).
  - `caw.account` con campos `partner_id`, `company_id`, `currency_id`, `credit_limit`, `limit_mode`, `active`. Los campos `balance`, `overdue_balance`, `credit_balance` se agregan en Task 7.
  - `res.partner.caw_enabled` (Boolean) y `res.partner.caw_account_ids` (One2many).
  - `caw.account._get_or_create(partner, company)` → devuelve el recordset de la cuenta.
  - `tests/common.py` con la clase `CawCommon` que las demás tareas de test heredan.

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/__init__.py`:
```python
from . import test_account
```

`checking_account_withdrawals/tests/common.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CawCommon(TransactionCase):
    """Fixtures compartidos por todos los tests del módulo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.partner = cls.env["res.partner"].create({
            "name": "Fiado Test",
            "company_id": False,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Producto CC Test",
            "type": "consu",
            "is_storable": True,
            "list_price": 100.0,
        })
```

`checking_account_withdrawals/tests/test_account.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawAccount(CawCommon):

    def test_enabling_partner_creates_account(self):
        """Marcar caw_enabled crea automáticamente la cuenta de la compañía activa."""
        self.assertFalse(self.partner.caw_account_ids)
        self.partner.caw_enabled = True
        account = self.partner.caw_account_ids
        self.assertEqual(len(account), 1)
        self.assertEqual(account.partner_id, self.partner)
        self.assertEqual(account.company_id, self.company)
        self.assertEqual(account.limit_mode, "none")

    def test_account_is_unique_per_partner_and_company(self):
        """No se pueden crear dos cuentas para el mismo partner en la misma compañía."""
        self.partner.caw_enabled = True
        with self.assertRaises(Exception):
            self.env["caw.account"].create({
                "partner_id": self.partner.id,
                "company_id": self.company.id,
            })
            self.env.flush_all()

    def test_get_or_create_is_idempotent(self):
        """_get_or_create devuelve la cuenta existente en vez de duplicarla."""
        first = self.env["caw.account"]._get_or_create(self.partner, self.company)
        second = self.env["caw.account"]._get_or_create(self.partner, self.company)
        self.assertEqual(first, second)
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals \
  --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http
```
Esperado: FAIL — el modelo `caw.account` no existe y `res.partner` no tiene `caw_enabled`.

- [ ] **Step 3: Implementar la configuración por compañía**

`checking_account_withdrawals/models/res_company.py`:
```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    caw_installment_count = fields.Integer(
        string="Cuotas por defecto",
        default=1,
        help="Cantidad de cuotas propuesta al confirmar un retiro.",
    )
    caw_installment_days = fields.Integer(
        string="Días hasta el primer vencimiento",
        default=30,
        help="Días desde la fecha del retiro hasta el vencimiento de la primera cuota.",
    )
    caw_installment_period = fields.Selection(
        selection=[("days", "Días"), ("weeks", "Semanas"), ("months", "Meses")],
        string="Periodicidad de cuotas",
        default="months",
    )
    caw_cutoff_day = fields.Integer(
        string="Día de corte",
        default=0,
        help="Día del mes al que se ajustan los vencimientos. 0 = sin día de corte.",
    )
    caw_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Tipo de operación para retiros",
        domain="[('code', '=', 'outgoing'), ('company_id', '=', id)]",
        help="Tipo de operación usado para el albarán de salida del retiro. "
             "Si está vacío se usa el de salidas del almacén principal.",
    )
```

- [ ] **Step 4: Implementar `caw.account`**

`checking_account_withdrawals/models/caw_account.py`:
```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CawAccount(models.Model):
    _name = "caw.account"
    _description = "Cuenta corriente de retiros"
    _inherit = ["mail.thread"]
    _rec_name = "partner_id"
    _order = "partner_id, company_id"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contacto",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Moneda",
        readonly=True,
    )
    credit_limit = fields.Monetary(
        string="Límite de crédito",
        currency_field="currency_id",
        tracking=True,
        groups="checking_account_withdrawals.group_cc_manager",
    )
    limit_mode = fields.Selection(
        selection=[
            ("none", "Sin control"),
            ("warn", "Advertencia"),
            ("block", "Bloqueo"),
        ],
        string="Modo de límite",
        default="none",
        required=True,
        tracking=True,
        groups="checking_account_withdrawals.group_cc_manager",
        help="Advertencia: el Operador ve el aviso y puede continuar. "
             "Bloqueo: solo un Manager puede forzar el retiro.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "partner_company_uniq",
            "UNIQUE(partner_id, company_id)",
            "Ya existe una cuenta corriente para este contacto en esta compañía.",
        ),
    ]

    @api.constrains("credit_limit")
    def _check_credit_limit(self):
        """El límite de crédito no puede ser negativo."""
        for account in self:
            if account.credit_limit < 0:
                raise ValidationError(_("El límite de crédito no puede ser negativo."))

    @api.model
    def _get_or_create(self, partner, company):
        """Devuelve la cuenta del partner en la compañía, creándola si no existe."""
        account = self.with_context(active_test=False).search([
            ("partner_id", "=", partner.id),
            ("company_id", "=", company.id),
        ], limit=1)
        if account:
            if not account.active:
                account.active = True
            return account
        _logger.info("Creando cuenta corriente para %s en %s", partner.display_name, company.name)
        return self.create({
            "partner_id": partner.id,
            "company_id": company.id,
        })
```

- [ ] **Step 5: Implementar la habilitación en el partner**

`checking_account_withdrawals/models/res_partner.py`:
```python
# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    caw_enabled = fields.Boolean(
        string="Habilitado para cuenta corriente",
        tracking=True,
        help="Si está marcado, este contacto puede retirar mercadería a cuenta corriente. "
             "Al marcarlo se crea automáticamente su cuenta en la compañía activa.",
    )
    caw_account_ids = fields.One2many(
        comodel_name="caw.account",
        inverse_name="partner_id",
        string="Cuentas corrientes",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Crea la cuenta corriente de los contactos que nacen habilitados."""
        partners = super().create(vals_list)
        partners.filtered("caw_enabled")._caw_ensure_account()
        return partners

    def write(self, vals):
        """Crea la cuenta corriente al habilitar el contacto."""
        res = super().write(vals)
        if vals.get("caw_enabled"):
            self._caw_ensure_account()
        return res

    def _caw_ensure_account(self):
        """Garantiza que exista la cuenta del contacto en la compañía activa."""
        account_model = self.env["caw.account"].sudo()
        for partner in self:
            account_model._get_or_create(partner, self.env.company)
```

- [ ] **Step 6: Registrar los modelos y los accesos**

`checking_account_withdrawals/models/__init__.py`:
```python
from . import res_company
from . import caw_account
from . import res_partner
```

`checking_account_withdrawals/__init__.py` queda sin cambios (`from . import models`). Odoo descubre el paquete `tests/` solo — **no** lo importes desde el `__init__.py` raíz.

Agregar a `checking_account_withdrawals/security/ir.model.access.csv`:
```csv
access_caw_account_user,caw.account user,model_caw_account,checking_account_withdrawals.group_cc_user,1,0,0,0
access_caw_account_manager,caw.account manager,model_caw_account,checking_account_withdrawals.group_cc_manager,1,1,1,1
```

Agregar la regla por compañía al final de `security/security.xml`, antes de `</odoo>`:
```xml
    <record id="caw_account_company_rule" model="ir.rule">
        <field name="name">caw.account: multi-compañía</field>
        <field name="model_id" ref="model_caw_account"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals \
  --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http
```
Esperado: `3 tests, 0 failed, 0 error`.

- [ ] **Step 8: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): cuenta corriente y habilitación del partner"
```

---

### Task 3: Retiro en borrador con sus líneas y total

**Files:**
- Create: `checking_account_withdrawals/models/caw_withdrawal.py`
- Create: `checking_account_withdrawals/models/caw_withdrawal_line.py`
- Create: `checking_account_withdrawals/data/ir_sequence.xml`
- Create: `checking_account_withdrawals/tests/test_withdrawal.py`
- Modify: `checking_account_withdrawals/models/__init__.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`
- Modify: `checking_account_withdrawals/__manifest__.py`
- Modify: `checking_account_withdrawals/security/ir.model.access.csv`
- Modify: `checking_account_withdrawals/security/security.xml`

**Interfaces:**
- Consumes: `caw.account` y `caw.account._get_or_create` (Task 2).
- Produces:
  - `caw.withdrawal` con `name`, `account_id`, `partner_id`, `date`, `user_id`, `company_id`, `currency_id`, `note`, `line_ids`, `amount_total`, `state`.
  - `caw.withdrawal.line` con `withdrawal_id`, `product_id`, `name`, `quantity`, `price_unit`, `price_subtotal`.
  - **`state` es un Selection plano en esta tarea** con valores `draft`/`pending`/`partial`/`paid`/`cancel`. La Task 6 lo **reemplaza** por un `compute store=True`; los valores no cambian.
  - Secuencia `checking_account_withdrawals.seq_caw_withdrawal` (prefijo `CC/%(year)s/`).

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_withdrawal.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawWithdrawal(CawCommon):

    def _new_withdrawal(self, lines=None):
        """Crea un retiro en borrador con las líneas indicadas."""
        self.partner.caw_enabled = True
        lines = lines or [(2.0, 150.0), (1.0, 300.0)]
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "line_ids": [
                (0, 0, {
                    "product_id": self.product.id,
                    "quantity": qty,
                    "price_unit": price,
                })
                for qty, price in lines
            ],
        })

    def test_amount_total_sums_lines(self):
        """El total del retiro es la suma de los subtotales de sus líneas."""
        withdrawal = self._new_withdrawal()
        self.assertEqual(withdrawal.line_ids[0].price_subtotal, 300.0)
        self.assertEqual(withdrawal.line_ids[1].price_subtotal, 300.0)
        self.assertEqual(withdrawal.amount_total, 600.0)

    def test_account_is_assigned_from_partner(self):
        """Al crear el retiro se resuelve la cuenta corriente del partner."""
        withdrawal = self._new_withdrawal()
        self.assertTrue(withdrawal.account_id)
        self.assertEqual(withdrawal.account_id.partner_id, self.partner)
        self.assertEqual(withdrawal.account_id.company_id, withdrawal.company_id)

    def test_name_comes_from_sequence(self):
        """El retiro toma su número de la secuencia propia del módulo."""
        withdrawal = self._new_withdrawal()
        self.assertNotEqual(withdrawal.name, "/")
        self.assertTrue(withdrawal.name.startswith("CC/"))

    def test_starts_in_draft(self):
        """Un retiro nace en borrador."""
        self.assertEqual(self._new_withdrawal().state, "draft")

    def test_disabled_partner_is_rejected(self):
        """No se puede crear un retiro para un contacto sin cuenta corriente habilitada."""
        from odoo.exceptions import UserError
        other = self.env["res.partner"].create({"name": "No habilitado"})
        with self.assertRaises(UserError):
            self.env["caw.withdrawal"].create({"partner_id": other.id})
```

`checking_account_withdrawals/tests/__init__.py`:
```python
from . import test_account
from . import test_withdrawal
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — el modelo `caw.withdrawal` no existe.

- [ ] **Step 3: Crear la secuencia**

`checking_account_withdrawals/data/ir_sequence.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="seq_caw_withdrawal" model="ir.sequence">
        <field name="name">Retiro de cuenta corriente</field>
        <field name="code">caw.withdrawal</field>
        <field name="prefix">CC/%(year)s/</field>
        <field name="padding">5</field>
        <field name="company_id" eval="False"/>
    </record>
</odoo>
```

- [ ] **Step 4: Implementar la línea del retiro**

`checking_account_withdrawals/models/caw_withdrawal_line.py`:
```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CawWithdrawalLine(models.Model):
    _name = "caw.withdrawal.line"
    _description = "Línea de retiro de cuenta corriente"
    _order = "withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="caw.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        related="withdrawal_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto",
        required=True,
        ondelete="restrict",
    )
    name = fields.Char(string="Descripción")
    quantity = fields.Float(
        string="Cantidad",
        default=1.0,
        required=True,
        digits="Product Unit of Measure",
    )
    price_unit = fields.Float(
        string="Precio unitario",
        required=True,
        digits="Product Price",
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
        currency_field="currency_id",
    )

    @api.depends("quantity", "price_unit")
    def _compute_price_subtotal(self):
        """Subtotal de la línea, sin impuestos."""
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.constrains("quantity", "price_unit")
    def _check_positive_values(self):
        """Cantidad y precio no pueden ser negativos."""
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("La cantidad de la línea debe ser mayor a cero."))
            if line.price_unit < 0:
                raise ValidationError(_("El precio unitario no puede ser negativo."))

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Propone descripción y precio de lista del producto."""
        for line in self:
            if line.product_id:
                line.name = line.product_id.display_name
                line.price_unit = line.product_id.list_price
```

- [ ] **Step 5: Implementar el retiro**

`checking_account_withdrawals/models/caw_withdrawal.py`:
```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("pending", "Pendiente"),
    ("partial", "Pago parcial"),
    ("paid", "Pagado"),
    ("cancel", "Cancelado"),
]


class CawWithdrawal(models.Model):
    _name = "caw.withdrawal"
    _description = "Retiro de mercadería a cuenta corriente"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(
        string="Número",
        required=True,
        copy=False,
        readonly=True,
        default="/",
    )
    account_id = fields.Many2one(
        comodel_name="caw.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contacto",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        domain="[('caw_enabled', '=', True)]",
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsable",
        default=lambda self: self.env.user,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Moneda",
        readonly=True,
    )
    note = fields.Text(string="Notas")
    line_ids = fields.One2many(
        comodel_name="caw.withdrawal.line",
        inverse_name="withdrawal_id",
        string="Líneas",
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        default="draft",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )

    @api.depends("line_ids.price_subtotal")
    def _compute_amount_total(self):
        """Total del retiro: suma de los subtotales de sus líneas."""
        for withdrawal in self:
            withdrawal.amount_total = sum(withdrawal.line_ids.mapped("price_subtotal"))

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna número de secuencia y resuelve la cuenta corriente del contacto."""
        for vals in vals_list:
            if not vals.get("account_id"):
                vals["account_id"] = self._caw_resolve_account(vals).id
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("caw.withdrawal") or "/"
        return super().create(vals_list)

    @api.model
    def _caw_resolve_account(self, vals):
        """Devuelve la cuenta corriente del contacto, validando que esté habilitado."""
        partner = self.env["res.partner"].browse(vals.get("partner_id"))
        company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
        if not partner or not partner.caw_enabled:
            raise UserError(_(
                "El contacto %s no está habilitado para cuenta corriente.",
                partner.display_name or "",
            ))
        return self.env["caw.account"].sudo()._get_or_create(partner, company)

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        """Restringe el selector de contactos a los habilitados."""
        if self.partner_id and not self.partner_id.caw_enabled:
            self.partner_id = False
            return {"warning": {
                "title": _("Contacto no habilitado"),
                "message": _("Ese contacto no está habilitado para cuenta corriente."),
            }}

    def unlink(self):
        """Solo se pueden borrar retiros en borrador o cancelados."""
        if any(w.state not in ("draft", "cancel") for w in self):
            raise UserError(_("Solo se pueden eliminar retiros en borrador o cancelados."))
        return super().unlink()
```

- [ ] **Step 6: Registrar modelos, datos y accesos**

`checking_account_withdrawals/models/__init__.py`:
```python
from . import res_company
from . import caw_account
from . import res_partner
from . import caw_withdrawal
from . import caw_withdrawal_line
```

En `__manifest__.py`, la clave `data` pasa a:
```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
    ],
```

Agregar a `security/ir.model.access.csv`:
```csv
access_caw_withdrawal_user,caw.withdrawal user,model_caw_withdrawal,checking_account_withdrawals.group_cc_user,1,1,1,0
access_caw_withdrawal_manager,caw.withdrawal manager,model_caw_withdrawal,checking_account_withdrawals.group_cc_manager,1,1,1,1
access_caw_withdrawal_line_user,caw.withdrawal.line user,model_caw_withdrawal_line,checking_account_withdrawals.group_cc_user,1,1,1,1
access_caw_withdrawal_line_manager,caw.withdrawal.line manager,model_caw_withdrawal_line,checking_account_withdrawals.group_cc_manager,1,1,1,1
```

Agregar a `security/security.xml` antes de `</odoo>`:
```xml
    <record id="caw_withdrawal_company_rule" model="ir.rule">
        <field name="name">caw.withdrawal: multi-compañía</field>
        <field name="model_id" ref="model_caw_withdrawal"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>

    <record id="caw_withdrawal_line_company_rule" model="ir.rule">
        <field name="name">caw.withdrawal.line: multi-compañía</field>
        <field name="model_id" ref="model_caw_withdrawal_line"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `8 tests, 0 failed, 0 error`.

- [ ] **Step 8: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): retiro en borrador con líneas y total"
```

---

### Task 4: Cuotas y generación automática al confirmar

**Files:**
- Create: `checking_account_withdrawals/models/caw_installment.py`
- Create: `checking_account_withdrawals/tests/test_installment.py`
- Modify: `checking_account_withdrawals/models/caw_withdrawal.py`
- Modify: `checking_account_withdrawals/models/__init__.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`
- Modify: `checking_account_withdrawals/security/ir.model.access.csv`
- Modify: `checking_account_withdrawals/security/security.xml`

**Interfaces:**
- Consumes: `caw.withdrawal` (Task 3), los campos `caw_installment_*` y `caw_cutoff_day` de `res.company` (Task 2).
- Produces:
  - `caw.installment` con `withdrawal_id`, `account_id`, `partner_id`, `company_id`, `currency_id`, `sequence`, `date_due`, `amount`, `amount_allocated`, `amount_residual`, `state`. `amount_allocated` es un Float plano en esta tarea; la Task 5 lo **reemplaza** por un compute sobre `allocation_ids`.
  - `caw.withdrawal.installment_ids` (One2many).
  - `caw.withdrawal._caw_build_installment_values(count, first_days, period, cutoff_day)` → lista de dicts listos para `create`. Redondea en la última cuota.
  - `caw.withdrawal.action_confirm()` → genera cuotas con los defaults de la compañía y pasa a `pending`.

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_installment.py`:
```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawInstallment(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True

    def _withdrawal(self, total=1000.0):
        """Retiro en borrador por el total indicado (una sola línea)."""
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-15",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })

    def test_single_installment_cash_mode(self):
        """Contado en cuenta: una sola cuota por el total, a X días."""
        withdrawal = self._withdrawal(1000.0)
        withdrawal._caw_generate_installments(count=1, first_days=30, period="months", cutoff_day=0)
        self.assertEqual(len(withdrawal.installment_ids), 1)
        installment = withdrawal.installment_ids
        self.assertEqual(installment.amount, 1000.0)
        self.assertEqual(str(installment.date_due), "2026-02-14")

    def test_fixed_installments_sum_equals_total(self):
        """Tres cuotas sobre 1000: la suma iguala exactamente el total."""
        withdrawal = self._withdrawal(1000.0)
        withdrawal._caw_generate_installments(count=3, first_days=30, period="months", cutoff_day=0)
        amounts = withdrawal.installment_ids.mapped("amount")
        self.assertEqual(len(amounts), 3)
        self.assertEqual(sum(amounts), 1000.0)

    def test_rounding_goes_to_last_installment(self):
        """El resto del redondeo se acumula en la última cuota, no en las primeras."""
        withdrawal = self._withdrawal(1000.0)
        withdrawal._caw_generate_installments(count=3, first_days=30, period="months", cutoff_day=0)
        amounts = withdrawal.installment_ids.sorted("sequence").mapped("amount")
        self.assertEqual(amounts[0], 333.33)
        self.assertEqual(amounts[1], 333.33)
        self.assertEqual(amounts[2], 333.34)

    def test_cutoff_day_shifts_due_dates(self):
        """Con día de corte 10, los vencimientos caen el 10 de cada mes."""
        withdrawal = self._withdrawal(900.0)
        withdrawal._caw_generate_installments(count=3, first_days=30, period="months", cutoff_day=10)
        dues = [str(d) for d in withdrawal.installment_ids.sorted("sequence").mapped("date_due")]
        self.assertEqual(dues, ["2026-02-10", "2026-03-10", "2026-04-10"])

    def test_confirm_generates_installments_and_moves_state(self):
        """Confirmar genera las cuotas con los defaults de la compañía y pasa a pendiente."""
        self.company.caw_installment_count = 2
        self.company.caw_installment_days = 15
        self.company.caw_cutoff_day = 0
        withdrawal = self._withdrawal(500.0)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(len(withdrawal.installment_ids), 2)
        self.assertEqual(sum(withdrawal.installment_ids.mapped("amount")), 500.0)

    def test_confirm_rejects_empty_withdrawal(self):
        """No se confirma un retiro sin líneas."""
        withdrawal = self.env["caw.withdrawal"].create({"partner_id": self.partner.id})
        with self.assertRaises(UserError):
            withdrawal.action_confirm()

    def test_confirm_rejects_zero_total(self):
        """No se confirma un retiro con total menor o igual a cero."""
        withdrawal = self._withdrawal(0.0)
        with self.assertRaises(UserError):
            withdrawal.action_confirm()

    def test_manual_installments_must_match_total(self):
        """La suma de cuotas cargadas a mano debe igualar exactamente el total."""
        withdrawal = self._withdrawal(1000.0)
        with self.assertRaises(ValidationError):
            self.env["caw.installment"].create({
                "withdrawal_id": withdrawal.id,
                "sequence": 1,
                "date_due": "2026-02-15",
                "amount": 400.0,
            })
            withdrawal.installment_ids._check_total_matches_withdrawal()

    def test_due_date_cannot_precede_withdrawal_date(self):
        """El vencimiento de una cuota no puede ser anterior a la fecha del retiro."""
        withdrawal = self._withdrawal(1000.0)
        with self.assertRaises(ValidationError):
            self.env["caw.installment"].create({
                "withdrawal_id": withdrawal.id,
                "sequence": 1,
                "date_due": "2026-01-01",
                "amount": 1000.0,
            })

    def test_lines_are_locked_after_confirm(self):
        """Un retiro confirmado no admite edición de líneas."""
        withdrawal = self._withdrawal(500.0)
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 50.0,
            })]})
```

`checking_account_withdrawals/tests/__init__.py`:
```python
from . import test_account
from . import test_withdrawal
from . import test_installment
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — `caw.installment` no existe y `caw.withdrawal` no tiene `action_confirm`.

- [ ] **Step 3: Implementar la cuota**

`checking_account_withdrawals/models/caw_installment.py`:
```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero

STATE_SELECTION = [
    ("pending", "Pendiente"),
    ("partial", "Parcial"),
    ("paid", "Pagada"),
    ("overdue", "Vencida"),
]


class CawInstallment(models.Model):
    _name = "caw.installment"
    _description = "Cuota de retiro de cuenta corriente"
    _order = "date_due, withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="caw.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
        index=True,
    )
    account_id = fields.Many2one(
        related="withdrawal_id.account_id",
        store=True,
        index=True,
        string="Cuenta corriente",
    )
    partner_id = fields.Many2one(
        related="withdrawal_id.partner_id",
        store=True,
        index=True,
        string="Contacto",
    )
    company_id = fields.Many2one(
        related="withdrawal_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    sequence = fields.Integer(string="Nº de cuota", default=1, required=True)
    date_due = fields.Date(string="Vencimiento", required=True, index=True)
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
    )
    amount_allocated = fields.Monetary(
        string="Imputado",
        currency_field="currency_id",
        default=0.0,
    )
    amount_residual = fields.Monetary(
        string="Residual",
        compute="_compute_amount_residual",
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

    @api.depends("amount", "amount_allocated")
    def _compute_amount_residual(self):
        """Residual de la cuota: monto menos lo imputado, nunca negativo."""
        for installment in self:
            residual = installment.amount - installment.amount_allocated
            installment.amount_residual = max(residual, 0.0)

    @api.depends("amount", "amount_allocated", "amount_residual", "date_due")
    def _compute_state(self):
        """Estado de la cuota. Solo es 'pagada' cuando el residual llega a cero."""
        today = fields.Date.context_today(self)
        for installment in self:
            rounding = installment.currency_id.rounding or 0.01
            if float_is_zero(installment.amount_residual, precision_rounding=rounding):
                installment.state = "paid"
            elif installment.date_due and installment.date_due < today:
                installment.state = "overdue"
            elif installment.amount_allocated > 0:
                installment.state = "partial"
            else:
                installment.state = "pending"

    @api.constrains("date_due", "withdrawal_id")
    def _check_due_date(self):
        """El vencimiento no puede ser anterior a la fecha del retiro."""
        for installment in self:
            withdrawal_date = installment.withdrawal_id.date
            if withdrawal_date and installment.date_due < withdrawal_date:
                raise ValidationError(_(
                    "El vencimiento de la cuota %(seq)s (%(due)s) es anterior a la fecha del retiro (%(date)s).",
                    seq=installment.sequence,
                    due=installment.date_due,
                    date=withdrawal_date,
                ))

    @api.constrains("amount", "withdrawal_id")
    def _check_total_matches_withdrawal(self):
        """Valida que la suma de cuotas del retiro iguale exactamente su total (CC-21).

        Es bloqueante y aplica tanto a la generación automática como a la carga manual.
        Odoo evalúa los constrains al final del create/write, así que crear las N cuotas
        en una sola llamada no lo dispara a mitad de camino.
        """
        for withdrawal in self.mapped("withdrawal_id"):
            total_installments = sum(withdrawal.installment_ids.mapped("amount"))
            if withdrawal.currency_id.compare_amounts(total_installments, withdrawal.amount_total) != 0:
                raise ValidationError(_(
                    "La suma de las cuotas (%(sum)s) no coincide con el total del retiro %(name)s (%(total)s).",
                    sum=total_installments,
                    name=withdrawal.name,
                    total=withdrawal.amount_total,
                ))
```

- [ ] **Step 4: Agregar la generación de cuotas y `action_confirm` al retiro**

En `models/caw_withdrawal.py`, agregar los imports arriba:
```python
from dateutil.relativedelta import relativedelta
```

Agregar el campo, después de `line_ids`:
```python
    installment_ids = fields.One2many(
        comodel_name="caw.installment",
        inverse_name="withdrawal_id",
        string="Cuotas",
    )
```

Agregar los métodos al final de la clase:
```python
    def _caw_due_date(self, index, first_days, period, cutoff_day):
        """Calcula el vencimiento de la cuota `index` (base 0) del retiro."""
        due = self.date + relativedelta(days=first_days)
        if period == "days":
            due += relativedelta(days=first_days * index)
        elif period == "weeks":
            due += relativedelta(weeks=index)
        else:
            due += relativedelta(months=index)
        if cutoff_day:
            due += relativedelta(day=min(cutoff_day, 28))
        return due

    def _caw_build_installment_values(self, count, first_days, period, cutoff_day):
        """Arma los valores de las cuotas. El resto del redondeo va a la última."""
        self.ensure_one()
        if count < 1:
            raise UserError(_("La cantidad de cuotas debe ser al menos 1."))
        currency = self.currency_id
        base = currency.round(self.amount_total / count)
        values = []
        accumulated = 0.0
        for index in range(count):
            is_last = index == count - 1
            amount = currency.round(self.amount_total - accumulated) if is_last else base
            accumulated += amount
            values.append({
                "withdrawal_id": self.id,
                "sequence": index + 1,
                "date_due": self._caw_due_date(index, first_days, period, cutoff_day),
                "amount": amount,
            })
        return values

    def _caw_generate_installments(self, count, first_days, period, cutoff_day):
        """Borra las cuotas existentes y genera el plan indicado."""
        for withdrawal in self:
            withdrawal.installment_ids.unlink()
            values = withdrawal._caw_build_installment_values(count, first_days, period, cutoff_day)
            self.env["caw.installment"].create(values)
            _logger.info("Retiro %s: generadas %s cuotas", withdrawal.name, count)
        return True

    def _caw_check_confirmable(self):
        """Valida las precondiciones para confirmar un retiro."""
        for withdrawal in self:
            if withdrawal.state != "draft":
                raise UserError(_("El retiro %s ya fue confirmado.", withdrawal.name))
            if not withdrawal.partner_id.caw_enabled:
                raise UserError(_(
                    "El contacto %s no está habilitado para cuenta corriente.",
                    withdrawal.partner_id.display_name,
                ))
            if not withdrawal.line_ids:
                raise UserError(_("El retiro %s no tiene líneas.", withdrawal.name))
            if withdrawal.currency_id.compare_amounts(withdrawal.amount_total, 0.0) <= 0:
                raise UserError(_("El total del retiro %s debe ser mayor a cero.", withdrawal.name))

    def action_confirm(self):
        """Confirma el retiro generando las cuotas con los defaults de la compañía."""
        self._caw_check_confirmable()
        for withdrawal in self:
            company = withdrawal.company_id
            withdrawal._caw_generate_installments(
                count=company.caw_installment_count or 1,
                first_days=company.caw_installment_days or 30,
                period=company.caw_installment_period or "months",
                cutoff_day=company.caw_cutoff_day or 0,
            )
            withdrawal.state = "pending"
            withdrawal.message_post(body=_("Retiro confirmado por %s.", self.env.user.display_name))
        return True
```

Agregar el bloqueo de edición de líneas, sobrescribiendo `write`:
```python
    def write(self, vals):
        """Impide editar las líneas de un retiro que ya salió de borrador."""
        if "line_ids" in vals and any(w.state not in ("draft",) for w in self):
            raise UserError(_("No se pueden modificar las líneas de un retiro confirmado."))
        return super().write(vals)
```

- [ ] **Step 5: Registrar el modelo y los accesos**

`models/__init__.py` — agregar `from . import caw_installment` **después** de `caw_withdrawal`.

Agregar a `security/ir.model.access.csv`:
```csv
access_caw_installment_user,caw.installment user,model_caw_installment,checking_account_withdrawals.group_cc_user,1,0,0,0
access_caw_installment_manager,caw.installment manager,model_caw_installment,checking_account_withdrawals.group_cc_manager,1,1,1,1
```

Agregar a `security/security.xml` antes de `</odoo>`:
```xml
    <record id="caw_installment_company_rule" model="ir.rule">
        <field name="name">caw.installment: multi-compañía</field>
        <field name="model_id" ref="model_caw_installment"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>
```

Nota: el Operador tiene la cuota en solo lectura; las cuotas se crean desde `action_confirm`, que corre con los permisos del propio retiro. Si el test falla por AccessError, envolvé la creación en `self.env["caw.installment"].sudo().create(values)` — es el patrón sudo, no ampliar el CSV.

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `18 tests, 0 failed, 0 error`.

- [ ] **Step 7: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): cuotas y generación automática al confirmar"
```

---

### Task 5: Pagos, imputación e imputación FIFO

**Files:**
- Create: `checking_account_withdrawals/models/caw_allocation.py`
- Create: `checking_account_withdrawals/models/caw_payment.py`
- Create: `checking_account_withdrawals/tests/test_payment.py`
- Modify: `checking_account_withdrawals/models/caw_installment.py`
- Modify: `checking_account_withdrawals/models/__init__.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`
- Modify: `checking_account_withdrawals/data/ir_sequence.xml`
- Modify: `checking_account_withdrawals/security/ir.model.access.csv`
- Modify: `checking_account_withdrawals/security/security.xml`

**Interfaces:**
- Consumes: `caw.account` (Task 2), `caw.installment` (Task 4).
- Produces:
  - `caw.allocation` con `payment_id`, `installment_id`, `withdrawal_id` (related store), `amount`, `company_id`, `currency_id`.
  - `caw.payment` con `name`, `account_id`, `partner_id`, `date`, `amount`, `payment_method`, `ref`, `state`, `allocation_ids`, `amount_allocated`, `amount_unallocated`.
  - `caw.payment.action_post()` → publica el pago e imputa FIFO.
  - `caw.payment._caw_allocate_fifo()` → imputa el remanente a las cuotas abiertas más antiguas del partner.
  - `caw.installment.amount_allocated` pasa a ser **compute store** sobre `allocation_ids.amount` (reemplaza el Float plano de la Task 4), y gana el campo `allocation_ids`.
  - Secuencia `checking_account_withdrawals.seq_caw_payment` (prefijo `CCP/%(year)s/`).

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_payment.py`:
```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawPayment(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.company.caw_installment_days = 30
        self.company.caw_cutoff_day = 0
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _confirmed_withdrawal(self, total, date, count=1):
        """Crea y confirma un retiro con `count` cuotas."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date,
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })
        withdrawal._caw_check_confirmable()
        withdrawal._caw_generate_installments(count=count, first_days=30, period="months", cutoff_day=0)
        withdrawal.state = "pending"
        return withdrawal

    def _payment(self, amount):
        """Crea un pago en borrador sobre la cuenta del partner."""
        return self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": amount,
            "date": "2026-06-01",
            "payment_method": "cash",
        })

    def test_fifo_pays_oldest_installment_first(self):
        """El pago se imputa primero a la cuota con vencimiento más antiguo."""
        old = self._confirmed_withdrawal(100.0, "2026-01-01")
        new = self._confirmed_withdrawal(100.0, "2026-03-01")
        self._payment(100.0).action_post()
        self.assertEqual(old.installment_ids.amount_residual, 0.0)
        self.assertEqual(new.installment_ids.amount_residual, 100.0)

    def test_fifo_spans_multiple_withdrawals(self):
        """Un solo pago puede cubrir cuotas de varios retiros del mismo partner."""
        first = self._confirmed_withdrawal(100.0, "2026-01-01")
        second = self._confirmed_withdrawal(100.0, "2026-03-01")
        self._payment(150.0).action_post()
        self.assertEqual(first.installment_ids.amount_residual, 0.0)
        self.assertEqual(second.installment_ids.amount_residual, 50.0)

    def test_excess_becomes_credit_not_forced_allocation(self):
        """El sobrante no se fuerza contra ninguna cuota: queda como saldo a favor."""
        withdrawal = self._confirmed_withdrawal(100.0, "2026-01-01")
        payment = self._payment(300.0)
        payment.action_post()
        self.assertEqual(withdrawal.installment_ids.amount_allocated, 100.0)
        self.assertEqual(payment.amount_allocated, 100.0)
        self.assertEqual(payment.amount_unallocated, 200.0)

    def test_allocation_cannot_exceed_installment_residual(self):
        """No se puede imputar más que el residual de la cuota."""
        withdrawal = self._confirmed_withdrawal(100.0, "2026-01-01")
        payment = self._payment(500.0)
        payment.state = "posted"
        with self.assertRaises(ValidationError):
            self.env["caw.allocation"].create({
                "payment_id": payment.id,
                "installment_id": withdrawal.installment_ids.id,
                "amount": 150.0,
            })

    def test_allocation_cannot_exceed_payment_amount(self):
        """La suma de imputaciones no puede superar el monto del pago."""
        first = self._confirmed_withdrawal(100.0, "2026-01-01")
        second = self._confirmed_withdrawal(100.0, "2026-03-01")
        payment = self._payment(120.0)
        payment.action_post()
        with self.assertRaises(ValidationError):
            self.env["caw.allocation"].create({
                "payment_id": payment.id,
                "installment_id": second.installment_ids.id,
                "amount": 80.0,
            })

    def test_cancel_payment_reverts_allocations(self):
        """Anular un pago revierte sus imputaciones y las cuotas recalculan estado."""
        withdrawal = self._confirmed_withdrawal(100.0, "2026-01-01")
        payment = self._payment(100.0)
        payment.action_post()
        self.assertEqual(withdrawal.installment_ids.state, "paid")
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")
        self.assertFalse(payment.allocation_ids)
        self.assertEqual(withdrawal.installment_ids.amount_allocated, 0.0)

    def test_payment_amount_must_be_positive(self):
        """Un pago con monto menor o igual a cero no se publica."""
        payment = self._payment(0.0)
        with self.assertRaises(UserError):
            payment.action_post()
```

`checking_account_withdrawals/tests/__init__.py` — agregar `from . import test_payment`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — `caw.payment` y `caw.allocation` no existen.

- [ ] **Step 3: Agregar la secuencia del pago**

En `data/ir_sequence.xml`, antes de `</odoo>`:
```xml
    <record id="seq_caw_payment" model="ir.sequence">
        <field name="name">Pago de cuenta corriente</field>
        <field name="code">caw.payment</field>
        <field name="prefix">CCP/%(year)s/</field>
        <field name="padding">5</field>
        <field name="company_id" eval="False"/>
    </record>
```

- [ ] **Step 4: Implementar la imputación**

`checking_account_withdrawals/models/caw_allocation.py`:
```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CawAllocation(models.Model):
    _name = "caw.allocation"
    _description = "Imputación de pago a cuota de cuenta corriente"
    _order = "payment_id, installment_id, id"

    payment_id = fields.Many2one(
        comodel_name="caw.payment",
        string="Pago",
        required=True,
        ondelete="cascade",
        index=True,
    )
    installment_id = fields.Many2one(
        comodel_name="caw.installment",
        string="Cuota",
        required=True,
        ondelete="cascade",
        index=True,
    )
    withdrawal_id = fields.Many2one(
        related="installment_id.withdrawal_id",
        store=True,
        index=True,
        string="Retiro",
    )
    partner_id = fields.Many2one(related="installment_id.partner_id", store=True, index=True)
    company_id = fields.Many2one(related="payment_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="payment_id.currency_id", readonly=True)
    date = fields.Date(related="payment_id.date", store=True, index=True)
    amount = fields.Monetary(
        string="Monto imputado",
        required=True,
        currency_field="currency_id",
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto imputado debe ser mayor a cero.",
        ),
    ]

    @api.constrains("amount", "installment_id", "payment_id")
    def _check_amounts(self):
        """No se puede imputar más que el residual de la cuota ni más que el pago."""
        for allocation in self:
            installment = allocation.installment_id
            currency = allocation.currency_id
            others = sum(
                installment.allocation_ids.filtered(lambda a: a.id != allocation.id).mapped("amount")
            )
            if currency.compare_amounts(others + allocation.amount, installment.amount) > 0:
                raise ValidationError(_(
                    "No se puede imputar %(amount)s a la cuota %(seq)s: supera su residual.",
                    amount=allocation.amount,
                    seq=installment.sequence,
                ))
            payment = allocation.payment_id
            total_allocated = sum(payment.allocation_ids.mapped("amount"))
            if currency.compare_amounts(total_allocated, payment.amount) > 0:
                raise ValidationError(_(
                    "Las imputaciones del pago %(name)s (%(alloc)s) superan su monto (%(amount)s).",
                    name=payment.name,
                    alloc=total_allocated,
                    amount=payment.amount,
                ))
```

- [ ] **Step 5: Convertir `amount_allocated` de la cuota en compute**

En `models/caw_installment.py`, agregar el One2many después de `sequence`:
```python
    allocation_ids = fields.One2many(
        comodel_name="caw.allocation",
        inverse_name="installment_id",
        string="Imputaciones",
    )
```

Y **reemplazar** la definición de `amount_allocated` (el Float plano de la Task 4) por:
```python
    amount_allocated = fields.Monetary(
        string="Imputado",
        compute="_compute_amount_allocated",
        store=True,
        currency_field="currency_id",
    )
```

Agregar el compute correspondiente, antes de `_compute_amount_residual`:
```python
    @api.depends("allocation_ids.amount", "allocation_ids.payment_id.state")
    def _compute_amount_allocated(self):
        """Suma de las imputaciones de pagos publicados sobre esta cuota."""
        for installment in self:
            installment.amount_allocated = sum(
                installment.allocation_ids
                .filtered(lambda a: a.payment_id.state == "posted")
                .mapped("amount")
            )
```

- [ ] **Step 6: Implementar el pago**

`checking_account_withdrawals/models/caw_payment.py`:
```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CawPayment(models.Model):
    _name = "caw.payment"
    _description = "Pago de cuenta corriente"
    _inherit = ["mail.thread"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    account_id = fields.Many2one(
        comodel_name="caw.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        related="account_id.partner_id",
        store=True,
        index=True,
        string="Contacto",
    )
    company_id = fields.Many2one(
        related="account_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        index=True,
        tracking=True,
    )
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
        tracking=True,
    )
    payment_method = fields.Selection(
        selection=[
            ("cash", "Efectivo"),
            ("transfer", "Transferencia"),
            ("check", "Cheque"),
            ("card", "Tarjeta"),
            ("other", "Otro"),
        ],
        string="Medio de pago",
        default="cash",
        required=True,
    )
    ref = fields.Char(string="Referencia")
    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("posted", "Publicado"),
            ("cancel", "Anulado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    allocation_ids = fields.One2many(
        comodel_name="caw.allocation",
        inverse_name="payment_id",
        string="Imputaciones",
    )
    amount_allocated = fields.Monetary(
        string="Imputado",
        compute="_compute_allocated",
        store=True,
        currency_field="currency_id",
    )
    amount_unallocated = fields.Monetary(
        string="Saldo a favor",
        compute="_compute_allocated",
        store=True,
        currency_field="currency_id",
    )

    @api.depends("amount", "allocation_ids.amount", "state")
    def _compute_allocated(self):
        """Monto imputado y remanente disponible como saldo a favor."""
        for payment in self:
            allocated = sum(payment.allocation_ids.mapped("amount"))
            payment.amount_allocated = allocated
            payment.amount_unallocated = max(payment.amount - allocated, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna el número de secuencia del pago."""
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("caw.payment") or "/"
        return super().create(vals_list)

    def _caw_open_installments(self):
        """Cuotas abiertas del partner, ordenadas FIFO: vencimiento, luego retiro."""
        self.ensure_one()
        return self.env["caw.installment"].search(
            [
                ("partner_id", "=", self.partner_id.id),
                ("company_id", "=", self.company_id.id),
                ("amount_residual", ">", 0),
                ("withdrawal_id.state", "not in", ("draft", "cancel")),
            ],
            order="date_due asc, withdrawal_id asc, sequence asc",
        )

    def _caw_allocate_fifo(self):
        """Imputa el remanente del pago a las cuotas abiertas más antiguas."""
        allocation_model = self.env["caw.allocation"]
        for payment in self:
            remaining = payment.amount - payment.amount_allocated
            currency = payment.currency_id
            for installment in payment._caw_open_installments():
                if currency.compare_amounts(remaining, 0.0) <= 0:
                    break
                amount = min(remaining, installment.amount_residual)
                if currency.compare_amounts(amount, 0.0) <= 0:
                    continue
                allocation_model.create({
                    "payment_id": payment.id,
                    "installment_id": installment.id,
                    "amount": currency.round(amount),
                })
                remaining -= amount
            if currency.compare_amounts(remaining, 0.0) > 0:
                _logger.info(
                    "Pago %s: quedan %s sin imputar como saldo a favor de %s",
                    payment.name, remaining, payment.partner_id.display_name,
                )
        return True

    def action_post(self):
        """Publica el pago e imputa automáticamente por FIFO."""
        for payment in self:
            if payment.state != "draft":
                raise UserError(_("El pago %s ya fue publicado o anulado.", payment.name))
            if payment.currency_id.compare_amounts(payment.amount, 0.0) <= 0:
                raise UserError(_("El monto del pago %s debe ser mayor a cero.", payment.name))
            payment.state = "posted"
            payment._caw_allocate_fifo()
            payment.message_post(body=_("Pago publicado por %s.", self.env.user.display_name))
        return True

    def action_cancel(self):
        """Anula el pago revirtiendo todas sus imputaciones."""
        for payment in self:
            if payment.state == "cancel":
                raise UserError(_("El pago %s ya está anulado.", payment.name))
            payment.allocation_ids.unlink()
            payment.state = "cancel"
            payment.message_post(body=_("Pago anulado por %s.", self.env.user.display_name))
        return True
```

- [ ] **Step 7: Registrar modelos y accesos**

`models/__init__.py` — agregar, después de `caw_installment`:
```python
from . import caw_payment
from . import caw_allocation
```

Agregar a `security/ir.model.access.csv`:
```csv
access_caw_payment_user,caw.payment user,model_caw_payment,checking_account_withdrawals.group_cc_user,1,1,1,0
access_caw_payment_manager,caw.payment manager,model_caw_payment,checking_account_withdrawals.group_cc_manager,1,1,1,1
access_caw_allocation_user,caw.allocation user,model_caw_allocation,checking_account_withdrawals.group_cc_user,1,0,0,0
access_caw_allocation_manager,caw.allocation manager,model_caw_allocation,checking_account_withdrawals.group_cc_manager,1,1,1,1
```

Agregar a `security/security.xml` antes de `</odoo>`:
```xml
    <record id="caw_payment_company_rule" model="ir.rule">
        <field name="name">caw.payment: multi-compañía</field>
        <field name="model_id" ref="model_caw_payment"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>

    <record id="caw_allocation_company_rule" model="ir.rule">
        <field name="name">caw.allocation: multi-compañía</field>
        <field name="model_id" ref="model_caw_allocation"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>
```

El Operador crea pagos pero no imputaciones: `_caw_allocate_fifo` corre con `sudo()` si el test da AccessError. Cambiá `allocation_model = self.env["caw.allocation"]` por `allocation_model = self.env["caw.allocation"].sudo()`.

- [ ] **Step 8: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `25 tests, 0 failed, 0 error`.

- [ ] **Step 9: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): pagos con imputación FIFO y saldo a favor"
```

---

### Task 6: Estado derivado del retiro — el requisito crítico (CC-30 / CC-31)

Esta es la tarea que justifica todo el módulo. Un retiro **solo** figura como pagado cuando
**todas** sus cuotas están canceladas. El monto total imputado nunca es criterio suficiente.

**Files:**
- Modify: `checking_account_withdrawals/models/caw_withdrawal.py`
- Create: `checking_account_withdrawals/tests/test_withdrawal_state.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`

**Interfaces:**
- Consumes: `caw.installment.state` y `amount_residual` (Task 4/5), `caw.allocation` (Task 5).
- Produces:
  - `caw.withdrawal.state` pasa de Selection plano a **`compute="_compute_state", store=True, readonly=True`**. Los cinco valores no cambian.
  - `caw.withdrawal.amount_residual` (Monetary compute store).
  - `caw.withdrawal.is_overdue` (Boolean compute store) — indicador de mora **independiente** del estado.
  - `caw.withdrawal.is_cancelled` (Boolean, store) — bandera que el compute respeta para no pisar el estado `cancel`.

- [ ] **Step 1: Escribir los tests que fallan**

`checking_account_withdrawals/tests/test_withdrawal_state.py`:
```python
# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawWithdrawalState(CawCommon):
    """Casos obligatorios de CC-31: el falso pagado total no debe poder ocurrir."""

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _confirmed(self, total, count):
        """Retiro confirmado por `total` con `count` cuotas iguales."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })
        withdrawal._caw_generate_installments(
            count=count, first_days=30, period="months", cutoff_day=0
        )
        return withdrawal

    def _posted_payment(self, amount):
        """Pago publicado sin imputación automática (para imputar a mano)."""
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": amount,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        payment.state = "posted"
        return payment

    def _allocate(self, payment, installment, amount):
        """Imputa manualmente un monto de un pago a una cuota."""
        return self.env["caw.allocation"].create({
            "payment_id": payment.id,
            "installment_id": installment.id,
            "amount": amount,
        })

    def test_pending_when_no_allocation(self):
        """Sin ninguna imputación el retiro está pendiente."""
        withdrawal = self._confirmed(600.0, 3)
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.amount_residual, 600.0)

    def test_partial_when_some_allocation(self):
        """Con imputación parcial el retiro queda en parcial."""
        withdrawal = self._confirmed(600.0, 3)
        payment = self._posted_payment(200.0)
        self._allocate(payment, withdrawal.installment_ids.sorted("sequence")[0], 200.0)
        self.assertEqual(withdrawal.state, "partial")

    def test_paid_only_when_every_installment_is_paid(self):
        """El retiro pasa a pagado únicamente con todas las cuotas canceladas."""
        withdrawal = self._confirmed(600.0, 3)
        payment = self._posted_payment(600.0)
        for installment in withdrawal.installment_ids:
            self._allocate(payment, installment, installment.amount)
        self.assertEqual(withdrawal.state, "paid")
        self.assertEqual(withdrawal.amount_residual, 0.0)

    def test_five_of_six_installments_paid_is_never_paid(self):
        """CC-31: retiro de 6 cuotas con 5 canceladas → parcial, nunca pagado."""
        withdrawal = self._confirmed(600.0, 6)
        installments = withdrawal.installment_ids.sorted("sequence")
        payment = self._posted_payment(500.0)
        for installment in installments[:5]:
            self._allocate(payment, installment, installment.amount)
        self.assertEqual(withdrawal.state, "partial")
        self.assertNotEqual(withdrawal.state, "paid")
        self.assertGreater(withdrawal.amount_residual, 0.0)

    def test_overpay_first_underpay_second_stays_partial(self):
        """CC-31: total imputado = total del retiro pero con una cuota abierta → parcial.

        La cuota 1 no puede recibir más que su residual, así que el excedente queda
        sin imputar. El retiro NUNCA debe cerrarse por coincidencia de montos.
        """
        withdrawal = self._confirmed(200.0, 2)
        installments = withdrawal.installment_ids.sorted("sequence")
        payment = self._posted_payment(200.0)
        self._allocate(payment, installments[0], 100.0)
        self._allocate(payment, installments[1], 60.0)
        self.assertEqual(installments[0].state, "paid")
        self.assertEqual(installments[1].amount_residual, 40.0)
        self.assertEqual(withdrawal.state, "partial")

    def test_constraint_blocks_manual_paid_with_open_installments(self):
        """El constraint rechaza forzar 'paid' con alguna cuota con residual > 0."""
        withdrawal = self._confirmed(600.0, 3)
        with self.assertRaises(ValidationError):
            withdrawal.with_context(caw_skip_state_compute=True).write({"state": "paid"})
            withdrawal.flush_recordset()

    def test_cancelling_payment_reverts_paid_to_partial(self):
        """Anular un pago devuelve el retiro de pagado a parcial."""
        withdrawal = self._confirmed(200.0, 2)
        installments = withdrawal.installment_ids.sorted("sequence")
        payment = self._posted_payment(200.0)
        for installment in installments:
            self._allocate(payment, installment, installment.amount)
        self.assertEqual(withdrawal.state, "paid")
        payment.action_cancel()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.amount_residual, 200.0)

    def test_overdue_flag_is_independent_of_state(self):
        """Un retiro puede estar parcial y en mora a la vez."""
        withdrawal = self._confirmed(200.0, 2)
        installments = withdrawal.installment_ids.sorted("sequence")
        installments[0].date_due = "2026-01-02"
        payment = self._posted_payment(50.0)
        self._allocate(payment, installments[0], 50.0)
        withdrawal.invalidate_recordset()
        self.assertEqual(withdrawal.state, "partial")
        self.assertTrue(withdrawal.is_overdue)
```

`checking_account_withdrawals/tests/__init__.py` — agregar `from . import test_withdrawal_state`.

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — `state` sigue siendo un Selection editable y no existen `amount_residual` ni `is_overdue`.

- [ ] **Step 3: Convertir `state` en computed y agregar los campos derivados**

En `models/caw_withdrawal.py`, **reemplazar** la definición de `state` de la Task 3 por:
```python
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        compute="_compute_state",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
        default="draft",
    )
    is_cancelled = fields.Boolean(
        string="Cancelado",
        default=False,
        copy=False,
        help="Bandera interna: el estado computado la respeta para no pisar la cancelación.",
    )
    is_confirmed = fields.Boolean(
        string="Confirmado",
        default=False,
        copy=False,
        help="Bandera interna: pasa a True al confirmar y saca al retiro de borrador.",
    )
    amount_residual = fields.Monetary(
        string="Residual",
        compute="_compute_amount_residual",
        store=True,
        currency_field="currency_id",
    )
    is_overdue = fields.Boolean(
        string="En mora",
        compute="_compute_is_overdue",
        store=True,
        index=True,
        help="Indicador independiente del estado: el retiro tiene al menos una cuota vencida.",
    )
```

- [ ] **Step 4: Implementar los computes y el constraint**

Agregar a `models/caw_withdrawal.py` (importar `ValidationError` junto a `UserError`):
```python
    @api.depends("installment_ids.amount_residual")
    def _compute_amount_residual(self):
        """Residual del retiro: suma de los residuales de sus cuotas."""
        for withdrawal in self:
            withdrawal.amount_residual = sum(withdrawal.installment_ids.mapped("amount_residual"))

    @api.depends("installment_ids.state")
    def _compute_is_overdue(self):
        """Mora: al menos una cuota vencida. No altera el estado de pago."""
        for withdrawal in self:
            withdrawal.is_overdue = any(
                installment.state == "overdue" for installment in withdrawal.installment_ids
            )

    @api.depends(
        "is_cancelled",
        "is_confirmed",
        "amount_total",
        "installment_ids.state",
        "installment_ids.amount_allocated",
        "installment_ids.amount_residual",
    )
    def _compute_state(self):
        """Deriva el estado del retiro del estado de sus cuotas. Nunca se escribe a mano.

        pending: ninguna cuota con imputación.
        partial: al menos una cuota con imputación y residual total > 0.
        paid:    TODAS las cuotas pagadas y residual del retiro en cero.
        """
        for withdrawal in self:
            if withdrawal.is_cancelled:
                withdrawal.state = "cancel"
                continue
            if not withdrawal.is_confirmed:
                withdrawal.state = "draft"
                continue
            installments = withdrawal.installment_ids
            currency = withdrawal.currency_id
            residual = sum(installments.mapped("amount_residual"))
            all_paid = bool(installments) and all(i.state == "paid" for i in installments)
            if all_paid and currency.compare_amounts(residual, 0.0) == 0:
                withdrawal.state = "paid"
            elif any(i.amount_allocated > 0 for i in installments):
                withdrawal.state = "partial"
            else:
                withdrawal.state = "pending"

    @api.constrains("state", "installment_ids", "amount_residual")
    def _check_no_false_paid(self):
        """Blindaje de CC-31: rechaza 'paid' si alguna cuota tiene residual > 0."""
        for withdrawal in self:
            if withdrawal.state != "paid":
                continue
            open_installments = withdrawal.installment_ids.filtered(
                lambda i: i.currency_id.compare_amounts(i.amount_residual, 0.0) > 0
            )
            if open_installments:
                raise ValidationError(_(
                    "El retiro %(name)s no puede figurar como pagado: tiene %(count)s cuota(s) "
                    "con saldo pendiente.",
                    name=withdrawal.name,
                    count=len(open_installments),
                ))
```

- [ ] **Step 5: Adaptar `action_confirm` a las banderas**

En `action_confirm`, **reemplazar** la línea `withdrawal.state = "pending"` por:
```python
            withdrawal.is_confirmed = True
```

Y en `write`, cambiar la guarda de líneas para que use la bandera en vez del estado:
```python
    def write(self, vals):
        """Impide editar las líneas de un retiro que ya salió de borrador."""
        if "line_ids" in vals and any(w.is_confirmed or w.is_cancelled for w in self):
            raise UserError(_("No se pueden modificar las líneas de un retiro confirmado."))
        return super().write(vals)
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `33 tests, 0 failed, 0 error`. Si `test_constraint_blocks_manual_paid_with_open_installments` no levanta `ValidationError` porque el compute pisa la escritura, es la prueba de que el estado no es escribible: cambiá ese test por `self.assertNotEqual(withdrawal.state, "paid")` tras el intento de escritura y dejá el constraint como red de seguridad de segunda línea.

- [ ] **Step 7: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): estado del retiro derivado de sus cuotas (CC-30/CC-31)"
```

---

### Task 7: Saldos de la cuenta, saldo a favor y cron de vencidas

**Files:**
- Modify: `checking_account_withdrawals/models/caw_account.py`
- Modify: `checking_account_withdrawals/models/res_partner.py`
- Create: `checking_account_withdrawals/data/ir_cron.xml`
- Create: `checking_account_withdrawals/tests/test_balance.py`
- Modify: `checking_account_withdrawals/models/caw_installment.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`
- Modify: `checking_account_withdrawals/__manifest__.py`

**Interfaces:**
- Consumes: `caw.withdrawal.state` / `amount_residual` (Task 6), `caw.payment.amount_unallocated` (Task 5).
- Produces:
  - `caw.account.withdrawal_ids`, `payment_ids`, `installment_ids` (One2many).
  - `caw.account.balance`, `overdue_balance`, `credit_balance` (Monetary compute store).
  - `res.partner.caw_balance`, `caw_overdue_balance`, `caw_credit_balance`, `caw_withdrawal_count` (compute, no store) + `action_caw_open_withdrawals()`.
  - `caw.installment._cron_update_overdue()` → recalcula estados vencidos, invocado por el cron diario.

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_balance.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawBalance(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _confirmed(self, total, count=1, date="2026-01-01"):
        """Retiro confirmado por `total` con `count` cuotas."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date,
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })
        withdrawal._caw_generate_installments(
            count=count, first_days=30, period="months", cutoff_day=0
        )
        return withdrawal

    def test_balance_sums_open_residuals(self):
        """El saldo suma únicamente residuales de cuotas no canceladas."""
        self._confirmed(500.0)
        self._confirmed(300.0)
        self.account.invalidate_recordset()
        self.assertEqual(self.account.balance, 800.0)

    def test_draft_withdrawals_do_not_count(self):
        """Un retiro en borrador no suma al saldo."""
        self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 999.0,
            })],
        })
        self.account.invalidate_recordset()
        self.assertEqual(self.account.balance, 0.0)

    def test_overdue_balance_counts_only_past_due(self):
        """El vencido cuenta solo cuotas impagas con vencimiento anterior a hoy."""
        withdrawal = self._confirmed(400.0, count=2)
        installments = withdrawal.installment_ids.sorted("sequence")
        installments[0].date_due = "2020-01-01"
        self.env["caw.installment"]._cron_update_overdue()
        self.account.invalidate_recordset()
        self.assertEqual(self.account.balance, 400.0)
        self.assertEqual(self.account.overdue_balance, 200.0)

    def test_credit_balance_reflects_unallocated_payments(self):
        """El sobrante de los pagos publicados es el saldo a favor de la cuenta."""
        self._confirmed(100.0)
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 250.0,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        payment.action_post()
        self.account.invalidate_recordset()
        self.assertEqual(self.account.credit_balance, 150.0)
        self.assertEqual(self.account.balance, 0.0)

    def test_partner_fields_aggregate_accounts(self):
        """Los campos del partner agregan los saldos de todas sus cuentas."""
        self._confirmed(700.0)
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.caw_balance, 700.0)
        self.assertEqual(self.partner.caw_withdrawal_count, 1)

    def test_cron_marks_installments_overdue(self):
        """El cron marca como vencidas las cuotas impagas con vencimiento pasado."""
        withdrawal = self._confirmed(100.0)
        withdrawal.installment_ids.date_due = "2020-01-01"
        self.env["caw.installment"]._cron_update_overdue()
        self.assertEqual(withdrawal.installment_ids.state, "overdue")
        self.assertTrue(withdrawal.is_overdue)
```

`checking_account_withdrawals/tests/__init__.py` — agregar `from . import test_balance`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — `caw.account` no tiene `balance` y `caw.installment` no tiene `_cron_update_overdue`.

- [ ] **Step 3: Agregar los saldos a la cuenta**

En `models/caw_account.py`, agregar los One2many después de `active`:
```python
    withdrawal_ids = fields.One2many(
        comodel_name="caw.withdrawal",
        inverse_name="account_id",
        string="Retiros",
    )
    payment_ids = fields.One2many(
        comodel_name="caw.payment",
        inverse_name="account_id",
        string="Pagos",
    )
    installment_ids = fields.One2many(
        comodel_name="caw.installment",
        inverse_name="account_id",
        string="Cuotas",
    )
    balance = fields.Monetary(
        string="Saldo",
        compute="_compute_balances",
        store=True,
        currency_field="currency_id",
    )
    overdue_balance = fields.Monetary(
        string="Saldo vencido",
        compute="_compute_balances",
        store=True,
        currency_field="currency_id",
    )
    credit_balance = fields.Monetary(
        string="Saldo a favor",
        compute="_compute_credit_balance",
        store=True,
        currency_field="currency_id",
    )
```

Y los computes:
```python
    @api.depends(
        "installment_ids.amount_residual",
        "installment_ids.state",
        "installment_ids.date_due",
        "installment_ids.withdrawal_id.state",
    )
    def _compute_balances(self):
        """Saldo y vencido: residuales de cuotas de retiros vivos (ni borrador ni cancelados)."""
        today = fields.Date.context_today(self)
        for account in self:
            open_installments = account.installment_ids.filtered(
                lambda i: i.withdrawal_id.state not in ("draft", "cancel")
            )
            account.balance = sum(open_installments.mapped("amount_residual"))
            account.overdue_balance = sum(
                open_installments
                .filtered(lambda i: i.date_due and i.date_due < today and i.amount_residual > 0)
                .mapped("amount_residual")
            )

    @api.depends("payment_ids.amount_unallocated", "payment_ids.state")
    def _compute_credit_balance(self):
        """Saldo a favor: remanente no imputado de los pagos publicados."""
        for account in self:
            account.credit_balance = sum(
                account.payment_ids
                .filtered(lambda p: p.state == "posted")
                .mapped("amount_unallocated")
            )
```

- [ ] **Step 4: Agregar el cron de vencidas**

En `models/caw_installment.py`, agregar al final de la clase:
```python
    @api.model
    def _cron_update_overdue(self):
        """Cron diario: recalcula el estado de las cuotas impagas ya vencidas.

        El estado es computado y almacenado, pero depende de la fecha de hoy, que no es
        un campo. Este cron fuerza el recálculo invalidando la caché de las candidatas.
        """
        today = fields.Date.context_today(self)
        candidates = self.search([
            ("date_due", "<", today),
            ("state", "in", ("pending", "partial")),
            ("withdrawal_id.state", "not in", ("draft", "cancel")),
        ])
        candidates.invalidate_recordset(["state"])
        candidates.modified(["date_due"])
        candidates._compute_state()
        candidates.mapped("account_id").invalidate_recordset(["overdue_balance"])
        _logger.info("Cron de vencidas: %s cuotas revisadas", len(candidates))
        return True
```

Agregar el logger al principio de `caw_installment.py`:
```python
import logging

_logger = logging.getLogger(__name__)
```

`checking_account_withdrawals/data/ir_cron.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="cron_caw_update_overdue" model="ir.cron">
        <field name="name">Cuenta corriente: marcar cuotas vencidas</field>
        <field name="model_id" ref="model_caw_installment"/>
        <field name="state">code</field>
        <field name="code">model._cron_update_overdue()</field>
        <field name="interval_number">1</field>
        <field name="interval_type">days</field>
        <field name="numbercall">-1</field>
        <field name="active" eval="True"/>
    </record>
</odoo>
```

En `__manifest__.py`, agregar `"data/ir_cron.xml",` después de `"data/ir_sequence.xml",`.

- [ ] **Step 5: Agregar los campos agregados al partner**

En `models/res_partner.py`, agregar los campos y el compute:
```python
    caw_balance = fields.Monetary(
        string="Saldo cuenta corriente",
        compute="_compute_caw_amounts",
        currency_field="currency_id",
    )
    caw_overdue_balance = fields.Monetary(
        string="Saldo vencido",
        compute="_compute_caw_amounts",
        currency_field="currency_id",
    )
    caw_credit_balance = fields.Monetary(
        string="Saldo a favor",
        compute="_compute_caw_amounts",
        currency_field="currency_id",
    )
    caw_withdrawal_count = fields.Integer(
        string="Retiros",
        compute="_compute_caw_amounts",
    )

    @api.depends(
        "caw_account_ids.balance",
        "caw_account_ids.overdue_balance",
        "caw_account_ids.credit_balance",
    )
    def _compute_caw_amounts(self):
        """Agrega los saldos de todas las cuentas del contacto visibles al usuario."""
        withdrawal_model = self.env["caw.withdrawal"]
        for partner in self:
            accounts = partner.caw_account_ids
            partner.caw_balance = sum(accounts.mapped("balance"))
            partner.caw_overdue_balance = sum(accounts.mapped("overdue_balance"))
            partner.caw_credit_balance = sum(accounts.mapped("credit_balance"))
            partner.caw_withdrawal_count = withdrawal_model.search_count([
                ("partner_id", "=", partner.id),
            ]) if partner.id else 0

    def action_caw_open_withdrawals(self):
        """Botón inteligente: abre los retiros del contacto."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Retiros de %s", self.display_name),
            "res_model": "caw.withdrawal",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
```

Actualizar el import de `res_partner.py` a `from odoo import _, api, fields, models`.
`res.partner` ya trae `currency_id` de `base`, no hace falta declararlo.

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `39 tests, 0 failed, 0 error`.

- [ ] **Step 7: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): saldos de cuenta, saldo a favor y cron de vencidas"
```

---

### Task 8: Albarán de salida y descuento de stock

**Files:**
- Modify: `checking_account_withdrawals/models/caw_withdrawal.py`
- Create: `checking_account_withdrawals/tests/test_picking.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`
- Modify: `checking_account_withdrawals/tests/common.py`

**Interfaces:**
- Consumes: `res.company.caw_picking_type_id` (Task 2), `action_confirm` (Task 4/6).
- Produces:
  - `caw.withdrawal.picking_id` (Many2one `stock.picking`), `picking_state` (related store), `is_inconsistent` (Boolean compute store).
  - `caw.withdrawal._caw_picking_type()` → devuelve el `stock.picking.type` a usar.
  - `caw.withdrawal._caw_create_picking()` → crea el albarán, invocado desde `action_confirm`.
  - `caw.withdrawal.action_view_picking()` → acción para navegar al albarán.

- [ ] **Step 1: Escribir el test que falla**

En `tests/common.py`, agregar al final de `setUpClass`:
```python
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
```

`checking_account_withdrawals/tests/test_picking.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawPicking(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.company.caw_picking_type_id = self.warehouse.out_type_id

    def _confirmed(self, qty=3.0, price=100.0):
        """Retiro confirmado de `qty` unidades del producto de prueba."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": qty,
                "price_unit": price,
            })],
        })
        withdrawal.action_confirm()
        return withdrawal

    def test_confirm_creates_outgoing_picking(self):
        """Confirmar el retiro genera un albarán de salida con las mismas líneas."""
        withdrawal = self._confirmed(qty=3.0)
        picking = withdrawal.picking_id
        self.assertTrue(picking)
        self.assertEqual(picking.picking_type_id.code, "outgoing")
        self.assertEqual(picking.partner_id, self.partner)
        self.assertEqual(len(picking.move_ids), 1)
        self.assertEqual(picking.move_ids.product_id, self.product)
        self.assertEqual(picking.move_ids.product_uom_qty, 3.0)

    def test_stock_is_not_deducted_on_confirm(self):
        """El descuento de stock ocurre al validar el albarán, no al confirmar el retiro."""
        withdrawal = self._confirmed()
        self.assertNotEqual(withdrawal.picking_id.state, "done")

    def test_cancelled_picking_flags_inconsistency(self):
        """Si el albarán se cancela con el retiro vivo, queda señalizado para revisión."""
        withdrawal = self._confirmed()
        withdrawal.picking_id.action_cancel()
        withdrawal.invalidate_recordset()
        self.assertEqual(withdrawal.picking_state, "cancel")
        self.assertTrue(withdrawal.is_inconsistent)

    def test_picking_type_falls_back_to_warehouse(self):
        """Sin tipo configurado en la compañía se usa el de salidas del almacén."""
        self.company.caw_picking_type_id = False
        withdrawal = self._confirmed()
        self.assertEqual(withdrawal.picking_id.picking_type_id, self.warehouse.out_type_id)
```

`tests/__init__.py` — agregar `from . import test_picking`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — `caw.withdrawal` no tiene `picking_id`.

- [ ] **Step 3: Agregar los campos de stock al retiro**

En `models/caw_withdrawal.py`, agregar después de `is_overdue`:
```python
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Albarán",
        readonly=True,
        copy=False,
        index=True,
    )
    picking_state = fields.Selection(
        related="picking_id.state",
        string="Estado del albarán",
        store=True,
    )
    is_inconsistent = fields.Boolean(
        string="Inconsistente",
        compute="_compute_is_inconsistent",
        store=True,
        help="El albarán fue cancelado pero el retiro sigue vivo. Requiere revisión del Manager.",
    )
```

Y el compute:
```python
    @api.depends("picking_state", "is_cancelled")
    def _compute_is_inconsistent(self):
        """Señala los retiros vivos cuyo albarán fue cancelado."""
        for withdrawal in self:
            withdrawal.is_inconsistent = bool(
                withdrawal.picking_state == "cancel" and not withdrawal.is_cancelled
            )
```

- [ ] **Step 4: Implementar la creación del albarán**

Agregar a `models/caw_withdrawal.py`:
```python
    def _caw_picking_type(self):
        """Tipo de operación del albarán: el de la compañía o el de salidas del almacén."""
        self.ensure_one()
        picking_type = self.company_id.caw_picking_type_id
        if picking_type:
            return picking_type
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if not warehouse:
            raise UserError(_(
                "No hay un almacén configurado en la compañía %s.", self.company_id.name
            ))
        return warehouse.out_type_id

    def _caw_picking_values(self, picking_type):
        """Valores de cabecera del albarán de salida del retiro."""
        self.ensure_one()
        return {
            "partner_id": self.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "scheduled_date": fields.Datetime.to_datetime(self.date),
            "origin": self.name,
            "company_id": self.company_id.id,
        }

    def _caw_move_values(self, line, picking):
        """Valores del movimiento de stock de una línea del retiro."""
        return {
            "picking_id": picking.id,
            "name": line.name or line.product_id.display_name,
            "product_id": line.product_id.id,
            "product_uom_qty": line.quantity,
            "product_uom": line.product_id.uom_id.id,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
            "company_id": self.company_id.id,
        }

    def _caw_create_picking(self):
        """Crea el albarán de salida del retiro. Usa sudo: el Operador no es de stock."""
        picking_model = self.env["stock.picking"].sudo()
        move_model = self.env["stock.move"].sudo()
        for withdrawal in self.filtered(lambda w: not w.picking_id):
            storable_lines = withdrawal.line_ids.filtered(
                lambda l: l.product_id.is_storable
            )
            if not storable_lines:
                _logger.info("Retiro %s sin productos almacenables: no genera albarán", withdrawal.name)
                continue
            picking_type = withdrawal._caw_picking_type()
            picking = picking_model.create(withdrawal._caw_picking_values(picking_type))
            move_model.create([
                withdrawal._caw_move_values(line, picking) for line in storable_lines
            ])
            picking.action_confirm()
            withdrawal.picking_id = picking.id
            _logger.info("Retiro %s: albarán %s generado", withdrawal.name, picking.name)
        return True

    def action_view_picking(self):
        """Abre el albarán asociado al retiro."""
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_("El retiro %s no tiene albarán asociado.", self.name))
        return {
            "type": "ir.actions.act_window",
            "name": _("Albarán del retiro %s", self.name),
            "res_model": "stock.picking",
            "res_id": self.picking_id.id,
            "view_mode": "form",
        }
```

- [ ] **Step 5: Enganchar la creación del albarán en `action_confirm`**

En `action_confirm`, agregar `withdrawal._caw_create_picking()` **antes** de `withdrawal.is_confirmed = True`:
```python
            withdrawal._caw_create_picking()
            withdrawal.is_confirmed = True
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `43 tests, 0 failed, 0 error`.

- [ ] **Step 7: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): albarán de salida y detección de inconsistencia"
```

---

### Task 9: Límite de crédito, wizard de confirmación y cancelación

**Files:**
- Create: `checking_account_withdrawals/wizards/__init__.py`
- Create: `checking_account_withdrawals/wizards/caw_confirm_wizard.py`
- Create: `checking_account_withdrawals/tests/test_limit_and_cancel.py`
- Modify: `checking_account_withdrawals/models/caw_withdrawal.py`
- Modify: `checking_account_withdrawals/__init__.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`
- Modify: `checking_account_withdrawals/security/ir.model.access.csv`

**Interfaces:**
- Consumes: `caw.account.credit_limit` / `limit_mode` / `balance` (Task 2, 7), `_caw_generate_installments` (Task 4), `_caw_create_picking` (Task 8).
- Produces:
  - `caw.withdrawal._caw_check_limit(force=False)` → levanta `UserError` en modo `block` sin `force`; devuelve el mensaje de advertencia (str) en modo `warn`; `""` si no hay problema.
  - `caw.withdrawal.action_open_confirm_wizard()` → abre el wizard.
  - `caw.withdrawal.action_cancel()` → cancela; bloquea si hay imputaciones vivas.
  - `caw.confirm.wizard` (TransientModel) con `withdrawal_id`, `plan_mode`, `installment_count`, `first_days`, `period`, `cutoff_day`, `limit_warning`, `limit_blocked`, `force_limit`, y `action_confirm()`.

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_limit_and_cancel.py`:
```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawLimitAndCancel(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _draft(self, total):
        """Retiro en borrador por el total indicado."""
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })

    def test_no_limit_control_allows_any_amount(self):
        """Con modo 'sin control' no hay chequeo de límite."""
        self.account.write({"limit_mode": "none", "credit_limit": 10.0})
        self.assertEqual(self._draft(5000.0)._caw_check_limit(), "")

    def test_warn_mode_returns_message_but_allows(self):
        """Modo advertencia: devuelve el aviso y no bloquea."""
        self.account.write({"limit_mode": "warn", "credit_limit": 100.0})
        withdrawal = self._draft(500.0)
        message = withdrawal._caw_check_limit()
        self.assertTrue(message)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")

    def test_block_mode_raises_without_force(self):
        """Modo bloqueo: sin forzar, no se puede confirmar."""
        self.account.write({"limit_mode": "block", "credit_limit": 100.0})
        with self.assertRaises(UserError):
            self._draft(500.0).action_confirm()

    def test_block_mode_allows_manager_force(self):
        """Modo bloqueo: el Manager puede forzar y queda registro en el chatter."""
        self.account.write({"limit_mode": "block", "credit_limit": 100.0})
        withdrawal = self._draft(500.0)
        withdrawal.with_context(caw_force_limit=True).action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        bodies = " ".join(withdrawal.message_ids.mapped("body"))
        self.assertIn("límite", bodies.lower())

    def test_limit_counts_existing_balance(self):
        """El chequeo evalúa saldo actual + total del retiro contra el límite."""
        self.account.write({"limit_mode": "block", "credit_limit": 1000.0})
        self._draft(800.0).action_confirm()
        self.account.invalidate_recordset()
        with self.assertRaises(UserError):
            self._draft(300.0).action_confirm()

    def test_cancel_without_payments_reverts_everything(self):
        """Sin pagos imputados: se cancelan las cuotas y se cancela el albarán."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        withdrawal.action_confirm()
        picking = withdrawal.picking_id
        withdrawal.action_cancel()
        self.assertEqual(withdrawal.state, "cancel")
        self.assertFalse(withdrawal.installment_ids)
        if picking:
            self.assertEqual(picking.state, "cancel")

    def test_cancel_is_blocked_with_allocated_payments(self):
        """Con pagos imputados la cancelación se bloquea: primero hay que anular el pago."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        withdrawal.action_confirm()
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 50.0,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        payment.action_post()
        with self.assertRaises(UserError):
            withdrawal.action_cancel()
        self.assertNotEqual(withdrawal.state, "cancel")

    def test_wizard_generates_custom_plan(self):
        """El wizard genera el plan elegido en vez de los defaults de la compañía."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(900.0)
        wizard = self.env["caw.confirm.wizard"].create({
            "withdrawal_id": withdrawal.id,
            "plan_mode": "fixed",
            "installment_count": 3,
            "first_days": 30,
            "period": "months",
            "cutoff_day": 0,
        })
        wizard.action_confirm()
        self.assertEqual(len(withdrawal.installment_ids), 3)
        self.assertEqual(withdrawal.state, "pending")
```

`tests/__init__.py` — agregar `from . import test_limit_and_cancel`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — no existen `_caw_check_limit`, `action_cancel` ni `caw.confirm.wizard`.

- [ ] **Step 3: Implementar el chequeo de límite y la cancelación**

Agregar a `models/caw_withdrawal.py`:
```python
    def _caw_check_limit(self, force=False):
        """Evalúa saldo actual + total del retiro contra el límite de la cuenta.

        Devuelve el texto de advertencia en modo 'warn' (o vacío si no se supera).
        En modo 'block' levanta UserError salvo que `force` sea True.
        """
        self.ensure_one()
        account = self.account_id.sudo()
        if account.limit_mode == "none" or not account.credit_limit:
            return ""
        projected = account.balance + self.amount_total
        if self.currency_id.compare_amounts(projected, account.credit_limit) <= 0:
            return ""
        message = _(
            "El retiro deja a %(partner)s con un saldo de %(projected)s, "
            "por encima de su límite de %(limit)s.",
            partner=self.partner_id.display_name,
            projected=projected,
            limit=account.credit_limit,
        )
        if account.limit_mode == "block" and not force:
            raise UserError(_(
                "%(message)s\n\nSolo un Manager de Cuenta Corriente puede forzar este retiro.",
                message=message,
            ))
        return message

    def action_cancel(self):
        """Cancela el retiro. Se bloquea si tiene pagos imputados."""
        for withdrawal in self:
            if withdrawal.is_cancelled:
                raise UserError(_("El retiro %s ya está cancelado.", withdrawal.name))
            allocations = withdrawal.installment_ids.mapped("allocation_ids").filtered(
                lambda a: a.payment_id.state == "posted"
            )
            if allocations:
                raise UserError(_(
                    "El retiro %(name)s tiene pagos imputados por %(amount)s. "
                    "Anulá primero esos pagos y volvé a intentar la cancelación.",
                    name=withdrawal.name,
                    amount=sum(allocations.mapped("amount")),
                ))
            if withdrawal.picking_id and withdrawal.picking_id.state != "done":
                withdrawal.picking_id.sudo().action_cancel()
            withdrawal.installment_ids.unlink()
            withdrawal.is_cancelled = True
            withdrawal.message_post(body=_(
                "Retiro cancelado por %s.", self.env.user.display_name
            ))
        return True

    def action_draft(self):
        """Devuelve a borrador un retiro cancelado, para corregirlo."""
        for withdrawal in self:
            if not withdrawal.is_cancelled:
                raise UserError(_("Solo se puede reabrir un retiro cancelado."))
            withdrawal.write({"is_cancelled": False, "is_confirmed": False, "picking_id": False})
        return True

    def action_open_confirm_wizard(self):
        """Abre el wizard de confirmación con el plan de cuotas y el chequeo de límite."""
        self.ensure_one()
        self._caw_check_confirmable()
        return {
            "type": "ir.actions.act_window",
            "name": _("Confirmar retiro %s", self.name),
            "res_model": "caw.confirm.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_withdrawal_id": self.id},
        }
```

En `action_confirm`, insertar el chequeo de límite **antes** de generar las cuotas:
```python
        for withdrawal in self:
            force = bool(self.env.context.get("caw_force_limit"))
            warning = withdrawal._caw_check_limit(force=force)
            if warning:
                withdrawal.message_post(body=_(
                    "Retiro confirmado por encima del límite de crédito%(forced)s: %(warning)s",
                    forced=_(" (forzado por el Manager)") if force else "",
                    warning=warning,
                ))
            company = withdrawal.company_id
            ...
```

(El resto del cuerpo de `action_confirm` queda igual.)

- [ ] **Step 4: Implementar el wizard de confirmación**

`checking_account_withdrawals/wizards/__init__.py`:
```python
from . import caw_confirm_wizard
```

`checking_account_withdrawals/wizards/caw_confirm_wizard.py`:
```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CawConfirmWizard(models.TransientModel):
    _name = "caw.confirm.wizard"
    _description = "Confirmación de retiro: plan de cuotas y límite de crédito"

    withdrawal_id = fields.Many2one(
        comodel_name="caw.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(related="withdrawal_id.partner_id", readonly=True)
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    amount_total = fields.Monetary(
        related="withdrawal_id.amount_total",
        string="Total del retiro",
        readonly=True,
        currency_field="currency_id",
    )
    current_balance = fields.Monetary(
        string="Saldo actual",
        compute="_compute_account_info",
        currency_field="currency_id",
    )
    overdue_balance = fields.Monetary(
        string="Saldo vencido",
        compute="_compute_account_info",
        currency_field="currency_id",
    )
    plan_mode = fields.Selection(
        selection=[
            ("cash", "Contado en cuenta (una cuota)"),
            ("fixed", "Cuotas fijas"),
        ],
        string="Plan",
        default="cash",
        required=True,
    )
    installment_count = fields.Integer(string="Cantidad de cuotas", default=1, required=True)
    first_days = fields.Integer(string="Días al primer vencimiento", default=30, required=True)
    period = fields.Selection(
        selection=[("days", "Días"), ("weeks", "Semanas"), ("months", "Meses")],
        string="Periodicidad",
        default="months",
        required=True,
    )
    cutoff_day = fields.Integer(
        string="Día de corte",
        default=0,
        help="Día del mes al que se ajustan los vencimientos. 0 = sin día de corte.",
    )
    limit_warning = fields.Text(string="Advertencia de límite", compute="_compute_limit")
    limit_blocked = fields.Boolean(string="Bloqueado por límite", compute="_compute_limit")
    force_limit = fields.Boolean(
        string="Forzar sobre el límite",
        help="Solo un Manager puede forzar un retiro que supera el límite en modo bloqueo.",
    )

    @api.model
    def default_get(self, fields_list):
        """Propone el plan por defecto de la compañía del retiro."""
        values = super().default_get(fields_list)
        withdrawal = self.env["caw.withdrawal"].browse(values.get("withdrawal_id"))
        if withdrawal:
            company = withdrawal.company_id
            values.update({
                "installment_count": company.caw_installment_count or 1,
                "first_days": company.caw_installment_days or 30,
                "period": company.caw_installment_period or "months",
                "cutoff_day": company.caw_cutoff_day or 0,
                "plan_mode": "fixed" if (company.caw_installment_count or 1) > 1 else "cash",
            })
        return values

    @api.depends("withdrawal_id")
    def _compute_account_info(self):
        """Muestra el saldo del partner al momento de decidir el retiro."""
        for wizard in self:
            account = wizard.withdrawal_id.account_id.sudo()
            wizard.current_balance = account.balance
            wizard.overdue_balance = account.overdue_balance

    @api.depends("withdrawal_id", "amount_total")
    def _compute_limit(self):
        """Calcula el aviso de límite sin levantar excepción, para mostrarlo en el wizard."""
        for wizard in self:
            account = wizard.withdrawal_id.account_id.sudo()
            wizard.limit_warning = ""
            wizard.limit_blocked = False
            if account.limit_mode == "none" or not account.credit_limit:
                continue
            projected = account.balance + wizard.amount_total
            if wizard.currency_id.compare_amounts(projected, account.credit_limit) > 0:
                wizard.limit_warning = _(
                    "Saldo proyectado %(projected)s sobre un límite de %(limit)s.",
                    projected=projected,
                    limit=account.credit_limit,
                )
                wizard.limit_blocked = account.limit_mode == "block"

    @api.onchange("plan_mode")
    def _onchange_plan_mode(self):
        """En modo contado siempre hay una sola cuota."""
        for wizard in self:
            if wizard.plan_mode == "cash":
                wizard.installment_count = 1

    def action_confirm(self):
        """Confirma el retiro con el plan elegido en el wizard."""
        self.ensure_one()
        count = 1 if self.plan_mode == "cash" else self.installment_count
        if count < 1:
            raise UserError(_("La cantidad de cuotas debe ser al menos 1."))
        withdrawal = self.withdrawal_id
        force = self.force_limit and self.env.user.has_group(
            "checking_account_withdrawals.group_cc_manager"
        )
        withdrawal = withdrawal.with_context(
            caw_force_limit=force,
            caw_plan=(count, self.first_days, self.period, self.cutoff_day),
        )
        withdrawal.action_confirm()
        return {"type": "ir.actions.act_window_close"}
```

Para que el plan del wizard gane sobre los defaults de la compañía, en `action_confirm`
del retiro **reemplazá** el bloque de generación por:
```python
            plan = self.env.context.get("caw_plan")
            if plan:
                count, first_days, period, cutoff_day = plan
            else:
                company = withdrawal.company_id
                count = company.caw_installment_count or 1
                first_days = company.caw_installment_days or 30
                period = company.caw_installment_period or "months"
                cutoff_day = company.caw_cutoff_day or 0
            withdrawal._caw_generate_installments(
                count=count, first_days=first_days, period=period, cutoff_day=cutoff_day
            )
```

- [ ] **Step 5: Registrar el wizard**

`checking_account_withdrawals/__init__.py`:
```python
from . import models
from . import wizards
```

Agregar a `security/ir.model.access.csv`:
```csv
access_caw_confirm_wizard_user,caw.confirm.wizard user,model_caw_confirm_wizard,checking_account_withdrawals.group_cc_user,1,1,1,1
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `51 tests, 0 failed, 0 error`.

- [ ] **Step 7: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): límite de crédito, wizard de confirmación y cancelación"
```

---

### Task 10: Imputación manual del Manager

**Files:**
- Create: `checking_account_withdrawals/wizards/caw_allocate_wizard.py`
- Create: `checking_account_withdrawals/tests/test_allocate_wizard.py`
- Modify: `checking_account_withdrawals/wizards/__init__.py`
- Modify: `checking_account_withdrawals/models/caw_payment.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`
- Modify: `checking_account_withdrawals/security/ir.model.access.csv`

**Interfaces:**
- Consumes: `caw.payment` (Task 5), `caw.allocation` (Task 5), `_caw_open_installments` (Task 5).
- Produces:
  - `caw.allocate.wizard` (TransientModel) con `payment_id`, `line_ids`, `amount_available`, `amount_to_allocate`, `action_allocate()`.
  - `caw.allocate.wizard.line` (TransientModel) con `wizard_id`, `installment_id`, `amount_residual`, `amount`.
  - `caw.payment.action_open_allocate_wizard()`.

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_allocate_wizard.py`:
```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawAllocateWizard(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)
        self.withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 600.0,
            })],
        })
        self.withdrawal._caw_generate_installments(
            count=3, first_days=30, period="months", cutoff_day=0
        )
        self.payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 300.0,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        self.payment.state = "posted"

    def _wizard(self):
        """Abre el wizard de imputación manual precargado con las cuotas abiertas."""
        return self.env["caw.allocate.wizard"].with_context(
            active_model="caw.payment", active_id=self.payment.id
        ).create({"payment_id": self.payment.id})

    def test_wizard_preloads_open_installments(self):
        """El wizard lista las cuotas abiertas del partner."""
        wizard = self._wizard()
        self.assertEqual(len(wizard.line_ids), 3)
        self.assertEqual(wizard.amount_available, 300.0)

    def test_manual_allocation_targets_chosen_installments(self):
        """El Manager elige a qué cuotas aplicar, salteando el orden FIFO."""
        wizard = self._wizard()
        last_line = wizard.line_ids.sorted(lambda l: l.installment_id.sequence)[-1]
        wizard.line_ids.amount = 0.0
        last_line.amount = 200.0
        wizard.action_allocate()
        installments = self.withdrawal.installment_ids.sorted("sequence")
        self.assertEqual(installments[0].amount_allocated, 0.0)
        self.assertEqual(installments[2].amount_allocated, 200.0)

    def test_cannot_allocate_more_than_payment(self):
        """La suma de las líneas no puede superar el disponible del pago."""
        wizard = self._wizard()
        for line in wizard.line_ids:
            line.amount = 200.0
        with self.assertRaises(UserError):
            wizard.action_allocate()

    def test_cannot_allocate_more_than_residual(self):
        """Una línea no puede imputar más que el residual de su cuota."""
        wizard = self._wizard()
        wizard.line_ids.amount = 0.0
        first = wizard.line_ids.sorted(lambda l: l.installment_id.sequence)[0]
        first.amount = 250.0
        with self.assertRaises(UserError):
            wizard.action_allocate()
```

`tests/__init__.py` — agregar `from . import test_allocate_wizard`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — `caw.allocate.wizard` no existe.

- [ ] **Step 3: Implementar el wizard**

`checking_account_withdrawals/wizards/caw_allocate_wizard.py`:
```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CawAllocateWizard(models.TransientModel):
    _name = "caw.allocate.wizard"
    _description = "Imputación manual de un pago a cuotas"

    payment_id = fields.Many2one(
        comodel_name="caw.payment",
        string="Pago",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="payment_id.currency_id", readonly=True)
    amount_available = fields.Monetary(
        string="Disponible",
        compute="_compute_amount_available",
        currency_field="currency_id",
    )
    amount_to_allocate = fields.Monetary(
        string="A imputar",
        compute="_compute_amount_to_allocate",
        currency_field="currency_id",
    )
    line_ids = fields.One2many(
        comodel_name="caw.allocate.wizard.line",
        inverse_name="wizard_id",
        string="Cuotas",
    )

    @api.model
    def default_get(self, fields_list):
        """Precarga las cuotas abiertas del partner en orden FIFO."""
        values = super().default_get(fields_list)
        payment_id = values.get("payment_id") or self.env.context.get("active_id")
        payment = self.env["caw.payment"].browse(payment_id)
        if payment:
            values["payment_id"] = payment.id
            values["line_ids"] = [
                (0, 0, {"installment_id": installment.id, "amount": 0.0})
                for installment in payment._caw_open_installments()
            ]
        return values

    @api.depends("payment_id.amount", "payment_id.amount_allocated")
    def _compute_amount_available(self):
        """Monto del pago todavía no imputado."""
        for wizard in self:
            payment = wizard.payment_id
            wizard.amount_available = payment.amount - payment.amount_allocated

    @api.depends("line_ids.amount")
    def _compute_amount_to_allocate(self):
        """Suma de los montos cargados en las líneas del wizard."""
        for wizard in self:
            wizard.amount_to_allocate = sum(wizard.line_ids.mapped("amount"))

    def action_allocate(self):
        """Crea las imputaciones elegidas, validando residuales y disponible."""
        self.ensure_one()
        currency = self.currency_id
        lines = self.line_ids.filtered(lambda l: currency.compare_amounts(l.amount, 0.0) > 0)
        if not lines:
            raise UserError(_("No cargaste ningún monto a imputar."))
        if currency.compare_amounts(sum(lines.mapped("amount")), self.amount_available) > 0:
            raise UserError(_(
                "Estás imputando %(total)s pero el pago solo tiene %(available)s disponible.",
                total=sum(lines.mapped("amount")),
                available=self.amount_available,
            ))
        for line in lines:
            if currency.compare_amounts(line.amount, line.installment_id.amount_residual) > 0:
                raise UserError(_(
                    "No se puede imputar %(amount)s a la cuota %(seq)s: su residual es %(residual)s.",
                    amount=line.amount,
                    seq=line.installment_id.sequence,
                    residual=line.installment_id.amount_residual,
                ))
        self.env["caw.allocation"].create([
            {
                "payment_id": self.payment_id.id,
                "installment_id": line.installment_id.id,
                "amount": line.amount,
            }
            for line in lines
        ])
        self.payment_id.message_post(body=_(
            "Imputación manual de %(total)s realizada por %(user)s.",
            total=sum(lines.mapped("amount")),
            user=self.env.user.display_name,
        ))
        return {"type": "ir.actions.act_window_close"}


class CawAllocateWizardLine(models.TransientModel):
    _name = "caw.allocate.wizard.line"
    _description = "Línea de imputación manual"
    _order = "wizard_id, id"

    wizard_id = fields.Many2one(
        comodel_name="caw.allocate.wizard",
        required=True,
        ondelete="cascade",
    )
    installment_id = fields.Many2one(
        comodel_name="caw.installment",
        string="Cuota",
        required=True,
        ondelete="cascade",
    )
    withdrawal_id = fields.Many2one(related="installment_id.withdrawal_id", readonly=True)
    date_due = fields.Date(related="installment_id.date_due", readonly=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id", readonly=True)
    amount_residual = fields.Monetary(
        related="installment_id.amount_residual",
        string="Residual",
        readonly=True,
        currency_field="currency_id",
    )
    amount = fields.Monetary(
        string="A imputar",
        default=0.0,
        currency_field="currency_id",
    )
```

- [ ] **Step 4: Agregar el botón en el pago**

En `models/caw_payment.py`, al final de la clase:
```python
    def action_open_allocate_wizard(self):
        """Abre el wizard de imputación manual (solo Manager)."""
        self.ensure_one()
        if self.state != "posted":
            raise UserError(_("Solo se puede imputar manualmente un pago publicado."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Imputar el pago %s", self.name),
            "res_model": "caw.allocate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payment_id": self.id, "active_id": self.id},
        }
```

- [ ] **Step 5: Registrar el wizard y los accesos**

`wizards/__init__.py`:
```python
from . import caw_confirm_wizard
from . import caw_allocate_wizard
```

Agregar a `security/ir.model.access.csv`:
```csv
access_caw_allocate_wizard_manager,caw.allocate.wizard manager,model_caw_allocate_wizard,checking_account_withdrawals.group_cc_manager,1,1,1,1
access_caw_allocate_wizard_line_manager,caw.allocate.wizard.line manager,model_caw_allocate_wizard_line,checking_account_withdrawals.group_cc_manager,1,1,1,1
```

Nota: el wizard **no** se le da al Operador — CC-60 dice que el Operador no puede alterar imputaciones.

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `55 tests, 0 failed, 0 error`.

- [ ] **Step 7: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): wizard de imputación manual para el Manager"
```

---

### Task 11: Vistas, menús y filtros de consulta (Épica 6)

**Files:**
- Create: `checking_account_withdrawals/views/caw_withdrawal_views.xml`
- Create: `checking_account_withdrawals/views/caw_installment_views.xml`
- Create: `checking_account_withdrawals/views/caw_payment_views.xml`
- Create: `checking_account_withdrawals/views/caw_account_views.xml`
- Create: `checking_account_withdrawals/views/res_partner_views.xml`
- Create: `checking_account_withdrawals/views/res_config_settings_views.xml`
- Create: `checking_account_withdrawals/views/caw_wizard_views.xml`
- Create: `checking_account_withdrawals/views/menu_views.xml`
- Modify: `checking_account_withdrawals/__manifest__.py`

**Interfaces:**
- Consumes: todos los modelos y acciones de las tareas 2 a 10.
- Produces: los xmlids de acción `action_caw_withdrawal`, `action_caw_installment`, `action_caw_payment`, `action_caw_account`, y el menú raíz `menu_caw_root`.

Esta tarea no lleva tests unitarios: la validación es que el módulo instale sin errores de vista
y que las vistas abran en el navegador.

- [ ] **Step 1: Vistas del retiro**

`checking_account_withdrawals/views/caw_withdrawal_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_caw_withdrawal_list" model="ir.ui.view">
        <field name="name">caw.withdrawal.list</field>
        <field name="model">caw.withdrawal</field>
        <field name="arch" type="xml">
            <list decoration-danger="is_overdue" decoration-muted="state == 'cancel'"
                  decoration-success="state == 'paid'">
                <field name="name"/>
                <field name="date"/>
                <field name="partner_id"/>
                <field name="user_id" optional="show"/>
                <field name="company_id" groups="base.group_multi_company"/>
                <field name="amount_total" sum="Total"/>
                <field name="amount_residual" sum="Residual"/>
                <field name="is_overdue" string="Mora" optional="show"/>
                <field name="is_inconsistent" optional="hide"/>
                <field name="state" widget="badge"
                       decoration-success="state == 'paid'"
                       decoration-warning="state == 'partial'"
                       decoration-info="state == 'pending'"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_caw_withdrawal_form" model="ir.ui.view">
        <field name="name">caw.withdrawal.form</field>
        <field name="model">caw.withdrawal</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_open_confirm_wizard" type="object" string="Confirmar"
                            class="oe_highlight" invisible="state != 'draft'"/>
                    <button name="action_cancel" type="object" string="Cancelar"
                            invisible="state in ('draft', 'cancel')"
                            groups="checking_account_withdrawals.group_cc_manager"
                            confirm="¿Confirmás la cancelación de este retiro?"/>
                    <button name="action_draft" type="object" string="Volver a borrador"
                            invisible="state != 'cancel'"
                            groups="checking_account_withdrawals.group_cc_manager"/>
                    <field name="state" widget="statusbar"
                           statusbar_visible="draft,pending,partial,paid"/>
                </header>
                <sheet>
                    <div class="oe_button_box" name="button_box">
                        <button name="action_view_picking" type="object" class="oe_stat_button"
                                icon="fa-truck" invisible="not picking_id">
                            <field name="picking_state" widget="statinfo" string="Albarán"/>
                        </button>
                    </div>
                    <widget name="web_ribbon" title="Inconsistente" bg_color="text-bg-danger"
                            invisible="not is_inconsistent"/>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="partner_id" readonly="state != 'draft'"
                                   options="{'no_create': True}"/>
                            <field name="account_id" readonly="1" groups="base.group_no_one"/>
                            <field name="date" readonly="state != 'draft'"/>
                            <field name="user_id"/>
                        </group>
                        <group>
                            <field name="company_id" groups="base.group_multi_company"/>
                            <field name="currency_id" invisible="1"/>
                            <field name="amount_total"/>
                            <field name="amount_residual"/>
                            <field name="is_overdue"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Líneas" name="lines">
                            <field name="line_ids" readonly="state != 'draft'">
                                <list editable="bottom">
                                    <field name="sequence" widget="handle"/>
                                    <field name="product_id"/>
                                    <field name="name"/>
                                    <field name="quantity"/>
                                    <field name="price_unit"/>
                                    <field name="price_subtotal" sum="Total"/>
                                    <field name="currency_id" column_invisible="True"/>
                                </list>
                            </field>
                        </page>
                        <page string="Cuotas" name="installments">
                            <!-- CC-21: el Manager edita montos y vencimientos libres; el
                                 Operador la ve en solo lectura. El constraint de la Task 4
                                 rechaza que la suma se aparte del total del retiro. -->
                            <field name="installment_ids"
                                   groups="checking_account_withdrawals.group_cc_manager">
                                <list editable="bottom"
                                      decoration-danger="state == 'overdue'"
                                      decoration-success="state == 'paid'">
                                    <field name="sequence"/>
                                    <field name="date_due"/>
                                    <field name="amount" sum="Total"/>
                                    <field name="amount_allocated" sum="Imputado" readonly="1"/>
                                    <field name="amount_residual" sum="Residual" readonly="1"/>
                                    <field name="state" widget="badge" readonly="1"/>
                                    <field name="currency_id" column_invisible="True"/>
                                </list>
                            </field>
                            <field name="installment_ids" readonly="1"
                                   groups="!checking_account_withdrawals.group_cc_manager">
                                <list decoration-danger="state == 'overdue'"
                                      decoration-success="state == 'paid'">
                                    <field name="sequence"/>
                                    <field name="date_due"/>
                                    <field name="amount" sum="Total"/>
                                    <field name="amount_allocated" sum="Imputado"/>
                                    <field name="amount_residual" sum="Residual"/>
                                    <field name="state" widget="badge"/>
                                    <field name="currency_id" column_invisible="True"/>
                                </list>
                            </field>
                        </page>
                        <page string="Notas" name="notes">
                            <field name="note" placeholder="Notas internas del retiro..."/>
                        </page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="view_caw_withdrawal_search" model="ir.ui.view">
        <field name="name">caw.withdrawal.search</field>
        <field name="model">caw.withdrawal</field>
        <field name="arch" type="xml">
            <search>
                <field name="name"/>
                <field name="partner_id"/>
                <field name="user_id"/>
                <filter name="filter_pending" string="Pendientes"
                        domain="[('state', '=', 'pending')]"/>
                <filter name="filter_partial" string="Pago parcial"
                        domain="[('state', '=', 'partial')]"/>
                <filter name="filter_paid" string="Pagados"
                        domain="[('state', '=', 'paid')]"/>
                <separator/>
                <filter name="filter_overdue" string="Con cuotas vencidas"
                        domain="[('is_overdue', '=', True)]"/>
                <filter name="filter_inconsistent" string="Inconsistentes"
                        domain="[('is_inconsistent', '=', True)]"/>
                <separator/>
                <filter name="filter_this_month" string="Este mes"
                        date="date" default_period="this_month"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_partner" string="Contacto"
                            context="{'group_by': 'partner_id'}"/>
                    <filter name="group_state" string="Estado"
                            context="{'group_by': 'state'}"/>
                    <filter name="group_company" string="Compañía"
                            context="{'group_by': 'company_id'}"
                            groups="base.group_multi_company"/>
                    <filter name="group_date" string="Fecha"
                            context="{'group_by': 'date:month'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_caw_withdrawal" model="ir.actions.act_window">
        <field name="name">Retiros</field>
        <field name="res_model">caw.withdrawal</field>
        <field name="view_mode">list,form</field>
        <field name="search_view_id" ref="view_caw_withdrawal_search"/>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Registrá el primer retiro a cuenta corriente</p>
            <p>Los retiros descuentan stock y generan las cuotas que el contacto deberá pagar.</p>
        </field>
    </record>
</odoo>
```

- [ ] **Step 2: Vistas de cuotas, pagos y cuentas**

`checking_account_withdrawals/views/caw_installment_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_caw_installment_list" model="ir.ui.view">
        <field name="name">caw.installment.list</field>
        <field name="model">caw.installment</field>
        <field name="arch" type="xml">
            <list decoration-danger="state == 'overdue'" decoration-success="state == 'paid'"
                  create="false">
                <field name="partner_id"/>
                <field name="withdrawal_id"/>
                <field name="sequence" string="Cuota"/>
                <field name="date_due"/>
                <field name="amount" sum="Monto"/>
                <field name="amount_allocated" sum="Imputado"/>
                <field name="amount_residual" sum="Residual"/>
                <field name="state" widget="badge"/>
                <field name="company_id" groups="base.group_multi_company" optional="hide"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_caw_installment_search" model="ir.ui.view">
        <field name="name">caw.installment.search</field>
        <field name="model">caw.installment</field>
        <field name="arch" type="xml">
            <search>
                <field name="partner_id"/>
                <field name="withdrawal_id"/>
                <filter name="filter_open" string="Abiertas"
                        domain="[('amount_residual', '&gt;', 0)]"/>
                <filter name="filter_overdue" string="Vencidas"
                        domain="[('state', '=', 'overdue')]"/>
                <filter name="filter_due_soon" string="Vencen este mes"
                        date="date_due" default_period="this_month"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_partner" string="Contacto"
                            context="{'group_by': 'partner_id'}"/>
                    <filter name="group_state" string="Estado"
                            context="{'group_by': 'state'}"/>
                    <filter name="group_due" string="Vencimiento"
                            context="{'group_by': 'date_due:month'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_caw_installment" model="ir.actions.act_window">
        <field name="name">Cuotas por vencer</field>
        <field name="res_model">caw.installment</field>
        <field name="view_mode">list</field>
        <field name="search_view_id" ref="view_caw_installment_search"/>
        <field name="context">{'search_default_filter_open': 1}</field>
    </record>
</odoo>
```

`checking_account_withdrawals/views/caw_payment_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_caw_payment_list" model="ir.ui.view">
        <field name="name">caw.payment.list</field>
        <field name="model">caw.payment</field>
        <field name="arch" type="xml">
            <list decoration-muted="state == 'cancel'">
                <field name="name"/>
                <field name="date"/>
                <field name="partner_id"/>
                <field name="payment_method"/>
                <field name="ref" optional="show"/>
                <field name="amount" sum="Total"/>
                <field name="amount_allocated" sum="Imputado"/>
                <field name="amount_unallocated" sum="Saldo a favor"/>
                <field name="state" widget="badge"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_caw_payment_form" model="ir.ui.view">
        <field name="name">caw.payment.form</field>
        <field name="model">caw.payment</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_post" type="object" string="Publicar"
                            class="oe_highlight" invisible="state != 'draft'"/>
                    <button name="action_open_allocate_wizard" type="object"
                            string="Imputar manualmente" invisible="state != 'posted'"
                            groups="checking_account_withdrawals.group_cc_manager"/>
                    <button name="action_cancel" type="object" string="Anular"
                            invisible="state == 'cancel'"
                            groups="checking_account_withdrawals.group_cc_manager"
                            confirm="Se revertirán todas las imputaciones de este pago. ¿Continuar?"/>
                    <field name="state" widget="statusbar"/>
                </header>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="account_id" readonly="state != 'draft'"
                                   options="{'no_create': True}"/>
                            <field name="partner_id" readonly="1"/>
                            <field name="date" readonly="state != 'draft'"/>
                        </group>
                        <group>
                            <field name="currency_id" invisible="1"/>
                            <field name="amount" readonly="state != 'draft'"/>
                            <field name="payment_method" readonly="state != 'draft'"/>
                            <field name="ref"/>
                            <field name="amount_allocated"/>
                            <field name="amount_unallocated"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Imputaciones" name="allocations">
                            <field name="allocation_ids" readonly="1">
                                <list>
                                    <field name="withdrawal_id"/>
                                    <field name="installment_id"/>
                                    <field name="amount" sum="Imputado"/>
                                    <field name="currency_id" column_invisible="True"/>
                                </list>
                            </field>
                        </page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="action_caw_payment" model="ir.actions.act_window">
        <field name="name">Pagos</field>
        <field name="res_model">caw.payment</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

`checking_account_withdrawals/views/caw_account_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_caw_account_list" model="ir.ui.view">
        <field name="name">caw.account.list</field>
        <field name="model">caw.account</field>
        <field name="arch" type="xml">
            <list>
                <field name="partner_id"/>
                <field name="company_id" groups="base.group_multi_company"/>
                <field name="balance" sum="Saldo"/>
                <field name="overdue_balance" sum="Vencido"/>
                <field name="credit_balance" sum="A favor"/>
                <field name="credit_limit" groups="checking_account_withdrawals.group_cc_manager"/>
                <field name="limit_mode" groups="checking_account_withdrawals.group_cc_manager"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_caw_account_form" model="ir.ui.view">
        <field name="name">caw.account.form</field>
        <field name="model">caw.account</field>
        <field name="arch" type="xml">
            <form>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="partner_id" options="{'no_create': True}"/></h1>
                    </div>
                    <group>
                        <group string="Saldos">
                            <field name="currency_id" invisible="1"/>
                            <field name="balance"/>
                            <field name="overdue_balance"/>
                            <field name="credit_balance"/>
                        </group>
                        <group string="Límite de crédito"
                               groups="checking_account_withdrawals.group_cc_manager">
                            <field name="credit_limit"/>
                            <field name="limit_mode"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Retiros" name="withdrawals">
                            <field name="withdrawal_ids" readonly="1"/>
                        </page>
                        <page string="Pagos" name="payments">
                            <field name="payment_ids" readonly="1"/>
                        </page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="action_caw_account" model="ir.actions.act_window">
        <field name="name">Cuentas corrientes</field>
        <field name="res_model">caw.account</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

- [ ] **Step 3: Vistas del partner, ajustes y wizards**

`checking_account_withdrawals/views/res_partner_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_partner_form_caw" model="ir.ui.view">
        <field name="name">res.partner.form.caw</field>
        <field name="model">res.partner</field>
        <field name="inherit_id" ref="base.view_partner_form"/>
        <field name="arch" type="xml">
            <xpath expr="//div[@name='button_box']" position="inside">
                <button name="action_caw_open_withdrawals" type="object" class="oe_stat_button"
                        icon="fa-shopping-basket" invisible="not caw_enabled"
                        groups="checking_account_withdrawals.group_cc_user">
                    <field name="caw_withdrawal_count" widget="statinfo" string="Retiros"/>
                </button>
            </xpath>
            <xpath expr="//page[@name='sales_purchases']" position="after">
                <page string="Cuenta corriente" name="caw"
                      groups="checking_account_withdrawals.group_cc_user">
                    <group>
                        <group>
                            <field name="caw_enabled"/>
                        </group>
                        <group invisible="not caw_enabled">
                            <field name="caw_balance"/>
                            <field name="caw_overdue_balance"/>
                            <field name="caw_credit_balance"/>
                        </group>
                    </group>
                    <field name="caw_account_ids" readonly="1" invisible="not caw_enabled"/>
                </page>
            </xpath>
        </field>
    </record>
</odoo>
```

`checking_account_withdrawals/views/res_config_settings_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_caw_company_form" model="ir.ui.view">
        <field name="name">res.company.form.caw</field>
        <field name="model">res.company</field>
        <field name="inherit_id" ref="base.view_company_form"/>
        <field name="arch" type="xml">
            <xpath expr="//sheet//notebook" position="inside">
                <page string="Cuenta corriente" name="caw"
                      groups="checking_account_withdrawals.group_cc_manager">
                    <group>
                        <group string="Plan de cuotas por defecto">
                            <field name="caw_installment_count"/>
                            <field name="caw_installment_days"/>
                            <field name="caw_installment_period"/>
                            <field name="caw_cutoff_day"/>
                        </group>
                        <group string="Stock">
                            <field name="caw_picking_type_id"/>
                        </group>
                    </group>
                </page>
            </xpath>
        </field>
    </record>
</odoo>
```

`checking_account_withdrawals/views/caw_wizard_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_caw_confirm_wizard_form" model="ir.ui.view">
        <field name="name">caw.confirm.wizard.form</field>
        <field name="model">caw.confirm.wizard</field>
        <field name="arch" type="xml">
            <form string="Confirmar retiro">
                <field name="withdrawal_id" invisible="1"/>
                <field name="currency_id" invisible="1"/>
                <div class="alert alert-warning" role="alert" invisible="not limit_warning">
                    <field name="limit_warning" readonly="1" nolabel="1"/>
                </div>
                <group>
                    <group string="Situación del contacto">
                        <field name="partner_id" readonly="1"/>
                        <field name="current_balance"/>
                        <field name="overdue_balance"/>
                        <field name="amount_total"/>
                    </group>
                    <group string="Plan de cuotas">
                        <field name="plan_mode" widget="radio"/>
                        <field name="installment_count" invisible="plan_mode == 'cash'"/>
                        <field name="first_days"/>
                        <field name="period" invisible="plan_mode == 'cash'"/>
                        <field name="cutoff_day"/>
                    </group>
                </group>
                <group invisible="not limit_blocked"
                       groups="checking_account_withdrawals.group_cc_manager">
                    <field name="force_limit"/>
                </group>
                <div class="alert alert-danger" role="alert"
                     invisible="not limit_blocked">
                    Este retiro supera el límite de crédito en modo bloqueo.
                    Solo un Manager puede forzarlo.
                </div>
                <footer>
                    <button name="action_confirm" type="object" string="Confirmar"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="view_caw_allocate_wizard_form" model="ir.ui.view">
        <field name="name">caw.allocate.wizard.form</field>
        <field name="model">caw.allocate.wizard</field>
        <field name="arch" type="xml">
            <form string="Imputar pago">
                <field name="payment_id" invisible="1"/>
                <field name="currency_id" invisible="1"/>
                <group>
                    <field name="amount_available"/>
                    <field name="amount_to_allocate"/>
                </group>
                <field name="line_ids">
                    <list editable="bottom" create="false">
                        <field name="withdrawal_id" readonly="1"/>
                        <field name="installment_id" readonly="1"/>
                        <field name="date_due" readonly="1"/>
                        <field name="amount_residual" readonly="1"/>
                        <field name="amount"/>
                        <field name="currency_id" column_invisible="True"/>
                    </list>
                </field>
                <footer>
                    <button name="action_allocate" type="object" string="Imputar"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>
</odoo>
```

- [ ] **Step 4: Menús**

`checking_account_withdrawals/views/menu_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_caw_root" name="Cuenta Corriente"
              groups="checking_account_withdrawals.group_cc_user"
              web_icon="checking_account_withdrawals,static/description/icon.png"
              sequence="52"/>

    <menuitem id="menu_caw_operations" name="Operaciones"
              parent="menu_caw_root" sequence="10"/>

    <menuitem id="menu_caw_withdrawal" name="Retiros"
              parent="menu_caw_operations" action="action_caw_withdrawal" sequence="10"/>

    <menuitem id="menu_caw_payment" name="Pagos"
              parent="menu_caw_operations" action="action_caw_payment" sequence="20"/>

    <menuitem id="menu_caw_installment" name="Cuotas por vencer"
              parent="menu_caw_operations" action="action_caw_installment" sequence="30"/>

    <menuitem id="menu_caw_config" name="Configuración"
              parent="menu_caw_root" sequence="90"
              groups="checking_account_withdrawals.group_cc_manager"/>

    <menuitem id="menu_caw_account" name="Cuentas corrientes"
              parent="menu_caw_config" action="action_caw_account" sequence="10"/>
</odoo>
```

- [ ] **Step 5: Declarar las vistas en el manifiesto**

En `__manifest__.py`, la clave `data` queda:
```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "views/caw_account_views.xml",
        "views/caw_withdrawal_views.xml",
        "views/caw_installment_views.xml",
        "views/caw_payment_views.xml",
        "views/caw_wizard_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
```

El menú raíz apunta a un `icon.png` que todavía no existe (Task 15). Odoo tolera la
referencia faltante mostrando el ícono por defecto; no rompe la instalación.

- [ ] **Step 6: Validar el XML y actualizar el módulo**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/checking_account_withdrawals
for f in views/*.xml security/*.xml data/*.xml; do
  python3 -c "import xml.dom.minidom as m; m.parse('$f')" || echo "FALLA: $f"
done
docker exec odoo-odoo-1 odoo -u checking_account_withdrawals -d calidad --stop-after-init --no-http
```
Esperado: sin errores de parseo y sin `ParseError` en el log de Odoo.

- [ ] **Step 7: Correr los tests para verificar que no se rompió nada**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `55 tests, 0 failed, 0 error`.

- [ ] **Step 8: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): vistas, filtros y menús"
```

---

### Task 12: Resumen de cuenta en PDF (CC-52)

**Files:**
- Create: `checking_account_withdrawals/wizards/caw_statement_wizard.py`
- Create: `checking_account_withdrawals/report/report_caw_statement.xml`
- Create: `checking_account_withdrawals/report/report_caw_statement_templates.xml`
- Create: `checking_account_withdrawals/tests/test_statement.py`
- Modify: `checking_account_withdrawals/wizards/__init__.py`
- Modify: `checking_account_withdrawals/views/caw_wizard_views.xml`
- Modify: `checking_account_withdrawals/views/menu_views.xml`
- Modify: `checking_account_withdrawals/__manifest__.py`
- Modify: `checking_account_withdrawals/security/ir.model.access.csv`
- Modify: `checking_account_withdrawals/tests/__init__.py`

**Interfaces:**
- Consumes: `caw.account`, `caw.withdrawal`, `caw.installment`, `caw.payment`.
- Produces:
  - `caw.statement.wizard` con `account_id`, `date_to`, `action_print()`.
  - `caw.statement.wizard._caw_statement_data()` → dict con claves `account`, `withdrawals`, `payments`, `balance`, `overdue`, `credit`, `date_to`.
  - Reporte `checking_account_withdrawals.action_report_caw_statement`.

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_statement.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawStatement(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)
        self.withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 500.0,
            })],
        })
        self.withdrawal._caw_generate_installments(
            count=2, first_days=30, period="months", cutoff_day=0
        )

    def test_statement_data_respects_cutoff_date(self):
        """El resumen solo incluye movimientos hasta la fecha de corte."""
        late = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-12-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 999.0,
            })],
        })
        late._caw_generate_installments(count=1, first_days=30, period="months", cutoff_day=0)
        wizard = self.env["caw.statement.wizard"].create({
            "account_id": self.account.id,
            "date_to": "2026-06-30",
        })
        data = wizard._caw_statement_data()
        self.assertIn(self.withdrawal, data["withdrawals"])
        self.assertNotIn(late, data["withdrawals"])

    def test_statement_includes_payments_and_balance(self):
        """El resumen trae los pagos imputados y el saldo final a la fecha."""
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 250.0,
            "date": "2026-03-01",
            "payment_method": "cash",
        })
        payment.action_post()
        wizard = self.env["caw.statement.wizard"].create({
            "account_id": self.account.id,
            "date_to": "2026-06-30",
        })
        data = wizard._caw_statement_data()
        self.assertIn(payment, data["payments"])
        self.assertEqual(data["balance"], 250.0)

    def test_report_renders_without_error(self):
        """El PDF se renderiza sin excepciones."""
        wizard = self.env["caw.statement.wizard"].create({
            "account_id": self.account.id,
            "date_to": "2026-06-30",
        })
        report = self.env["ir.actions.report"]._render_qweb_html(
            "checking_account_withdrawals.action_report_caw_statement", wizard.ids
        )
        self.assertTrue(report[0])
```

`tests/__init__.py` — agregar `from . import test_statement`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — `caw.statement.wizard` no existe.

- [ ] **Step 3: Implementar el wizard del resumen**

`checking_account_withdrawals/wizards/caw_statement_wizard.py`:
```python
# -*- coding: utf-8 -*-
from odoo import _, fields, models


class CawStatementWizard(models.TransientModel):
    _name = "caw.statement.wizard"
    _description = "Resumen de cuenta corriente a una fecha"

    account_id = fields.Many2one(
        comodel_name="caw.account",
        string="Cuenta corriente",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(related="account_id.partner_id", readonly=True)
    currency_id = fields.Many2one(related="account_id.currency_id", readonly=True)
    date_to = fields.Date(
        string="Saldo a la fecha",
        required=True,
        default=fields.Date.context_today,
    )

    def _caw_statement_data(self):
        """Arma los datos del resumen: retiros, cuotas, pagos y saldo a la fecha."""
        self.ensure_one()
        account = self.account_id
        withdrawals = self.env["caw.withdrawal"].search(
            [
                ("account_id", "=", account.id),
                ("date", "<=", self.date_to),
                ("state", "not in", ("draft", "cancel")),
            ],
            order="date asc, name asc",
        )
        payments = self.env["caw.payment"].search(
            [
                ("account_id", "=", account.id),
                ("date", "<=", self.date_to),
                ("state", "=", "posted"),
            ],
            order="date asc, name asc",
        )
        installments = withdrawals.mapped("installment_ids")
        total_withdrawn = sum(withdrawals.mapped("amount_total"))
        total_paid = sum(
            installments.mapped("allocation_ids")
            .filtered(lambda a: a.date <= self.date_to and a.payment_id.state == "posted")
            .mapped("amount")
        )
        return {
            "account": account,
            "withdrawals": withdrawals,
            "installments": installments,
            "payments": payments,
            "total_withdrawn": total_withdrawn,
            "total_paid": total_paid,
            "balance": total_withdrawn - total_paid,
            "overdue": account.overdue_balance,
            "credit": account.credit_balance,
            "date_to": self.date_to,
        }

    def action_print(self):
        """Genera el PDF del resumen de cuenta."""
        self.ensure_one()
        return self.env.ref(
            "checking_account_withdrawals.action_report_caw_statement"
        ).report_action(self)
```

`wizards/__init__.py` — agregar `from . import caw_statement_wizard`.

- [ ] **Step 4: Declarar el reporte**

`checking_account_withdrawals/report/report_caw_statement.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_report_caw_statement" model="ir.actions.report">
        <field name="name">Resumen de cuenta corriente</field>
        <field name="model">caw.statement.wizard</field>
        <field name="report_type">qweb-pdf</field>
        <field name="report_name">checking_account_withdrawals.report_caw_statement</field>
        <field name="report_file">checking_account_withdrawals.report_caw_statement</field>
        <field name="print_report_name">'Resumen %s' % (object.partner_id.display_name)</field>
    </record>
</odoo>
```

- [ ] **Step 5: Escribir la plantilla QWeb**

`checking_account_withdrawals/report/report_caw_statement_templates.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <template id="report_caw_statement_document">
        <t t-set="data" t-value="doc._caw_statement_data()"/>
        <t t-call="web.external_layout">
            <div class="page">
                <h2>Resumen de cuenta corriente</h2>
                <div class="row mb-4">
                    <div class="col-6">
                        <strong>Contacto:</strong>
                        <span t-field="doc.partner_id.display_name"/><br/>
                        <strong>Compañía:</strong>
                        <span t-field="data['account'].company_id.name"/>
                    </div>
                    <div class="col-6 text-end">
                        <strong>Saldo a la fecha:</strong>
                        <span t-esc="data['date_to']"/><br/>
                        <strong>Emitido:</strong>
                        <span t-esc="context_timestamp(datetime.datetime.now()).strftime('%d/%m/%Y')"/>
                    </div>
                </div>

                <h4>Retiros</h4>
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>Número</th>
                            <th>Fecha</th>
                            <th class="text-end">Total</th>
                            <th class="text-end">Residual</th>
                            <th>Estado</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr t-foreach="data['withdrawals']" t-as="withdrawal">
                            <td><span t-field="withdrawal.name"/></td>
                            <td><span t-field="withdrawal.date"/></td>
                            <td class="text-end">
                                <span t-field="withdrawal.amount_total"
                                      t-options='{"widget": "monetary", "display_currency": withdrawal.currency_id}'/>
                            </td>
                            <td class="text-end">
                                <span t-field="withdrawal.amount_residual"
                                      t-options='{"widget": "monetary", "display_currency": withdrawal.currency_id}'/>
                            </td>
                            <td><span t-field="withdrawal.state"/></td>
                        </tr>
                    </tbody>
                </table>

                <h4>Cuotas</h4>
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>Retiro</th>
                            <th>Cuota</th>
                            <th>Vencimiento</th>
                            <th class="text-end">Monto</th>
                            <th class="text-end">Imputado</th>
                            <th class="text-end">Residual</th>
                            <th>Estado</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr t-foreach="data['installments']" t-as="installment">
                            <td><span t-field="installment.withdrawal_id.name"/></td>
                            <td><span t-field="installment.sequence"/></td>
                            <td><span t-field="installment.date_due"/></td>
                            <td class="text-end">
                                <span t-field="installment.amount"
                                      t-options='{"widget": "monetary", "display_currency": installment.currency_id}'/>
                            </td>
                            <td class="text-end">
                                <span t-field="installment.amount_allocated"
                                      t-options='{"widget": "monetary", "display_currency": installment.currency_id}'/>
                            </td>
                            <td class="text-end">
                                <span t-field="installment.amount_residual"
                                      t-options='{"widget": "monetary", "display_currency": installment.currency_id}'/>
                            </td>
                            <td><span t-field="installment.state"/></td>
                        </tr>
                    </tbody>
                </table>

                <h4>Pagos</h4>
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>Número</th>
                            <th>Fecha</th>
                            <th>Medio</th>
                            <th>Referencia</th>
                            <th class="text-end">Monto</th>
                            <th class="text-end">Imputado</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr t-foreach="data['payments']" t-as="payment">
                            <td><span t-field="payment.name"/></td>
                            <td><span t-field="payment.date"/></td>
                            <td><span t-field="payment.payment_method"/></td>
                            <td><span t-field="payment.ref"/></td>
                            <td class="text-end">
                                <span t-field="payment.amount"
                                      t-options='{"widget": "monetary", "display_currency": payment.currency_id}'/>
                            </td>
                            <td class="text-end">
                                <span t-field="payment.amount_allocated"
                                      t-options='{"widget": "monetary", "display_currency": payment.currency_id}'/>
                            </td>
                        </tr>
                    </tbody>
                </table>

                <div class="row mt-4">
                    <div class="col-6 offset-6">
                        <table class="table table-sm">
                            <tr>
                                <td><strong>Total retirado</strong></td>
                                <td class="text-end">
                                    <span t-esc="data['total_withdrawn']"
                                          t-options='{"widget": "monetary", "display_currency": doc.currency_id}'/>
                                </td>
                            </tr>
                            <tr>
                                <td><strong>Total pagado</strong></td>
                                <td class="text-end">
                                    <span t-esc="data['total_paid']"
                                          t-options='{"widget": "monetary", "display_currency": doc.currency_id}'/>
                                </td>
                            </tr>
                            <tr class="border-top">
                                <td><strong>Saldo final</strong></td>
                                <td class="text-end">
                                    <strong>
                                        <span t-esc="data['balance']"
                                              t-options='{"widget": "monetary", "display_currency": doc.currency_id}'/>
                                    </strong>
                                </td>
                            </tr>
                            <tr>
                                <td>Saldo vencido</td>
                                <td class="text-end">
                                    <span t-esc="data['overdue']"
                                          t-options='{"widget": "monetary", "display_currency": doc.currency_id}'/>
                                </td>
                            </tr>
                            <tr>
                                <td>Saldo a favor</td>
                                <td class="text-end">
                                    <span t-esc="data['credit']"
                                          t-options='{"widget": "monetary", "display_currency": doc.currency_id}'/>
                                </td>
                            </tr>
                        </table>
                    </div>
                </div>
            </div>
        </t>
    </template>

    <template id="report_caw_statement">
        <t t-call="web.html_container">
            <t t-foreach="docs" t-as="doc">
                <t t-call="checking_account_withdrawals.report_caw_statement_document"/>
            </t>
        </t>
    </template>
</odoo>
```

- [ ] **Step 6: Agregar vista del wizard, menú y manifiesto**

Agregar a `views/caw_wizard_views.xml` antes de `</odoo>`:
```xml
    <record id="view_caw_statement_wizard_form" model="ir.ui.view">
        <field name="name">caw.statement.wizard.form</field>
        <field name="model">caw.statement.wizard</field>
        <field name="arch" type="xml">
            <form string="Resumen de cuenta">
                <group>
                    <field name="account_id" options="{'no_create': True}"/>
                    <field name="date_to"/>
                </group>
                <footer>
                    <button name="action_print" type="object" string="Imprimir"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="action_caw_statement_wizard" model="ir.actions.act_window">
        <field name="name">Resumen de cuenta</field>
        <field name="res_model">caw.statement.wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
    </record>
```

Agregar a `views/menu_views.xml` antes de `</odoo>`:
```xml
    <menuitem id="menu_caw_statement" name="Resumen de cuenta"
              parent="menu_caw_operations" action="action_caw_statement_wizard" sequence="40"/>
```

En `__manifest__.py`, agregar al final de `data`:
```python
        "report/report_caw_statement.xml",
        "report/report_caw_statement_templates.xml",
```

Agregar a `security/ir.model.access.csv`:
```csv
access_caw_statement_wizard_user,caw.statement.wizard user,model_caw_statement_wizard,checking_account_withdrawals.group_cc_user,1,1,1,1
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `58 tests, 0 failed, 0 error`.

- [ ] **Step 8: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): resumen de cuenta en PDF"
```

---

### Task 13: Controller del dashboard

**Files:**
- Create: `checking_account_withdrawals/controllers/__init__.py`
- Create: `checking_account_withdrawals/controllers/dashboard_controller.py`
- Create: `checking_account_withdrawals/tests/test_dashboard_controller.py`
- Modify: `checking_account_withdrawals/__init__.py`
- Modify: `checking_account_withdrawals/tests/__init__.py`

**Interfaces:**
- Consumes: las tablas `caw_account`, `caw_withdrawal`, `caw_installment`, `caw_payment`, `caw_allocation`.
- Produces cuatro endpoints:
  - `POST /checking_account_withdrawals/filters` (json) → `{companies: [{id, name}], min_date, max_date}`
  - `POST /checking_account_withdrawals/metrics` (json) → `{kpis: {...}, charts: {...}}`
  - `POST /checking_account_withdrawals/records` (json) → `{records: [...], page, pages, total}` con `model` en `"withdrawals"` / `"installments"`
  - `GET /checking_account_withdrawals/export` (http) → CSV
- Claves exactas de `kpis`: `total_balance`, `overdue_balance`, `credit_balance`, `total_withdrawn`, `withdrawal_count`, `overdue_installments`, `overdue_rate`, `collected`.
- Claves exactas de `charts`: `balance_trend {labels, companies}`, `collected_vs_overdue {labels, collected, overdue}`, `installment_status {labels, values}`, `top_partners {labels, values}`, `by_company {labels, values}`.

- [ ] **Step 1: Escribir el test que falla**

`checking_account_withdrawals/tests/test_dashboard_controller.py`:
```python
# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawDashboard(CawCommon):
    """Testea la lógica del controller sin pasar por HTTP."""

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 1000.0,
            })],
        })
        withdrawal._caw_generate_installments(
            count=2, first_days=30, period="months", cutoff_day=0
        )
        self.withdrawal = withdrawal

    def _controller(self):
        """Instancia el controller para llamar sus helpers directamente."""
        from odoo.addons.checking_account_withdrawals.controllers.dashboard_controller import (
            CawDashboardController,
        )
        return CawDashboardController()

    def test_kpis_reflect_open_balance(self):
        """Los KPIs reportan el saldo de cartera y la cantidad de retiros."""
        kpis = self._controller()._caw_kpis(
            self.env, start_date=None, end_date=None, company="all"
        )
        self.assertEqual(kpis["total_balance"], 1000.0)
        self.assertEqual(kpis["withdrawal_count"], 1)
        self.assertEqual(kpis["credit_balance"], 0.0)

    def test_installment_status_chart_counts_states(self):
        """El gráfico de estados agrupa las cuotas por estado."""
        charts = self._controller()._caw_charts(
            self.env, start_date=None, end_date=None, company="all"
        )
        status = charts["installment_status"]
        self.assertEqual(sum(status["values"]), 2)

    def test_top_partners_lists_debtors(self):
        """El top de partners lista a los deudores por saldo."""
        charts = self._controller()._caw_charts(
            self.env, start_date=None, end_date=None, company="all"
        )
        self.assertIn(self.partner.display_name, charts["top_partners"]["labels"])

    def test_access_is_denied_without_group(self):
        """Un usuario sin el grupo Manager no accede al dashboard."""
        user = self.env["res.users"].create({
            "name": "Sin permisos CC",
            "login": "caw_no_access_test",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self._controller()._check_access(self.env(user=user))
```

`tests/__init__.py` — agregar `from . import test_dashboard_controller`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: FAIL — el módulo `controllers.dashboard_controller` no existe.

- [ ] **Step 3: Implementar el controller**

`checking_account_withdrawals/controllers/__init__.py`:
```python
from . import dashboard_controller
```

`checking_account_withdrawals/controllers/dashboard_controller.py`:
```python
# -*- coding: utf-8 -*-
import csv
import io
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

INSTALLMENT_STATES = {
    "pending": "Pendiente",
    "partial": "Parcial",
    "paid": "Pagada",
    "overdue": "Vencida",
}

WITHDRAWAL_STATES = {
    "draft": "Borrador",
    "pending": "Pendiente",
    "partial": "Pago parcial",
    "paid": "Pagado",
    "cancel": "Cancelado",
}


class CawDashboardController(http.Controller):

    def _check_access(self, env=None):
        """Valida que el usuario pertenezca al grupo Manager de Cuenta Corriente."""
        env = env or request.env
        if not env.user.has_group("checking_account_withdrawals.group_cc_manager"):
            raise AccessError("No tenés permisos para acceder al dashboard de cuenta corriente.")

    def _caw_where(self, env, start_date, end_date, company, alias="w"):
        """WHERE parametrizado sobre caw_withdrawal (alias `w`), scopeado a las compañías."""
        where = f"{alias}.state NOT IN ('draft', 'cancel') AND {alias}.company_id IN %s"
        params = [tuple(env.companies.ids)]
        if start_date:
            where += f" AND {alias}.date >= %s"
            params.append(start_date)
        if end_date:
            where += f" AND {alias}.date <= %s"
            params.append(end_date)
        if company and company != "all":
            where += f" AND {alias}.company_id = %s"
            params.append(int(company))
        return where, params

    def _caw_kpis(self, env, start_date, end_date, company):
        """Calcula los KPIs de la cartera de fiados en el período."""
        where, params = self._caw_where(env, start_date, end_date, company)
        env.cr.execute(f"""
            SELECT COUNT(*) AS withdrawal_count,
                   COALESCE(SUM(w.amount_total), 0) AS total_withdrawn
            FROM caw_withdrawal w
            WHERE {where}
        """, params)
        row = env.cr.dictfetchone() or {}

        env.cr.execute(f"""
            SELECT COALESCE(SUM(i.amount_residual), 0) AS total_balance,
                   COALESCE(SUM(i.amount_residual) FILTER (
                       WHERE i.date_due < CURRENT_DATE AND i.amount_residual > 0
                   ), 0) AS overdue_balance,
                   COUNT(*) FILTER (
                       WHERE i.date_due < CURRENT_DATE AND i.amount_residual > 0
                   ) AS overdue_installments,
                   COUNT(*) AS installment_count
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
        """, params)
        balances = env.cr.dictfetchone() or {}

        credit_params = [tuple(env.companies.ids)]
        credit_where = "p.state = 'posted' AND p.company_id IN %s"
        if company and company != "all":
            credit_where += " AND p.company_id = %s"
            credit_params.append(int(company))
        env.cr.execute(f"""
            SELECT COALESCE(SUM(p.amount_unallocated), 0) AS credit_balance,
                   COALESCE(SUM(p.amount) FILTER (WHERE TRUE), 0) AS collected
            FROM caw_payment p
            WHERE {credit_where}
        """, credit_params)
        payments = env.cr.dictfetchone() or {}

        installment_count = balances.get("installment_count") or 0
        overdue_installments = balances.get("overdue_installments") or 0
        return {
            "total_balance": float(balances.get("total_balance") or 0),
            "overdue_balance": float(balances.get("overdue_balance") or 0),
            "credit_balance": float(payments.get("credit_balance") or 0),
            "total_withdrawn": float(row.get("total_withdrawn") or 0),
            "withdrawal_count": int(row.get("withdrawal_count") or 0),
            "overdue_installments": int(overdue_installments),
            "overdue_rate": round(overdue_installments / installment_count * 100, 1)
                            if installment_count else 0.0,
            "collected": float(payments.get("collected") or 0),
        }

    def _caw_charts(self, env, start_date, end_date, company):
        """Arma las series de los cinco gráficos del dashboard."""
        where, params = self._caw_where(env, start_date, end_date, company)

        env.cr.execute(f"""
            SELECT to_char(date_trunc('month', w.date), 'YYYY-MM') AS period,
                   w.company_id,
                   COALESCE(SUM(i.amount_residual), 0) AS residual
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY period, w.company_id
            ORDER BY period
        """, params)
        trend_rows = env.cr.dictfetchall()
        company_names = self._resolve_names(env, "res.company", [r["company_id"] for r in trend_rows])
        labels = sorted({r["period"] for r in trend_rows})
        companies_series = {}
        for row in trend_rows:
            name = company_names.get(row["company_id"], "N/D")
            series = companies_series.setdefault(name, [0.0] * len(labels))
            series[labels.index(row["period"])] = float(row["residual"])

        env.cr.execute(f"""
            SELECT to_char(date_trunc('month', i.date_due), 'YYYY-MM') AS period,
                   COALESCE(SUM(i.amount_allocated), 0) AS collected,
                   COALESCE(SUM(i.amount_residual) FILTER (
                       WHERE i.date_due < CURRENT_DATE
                   ), 0) AS overdue
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY period
            ORDER BY period
        """, params)
        vs_rows = env.cr.dictfetchall()

        env.cr.execute(f"""
            SELECT i.state, COUNT(*) AS qty
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY i.state
        """, params)
        status_rows = env.cr.dictfetchall()

        env.cr.execute(f"""
            SELECT w.partner_id, COALESCE(SUM(i.amount_residual), 0) AS residual
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY w.partner_id
            HAVING SUM(i.amount_residual) > 0
            ORDER BY residual DESC
            LIMIT 10
        """, params)
        top_rows = env.cr.dictfetchall()
        partner_names = self._resolve_names(env, "res.partner", [r["partner_id"] for r in top_rows])

        env.cr.execute(f"""
            SELECT w.company_id, COALESCE(SUM(w.amount_total), 0) AS total
            FROM caw_withdrawal w
            WHERE {where}
            GROUP BY w.company_id
            ORDER BY total DESC
        """, params)
        company_rows = env.cr.dictfetchall()

        return {
            "balance_trend": {"labels": labels, "companies": companies_series},
            "collected_vs_overdue": {
                "labels": [r["period"] for r in vs_rows],
                "collected": [float(r["collected"]) for r in vs_rows],
                "overdue": [float(r["overdue"]) for r in vs_rows],
            },
            "installment_status": {
                "labels": [INSTALLMENT_STATES.get(r["state"], r["state"]) for r in status_rows],
                "values": [int(r["qty"]) for r in status_rows],
            },
            "top_partners": {
                "labels": [partner_names.get(r["partner_id"], "N/D") for r in top_rows],
                "values": [float(r["residual"]) for r in top_rows],
            },
            "by_company": {
                "labels": [company_names.get(r["company_id"], "N/D") for r in company_rows],
                "values": [float(r["total"]) for r in company_rows],
            },
        }

    def _resolve_names(self, env, model, ids):
        """Resuelve {id: display_name} vía ORM con sudo, evitando SQL sobre columnas jsonb."""
        ids = [i for i in set(ids) if i]
        if not ids:
            return {}
        return {rec.id: rec.display_name for rec in env[model].sudo().browse(ids)}

    @http.route("/checking_account_withdrawals/filters", type="json", auth="user")
    def filters(self, **kwargs):
        """Metadatos para poblar los selectores del dashboard."""
        self._check_access()
        env = request.env
        env.cr.execute("""
            SELECT MIN(date) AS min_date, MAX(date) AS max_date
            FROM caw_withdrawal WHERE company_id IN %s
        """, [tuple(env.companies.ids)])
        dates = env.cr.dictfetchone() or {}
        return {
            "companies": [
                {"id": c.id, "name": c.display_name} for c in env.companies
            ],
            "min_date": str(dates.get("min_date") or ""),
            "max_date": str(dates.get("max_date") or ""),
        }

    @http.route("/checking_account_withdrawals/metrics", type="json", auth="user")
    def metrics(self, start_date=None, end_date=None, company="all", **kwargs):
        """KPIs y series de gráficos del dashboard."""
        self._check_access()
        env = request.env
        return {
            "kpis": self._caw_kpis(env, start_date, end_date, company),
            "charts": self._caw_charts(env, start_date, end_date, company),
        }

    @http.route("/checking_account_withdrawals/records", type="json", auth="user")
    def records(self, model="withdrawals", start_date=None, end_date=None, company="all",
                search=None, page=1, per_page=15, **kwargs):
        """Listado paginado de retiros o cuotas para las pestañas del dashboard."""
        self._check_access()
        env = request.env
        page = max(int(page or 1), 1)
        per_page = min(max(int(per_page or 15), 1), 200)
        domain = [("company_id", "in", env.companies.ids)]
        if company and company != "all":
            domain.append(("company_id", "=", int(company)))
        if model == "installments":
            record_model = env["caw.installment"]
            date_field = "date_due"
        else:
            record_model = env["caw.withdrawal"]
            date_field = "date"
            domain.append(("state", "not in", ("draft", "cancel")))
        if start_date:
            domain.append((date_field, ">=", start_date))
        if end_date:
            domain.append((date_field, "<=", end_date))
        if search:
            domain.append(("partner_id", "ilike", search))
        total = record_model.search_count(domain)
        records = record_model.search(
            domain, offset=(page - 1) * per_page, limit=per_page, order=f"{date_field} desc"
        )
        return {
            "records": [self._caw_serialize(record, model) for record in records],
            "page": page,
            "pages": max((total + per_page - 1) // per_page, 1),
            "total": total,
        }

    def _caw_serialize(self, record, model):
        """Serializa un retiro o una cuota para la tabla del dashboard."""
        if model == "installments":
            return {
                "id": record.id,
                "partner": record.partner_id.display_name,
                "withdrawal": record.withdrawal_id.name,
                "sequence": record.sequence,
                "date_due": str(record.date_due or ""),
                "amount": record.amount,
                "allocated": record.amount_allocated,
                "residual": record.amount_residual,
                "state": INSTALLMENT_STATES.get(record.state, record.state),
            }
        return {
            "id": record.id,
            "name": record.name,
            "date": str(record.date or ""),
            "partner": record.partner_id.display_name,
            "company": record.company_id.display_name,
            "amount_total": record.amount_total,
            "residual": record.amount_residual,
            "overdue": record.is_overdue,
            "state": WITHDRAWAL_STATES.get(record.state, record.state),
        }

    @http.route("/checking_account_withdrawals/export", type="http", auth="user")
    def export(self, model="withdrawals", start_date=None, end_date=None, company="all",
               search=None, **kwargs):
        """Exporta el listado filtrado a CSV."""
        self._check_access()
        data = self.records(
            model=model, start_date=start_date, end_date=end_date,
            company=company, search=search, page=1, per_page=10000,
        )
        rows = data["records"]
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        filename = f"cuenta_corriente_{model}.csv"
        return request.make_response(
            output.getvalue().encode("utf-8-sig"),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
            ],
        )
```

`checking_account_withdrawals/__init__.py`:
```python
from . import models
from . import wizards
from . import controllers
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `62 tests, 0 failed, 0 error`.

- [ ] **Step 5: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): controller de métricas del dashboard"
```

---

### Task 14: Dashboard OWL (CC-53)

El front se **deriva** del de `account_management_metrics` para garantizar el mismo estilo.
No lo escribas de cero: copialo y adaptalo.

**Files:**
- Create: `checking_account_withdrawals/static/src/css/dashboard.css` (copia adaptada)
- Create: `checking_account_withdrawals/static/src/js/dashboard.js`
- Create: `checking_account_withdrawals/static/src/xml/dashboard.xml`
- Create: `checking_account_withdrawals/views/dashboard_views.xml`
- Modify: `checking_account_withdrawals/__manifest__.py`
- Modify: `checking_account_withdrawals/views/menu_views.xml`

**Interfaces:**
- Consumes: los endpoints y las claves exactas de KPIs/charts de la Task 13.
- Produces: el componente registrado como `checking_account_withdrawals.dashboard` en
  `registry.category("actions")`, la plantilla OWL `checking_account_withdrawals.DashboardTemplate`
  y la acción `action_caw_dashboard`.

- [ ] **Step 1: Copiar los tres archivos base**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
mkdir -p checking_account_withdrawals/static/src/{css,js,xml}
cp account_management_metrics/static/src/css/dashboard.css checking_account_withdrawals/static/src/css/dashboard.css
cp account_management_metrics/static/src/js/dashboard.js  checking_account_withdrawals/static/src/js/dashboard.js
cp account_management_metrics/static/src/xml/dashboard.xml checking_account_withdrawals/static/src/xml/dashboard.xml
```

- [ ] **Step 2: Renombrar el módulo en los tres archivos**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/checking_account_withdrawals/static/src
sed -i 's/account_management_metrics/checking_account_withdrawals/g' css/dashboard.css js/dashboard.js xml/dashboard.xml
sed -i 's/account-dashboard-wrap/caw-dashboard-wrap/g' css/dashboard.css xml/dashboard.xml
grep -c checking_account_withdrawals js/dashboard.js xml/dashboard.xml
```
Esperado: al menos 1 coincidencia en cada archivo.

El nombre de clase del componente pasa de `AccountDashboardMetrics` a `CawDashboard`
(cambiá también la referencia en la línea del `registry.category("actions").add(...)`).

- [ ] **Step 3: Adaptar el estado y los endpoints en `js/dashboard.js`**

Reemplazá el bloque `this.state = useState({...})` por:
```javascript
        this.state = useState({
            preset: "30days",
            startDate: "",
            endDate: "",
            company: "all",
            search: "",
            page: 1,
            perPage: 15,
            activeTab: "general",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark"
        });
```

Reemplazá `this.metricsData = useState({...})` por:
```javascript
        this.metricsData = useState({
            kpis: {
                total_balance: 0,
                overdue_balance: 0,
                credit_balance: 0,
                total_withdrawn: 0,
                withdrawal_count: 0,
                overdue_installments: 0,
                overdue_rate: 0,
                collected: 0
            },
            charts: {
                balance_trend: { labels: [], companies: {} },
                collected_vs_overdue: { labels: [], collected: [], overdue: [] },
                installment_status: { labels: [], values: [] },
                top_partners: { labels: [], values: [] },
                by_company: { labels: [], values: [] }
            }
        });

        this.withdrawalsData = useState({ records: [], page: 1, pages: 1, total: 0 });
        this.installmentsData = useState({ records: [], page: 1, pages: 1, total: 0 });
```

Reemplazá `getFilterPayload`, `loadFiltersMetadata`, `refreshData`, `loadInvoices` y
`loadDrafts` por:
```javascript
    getFilterPayload() {
        return {
            start_date: this.state.startDate || null,
            end_date: this.state.endDate || null,
            company: this.state.company
        };
    }

    async loadFiltersMetadata() {
        try {
            const data = await rpc("/checking_account_withdrawals/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const metrics = await rpc("/checking_account_withdrawals/metrics", this.getFilterPayload());
            Object.assign(this.metricsData, metrics);
            if (this.state.activeTab === "general") {
                this.renderAllCharts();
            } else if (this.state.activeTab === "withdrawals") {
                await this.loadRecords("withdrawals");
            } else if (this.state.activeTab === "installments") {
                await this.loadRecords("installments");
            }
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    async loadRecords(model) {
        try {
            const data = await rpc("/checking_account_withdrawals/records", {
                ...this.getFilterPayload(),
                model: model,
                search: this.state.search,
                page: this.state.page,
                per_page: this.state.perPage
            });
            const target = model === "installments" ? this.installmentsData : this.withdrawalsData;
            Object.assign(target, data);
        } catch (e) {
            console.error(`Error al cargar ${model}:`, e);
        }
    }

    exportCSV() {
        const params = new URLSearchParams({
            model: this.state.activeTab === "installments" ? "installments" : "withdrawals",
            start_date: this.state.startDate || '',
            end_date: this.state.endDate || '',
            company: this.state.company,
            search: this.state.search || ''
        });
        window.open(`/checking_account_withdrawals/export?${params.toString()}`, '_blank');
    }
```

En `switchTab`, cambiá las ramas `"invoices"` / `"drafts"` por `"withdrawals"` / `"installments"`,
llamando a `this.loadRecords(tab)` en ambas.

- [ ] **Step 4: Adaptar `renderAllCharts` a las cinco series nuevas**

Reemplazá el cuerpo de `renderAllCharts` (desde el comentario `// 1.` hasta el cierre del método)
manteniendo la cabecera de tema y `gridConfig` tal cual está. Las cinco llamadas:

```javascript
        // 1. Evolución del saldo (line, una serie por compañía)
        const trendData = this.metricsData.charts.balance_trend;
        const companies = trendData.companies || {};
        const companyColors = [
            { border: "#3b82f6", bg: "rgba(59, 130, 246, 0.08)" },
            { border: "#a855f7", bg: "rgba(168, 85, 247, 0.08)" },
            { border: "#10b981", bg: "rgba(16, 185, 129, 0.08)" },
            { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.08)" },
            { border: "#ec4899", bg: "rgba(236, 72, 153, 0.08)" },
            { border: "#06b6d4", bg: "rgba(6, 182, 212, 0.08)" }
        ];
        const datasets = Object.keys(companies).map((name, idx) => {
            const color = companyColors[idx % companyColors.length];
            return {
                label: name,
                data: companies[name],
                borderColor: color.border,
                backgroundColor: color.bg,
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointBackgroundColor: color.border,
                pointHoverRadius: 6
            };
        });
        this.createOrUpdateChart("chart-balance-trend", "line", {
            labels: trendData.labels,
            datasets: datasets.length ? datasets : [{ label: "Saldo", data: [], borderColor: "#3b82f6" }]
        }, {
            plugins: { legend: { display: true, position: "top", labels: { color: "#94a3b8", usePointStyle: true, pointStyle: "circle", padding: 15 } } },
            scales: {
                x: { grid: gridConfig },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } }
            }
        });

        // 2. Cobrado vs. vencido
        const vs = this.metricsData.charts.collected_vs_overdue;
        this.createOrUpdateChart("chart-collected-vs-overdue", "line", {
            labels: vs.labels,
            datasets: [
                { label: "Cobrado", data: vs.collected, borderColor: "#10b981", backgroundColor: "rgba(16, 185, 129, 0.08)", fill: true, tension: 0.4, borderWidth: 3, pointBackgroundColor: "#10b981", pointHoverRadius: 6 },
                { label: "Vencido", data: vs.overdue, borderColor: "#ef4444", backgroundColor: "rgba(239, 68, 68, 0.08)", fill: true, tension: 0.4, borderWidth: 3, pointBackgroundColor: "#ef4444", pointHoverRadius: 6 }
            ]
        }, {
            plugins: { legend: { display: true, position: "top", labels: { color: "#94a3b8", usePointStyle: true, pointStyle: "circle", padding: 15 } } },
            scales: {
                x: { grid: gridConfig },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } }
            }
        });

        // 3. Distribución de cuotas por estado (doughnut)
        this.createOrUpdateChart("chart-installment-status", "doughnut", {
            labels: this.metricsData.charts.installment_status.labels,
            datasets: [{
                data: this.metricsData.charts.installment_status.values,
                backgroundColor: ["rgba(59, 130, 246, 0.75)", "rgba(245, 158, 11, 0.75)", "rgba(16, 185, 129, 0.75)", "rgba(239, 68, 68, 0.75)"],
                borderColor: ["#3b82f6", "#f59e0b", "#10b981", "#ef4444"],
                borderWidth: 1.5
            }]
        }, {
            plugins: { legend: { display: true, position: "bottom", labels: { color: "#94a3b8", usePointStyle: true, pointStyle: "circle", padding: 15 } } }
        });

        // 4. Top deudores (bar horizontal)
        this.createOrUpdateChart("chart-top-partners", "bar", {
            labels: this.metricsData.charts.top_partners.labels.map(l => l.length > 22 ? l.substring(0, 19) + "..." : l),
            datasets: [{
                label: "Saldo",
                data: this.metricsData.charts.top_partners.values,
                backgroundColor: "rgba(139, 92, 246, 0.65)",
                borderColor: "#8b5cf6",
                borderWidth: 1.5,
                borderRadius: 4
            }]
        }, {
            indexAxis: "y",
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (ctx) => ` ${this.formatCurrency(ctx.raw)}` } }
            },
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
                y: { grid: { display: false } }
            }
        });

        // 5. Retiros por compañía
        this.createOrUpdateChart("chart-by-company", "bar", {
            labels: this.metricsData.charts.by_company.labels,
            datasets: [{
                label: "Retirado",
                data: this.metricsData.charts.by_company.values,
                backgroundColor: "rgba(16, 185, 129, 0.65)",
                borderColor: "#10b981",
                borderWidth: 1.5,
                borderRadius: 6
            }]
        }, {
            scales: {
                x: { grid: { display: false } },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } }
            }
        });
```

- [ ] **Step 5: Adaptar la plantilla `xml/dashboard.xml`**

Manteniendo intacta la estructura de sidebar, presets, toggle de tema y clases CSS:
- Cambiar el título de marca de "Invoicing Metrics" a "Cuenta Corriente" y el subtítulo a "Metrics Hub".
- Quitar del sidebar el selector "Tipo de comprobante" (`state.docType`); dejar el de empresa y la búsqueda.
- Reemplazar las tarjetas de KPI por las ocho nuevas, usando `formatCurrency` para las monetarias
  y valor plano para `withdrawal_count`, `overdue_installments` y `overdue_rate` (esta última con `%`):
  saldo total de cartera, saldo vencido, saldo a favor, total retirado, cantidad de retiros,
  cuotas vencidas, tasa de mora, cobrado en el período.
- Reemplazar los seis `<canvas>` por cinco con estos ids exactos:
  `chart-balance-trend`, `chart-collected-vs-overdue`, `chart-installment-status`,
  `chart-top-partners`, `chart-by-company`.
- Cambiar las dos pestañas de tabla: `withdrawals` (columnas número, fecha, contacto, compañía,
  total, residual, mora, estado) e `installments` (contacto, retiro, cuota, vencimiento, monto,
  imputado, residual, estado), iterando sobre `withdrawalsData.records` e `installmentsData.records`.
- La paginación pasa a llamar `loadRecords(state.activeTab)`.

- [ ] **Step 6: Registrar la acción cliente y los assets**

`checking_account_withdrawals/views/dashboard_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_caw_dashboard" model="ir.actions.client">
        <field name="name">Dashboard de Cuenta Corriente</field>
        <field name="tag">checking_account_withdrawals.dashboard</field>
    </record>
</odoo>
```

Agregar a `views/menu_views.xml` antes de `</odoo>`:
```xml
    <menuitem id="menu_caw_dashboard" name="Dashboard"
              parent="menu_caw_root" action="action_caw_dashboard" sequence="5"
              groups="checking_account_withdrawals.group_cc_manager"/>
```

En `__manifest__.py`, agregar `"views/dashboard_views.xml",` **antes** de `"views/menu_views.xml",`
y la clave `assets` después de `data`:
```python
    "assets": {
        "web.assets_backend": [
            "checking_account_withdrawals/static/src/css/dashboard.css",
            "checking_account_withdrawals/static/src/js/dashboard.js",
            "checking_account_withdrawals/static/src/xml/dashboard.xml",
        ],
    },
```

- [ ] **Step 7: Verificar en el navegador**

```bash
python3 -c "import xml.dom.minidom as m; m.parse('checking_account_withdrawals/static/src/xml/dashboard.xml')"
docker exec odoo-odoo-1 odoo -u checking_account_withdrawals -d calidad --stop-after-init --no-http
```
Después levantá Odoo normalmente, entrá a **Cuenta Corriente → Dashboard** con un usuario Manager y
verificá: los ocho KPIs traen números, los cinco gráficos dibujan, el toggle dark/light funciona,
los presets de fecha refiltran, las dos pestañas de tabla paginan y el export CSV descarga.
Sin errores en la consola del navegador.

- [ ] **Step 8: Commit**

```bash
git add checking_account_withdrawals
git commit -m "feat(checking_account_withdrawals): dashboard OWL con el estilo de account_management_metrics"
```

---

### Task 15: Ícono del módulo

**Files:**
- Create: `checking_account_withdrawals/static/description/icon.png`

**Interfaces:**
- Consumes: la plantilla `assets/cyber-glass-icon.svg` de la skill `odoo-prometeo-modules`.
- Produces: el PNG que ya referencian `menu_caw_root` (Task 11) y la lista de Apps.

- [ ] **Step 1: Generar el SVG a partir de la plantilla**

```bash
mkdir -p /home/alexis/Documents/Github/prometeo-odoo-modules/checking_account_withdrawals/static/description
cp ~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg /tmp/caw-icon.svg
```
Editá `/tmp/caw-icon.svg` y cambiá el `<text>` del glifo por `CC`. Dejá los acentos cyan
`#22e6ff` y magenta `#ff3df0` de la plantilla.

- [ ] **Step 2: Renderizar a PNG con Chrome headless**

```bash
cd /tmp
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="/home/alexis/Documents/Github/prometeo-odoo-modules/checking_account_withdrawals/static/description/icon.png" \
  "file:///tmp/caw-icon.svg"
```

**No uses ImageMagick** (`convert`/`magick`): su renderer MSVG descarta `<text>` y los gradientes
radiales, y el glifo desaparece.

- [ ] **Step 3: Verificar el PNG**

```bash
file /home/alexis/Documents/Github/prometeo-odoo-modules/checking_account_withdrawals/static/description/icon.png
```
Esperado: `PNG image data, 512 x 512`.

- [ ] **Step 4: Commit**

```bash
git add checking_account_withdrawals/static/description/icon.png
git commit -m "feat(checking_account_withdrawals): ícono Cyber-Glassmorphic del módulo"
```

---

## Verificación final

- [ ] **Suite completa verde**

Run: `docker exec odoo-odoo-1 odoo -d calidad -u checking_account_withdrawals --test-enable --test-tags /checking_account_withdrawals --stop-after-init --no-http`
Esperado: `62 tests, 0 failed, 0 error`.

- [ ] **Instalación limpia desde cero**

```bash
docker exec odoo-postgres18-1 createdb -U odoo -T template0 caw_fresh
docker exec odoo-odoo-1 odoo -i checking_account_withdrawals -d caw_fresh --stop-after-init --no-http
docker exec odoo-postgres18-1 dropdb -U odoo caw_fresh
```
Esperado: instala sin errores en una base virgen. **Nunca** ejecutes esto contra `prod`.

- [ ] **Prueba manual del requisito crítico en la UI**

Con un usuario Manager: creá un retiro de 600 en 6 cuotas, confirmá, registrá pagos que cancelen
5 cuotas y verificá en la lista de retiros que el estado sigue siendo **Pago parcial**, nunca
**Pagado**. Este es el requisito que justifica el módulo.
