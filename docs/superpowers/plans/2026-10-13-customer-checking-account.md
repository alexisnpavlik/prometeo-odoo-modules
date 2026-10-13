# customer_checking_account — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Módulo Odoo 18 `customer_checking_account` (prefijo `cca.`). Registra retiros de mercadería de cualquier contacto con DNI. Lleva recargo % por retiro, cuotas calculadas en vivo, stock descontado al confirmar y pagos con imputación FIFO automática.

**Architecture:** Fork simplificado de `checking_account_withdrawals` (`caw.`), con modelos propios y sin dependencia de `caw`. Hay un solo grupo de seguridad. Se portan de `caw` la cuenta, la imputación, el cron, el estado de cuenta PDF y el dashboard, renombrando `caw`→`cca`. El retiro, la confirmación, los pagos y las vistas se escriben nuevos.

**Tech Stack:** Odoo 18 (Python, XML views, QWeb, OWL), PostgreSQL. Tests con `TransactionCase` y `HttpCase` en el contenedor local `odoo-odoo-1`, base `test`.

**Spec:** `docs/superpowers/specs/2026-10-13-customer-checking-account-design.md`

## Global Constraints

- Ruta del módulo: `/home/alexis/Documents/Github/prometeo-odoo-modules/customer_checking_account/`. Rama: `feat/customer-checking-account`.
- Versión del manifest: `18.0.1.0.0`. `author` `"Alexis Medina"`, `website` `"alexis.medn@gmail.com"`, `license` `"LGPL-3"`, `application: True`.
- `depends`: `["base", "mail", "stock", "product", "web"]`. **No** depende de `checking_account_withdrawals`.
- Prefijo de modelos `cca.`, de campos en modelos heredados `cca_`, de xmlids `cca_`. Grupo único: `customer_checking_account.group_cca_user`.
- Precio de la línea: `product_id.list_price` (sin listas de precios).
- DNI = campo estándar `res.partner.vat`.
- Docstring en español en cada método. `_("texto %s", arg)`, nunca `%`.
- Estados del retiro: `draft`, `pending`, `partial`, `paid`, `cancel`. Estados de cuota: `pending`, `partial`, `paid`, `overdue`.
- Medios de pago: `cash` (Efectivo), `transfer` (Transferencia), `card` (Tarjeta), `other` (Otro).
- Comando de tests (todas las tareas):
  ```bash
  docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d test -i customer_checking_account -u customer_checking_account --test-enable --test-tags /customer_checking_account --stop-after-init --http-port 8079 --workers 0 2>&1 | grep -E "ERROR|FAIL|Ran |tests? |Error" | tail -30
  ```
  "PASS" significa que no aparece ninguna línea `ERROR`/`FAIL` del módulo y aparece `0 failed, 0 error(s)`. La base `test` es scratch y tiene datos residuales: los tests crean su propia compañía cuando el resultado depende de totales globales (dashboard).
- Commits terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No se pushea ni se abre PR sin pedido explícito.

## Review Focus

1. **Retiro con productos sin stock** (kiosco sin inventario cargado): confirmar no debe trabarse en el wizard de backorder/SMS. Se espera albarán `done` con stock negativo. Lo cubre `test_confirm_without_stock_validates_picking` (Task 4).
2. **Recargo 0 y 1 cuota** (caso más común): una cuota igual al subtotal y sin ValidationError de suma. Lo cubre `test_single_installment_no_surcharge` (Task 3).
3. **Cambiar líneas después de guardar el borrador por código** (sin onchange): las cuotas guardadas no quedan desfasadas del total. Lo cubre `test_write_lines_resyncs_draft_installments` (Task 3).
4. **Pago mayor a toda la deuda y luego un retiro nuevo**: el sobrante se imputa solo al confirmar. Lo cubre `test_credit_applied_on_confirm` (Task 5).
5. **Producto servicio (no almacenable)**: confirmar sin crear albarán y sin error. Lo cubre `test_confirm_service_only_no_picking` (Task 4).

---

## File Structure

```
customer_checking_account/
  __init__.py                      # models, controllers, wizards
  __manifest__.py
  models/
    __init__.py
    cca_account.py                 # cuenta por (contacto, compañía); saldos; límite (Task 2)
    cca_allocation.py              # imputación pago→cuota (Task 2)
    cca_withdrawal.py              # retiro, recargo, cuotas en vivo, confirmar/cancelar (Tasks 3-4)
    cca_withdrawal_line.py         # línea con list_price (Task 3)
    cca_installment.py             # cuota, estados, cron de vencidas (Task 3)
    cca_payment.py                 # pago directo + FIFO (Task 5)
    res_partner.py                 # saldos y smart button, sin flag de habilitación (Task 6)
    res_company.py                 # defaults de límite y tipo de albarán (Task 6)
    res_config_settings.py         # (Task 6)
  wizards/
    __init__.py
    cca_statement_wizard.py        # estado de cuenta (Task 7)
  controllers/
    __init__.py
    dashboard_controller.py        # (Task 8)
  security/security.xml            # grupo único + reglas multi-company
  security/ir.model.access.csv
  data/ir_sequence.xml
  data/ir_cron.xml
  views/cca_withdrawal_views.xml, cca_payment_views.xml, cca_account_views.xml,
        cca_installment_views.xml, cca_wizard_views.xml, res_partner_views.xml,
        res_config_settings_views.xml, dashboard_views.xml, menu_views.xml
  report/report_cca_statement.xml, report_cca_statement_templates.xml
  static/src/{css,js,xml}/dashboard.*
  static/description/icon.png
  tests/__init__.py, common.py, test_account.py, test_withdrawal.py, test_confirm.py,
        test_payment.py, test_partner.py, test_statement.py, test_dashboard_controller.py
```

---

### Task 1: Esqueleto instalable (manifest, seguridad, secuencias)

**Files:**
- Create: `customer_checking_account/__init__.py`, `__manifest__.py`, `models/__init__.py`, `wizards/__init__.py`, `controllers/__init__.py`, `security/security.xml`, `security/ir.model.access.csv`, `data/ir_sequence.xml`, `tests/__init__.py`, `tests/common.py`, `tests/test_install.py`

**Interfaces:**
- Produces: grupo `customer_checking_account.group_cca_user`; categoría `module_category_cca`; secuencias con code `cca.withdrawal` (prefijo `RC/%(year)s/`) y `cca.payment` (prefijo `RCP/%(year)s/`); clase de test `CcaCommon` con `cls.company`, `cls.partner` (con `vat="30111222"`), `cls.product` (almacenable, `list_price=100.0`), `cls.service` (servicio, `list_price=50.0`), `cls.warehouse`.

En esta tarea el manifest lista solo los archivos que existen. Cada tarea siguiente agrega sus entradas a `data` en el orden de la lista final (Task 6, Step 5).

- [ ] **Step 1: Crear los archivos base**

`customer_checking_account/__init__.py`:
```python
# -*- coding: utf-8 -*-
from . import models
from . import wizards
from . import controllers
```

`models/__init__.py`, `wizards/__init__.py`, `controllers/__init__.py`: vacíos, con solo `# -*- coding: utf-8 -*-`.

`__manifest__.py`:
```python
# -*- coding: utf-8 -*-
{
    "name": "Cuenta Corriente de Clientes",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Retiros de clientes con recargo, cuotas en vivo y pagos con imputación FIFO",
    "description": """
        Versión simplificada de checking_account_withdrawals pensada para una sola persona.

        Cualquier contacto con DNI puede retirar mercadería: no hace falta habilitarlo.
        Cada retiro define un % de recargo, la cantidad de cuotas, la fecha de la primera
        y la frecuencia; las cuotas se recalculan en pantalla mientras se cargan.

        Al confirmar se valida el albarán de salida (el stock baja en el momento). Los
        pagos se registran directo y se imputan por FIFO a la cuota más vieja; el
        sobrante queda como saldo a favor y se aplica al próximo retiro.

        No genera asientos contables ni comprobantes fiscales.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "stock", "product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": True,
}
```

`security/security.xml` (las `ir.rule` se agregan en la tarea que crea cada modelo):
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="module_category_cca" model="ir.module.category">
        <field name="name">Cuenta Corriente de Clientes</field>
        <field name="description">Retiros de clientes a cuenta corriente</field>
        <field name="sequence">21</field>
    </record>

    <record id="group_cca_user" model="res.groups">
        <field name="name">Cuenta Corriente de Clientes</field>
        <field name="category_id" ref="module_category_cca"/>
        <field name="comment">Acceso completo: retiros, pagos, límites, cancelaciones y dashboard.</field>
        <field name="users" eval="[(4, ref('base.user_admin'))]"/>
    </record>
</odoo>
```

`security/ir.model.access.csv`:
```
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
```

`data/ir_sequence.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="seq_cca_withdrawal" model="ir.sequence">
        <field name="name">Retiro de cliente</field>
        <field name="code">cca.withdrawal</field>
        <field name="prefix">RC/%(year)s/</field>
        <field name="padding">5</field>
        <field name="company_id" eval="False"/>
    </record>

    <record id="seq_cca_payment" model="ir.sequence">
        <field name="name">Pago de cliente</field>
        <field name="code">cca.payment</field>
        <field name="prefix">RCP/%(year)s/</field>
        <field name="padding">5</field>
        <field name="company_id" eval="False"/>
    </record>
</odoo>
```

- [ ] **Step 2: Fixtures y test de instalación**

`tests/common.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CcaCommon(TransactionCase):
    """Fixtures compartidos por los tests del módulo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        # main_company puede estar archivada en bases compartidas; se reactiva dentro
        # de la transacción del test (se revierte sola).
        cls.company.sudo().active = True
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.groups_id = [(4, cls.env.ref("customer_checking_account.group_cca_user").id)]
        cls.partner = cls.env["res.partner"].create({
            "name": "Cliente CCA Test",
            "vat": "30111222",
            "company_id": False,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Producto CCA Test",
            "type": "consu",
            "is_storable": True,
            "list_price": 100.0,
        })
        # is_storable puede venir True en servicios según la base: se fuerza False.
        cls.service = cls.env["product.product"].create({
            "name": "Servicio CCA Test",
            "type": "service",
            "is_storable": False,
            "list_price": 50.0,
        })
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
```

`tests/test_install.py`:
```python
# -*- coding: utf-8 -*-
from .common import CcaCommon


class TestInstall(CcaCommon):

    def test_group_and_sequences_exist(self):
        """El grupo único y las dos secuencias quedan instalados."""
        self.assertTrue(self.env.ref("customer_checking_account.group_cca_user"))
        seq = self.env["ir.sequence"]
        self.assertTrue(seq.search([("code", "=", "cca.withdrawal")]))
        self.assertTrue(seq.search([("code", "=", "cca.payment")]))
```

`tests/__init__.py`:
```python
# -*- coding: utf-8 -*-
from . import test_install
```

- [ ] **Step 3: Validar la sintaxis y correr los tests**

Run: `cd /home/alexis/Documents/Github/prometeo-odoo-modules/customer_checking_account && python3 -c "import ast;ast.parse(open('__manifest__.py').read())" && for f in security/security.xml data/ir_sequence.xml; do python3 -c "import xml.dom.minidom as m;m.parse('$f')"; done && echo OK`
Expected: `OK`

Run: el comando de tests de Global Constraints.
Expected: `0 failed, 0 error(s)` con 1 test.

- [ ] **Step 4: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): esqueleto instalable con grupo único y secuencias

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Cuenta e imputación (`cca.account`, `cca.allocation`)

**Files:**
- Create: `models/cca_account.py`, `models/cca_allocation.py`, `tests/test_account.py`
- Modify: `models/__init__.py`, `security/security.xml`, `security/ir.model.access.csv`, `tests/__init__.py`

**Interfaces:**
- Consumes: `CcaCommon` (Task 1).
- Produces:
  - `cca.account` con campos `partner_id`, `company_id`, `currency_id`, `credit_limit` (Monetary), `limit_mode` (`none`/`warn`/`block`), `active`, `withdrawal_ids`, `payment_ids`, `installment_ids`, `balance`, `overdue_balance`, `credit_balance` (stored computes).
  - `cca.account._get_or_create(partner, company) -> cca.account`.
  - `cca.allocation` con campos `payment_id`, `installment_id`, `withdrawal_id`, `partner_id`, `company_id`, `currency_id`, `date`, `amount`.

Los One2many apuntan a `cca.withdrawal`, `cca.payment` y `cca.installment`, que se crean en Tasks 3 y 5. Para que el registry cargue en esta tarea, este Step crea **stubs mínimos** de esos tres modelos. Tasks 3 y 5 los reemplazan por el archivo completo.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_account.py`:
```python
# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import CcaCommon


class TestAccount(CcaCommon):

    def test_get_or_create_is_idempotent(self):
        """La segunda llamada devuelve la misma cuenta."""
        account_model = self.env["cca.account"]
        first = account_model._get_or_create(self.partner, self.company)
        second = account_model._get_or_create(self.partner, self.company)
        self.assertEqual(first, second)

    def test_get_or_create_reactivates_archived(self):
        """Una cuenta archivada se reactiva en lugar de duplicarse."""
        account = self.env["cca.account"]._get_or_create(self.partner, self.company)
        account.active = False
        again = self.env["cca.account"]._get_or_create(self.partner, self.company)
        self.assertEqual(account, again)
        self.assertTrue(again.active)

    def test_new_account_takes_company_defaults(self):
        """La cuenta nueva toma límite y modo por defecto de la compañía."""
        self.company.cca_default_credit_limit = 5000.0
        self.company.cca_default_limit_mode = "warn"
        account = self.env["cca.account"]._get_or_create(self.partner, self.company)
        self.assertEqual(account.credit_limit, 5000.0)
        self.assertEqual(account.limit_mode, "warn")

    def test_negative_credit_limit_rejected(self):
        """El límite de crédito no puede ser negativo."""
        account = self.env["cca.account"]._get_or_create(self.partner, self.company)
        with self.assertRaises(ValidationError):
            account.credit_limit = -1
```

Agregar `from . import test_account` a `tests/__init__.py`.

`test_new_account_takes_company_defaults` usa `res.company.cca_default_credit_limit` y `cca_default_limit_mode`. Esos campos se crean en este mismo Step 3 (`res_company.py`) y Task 6 los expone en Ajustes.

- [ ] **Step 2: Correr el test y verificar que falla**

Run: el comando de tests.
Expected: ERROR `KeyError: 'cca.account'` o equivalente.

- [ ] **Step 3: Implementar**

`models/cca_account.py`. Se copia `checking_account_withdrawals/models/caw_account.py` con estos cambios:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
sed -e 's/caw\./cca./g; s/CawAccount/CcaAccount/; s/"Cuenta corriente de retiros"/"Cuenta corriente de cliente"/' \
    -e '/groups="checking_account_withdrawals.group_cc_manager",/d' \
    -e 's/"Advertencia: el Operador ve el aviso y puede continuar. "/"Advertencia: avisa y deja continuar. "/' \
    -e 's/"Bloqueo: solo un Manager puede forzar el retiro."/"Bloqueo: no deja confirmar; subí el límite y reintentá."/' \
    checking_account_withdrawals/models/caw_account.py > customer_checking_account/models/cca_account.py
```
Después, editar a mano en `cca_account.py`:
- En `_compute_balances`, cambiar `("draft", "delivered", "cancel")` por `("draft", "cancel")`.
- Reemplazar el `return self.create({...})` final de `_get_or_create` por:
```python
        return self.create({
            "partner_id": partner.id,
            "company_id": company.id,
            "credit_limit": company.cca_default_credit_limit,
            "limit_mode": company.cca_default_limit_mode or "none",
        })
```
- Verificar: `grep -n "caw\|delivered\|group_cc" customer_checking_account/models/cca_account.py` no devuelve nada.

`models/cca_allocation.py`:
```bash
sed -e 's/caw\./cca./g; s/CawAllocation/CcaAllocation/' \
    checking_account_withdrawals/models/caw_allocation.py > customer_checking_account/models/cca_allocation.py
```

`models/res_company.py`. Contiene solo lo que usa este módulo; `cca_picking_type_id` lo usa Task 4:
```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    cca_default_credit_limit = fields.Monetary(
        string="Límite de crédito por defecto",
        currency_field="currency_id",
        help="Límite que toma cada cuenta nueva. 0 = sin límite.",
    )
    cca_default_limit_mode = fields.Selection(
        selection=[("none", "Sin control"), ("warn", "Advertencia"), ("block", "Bloqueo")],
        string="Modo de límite por defecto",
        default="none",
    )
    cca_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Tipo de operación para retiros",
        domain="[('code', '=', 'outgoing'), ('company_id', '=', id)]",
        help="Vacío = salidas del almacén principal de la compañía.",
    )
```

Stubs temporales. Tasks 3 y 5 los reemplazan enteros. `models/cca_withdrawal.py`:
```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class CcaWithdrawal(models.Model):
    _name = "cca.withdrawal"
    _description = "Retiro de cliente"

    account_id = fields.Many2one("cca.account", required=True, ondelete="restrict")
    state = fields.Selection([("draft", "Borrador"), ("cancel", "Cancelado")], default="draft")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
```
`models/cca_installment.py`:
```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class CcaInstallment(models.Model):
    _name = "cca.installment"
    _description = "Cuota de retiro de cliente"

    withdrawal_id = fields.Many2one("cca.withdrawal", required=True, ondelete="cascade")
    account_id = fields.Many2one(related="withdrawal_id.account_id", store=True)
    partner_id = fields.Many2one("res.partner")
    company_id = fields.Many2one("res.company")
    currency_id = fields.Many2one("res.currency")
    sequence = fields.Integer()
    date_due = fields.Date()
    amount = fields.Monetary(currency_field="currency_id")
    amount_residual = fields.Monetary(currency_field="currency_id")
    state = fields.Selection([("pending", "Pendiente")])
    allocation_ids = fields.One2many("cca.allocation", "installment_id")
```
`models/cca_payment.py`:
```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class CcaPayment(models.Model):
    _name = "cca.payment"
    _description = "Pago de cliente"

    name = fields.Char()
    account_id = fields.Many2one("cca.account", required=True, ondelete="restrict")
    company_id = fields.Many2one(related="account_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date()
    amount = fields.Monetary(currency_field="currency_id")
    state = fields.Selection([("posted", "Registrado"), ("cancel", "Anulado")], default="posted")
    allocation_ids = fields.One2many("cca.allocation", "payment_id")
    amount_unallocated = fields.Monetary(currency_field="currency_id")
```

`models/__init__.py`:
```python
# -*- coding: utf-8 -*-
from . import res_company
from . import cca_account
from . import cca_withdrawal
from . import cca_installment
from . import cca_payment
from . import cca_allocation
```

Agregar a `security/ir.model.access.csv`:
```
access_cca_account,cca.account,model_cca_account,group_cca_user,1,1,1,1
access_cca_allocation,cca.allocation,model_cca_allocation,group_cca_user,1,1,1,1
access_cca_withdrawal,cca.withdrawal,model_cca_withdrawal,group_cca_user,1,1,1,1
access_cca_installment,cca.installment,model_cca_installment,group_cca_user,1,1,1,1
access_cca_payment,cca.payment,model_cca_payment,group_cca_user,1,1,1,1
```

Agregar a `security/security.xml`, antes de `</odoo>`, una regla por modelo con este bloque. El bloque se repite para `account`, `allocation`, `withdrawal`, `installment` y `payment`, cambiando el sufijo:
```xml
    <record id="cca_account_company_rule" model="ir.rule">
        <field name="name">cca.account: multi-compañía</field>
        <field name="model_id" ref="model_cca_account"/>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
        <field name="global" eval="True"/>
    </record>
```

`security.xml` referencia `model_cca_*`. Por eso, en el manifest, `security/security.xml` tiene que cargarse **después** de que existan los modelos. Los modelos Python ya están registrados antes de cargar `data`, así que el orden actual sirve.

- [ ] **Step 4: Correr los tests**

Run: el comando de tests.
Expected: `0 failed, 0 error(s)` (5 tests).

- [ ] **Step 5: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): cuenta corriente e imputaciones

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Retiro, líneas, recargo y cuotas en vivo

**Files:**
- Replace: `models/cca_withdrawal.py`, `models/cca_installment.py`
- Create: `models/cca_withdrawal_line.py`, `tests/test_withdrawal.py`
- Modify: `models/__init__.py` (agregar `cca_withdrawal_line` después de `cca_withdrawal`), `security/ir.model.access.csv`, `security/security.xml`, `tests/__init__.py`

**Interfaces:**
- Consumes: `cca.account._get_or_create` (Task 2).
- Produces:
  - `cca.withdrawal` con campos `name`, `account_id`, `partner_id`, `partner_vat`, `date`, `company_id`, `currency_id`, `note`, `line_ids`, `installment_ids`, `surcharge_percent` (Float), `installment_count` (Integer, default 1), `first_due_date` (Date, default hoy + 1 mes), `frequency` (`monthly`/`weekly`), `amount_untaxed`, `amount_surcharge`, `amount_total`, `amount_residual`, `state`, `is_confirmed`, `is_cancelled`, `is_overdue`, `picking_id`.
  - `cca.withdrawal._cca_installment_values() -> list[dict]` (claves `sequence`, `date_due`, `amount`, sin `withdrawal_id`).
  - `cca.withdrawal._cca_regenerate_installments() -> True`.
  - `cca.withdrawal._cca_posted_allocations() -> cca.allocation`.
  - `cca.installment` con campos `amount_allocated`, `amount_residual`, `state` y `_cron_update_overdue()`.

Diseño de las cuotas: mientras el retiro está en borrador, las cuotas se **regeneran del lado servidor** en cada `create`/`write` que toque líneas o datos de financiación. El `onchange` muestra la misma vista previa en pantalla antes de guardar. Así las cuotas guardadas nunca quedan desfasadas del total.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_withdrawal.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form

from .common import CcaCommon


class TestWithdrawal(CcaCommon):

    def _withdrawal(self, qty=3, **vals):
        """Crea un retiro en borrador con `qty` unidades del producto de prueba."""
        values = {
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": qty})],
        }
        values.update(vals)
        return self.env["cca.withdrawal"].create(values)

    def test_any_partner_gets_account(self):
        """Cualquier contacto puede retirar: la cuenta se crea sola."""
        withdrawal = self._withdrawal()
        self.assertEqual(withdrawal.account_id.partner_id, self.partner)
        self.assertTrue(withdrawal.name.startswith("RC/"))

    def test_line_price_defaults_to_list_price(self):
        """El precio de la línea sale de list_price."""
        withdrawal = self._withdrawal(qty=2)
        self.assertEqual(withdrawal.line_ids.price_unit, 100.0)
        self.assertEqual(withdrawal.amount_untaxed, 200.0)

    def test_surcharge_applied_to_total(self):
        """El recargo % se suma al subtotal."""
        withdrawal = self._withdrawal(qty=3, surcharge_percent=10.0)
        self.assertEqual(withdrawal.amount_untaxed, 300.0)
        self.assertEqual(withdrawal.amount_surcharge, 30.0)
        self.assertEqual(withdrawal.amount_total, 330.0)

    def test_single_installment_no_surcharge(self):
        """Caso común: sin recargo y 1 cuota, la cuota es igual al subtotal."""
        withdrawal = self._withdrawal(qty=1)
        self.assertEqual(len(withdrawal.installment_ids), 1)
        self.assertEqual(withdrawal.installment_ids.amount, 100.0)
        self.assertEqual(withdrawal.installment_ids.date_due, date(2027, 2, 15))

    def test_last_installment_absorbs_rounding(self):
        """100 en 3 cuotas: 33.33, 33.33, 33.34."""
        withdrawal = self._withdrawal(qty=1, installment_count=3)
        amounts = withdrawal.installment_ids.sorted("sequence").mapped("amount")
        self.assertEqual(amounts, [33.33, 33.33, 33.34])
        self.assertAlmostEqual(sum(amounts), withdrawal.amount_total)

    def test_monthly_and_weekly_due_dates(self):
        """Los vencimientos avanzan por mes o por semana desde la primera fecha."""
        monthly = self._withdrawal(installment_count=3)
        self.assertEqual(
            monthly.installment_ids.sorted("sequence").mapped("date_due"),
            [date(2027, 2, 15), date(2027, 3, 15), date(2027, 4, 15)],
        )
        weekly = self._withdrawal(installment_count=2, frequency="weekly")
        self.assertEqual(
            weekly.installment_ids.sorted("sequence").mapped("date_due"),
            [date(2027, 2, 15), date(2027, 2, 22)],
        )

    def test_write_lines_resyncs_draft_installments(self):
        """Cambiar líneas por código en borrador regenera las cuotas."""
        withdrawal = self._withdrawal(qty=1, installment_count=2)
        withdrawal.write({"line_ids": [(1, withdrawal.line_ids.id, {"quantity": 4})]})
        self.assertEqual(sum(withdrawal.installment_ids.mapped("amount")), 400.0)

    def test_write_surcharge_resyncs_draft_installments(self):
        """Cambiar el recargo en borrador regenera las cuotas."""
        withdrawal = self._withdrawal(qty=1, installment_count=2)
        withdrawal.surcharge_percent = 20.0
        self.assertEqual(sum(withdrawal.installment_ids.mapped("amount")), 120.0)

    def test_onchange_previews_installments(self):
        """En el formulario, las cuotas se recalculan al escribir el recargo y la cantidad."""
        form = Form(self.env["cca.withdrawal"])
        form.partner_id = self.partner
        form.first_due_date = date(2027, 2, 15)
        with form.line_ids.new() as line:
            line.product_id = self.product
            line.quantity = 2
        form.surcharge_percent = 50.0
        form.installment_count = 4
        self.assertEqual(form.amount_total, 300.0)
        self.assertEqual(len(form.installment_ids), 4)
        self.assertEqual(form.installment_ids.edit(0).amount, 75.0)

    def test_negative_surcharge_rejected(self):
        """El recargo no puede ser negativo."""
        with self.assertRaises(ValidationError):
            self._withdrawal(surcharge_percent=-5.0)

    def test_zero_installments_rejected(self):
        """La cantidad de cuotas tiene que ser al menos 1."""
        with self.assertRaises(ValidationError):
            self._withdrawal(installment_count=0)

    def test_default_first_due_date_is_next_month(self):
        """Sin fecha explícita, la primera cuota vence en un mes."""
        withdrawal = self.env["cca.withdrawal"].create({"partner_id": self.partner.id})
        today = withdrawal.date
        self.assertEqual(withdrawal.first_due_date, today + relativedelta(months=1))

    def test_unlink_only_draft_or_cancel(self):
        """Un retiro en borrador se puede borrar."""
        withdrawal = self._withdrawal()
        withdrawal.unlink()
        self.assertFalse(withdrawal.exists())
```

Agregar `from . import test_withdrawal` a `tests/__init__.py`.

- [ ] **Step 2: Correr y verificar que fallan**

Run: el comando de tests.
Expected: fallan con `ValueError: Invalid field 'line_ids'` o equivalente.

- [ ] **Step 3: Implementar `cca_withdrawal_line.py`**

```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CcaWithdrawalLine(models.Model):
    _name = "cca.withdrawal.line"
    _description = "Línea de retiro de cliente"
    _order = "withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="cca.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="withdrawal_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto",
        required=True,
        domain="[('sale_ok', '=', True)]",
    )
    name = fields.Char(string="Descripción")
    quantity = fields.Float(string="Cantidad", default=1.0, digits="Product Unit of Measure")
    price_unit = fields.Float(
        string="Precio unitario",
        digits="Product Price",
        compute="_compute_price_unit",
        store=True,
        readonly=False,
        precompute=True,
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
        currency_field="currency_id",
    )

    @api.depends("product_id")
    def _compute_price_unit(self):
        """Precio de venta del producto (list_price). Editable mientras el retiro esté en borrador."""
        for line in self:
            line.price_unit = line.product_id.list_price if line.product_id else 0.0

    @api.depends("quantity", "price_unit")
    def _compute_price_subtotal(self):
        """Subtotal sin recargo: cantidad por precio."""
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Propone la descripción del producto."""
        if self.product_id:
            self.name = self.product_id.display_name

    @api.constrains("quantity", "price_unit")
    def _check_values(self):
        """Cantidad positiva y precio no negativo."""
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("La cantidad debe ser mayor a cero."))
            if line.price_unit < 0:
                raise ValidationError(_("El precio no puede ser negativo."))
```

- [ ] **Step 4: Implementar `cca_installment.py` (reemplaza el stub)**

Copiar desde `caw`:
```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
sed -e 's/caw\./cca./g; s/CawInstallment/CcaInstallment/; s/caw_skip_total_check/cca_skip_total_check/g' \
    -e 's/"Cuota de retiro de cuenta corriente"/"Cuota de retiro de cliente"/' \
    -e 's/("draft", "delivered", "cancel")/("draft", "cancel")/' \
    checking_account_withdrawals/models/caw_installment.py > customer_checking_account/models/cca_installment.py
```
Edición manual: el constraint `_check_total_matches_withdrawal` solo tiene que aplicar a retiros confirmados. En borrador las cuotas se regeneran en bloque y el chequeo no aporta. Reemplazar su primera línea de lógica por:
```python
        if self.env.context.get("cca_skip_total_check"):
            return
        for withdrawal in self.mapped("withdrawal_id").filtered("is_confirmed"):
```
Verificar: `grep -n "caw\|delivered" customer_checking_account/models/cca_installment.py` no devuelve nada.

- [ ] **Step 5: Implementar `cca_withdrawal.py` (reemplaza el stub; esta tarea solo cubre la parte de borrador)**

```python
# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("pending", "Pendiente"),
    ("partial", "Pago parcial"),
    ("paid", "Pagado"),
    ("cancel", "Cancelado"),
]

# Campos cuyo cambio en borrador obliga a regenerar las cuotas.
FINANCING_FIELDS = {
    "line_ids", "surcharge_percent", "installment_count", "first_due_date", "frequency", "date",
}


class CcaWithdrawal(models.Model):
    _name = "cca.withdrawal"
    _description = "Retiro de cliente"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    account_id = fields.Many2one(
        comodel_name="cca.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    partner_vat = fields.Char(related="partner_id.vat", string="DNI", store=True, index=True)
    account_balance = fields.Monetary(
        related="account_id.balance", string="Saldo actual", currency_field="currency_id"
    )
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", string="Moneda", readonly=True)
    note = fields.Text(string="Notas")
    line_ids = fields.One2many("cca.withdrawal.line", "withdrawal_id", string="Líneas", copy=True)
    installment_ids = fields.One2many("cca.installment", "withdrawal_id", string="Cuotas")
    surcharge_percent = fields.Float(string="Recargo (%)", digits=(5, 2), tracking=True)
    installment_count = fields.Integer(string="Cuotas", default=1, required=True, tracking=True)
    first_due_date = fields.Date(
        string="Primer vencimiento",
        required=True,
        default=lambda self: fields.Date.context_today(self) + relativedelta(months=1),
        tracking=True,
    )
    frequency = fields.Selection(
        selection=[("monthly", "Mensual"), ("weekly", "Semanal")],
        string="Frecuencia",
        default="monthly",
        required=True,
    )
    amount_untaxed = fields.Monetary(
        string="Subtotal", compute="_compute_amounts", store=True, currency_field="currency_id"
    )
    amount_surcharge = fields.Monetary(
        string="Recargo", compute="_compute_amounts", store=True, currency_field="currency_id"
    )
    amount_total = fields.Monetary(
        string="Total", compute="_compute_amounts", store=True, currency_field="currency_id",
        tracking=True,
    )
    amount_residual = fields.Monetary(
        string="Saldo", compute="_compute_amount_residual", store=True, currency_field="currency_id"
    )
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
    is_confirmed = fields.Boolean(copy=False, help="Bandera interna: se levanta al confirmar.")
    is_cancelled = fields.Boolean(copy=False, help="Bandera interna: el estado computado la respeta.")
    is_overdue = fields.Boolean(
        string="Vencido", compute="_compute_is_overdue", store=True, index=True
    )
    picking_id = fields.Many2one("stock.picking", string="Albarán", readonly=True, copy=False)
    return_picking_id = fields.Many2one(
        "stock.picking", string="Devolución", readonly=True, copy=False
    )

    @api.depends("line_ids.price_subtotal", "surcharge_percent")
    def _compute_amounts(self):
        """Subtotal de líneas, recargo sobre el subtotal y total."""
        for withdrawal in self:
            currency = withdrawal.currency_id or self.env.company.currency_id
            untaxed = sum(withdrawal.line_ids.mapped("price_subtotal"))
            surcharge = currency.round(untaxed * (withdrawal.surcharge_percent or 0.0) / 100.0)
            withdrawal.amount_untaxed = untaxed
            withdrawal.amount_surcharge = surcharge
            withdrawal.amount_total = untaxed + surcharge

    @api.depends("installment_ids.amount_residual", "is_confirmed", "is_cancelled")
    def _compute_amount_residual(self):
        """Saldo del retiro: residual de sus cuotas. En borrador no hay deuda."""
        for withdrawal in self:
            withdrawal.amount_residual = (
                sum(withdrawal.installment_ids.mapped("amount_residual"))
                if withdrawal.is_confirmed and not withdrawal.is_cancelled else 0.0
            )

    @api.depends("installment_ids.state", "is_confirmed", "is_cancelled")
    def _compute_is_overdue(self):
        """Vencido: confirmado y con al menos una cuota vencida."""
        for withdrawal in self:
            withdrawal.is_overdue = bool(
                withdrawal.is_confirmed and not withdrawal.is_cancelled
                and any(i.state == "overdue" for i in withdrawal.installment_ids)
            )

    @api.depends(
        "is_cancelled", "is_confirmed", "installment_ids.state",
        "installment_ids.amount_allocated", "installment_ids.amount_residual",
    )
    def _compute_state(self):
        """Deriva el estado de las banderas y de las cuotas. Nunca se escribe a mano."""
        for withdrawal in self:
            if withdrawal.is_cancelled:
                withdrawal.state = "cancel"
                continue
            if not withdrawal.is_confirmed:
                withdrawal.state = "draft"
                continue
            installments = withdrawal.installment_ids
            residual = sum(installments.mapped("amount_residual"))
            if installments and all(i.state == "paid" for i in installments) and \
                    withdrawal.currency_id.compare_amounts(residual, 0.0) == 0:
                withdrawal.state = "paid"
            elif any(i.amount_allocated > 0 for i in installments):
                withdrawal.state = "partial"
            else:
                withdrawal.state = "pending"

    @api.constrains("surcharge_percent", "installment_count")
    def _check_financing(self):
        """Recargo no negativo y al menos una cuota."""
        for withdrawal in self:
            if withdrawal.surcharge_percent < 0:
                raise ValidationError(_("El recargo no puede ser negativo."))
            if withdrawal.installment_count < 1:
                raise ValidationError(_("La cantidad de cuotas debe ser al menos 1."))

    def _cca_due_date(self, index):
        """Vencimiento de la cuota `index` (base 0) según la frecuencia."""
        self.ensure_one()
        step = relativedelta(weeks=index) if self.frequency == "weekly" else relativedelta(months=index)
        return self.first_due_date + step

    def _cca_installment_values(self):
        """Valores de las cuotas a partir del total. El resto del redondeo va a la última."""
        self.ensure_one()
        count = max(self.installment_count, 1)
        currency = self.currency_id or self.env.company.currency_id
        total = self.amount_total
        if currency.compare_amounts(total, 0.0) <= 0 or not self.first_due_date:
            return []
        base = currency.round(total / count)
        values, accumulated = [], 0.0
        for index in range(count):
            amount = currency.round(total - accumulated) if index == count - 1 else base
            accumulated += amount
            values.append({
                "sequence": index + 1,
                "date_due": self._cca_due_date(index),
                "amount": amount,
            })
        return values

    def _cca_regenerate_installments(self):
        """Borra y vuelve a crear las cuotas de retiros en borrador."""
        installment_model = self.env["cca.installment"].sudo()
        for withdrawal in self.filtered(lambda w: not w.is_confirmed and not w.is_cancelled):
            withdrawal.installment_ids.sudo().unlink()
            installment_model.create([
                dict(vals, withdrawal_id=withdrawal.id)
                for vals in withdrawal._cca_installment_values()
            ])
        return True

    @api.onchange("line_ids", "surcharge_percent", "installment_count", "first_due_date", "frequency")
    def _onchange_financing(self):
        """Vista previa de las cuotas mientras se carga el retiro."""
        if self.is_confirmed or self.is_cancelled:
            return
        commands = [fields.Command.clear()]
        commands += [fields.Command.create(vals) for vals in self._cca_installment_values()]
        self.installment_ids = commands

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        """Precarga la cuenta del cliente (el cliente web valida required antes de create)."""
        if self.partner_id:
            company = self.company_id or self.env.company
            self.account_id = self.env["cca.account"].sudo()._get_or_create(self.partner_id, company)
        else:
            self.account_id = False

    def _cca_posted_allocations(self):
        """Imputaciones del retiro que provienen de pagos vigentes."""
        self.ensure_one()
        return self.installment_ids.mapped("allocation_ids").filtered(
            lambda a: a.payment_id.state == "posted"
        )

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna número, resuelve la cuenta del cliente y genera las cuotas de borrador."""
        account_model = self.env["cca.account"].sudo()
        for vals in vals_list:
            if not vals.get("account_id"):
                partner = self.env["res.partner"].browse(vals.get("partner_id"))
                company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
                vals["account_id"] = account_model._get_or_create(partner, company).id
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("cca.withdrawal") or "/"
            # Las cuotas de la vista previa del onchange se descartan: se regeneran abajo.
            vals.pop("installment_ids", None)
        withdrawals = super().create(vals_list)
        withdrawals._cca_regenerate_installments()
        return withdrawals

    def write(self, vals):
        """Bloquea líneas fuera de borrador y resincroniza las cuotas en borrador."""
        if "line_ids" in vals and any(w.is_confirmed or w.is_cancelled for w in self):
            raise UserError(_("No se pueden modificar las líneas de un retiro confirmado o cancelado."))
        if FINANCING_FIELDS & set(vals) and any(w.is_confirmed for w in self):
            raise UserError(_("No se puede cambiar la financiación de un retiro confirmado."))
        if not any(w.is_confirmed for w in self):
            vals.pop("installment_ids", None)
        res = super().write(vals)
        if FINANCING_FIELDS & set(vals):
            self._cca_regenerate_installments()
        return res

    def unlink(self):
        """Solo se pueden borrar retiros en borrador o cancelados."""
        if any(w.state not in ("draft", "cancel") for w in self):
            raise UserError(_("Solo se pueden eliminar retiros en borrador o cancelados."))
        return super().unlink()
```

Agregar a `security/ir.model.access.csv`:
```
access_cca_withdrawal_line,cca.withdrawal.line,model_cca_withdrawal_line,group_cca_user,1,1,1,1
```
Agregar la regla multi-company de `cca_withdrawal_line` a `security.xml`, con el mismo bloque que en Task 2.

- [ ] **Step 6: Correr los tests**

Run: el comando de tests.
Expected: `0 failed, 0 error(s)`. Si `test_onchange_previews_installments` falla por `installment_ids` invisible o readonly en `Form`, es esperable: todavía no hay vista. En ese caso `Form` usa la vista por defecto generada, donde el campo es editable. Si aun así falla, verificar que `Form` reciba la vista de Task 6 cuando exista, y volver a correr este test al terminar Task 6.

- [ ] **Step 7: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): retiro con recargo y cuotas recalculadas en vivo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Confirmar (DNI, límite, stock), cancelar y reabrir

**Files:**
- Modify: `models/cca_withdrawal.py` (agregar métodos al final de la clase)
- Create: `tests/test_confirm.py`
- Modify: `tests/__init__.py`

**Interfaces:**
- Consumes: `_cca_regenerate_installments`, `_cca_posted_allocations` (Task 3), `res.company.cca_picking_type_id` (Task 2).
- Produces:
  - `cca.withdrawal.action_confirm() -> True | dict`: devuelve una acción `display_notification` cuando se supera el límite en modo `warn`.
  - `cca.withdrawal.action_cancel() -> True`.
  - `cca.withdrawal.action_draft() -> True`.
  - `cca.withdrawal.action_view_picking() -> dict`.
  - Hook `cca.withdrawal._cca_after_confirm()`: no hace nada en esta tarea; Task 5 lo sobrescribe para imputar el saldo a favor.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_confirm.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError

from .common import CcaCommon


class TestConfirm(CcaCommon):

    def _withdrawal(self, product=None, qty=2, partner=None, **vals):
        """Retiro en borrador listo para confirmar."""
        values = {
            "partner_id": (partner or self.partner).id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": (product or self.product).id, "quantity": qty})],
        }
        values.update(vals)
        return self.env["cca.withdrawal"].create(values)

    def test_confirm_requires_dni(self):
        """Sin DNI en el contacto no se puede confirmar."""
        partner = self.env["res.partner"].create({"name": "Sin DNI"})
        withdrawal = self._withdrawal(partner=partner)
        with self.assertRaisesRegex(UserError, "DNI"):
            withdrawal.action_confirm()

    def test_confirm_requires_lines(self):
        """Un retiro sin líneas no se confirma."""
        withdrawal = self.env["cca.withdrawal"].create({"partner_id": self.partner.id})
        with self.assertRaises(UserError):
            withdrawal.action_confirm()

    def test_confirm_validates_picking_and_moves_state(self):
        """Confirmar deja el albarán validado y el retiro pendiente."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.picking_id.state, "done")
        self.assertEqual(withdrawal.picking_id.move_ids.quantity, 2.0)
        self.assertEqual(withdrawal.amount_residual, 200.0)

    def test_confirm_without_stock_validates_picking(self):
        """Sin stock disponible el albarán igual se valida (stock negativo)."""
        withdrawal = self._withdrawal(qty=50)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.picking_id.state, "done")

    def test_confirm_service_only_no_picking(self):
        """Solo servicios: confirma sin albarán."""
        withdrawal = self._withdrawal(product=self.service, qty=1)
        withdrawal.action_confirm()
        self.assertFalse(withdrawal.picking_id)
        self.assertEqual(withdrawal.state, "pending")

    def test_confirm_freezes_lines_and_financing(self):
        """Confirmado, no se tocan líneas ni financiación."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [(1, withdrawal.line_ids.id, {"quantity": 9})]})
        with self.assertRaises(UserError):
            withdrawal.surcharge_percent = 5.0

    def test_limit_block_raises(self):
        """Modo bloqueo: superar el límite impide confirmar."""
        withdrawal = self._withdrawal()
        withdrawal.account_id.write({"credit_limit": 100.0, "limit_mode": "block"})
        with self.assertRaisesRegex(UserError, "límite"):
            withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "draft")

    def test_limit_warn_confirms_and_notifies(self):
        """Modo advertencia: confirma y devuelve una notificación."""
        withdrawal = self._withdrawal()
        withdrawal.account_id.write({"credit_limit": 100.0, "limit_mode": "warn"})
        result = withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(result["tag"], "display_notification")

    def test_cancel_returns_stock(self):
        """Cancelar un retiro sin pagos genera y valida la devolución."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        withdrawal.action_cancel()
        self.assertEqual(withdrawal.state, "cancel")
        self.assertEqual(withdrawal.return_picking_id.state, "done")
        self.assertFalse(withdrawal.installment_ids)

    def test_draft_from_cancel_regenerates_preview(self):
        """Volver a borrador desde cancelado regenera las cuotas como vista previa."""
        withdrawal = self._withdrawal(installment_count=2)
        withdrawal.action_confirm()
        withdrawal.action_cancel()
        withdrawal.action_draft()
        self.assertEqual(withdrawal.state, "draft")
        self.assertEqual(len(withdrawal.installment_ids), 2)
        self.assertFalse(withdrawal.picking_id)

    def test_draft_only_from_cancel(self):
        """No se puede volver a borrador un retiro confirmado."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.action_draft()
```

Agregar `from . import test_confirm` a `tests/__init__.py`.

- [ ] **Step 2: Correr y verificar que fallan**

Run: el comando de tests.
Expected: `AttributeError: ... 'action_confirm'`.

- [ ] **Step 3: Implementar (agregar al final de `CcaWithdrawal`)**

```python
    def _cca_check_confirmable(self):
        """Precondiciones para confirmar: borrador, DNI, líneas y total positivo."""
        for withdrawal in self:
            if withdrawal.state != "draft":
                raise UserError(_("El retiro %s ya fue confirmado o cancelado.", withdrawal.name))
            if not withdrawal.partner_id.vat:
                raise UserError(_(
                    "Cargá el DNI de %s antes de confirmar el retiro.",
                    withdrawal.partner_id.display_name,
                ))
            if not withdrawal.line_ids:
                raise UserError(_("El retiro %s no tiene líneas.", withdrawal.name))
            if withdrawal.currency_id.compare_amounts(withdrawal.amount_total, 0.0) <= 0:
                raise UserError(_("El total del retiro %s debe ser mayor a cero.", withdrawal.name))

    def _cca_check_limit(self):
        """Saldo actual + total contra el límite. Devuelve el aviso en 'warn'; bloquea en 'block'."""
        self.ensure_one()
        account = self.account_id.sudo()
        if account.limit_mode == "none" or not account.credit_limit:
            return ""
        projected = account.balance + self.amount_total
        if self.currency_id.compare_amounts(projected, account.credit_limit) <= 0:
            return ""
        message = _(
            "El retiro deja a %(partner)s con un saldo de %(projected)s, por encima de su límite de %(limit)s.",
            partner=self.partner_id.display_name,
            projected=projected,
            limit=account.credit_limit,
        )
        if account.limit_mode == "block":
            raise UserError(_("%s\n\nSubí el límite en la cuenta del cliente y volvé a confirmar.", message))
        return message

    def _cca_picking_type(self):
        """Tipo de operación: el de la compañía o el de salidas del almacén principal."""
        self.ensure_one()
        if self.company_id.cca_picking_type_id:
            return self.company_id.cca_picking_type_id
        warehouse = self.env["stock.warehouse"].sudo().search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if not warehouse:
            raise UserError(_("No hay un almacén configurado en la compañía %s.", self.company_id.name))
        return warehouse.out_type_id

    def _cca_storable_lines(self):
        """Líneas con mercadería física. Mira `type` además de `is_storable` (ver gotcha en tests)."""
        return self.line_ids.filtered(
            lambda l: l.product_id.type == "consu" and l.product_id.is_storable
        )

    def _cca_validate_picking(self, picking):
        """Valida un albarán sin diálogos: sin SMS, sin backorder, cantidades = demanda."""
        picking = picking.sudo().with_context(skip_sms=True, skip_backorder=True)
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.move_ids.picked = True
        result = picking.button_validate()
        if isinstance(result, dict) and result.get("res_model"):
            wizard_model = self.env[result["res_model"]].sudo().with_context(**(result.get("context") or {}))
            wizard = wizard_model.browse(result["res_id"]) if result.get("res_id") else wizard_model.create({})
            for method in ("process_cancel_backorder", "process"):
                if hasattr(wizard, method):
                    getattr(wizard, method)()
                    break
        if picking.state != "done":
            raise UserError(_(
                "No se pudo validar el albarán %(picking)s: quedó en estado '%(state)s'. Validalo desde Inventario.",
                picking=picking.name,
                state=picking.state,
            ))
        return True

    def _cca_create_and_validate_picking(self):
        """Crea el albarán de salida de las líneas almacenables y lo valida."""
        self.ensure_one()
        lines = self._cca_storable_lines()
        if not lines:
            _logger.info("Retiro %s sin productos almacenables: no genera albarán", self.name)
            return False
        picking_type = self._cca_picking_type()
        picking = self.env["stock.picking"].sudo().create({
            "partner_id": self.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "scheduled_date": fields.Datetime.to_datetime(self.date),
            "origin": self.name,
            "company_id": self.company_id.id,
            "move_ids": [fields.Command.create({
                "name": line.name or line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.quantity,
                "product_uom": line.product_id.uom_id.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
                "company_id": self.company_id.id,
            }) for line in lines],
        })
        picking.action_confirm()
        self._cca_validate_picking(picking)
        self.picking_id = picking.id
        return picking

    def _cca_return_picking(self):
        """Genera y valida la devolución del albarán del retiro."""
        self.ensure_one()
        picking = self.picking_id.sudo()
        wizard = self.env["stock.return.picking"].sudo().with_context(
            active_id=picking.id, active_ids=picking.ids, active_model="stock.picking"
        ).create({"picking_id": picking.id})
        for return_line in wizard.product_return_moves:
            return_line.quantity = return_line.move_id.quantity
        action = wizard.action_create_returns()
        return_picking = self.env["stock.picking"].sudo().browse(action["res_id"])
        self._cca_validate_picking(return_picking)
        self.return_picking_id = return_picking.id
        return return_picking

    def _cca_after_confirm(self):
        """Hook post-confirmación. Task 5 lo usa para imputar saldo a favor."""
        return True

    def action_confirm(self):
        """Confirma en un paso: valida, controla el límite, descuenta stock y congela las cuotas."""
        self._cca_check_confirmable()
        warnings = []
        for withdrawal in self:
            warning = withdrawal._cca_check_limit()
            withdrawal._cca_regenerate_installments()
            withdrawal._cca_create_and_validate_picking()
            withdrawal.is_confirmed = True
            withdrawal._cca_after_confirm()
            withdrawal._message_log(body=_("Retiro confirmado por %s.", self.env.user.display_name))
            if warning:
                withdrawal._message_log(body=warning)
                warnings.append(warning)
        if warnings:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Límite de crédito superado"),
                    "message": "\n".join(warnings),
                    "type": "warning",
                    "sticky": True,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return True

    def action_cancel(self):
        """Cancela: exige que no haya pagos imputados y devuelve el stock."""
        for withdrawal in self:
            if withdrawal.is_cancelled:
                raise UserError(_("El retiro %s ya está cancelado.", withdrawal.name))
            allocations = withdrawal._cca_posted_allocations()
            if allocations:
                raise UserError(_(
                    "El retiro %(name)s tiene pagos imputados por %(amount)s. Anulá esos pagos primero.",
                    name=withdrawal.name,
                    amount=sum(allocations.mapped("amount")),
                ))
            if withdrawal.picking_id and withdrawal.picking_id.state == "done":
                withdrawal._cca_return_picking()
            withdrawal.installment_ids.sudo().unlink()
            withdrawal.is_cancelled = True
            withdrawal._message_log(body=_("Retiro cancelado por %s.", self.env.user.display_name))
        return True

    def action_draft(self):
        """Reabre un retiro cancelado para corregirlo."""
        for withdrawal in self:
            if not withdrawal.is_cancelled:
                raise UserError(_("Solo se puede volver a borrador un retiro cancelado."))
            withdrawal.write({
                "is_cancelled": False,
                "is_confirmed": False,
                "picking_id": False,
                "return_picking_id": False,
            })
            withdrawal._cca_regenerate_installments()
        return True

    def action_view_picking(self):
        """Abre el albarán del retiro."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Albarán de %s", self.name),
            "res_model": "stock.picking",
            "res_id": self.picking_id.id,
            "view_mode": "form",
        }
```

Agregar a `security/ir.model.access.csv` la lectura de stock, para el botón del albarán y la devolución:
```
access_stock_picking_cca,stock.picking cca read,stock.model_stock_picking,group_cca_user,1,0,0,0
access_stock_move_cca,stock.move cca read,stock.model_stock_move,group_cca_user,1,0,0,0
access_stock_move_line_cca,stock.move.line cca read,stock.model_stock_move_line,group_cca_user,1,0,0,0
```

- [ ] **Step 4: Correr los tests**

Run: el comando de tests.
Expected: `0 failed, 0 error(s)`. Si `test_cancel_returns_stock` falla en `action_create_returns` porque devuelve otra clave, inspeccionar en el shell: `docker exec -i odoo-odoo-1 odoo shell -d test --no-http` y llamar al wizard sobre un albarán `done`. Ajustar a la clave que devuelva Odoo 18 (`res_id`), corriendo `env.cr.rollback()` al final.

- [ ] **Step 5: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): confirmar con DNI, límite y stock en un paso; cancelar con devolución

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pagos directos con FIFO, saldo a favor y cron de vencidas

**Files:**
- Replace: `models/cca_payment.py`
- Modify: `models/cca_withdrawal.py` (override de `_cca_after_confirm`)
- Create: `data/ir_cron.xml`, `tests/test_payment.py`
- Modify: `__manifest__.py` (agregar `"data/ir_cron.xml"` después de `data/ir_sequence.xml`), `tests/__init__.py`

**Interfaces:**
- Consumes: `action_confirm`, `_cca_after_confirm` (Task 4), `cca.installment._cron_update_overdue` (Task 3).
- Produces:
  - `cca.payment.create()`: deja el pago `posted` e imputa por FIFO.
  - `cca.payment._cca_allocate_fifo() -> True`.
  - `cca.payment.action_cancel() -> True`.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_payment.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError, ValidationError

from .common import CcaCommon


class TestPayment(CcaCommon):

    def _confirmed(self, qty=1, count=1, first_due=date(2027, 2, 15), **vals):
        """Retiro confirmado de `qty` × 100 en `count` cuotas."""
        withdrawal = self.env["cca.withdrawal"].create(dict({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": first_due,
            "installment_count": count,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": qty * 2})],
        }, **vals))
        withdrawal.action_confirm()
        return withdrawal

    def _pay(self, amount, account):
        """Registra un pago."""
        return self.env["cca.payment"].create({
            "account_id": account.id,
            "amount": amount,
            "date": date(2026, 2, 1),
        })

    def test_payment_posted_on_create(self):
        """El pago queda registrado sin pasos extra y con número."""
        withdrawal = self._confirmed()
        payment = self._pay(40, withdrawal.account_id)
        self.assertEqual(payment.state, "posted")
        self.assertTrue(payment.name.startswith("RCP/"))

    def test_partial_payment_fifo_oldest_first(self):
        """Un pago parcial va a la cuota más vieja del cliente."""
        older = self._confirmed(first_due=date(2027, 2, 1))
        newer = self._confirmed(first_due=date(2027, 3, 1))
        self._pay(60, older.account_id)
        self.assertEqual(older.amount_residual, 40.0)
        self.assertEqual(older.state, "partial")
        self.assertEqual(newer.amount_residual, 100.0)

    def test_payment_spans_installments(self):
        """Un pago que cubre una cuota y parte de la siguiente."""
        withdrawal = self._confirmed(qty=2, count=2)  # 2 cuotas de 100
        self._pay(150, withdrawal.account_id)
        first, second = withdrawal.installment_ids.sorted("sequence")
        self.assertEqual(first.state, "paid")
        self.assertEqual(second.amount_residual, 50.0)

    def test_full_payment_marks_paid(self):
        """Pagar todo deja el retiro pagado."""
        withdrawal = self._confirmed()
        self._pay(100, withdrawal.account_id)
        self.assertEqual(withdrawal.state, "paid")
        self.assertEqual(withdrawal.account_id.balance, 0.0)

    def test_overpayment_leaves_credit(self):
        """El sobrante queda como saldo a favor."""
        withdrawal = self._confirmed()
        payment = self._pay(130, withdrawal.account_id)
        self.assertEqual(payment.amount_unallocated, 30.0)
        self.assertEqual(withdrawal.account_id.credit_balance, 30.0)

    def test_credit_applied_on_confirm(self):
        """Al confirmar un retiro nuevo se le imputa el saldo a favor."""
        first = self._confirmed()
        self._pay(130, first.account_id)
        second = self._confirmed()
        self.assertEqual(second.amount_residual, 70.0)
        self.assertEqual(first.account_id.credit_balance, 0.0)

    def test_cancel_payment_reverts_allocations(self):
        """Anular un pago devuelve la deuda."""
        withdrawal = self._confirmed()
        payment = self._pay(100, withdrawal.account_id)
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")
        self.assertEqual(withdrawal.amount_residual, 100.0)
        self.assertEqual(withdrawal.state, "pending")

    def test_non_positive_amount_rejected(self):
        """El monto tiene que ser mayor a cero."""
        withdrawal = self._confirmed()
        with self.assertRaises(ValidationError):
            self._pay(0, withdrawal.account_id)

    def test_cannot_cancel_withdrawal_with_payments(self):
        """Un retiro con pagos imputados no se cancela."""
        withdrawal = self._confirmed()
        self._pay(10, withdrawal.account_id)
        with self.assertRaises(UserError):
            withdrawal.action_cancel()

    def test_cron_marks_overdue(self):
        """El cron marca vencida una cuota impaga con fecha pasada."""
        withdrawal = self._confirmed(first_due=date(2027, 2, 1))
        installment = withdrawal.installment_ids
        # Posterior a la fecha del retiro (2026-01-15) y anterior a hoy.
        installment.with_context(cca_skip_total_check=True).date_due = date(2026, 2, 1)
        self.env["cca.installment"]._cron_update_overdue()
        self.assertEqual(installment.state, "overdue")
        self.assertTrue(withdrawal.is_overdue)
```

El servicio cuesta 50, así que `qty * 2` unidades dan `qty × 100`. Se usa el servicio para que estos tests no dependan de stock.

Agregar `from . import test_payment` a `tests/__init__.py`.

- [ ] **Step 2: Correr y verificar que fallan**

Run: el comando de tests.
Expected: fallan con `state` `posted` faltante, `_cca_allocate_fifo` inexistente o similar.

- [ ] **Step 3: Implementar `cca_payment.py` (reemplaza el stub)**

```python
# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class CcaPayment(models.Model):
    _name = "cca.payment"
    _description = "Pago de cliente"
    _inherit = ["mail.thread"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    account_id = fields.Many2one(
        comodel_name="cca.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
    )
    partner_id = fields.Many2one(related="account_id.partner_id", store=True, index=True, string="Cliente")
    company_id = fields.Many2one(related="account_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today, index=True)
    amount = fields.Monetary(string="Monto", required=True, currency_field="currency_id")
    payment_method = fields.Selection(
        selection=[
            ("cash", "Efectivo"),
            ("transfer", "Transferencia"),
            ("card", "Tarjeta"),
            ("other", "Otro"),
        ],
        string="Medio de pago",
        default="cash",
        required=True,
    )
    ref = fields.Char(string="Referencia")
    state = fields.Selection(
        selection=[("posted", "Registrado"), ("cancel", "Anulado")],
        string="Estado",
        default="posted",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    allocation_ids = fields.One2many("cca.allocation", "payment_id", string="Imputaciones")
    amount_allocated = fields.Monetary(
        string="Imputado", compute="_compute_allocated", store=True, currency_field="currency_id"
    )
    amount_unallocated = fields.Monetary(
        string="Saldo a favor", compute="_compute_allocated", store=True, currency_field="currency_id"
    )

    @api.depends("amount", "allocation_ids.amount", "state")
    def _compute_allocated(self):
        """Imputado y remanente. Un pago anulado no deja saldo a favor."""
        for payment in self:
            allocated = sum(payment.allocation_ids.mapped("amount"))
            payment.amount_allocated = allocated
            payment.amount_unallocated = (
                max(payment.amount - allocated, 0.0) if payment.state == "posted" else 0.0
            )

    @api.constrains("amount")
    def _check_amount(self):
        """El monto debe ser mayor a cero."""
        for payment in self:
            if payment.currency_id.compare_amounts(payment.amount, 0.0) <= 0:
                raise ValidationError(_("El monto del pago debe ser mayor a cero."))

    @api.model_create_multi
    def create(self, vals_list):
        """Numera el pago y lo imputa por FIFO en el acto."""
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("cca.payment") or "/"
        payments = super().create(vals_list)
        payments._cca_allocate_fifo()
        return payments

    def _cca_open_installments(self):
        """Cuotas abiertas de la cuenta en orden FIFO: vencimiento, retiro, número."""
        self.ensure_one()
        return self.env["cca.installment"].search(
            [
                ("account_id", "=", self.account_id.id),
                ("amount_residual", ">", 0),
                ("withdrawal_id.state", "not in", ("draft", "cancel")),
            ],
            order="date_due asc, withdrawal_id asc, sequence asc",
        )

    def _cca_allocate_fifo(self):
        """Imputa el remanente de cada pago vigente a las cuotas abiertas más antiguas."""
        allocation_model = self.env["cca.allocation"].sudo()
        for payment in self.filtered(lambda p: p.state == "posted"):
            currency = payment.currency_id
            remaining = payment.amount - payment.amount_allocated
            for installment in payment._cca_open_installments():
                if currency.compare_amounts(remaining, 0.0) <= 0:
                    break
                amount = currency.round(min(remaining, installment.amount_residual))
                if currency.compare_amounts(amount, 0.0) <= 0:
                    continue
                allocation_model.create({
                    "payment_id": payment.id,
                    "installment_id": installment.id,
                    "amount": amount,
                })
                remaining -= amount
            if currency.compare_amounts(remaining, 0.0) > 0:
                _logger.info("Pago %s: %s queda como saldo a favor", payment.name, remaining)
        return True

    def action_cancel(self):
        """Anula el pago y deshace sus imputaciones."""
        for payment in self:
            if payment.state == "cancel":
                raise UserError(_("El pago %s ya está anulado.", payment.name))
            payment.allocation_ids.sudo().unlink()
            payment.state = "cancel"
            payment._message_log(body=_("Pago anulado por %s.", self.env.user.display_name))
        return True
```

- [ ] **Step 4: Imputar el saldo a favor al confirmar**

En `cca_withdrawal.py`, reemplazar el cuerpo de `_cca_after_confirm`:
```python
    def _cca_after_confirm(self):
        """Imputa al retiro recién confirmado el saldo a favor de pagos anteriores."""
        self.ensure_one()
        payments = self.env["cca.payment"].search(
            [
                ("account_id", "=", self.account_id.id),
                ("state", "=", "posted"),
                ("amount_unallocated", ">", 0),
            ],
            order="date asc, id asc",
        )
        payments._cca_allocate_fifo()
        return True
```

- [ ] **Step 5: Cron**

`data/ir_cron.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="cron_cca_update_overdue" model="ir.cron">
        <field name="name">Cuenta corriente de clientes: marcar cuotas vencidas</field>
        <field name="model_id" ref="model_cca_installment"/>
        <field name="state">code</field>
        <field name="code">model._cron_update_overdue()</field>
        <field name="interval_number">1</field>
        <field name="interval_type">days</field>
        <field name="active" eval="True"/>
    </record>
</odoo>
```

- [ ] **Step 6: Correr los tests**

Run: el comando de tests.
Expected: `0 failed, 0 error(s)`.

- [ ] **Step 7: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): pagos directos con FIFO, saldo a favor y cron de vencidas

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Contacto, ajustes, vistas y menú

**Files:**
- Create: `models/res_partner.py`, `models/res_config_settings.py`, `views/cca_withdrawal_views.xml`, `views/cca_payment_views.xml`, `views/cca_account_views.xml`, `views/cca_installment_views.xml`, `views/res_partner_views.xml`, `views/res_config_settings_views.xml`, `views/menu_views.xml`, `tests/test_partner.py`
- Modify: `models/__init__.py`, `__manifest__.py`, `tests/__init__.py`

**Interfaces:**
- Consumes: todos los modelos y acciones de Tasks 2-5.
- Produces:
  - `res.partner.cca_account_ids`, `cca_balance`, `cca_overdue_balance`, `cca_credit_balance`, `cca_withdrawal_count`.
  - `res.partner.action_cca_open_withdrawals()`.
  - Acciones de ventana `action_cca_withdrawal`, `action_cca_payment`, `action_cca_account`, `action_cca_installment`.
  - Menú raíz `menu_cca_root`, que Tasks 7 y 8 usan como padre.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_partner.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date

from .common import CcaCommon


class TestPartner(CcaCommon):

    def test_search_partner_by_dni(self):
        """El selector de cliente encuentra al contacto por DNI."""
        found = self.env["res.partner"].name_search("30111222")
        self.assertIn(self.partner.id, [pid for pid, _name in found])

    def test_display_name_shows_dni_with_context(self):
        """Con show_vat el nombre muestra el DNI."""
        name = self.partner.with_context(show_vat=True).display_name
        self.assertIn("30111222", name)

    def test_partner_balance_and_count(self):
        """El contacto muestra saldo y cantidad de retiros."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 2})],
        })
        withdrawal.action_confirm()
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.cca_balance, 100.0)
        self.assertEqual(self.partner.cca_withdrawal_count, 1)

    def test_views_load(self):
        """Las vistas principales se renderizan sin error."""
        for model in ("cca.withdrawal", "cca.payment", "cca.account", "cca.installment"):
            self.env[model].get_views([(False, "list"), (False, "form")])
```

Agregar `from . import test_partner` a `tests/__init__.py`.

`res.partner._rec_names_search` ya incluye `vat` en Odoo 18 y `show_vat` ya existe en el `_compute_display_name` de base. Si alguno de los dos tests de DNI falla, es porque la base no lo trae. En ese caso se agrega en `res_partner.py`, en Step 3:
```python
    @api.depends_context("show_vat")
    def _compute_display_name(self):
        """Agrega el DNI al nombre cuando el contexto lo pide."""
        super()._compute_display_name()
        if self.env.context.get("show_vat"):
            for partner in self.filtered("vat"):
                partner.display_name = f"{partner.display_name} ({partner.vat})"
```
Agregar este override solo si el test falla sin él, para no duplicar el DNI en el nombre.

- [ ] **Step 2: Correr y verificar que fallan**

Run: el comando de tests.
Expected: fallan los tests de `cca_balance` y de vistas. Los de búsqueda probablemente pasen; está bien.

- [ ] **Step 3: Modelos**

`models/res_partner.py`:
```python
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    cca_account_ids = fields.One2many("cca.account", "partner_id", string="Cuentas corrientes")
    cca_balance = fields.Monetary(
        string="Saldo cuenta corriente", compute="_compute_cca_amounts", currency_field="currency_id"
    )
    cca_overdue_balance = fields.Monetary(
        string="Saldo vencido", compute="_compute_cca_amounts", currency_field="currency_id"
    )
    cca_credit_balance = fields.Monetary(
        string="Saldo a favor", compute="_compute_cca_amounts", currency_field="currency_id"
    )
    cca_withdrawal_count = fields.Integer(string="Retiros", compute="_compute_cca_amounts")

    @api.depends("cca_account_ids.balance", "cca_account_ids.overdue_balance", "cca_account_ids.credit_balance")
    def _compute_cca_amounts(self):
        """Suma los saldos de las cuentas del contacto visibles al usuario."""
        withdrawal_model = self.env["cca.withdrawal"]
        for partner in self:
            accounts = partner.cca_account_ids
            partner.cca_balance = sum(accounts.mapped("balance"))
            partner.cca_overdue_balance = sum(accounts.mapped("overdue_balance"))
            partner.cca_credit_balance = sum(accounts.mapped("credit_balance"))
            partner.cca_withdrawal_count = withdrawal_model.search_count(
                [("partner_id", "=", partner.id)]
            ) if partner.id else 0

    def action_cca_open_withdrawals(self):
        """Smart button: retiros del contacto."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Retiros de %s", self.display_name),
            "res_model": "cca.withdrawal",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
```

`models/res_config_settings.py`:
```python
# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cca_default_credit_limit = fields.Monetary(
        related="company_id.cca_default_credit_limit", readonly=False, currency_field="currency_id"
    )
    cca_default_limit_mode = fields.Selection(
        related="company_id.cca_default_limit_mode", readonly=False
    )
    cca_picking_type_id = fields.Many2one(related="company_id.cca_picking_type_id", readonly=False)
```

`models/__init__.py`: agregar al final `from . import res_partner` y `from . import res_config_settings`.

- [ ] **Step 4: Vistas**

`views/cca_withdrawal_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cca_withdrawal_list" model="ir.ui.view">
        <field name="name">cca.withdrawal.list</field>
        <field name="model">cca.withdrawal</field>
        <field name="arch" type="xml">
            <list decoration-danger="is_overdue" decoration-muted="state == 'cancel'"
                  decoration-success="state == 'paid'">
                <field name="name"/>
                <field name="date"/>
                <field name="partner_id"/>
                <field name="partner_vat"/>
                <field name="amount_total" sum="Total"/>
                <field name="amount_residual" sum="Saldo"/>
                <field name="is_overdue" column_invisible="1"/>
                <field name="currency_id" column_invisible="1"/>
                <field name="state" widget="badge"
                       decoration-info="state == 'pending'" decoration-warning="state == 'partial'"
                       decoration-success="state == 'paid'"/>
            </list>
        </field>
    </record>

    <record id="view_cca_withdrawal_form" model="ir.ui.view">
        <field name="name">cca.withdrawal.form</field>
        <field name="model">cca.withdrawal</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_confirm" type="object" string="Confirmar"
                            class="btn-primary" invisible="state != 'draft'"/>
                    <button name="action_cancel" type="object" string="Cancelar"
                            invisible="state in ('draft', 'cancel')"
                            confirm="¿Cancelar el retiro? Se devuelve la mercadería al stock."/>
                    <button name="action_draft" type="object" string="Volver a borrador"
                            invisible="state != 'cancel'"/>
                    <field name="state" widget="statusbar" statusbar_visible="draft,pending,partial,paid"/>
                </header>
                <sheet>
                    <div class="oe_button_box" name="button_box">
                        <button name="action_view_picking" type="object" class="oe_stat_button"
                                icon="fa-truck" invisible="not picking_id">
                            <span>Albarán</span>
                        </button>
                    </div>
                    <widget name="web_ribbon" title="Vencido" bg_color="text-bg-danger" invisible="not is_overdue"/>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="partner_id" context="{'show_vat': True}"
                                   options="{'no_create_edit': True}"
                                   readonly="state != 'draft'"/>
                            <field name="partner_vat" readonly="1"/>
                            <field name="account_balance"/>
                            <field name="account_id" invisible="1"/>
                        </group>
                        <group>
                            <field name="date" readonly="state != 'draft'"/>
                            <field name="company_id" groups="base.group_multi_company"/>
                            <field name="currency_id" invisible="1"/>
                            <field name="is_overdue" invisible="1"/>
                            <field name="picking_id" invisible="1"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Productos" name="lines">
                            <field name="line_ids" readonly="state != 'draft'">
                                <list editable="bottom">
                                    <field name="product_id"/>
                                    <field name="name" optional="hide"/>
                                    <field name="quantity"/>
                                    <field name="price_unit"/>
                                    <field name="price_subtotal"/>
                                    <field name="currency_id" column_invisible="1"/>
                                </list>
                            </field>
                            <group>
                                <group string="Financiación" name="financing">
                                    <field name="surcharge_percent" readonly="state != 'draft'"/>
                                    <field name="installment_count" readonly="state != 'draft'"/>
                                    <field name="first_due_date" readonly="state != 'draft'"/>
                                    <field name="frequency" readonly="state != 'draft'"/>
                                </group>
                                <group class="oe_subtotal_footer" name="totals">
                                    <field name="amount_untaxed"/>
                                    <field name="amount_surcharge"/>
                                    <field name="amount_total" class="oe_subtotal_footer_separator"/>
                                    <field name="amount_residual" invisible="state == 'draft'"/>
                                </group>
                            </group>
                            <separator string="Cuotas"/>
                            <field name="installment_ids" readonly="1">
                                <list>
                                    <field name="sequence" string="Nº"/>
                                    <field name="date_due"/>
                                    <field name="amount" sum="Total"/>
                                    <field name="amount_residual" column_invisible="parent.state == 'draft'"/>
                                    <field name="state" widget="badge" column_invisible="parent.state == 'draft'"
                                           decoration-danger="state == 'overdue'"
                                           decoration-success="state == 'paid'"
                                           decoration-warning="state == 'partial'"/>
                                    <field name="currency_id" column_invisible="1"/>
                                </list>
                            </field>
                        </page>
                        <page string="Notas" name="notes">
                            <field name="note"/>
                        </page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="view_cca_withdrawal_search" model="ir.ui.view">
        <field name="name">cca.withdrawal.search</field>
        <field name="model">cca.withdrawal</field>
        <field name="arch" type="xml">
            <search>
                <field name="name"/>
                <field name="partner_id" filter_domain="['|', ('partner_id', 'ilike', self), ('partner_vat', 'ilike', self)]"/>
                <filter name="overdue" string="Vencidos" domain="[('is_overdue', '=', True)]"/>
                <filter name="unpaid" string="Impagos" domain="[('state', 'in', ('pending', 'partial'))]"/>
                <filter name="paid" string="Pagados" domain="[('state', '=', 'paid')]"/>
                <separator/>
                <filter name="draft" string="Borradores" domain="[('state', '=', 'draft')]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_partner" string="Cliente" context="{'group_by': 'partner_id'}"/>
                    <filter name="group_state" string="Estado" context="{'group_by': 'state'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_cca_withdrawal" model="ir.actions.act_window">
        <field name="name">Retiros</field>
        <field name="res_model">cca.withdrawal</field>
        <field name="view_mode">list,form</field>
        <field name="context">{'search_default_unpaid': 1}</field>
    </record>
</odoo>
```

`partner_vat` es `store=True` (Task 3), así que se puede buscar en el `filter_domain`.

`views/cca_payment_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cca_payment_list" model="ir.ui.view">
        <field name="name">cca.payment.list</field>
        <field name="model">cca.payment</field>
        <field name="arch" type="xml">
            <list decoration-muted="state == 'cancel'">
                <field name="name"/>
                <field name="date"/>
                <field name="partner_id"/>
                <field name="payment_method"/>
                <field name="amount" sum="Total"/>
                <field name="amount_unallocated" sum="Saldo a favor"/>
                <field name="currency_id" column_invisible="1"/>
                <field name="state" widget="badge" decoration-success="state == 'posted'"/>
            </list>
        </field>
    </record>

    <record id="view_cca_payment_form" model="ir.ui.view">
        <field name="name">cca.payment.form</field>
        <field name="model">cca.payment</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_cancel" type="object" string="Anular"
                            invisible="not id or state == 'cancel'"
                            confirm="¿Anular el pago? Se deshacen sus imputaciones."/>
                    <field name="state" widget="statusbar"/>
                </header>
                <sheet>
                    <div class="oe_title"><h1><field name="name" readonly="1"/></h1></div>
                    <group>
                        <group>
                            <field name="account_id" readonly="id"
                                   options="{'no_create': True}"/>
                            <field name="date" readonly="id"/>
                            <field name="ref"/>
                        </group>
                        <group>
                            <field name="amount" readonly="id"/>
                            <field name="payment_method" readonly="id"/>
                            <field name="amount_allocated" invisible="not id"/>
                            <field name="amount_unallocated" invisible="not id"/>
                            <field name="currency_id" invisible="1"/>
                        </group>
                    </group>
                    <field name="allocation_ids" readonly="1" invisible="not id">
                        <list>
                            <field name="withdrawal_id"/>
                            <field name="installment_id"/>
                            <field name="amount" sum="Total"/>
                            <field name="currency_id" column_invisible="1"/>
                        </list>
                    </field>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="action_cca_payment" model="ir.actions.act_window">
        <field name="name">Pagos</field>
        <field name="res_model">cca.payment</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

`views/cca_account_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cca_account_list" model="ir.ui.view">
        <field name="name">cca.account.list</field>
        <field name="model">cca.account</field>
        <field name="arch" type="xml">
            <list decoration-danger="overdue_balance > 0">
                <field name="partner_id"/>
                <field name="balance" sum="Total"/>
                <field name="overdue_balance" sum="Vencido"/>
                <field name="credit_balance" sum="A favor"/>
                <field name="credit_limit"/>
                <field name="limit_mode"/>
                <field name="currency_id" column_invisible="1"/>
            </list>
        </field>
    </record>

    <record id="view_cca_account_form" model="ir.ui.view">
        <field name="name">cca.account.form</field>
        <field name="model">cca.account</field>
        <field name="arch" type="xml">
            <form>
                <sheet>
                    <div class="oe_title"><h1><field name="partner_id" readonly="1"/></h1></div>
                    <group>
                        <group string="Saldos">
                            <field name="balance"/>
                            <field name="overdue_balance"/>
                            <field name="credit_balance"/>
                        </group>
                        <group string="Límite">
                            <field name="credit_limit"/>
                            <field name="limit_mode"/>
                            <field name="currency_id" invisible="1"/>
                            <field name="company_id" groups="base.group_multi_company" readonly="1"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Retiros"><field name="withdrawal_ids" readonly="1"/></page>
                        <page string="Pagos"><field name="payment_ids" readonly="1"/></page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="view_cca_account_search" model="ir.ui.view">
        <field name="name">cca.account.search</field>
        <field name="model">cca.account</field>
        <field name="arch" type="xml">
            <search>
                <field name="partner_id" filter_domain="['|', ('partner_id', 'ilike', self), ('partner_id.vat', 'ilike', self)]"/>
                <filter name="with_debt" string="Con deuda" domain="[('balance', '>', 0)]"/>
                <filter name="overdue" string="Con vencidos" domain="[('overdue_balance', '>', 0)]"/>
            </search>
        </field>
    </record>

    <record id="action_cca_account" model="ir.actions.act_window">
        <field name="name">Clientes</field>
        <field name="res_model">cca.account</field>
        <field name="view_mode">list,form</field>
        <field name="context">{'search_default_with_debt': 1}</field>
    </record>
</odoo>
```

`views/cca_installment_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cca_installment_list" model="ir.ui.view">
        <field name="name">cca.installment.list</field>
        <field name="model">cca.installment</field>
        <field name="arch" type="xml">
            <list create="0" edit="0" decoration-danger="state == 'overdue'">
                <field name="date_due"/>
                <field name="partner_id"/>
                <field name="withdrawal_id"/>
                <field name="sequence" string="Nº"/>
                <field name="amount" sum="Total"/>
                <field name="amount_residual" sum="Saldo"/>
                <field name="currency_id" column_invisible="1"/>
                <field name="state" widget="badge" decoration-danger="state == 'overdue'"
                       decoration-warning="state == 'partial'" decoration-success="state == 'paid'"/>
            </list>
        </field>
    </record>

    <record id="view_cca_installment_form" model="ir.ui.view">
        <field name="name">cca.installment.form</field>
        <field name="model">cca.installment</field>
        <field name="arch" type="xml">
            <form create="0" edit="0">
                <sheet>
                    <group>
                        <field name="withdrawal_id"/>
                        <field name="partner_id"/>
                        <field name="sequence"/>
                        <field name="date_due"/>
                        <field name="amount"/>
                        <field name="amount_allocated"/>
                        <field name="amount_residual"/>
                        <field name="state"/>
                        <field name="currency_id" invisible="1"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_cca_installment" model="ir.actions.act_window">
        <field name="name">Cuotas por cobrar</field>
        <field name="res_model">cca.installment</field>
        <field name="view_mode">list,form</field>
        <field name="domain">[('amount_residual', '>', 0), ('withdrawal_id.state', 'not in', ('draft', 'cancel'))]</field>
    </record>
</odoo>
```

`views/res_partner_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_partner_form_cca" model="ir.ui.view">
        <field name="name">res.partner.form.cca</field>
        <field name="model">res.partner</field>
        <field name="inherit_id" ref="base.view_partner_form"/>
        <field name="arch" type="xml">
            <xpath expr="//div[@name='button_box']" position="inside">
                <button name="action_cca_open_withdrawals" type="object" class="oe_stat_button"
                        icon="fa-credit-card" invisible="not cca_account_ids"
                        groups="customer_checking_account.group_cca_user">
                    <div class="o_field_widget o_stat_info">
                        <span class="o_stat_value"><field name="cca_balance" widget="monetary"/></span>
                        <span class="o_stat_text">Cuenta corriente</span>
                    </div>
                </button>
                <field name="cca_account_ids" invisible="1"/>
            </xpath>
        </field>
    </record>
</odoo>
```

`views/res_config_settings_views.xml`. La config va en su propia `<app>` de Ajustes:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cca_res_config_settings_form" model="ir.ui.view">
        <field name="name">res.config.settings.form.cca</field>
        <field name="model">res.config.settings</field>
        <field name="inherit_id" ref="base.res_config_settings_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//form" position="inside">
                <app data-string="Cuenta Corriente de Clientes" string="Cuenta Corriente de Clientes"
                     name="customer_checking_account"
                     groups="customer_checking_account.group_cca_user">
                    <block title="Límite de crédito" name="cca_limit_container">
                        <setting string="Límite por defecto"
                                 help="Límite que toma cada cliente nuevo. 0 = sin límite.">
                            <field name="cca_default_credit_limit"/>
                        </setting>
                        <setting string="Modo de límite por defecto"
                                 help="Advertencia avisa y deja seguir; Bloqueo impide confirmar.">
                            <field name="cca_default_limit_mode"/>
                        </setting>
                    </block>
                    <block title="Stock" name="cca_stock_container">
                        <setting string="Tipo de operación para retiros"
                                 help="Vacío = salidas del almacén principal.">
                            <field name="cca_picking_type_id" options="{'no_create': True}"
                                   domain="[('code', '=', 'outgoing'), ('company_id', '=', company_id)]"/>
                        </setting>
                    </block>
                </app>
            </xpath>
        </field>
    </record>
</odoo>
```

`views/menu_views.xml`. Los menús de Dashboard y Estado de cuenta se agregan en Tasks 7 y 8:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_cca_root" name="Cuenta Corriente de Clientes"
              groups="customer_checking_account.group_cca_user"
              web_icon="customer_checking_account,static/description/icon.png"
              sequence="53"/>
    <menuitem id="menu_cca_withdrawal" name="Retiros" parent="menu_cca_root"
              action="action_cca_withdrawal" sequence="10"/>
    <menuitem id="menu_cca_payment" name="Pagos" parent="menu_cca_root"
              action="action_cca_payment" sequence="20"/>
    <menuitem id="menu_cca_account" name="Clientes" parent="menu_cca_root"
              action="action_cca_account" sequence="30"/>
    <menuitem id="menu_cca_installment" name="Cuotas por cobrar" parent="menu_cca_root"
              action="action_cca_installment" sequence="40"/>
    <menuitem id="menu_cca_settings" name="Ajustes" parent="menu_cca_root"
              action="action_cca_settings" sequence="90"/>
</odoo>
```
`action_cca_settings` abre Ajustes directo en la app del módulo. Va en `menu_views.xml`, **antes** del primer `menuitem`:
```xml
    <record id="action_cca_settings" model="ir.actions.act_window">
        <field name="name">Ajustes</field>
        <field name="res_model">res.config.settings</field>
        <field name="view_mode">form</field>
        <field name="target">inline</field>
        <field name="context">{'module': 'customer_checking_account', 'bin_size': False}</field>
    </record>
```

- [ ] **Step 5: Manifest**

Lista final de `data` de esta tarea. Tasks 7 y 8 agregan sus líneas donde se indica:
```python
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "views/cca_withdrawal_views.xml",
        "views/cca_payment_views.xml",
        "views/cca_account_views.xml",
        "views/cca_installment_views.xml",
        # Task 7: "views/cca_wizard_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        # Task 8: "views/dashboard_views.xml",
        "views/menu_views.xml",
        # Task 7: "report/report_cca_statement.xml", "report/report_cca_statement_templates.xml",
    ],
```
No dejar los comentarios: cada tarea agrega la línea real.

El menú raíz referencia `static/description/icon.png`. Crearlo en esta tarea copiando el de `caw` como provisorio: `cp checking_account_withdrawals/static/description/icon.png customer_checking_account/static/description/icon.png`. Task 9 genera el definitivo.

- [ ] **Step 6: Correr los tests y validar el XML**

Run: `cd customer_checking_account && for f in views/*.xml; do python3 -c "import xml.dom.minidom as m;m.parse('$f')" || echo "BAD $f"; done`
Expected: sin `BAD`.

Run: el comando de tests.
Expected: `0 failed, 0 error(s)`, incluido `test_onchange_previews_installments` de Task 3 contra la vista real.

- [ ] **Step 7: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): vistas, menú, ajustes y smart button en el contacto

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Estado de cuenta en PDF

**Files:**
- Create: `wizards/cca_statement_wizard.py`, `views/cca_wizard_views.xml`, `report/report_cca_statement.xml`, `report/report_cca_statement_templates.xml`, `tests/test_statement.py`
- Modify: `wizards/__init__.py`, `security/ir.model.access.csv`, `views/menu_views.xml`, `views/cca_account_views.xml`, `__manifest__.py`, `tests/__init__.py`

**Interfaces:**
- Consumes: modelos de Tasks 2-5 y `menu_cca_root` (Task 6).
- Produces: `cca.statement.wizard` con `account_id` y `date_to`, `_cca_statement_data() -> dict` y `action_print()`. Reporte `customer_checking_account.action_report_cca_statement`.

El estado de cuenta usa saldo **a una fecha** (`date_to`), como en `caw`, y no un rango. Es la forma en que se lo muestra a un cliente: "a hoy debés X". La spec dice "rango de fechas"; esta decisión simplifica y se informa al usuario en el handoff.

- [ ] **Step 1: Test que falla**

`tests/test_statement.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date

from .common import CcaCommon


class TestStatement(CcaCommon):

    def test_statement_data_and_pdf(self):
        """El estado de cuenta suma retiros y pagos a la fecha y renderiza el PDF."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 4})],
        })
        withdrawal.action_confirm()
        self.env["cca.payment"].create({
            "account_id": withdrawal.account_id.id, "amount": 50, "date": date(2026, 2, 1),
        })
        wizard = self.env["cca.statement.wizard"].create({
            "account_id": withdrawal.account_id.id, "date_to": date(2027, 3, 1),
        })
        data = wizard._cca_statement_data()
        self.assertEqual(data["total_withdrawn"], 200.0)
        self.assertEqual(data["total_paid"], 50.0)
        self.assertEqual(data["balance"], 150.0)
        pdf, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "customer_checking_account.action_report_cca_statement", wizard.ids
        )
        self.assertIn(b"Cliente CCA Test", pdf)
```

Agregar `from . import test_statement` a `tests/__init__.py`.

- [ ] **Step 2: Correr y verificar que falla**

Run: el comando de tests. Expected: `KeyError: 'cca.statement.wizard'`.

- [ ] **Step 3: Portar desde `caw`**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
S='s/checking_account_withdrawals/customer_checking_account/g; s/caw\./cca./g; s/caw_/cca_/g; s/Caw/Cca/g; s/("draft", "delivered", "cancel")/("draft", "cancel")/g'
sed -e "$S" checking_account_withdrawals/wizards/caw_statement_wizard.py > customer_checking_account/wizards/cca_statement_wizard.py
sed -e "$S" checking_account_withdrawals/report/report_caw_statement.xml > customer_checking_account/report/report_cca_statement.xml
sed -e "$S" checking_account_withdrawals/report/report_caw_statement_templates.xml > customer_checking_account/report/report_cca_statement_templates.xml
sed -n '/view_caw_statement_wizard_form/,$p' checking_account_withdrawals/views/caw_wizard_views.xml | sed -e "$S" > /tmp/cca_wiz_body.xml
{ echo '<?xml version="1.0" encoding="utf-8"?>'; echo '<odoo>'; echo '    <record id="view_cca_statement_wizard_form" model="ir.ui.view">'; tail -n +2 /tmp/cca_wiz_body.xml; } > customer_checking_account/views/cca_wizard_views.xml
grep -n "caw\|delivered\|group_cc\|user_id\|pricelist\|payroll" customer_checking_account/wizards/*.py customer_checking_account/report/*.xml customer_checking_account/views/cca_wizard_views.xml
```
Expected del `grep`: ninguna salida. Por cada línea que aparezca:
- `delivered`: borrar la condición.
- `user_id`, `pricelist`, `payroll`: borrar la celda o fila del template QWeb que lo muestra.

Revisar a mano que `cca_wizard_views.xml` quede como XML válido con `python3 -c "import xml.dom.minidom as m;m.parse('customer_checking_account/views/cca_wizard_views.xml')"`.

En el template, la columna de líneas debe mostrar el recargo. Dentro del bloque que itera retiros, después del total, agregar:
```xml
<t t-if="w.amount_surcharge">
    <div class="text-muted small">Incluye recargo <t t-esc="w.surcharge_percent"/>%: <span t-field="w.amount_surcharge"/></div>
</t>
```
Usar el nombre de variable de iteración que tenga el template portado: `w`, `withdrawal` o el que corresponda. Verificar con `grep -n 't-foreach' customer_checking_account/report/report_cca_statement_templates.xml`.

`wizards/__init__.py`: `from . import cca_statement_wizard`.

`security/ir.model.access.csv`:
```
access_cca_statement_wizard,cca.statement.wizard,model_cca_statement_wizard,group_cca_user,1,1,1,1
```

Menú, en `views/menu_views.xml`:
```xml
    <menuitem id="menu_cca_statement" name="Estado de cuenta" parent="menu_cca_root"
              action="action_cca_statement_wizard" sequence="50"/>
```

Botón en el formulario de cuenta. En `view_cca_account_form`, dentro de `<form>` y antes de `<sheet>`:
```xml
                <header>
                    <button name="%(action_cca_statement_wizard)d" type="action" string="Estado de cuenta"
                            class="btn-primary" context="{'default_account_id': id}"/>
                </header>
```

Manifest: agregar `"views/cca_wizard_views.xml"` antes de `"views/res_partner_views.xml"`, y al final `"report/report_cca_statement.xml", "report/report_cca_statement_templates.xml"`. Como `cca_account_views.xml` referencia `action_cca_statement_wizard`, mover `"views/cca_wizard_views.xml"` **antes** de `"views/cca_account_views.xml"`.

- [ ] **Step 4: Correr los tests**

Run: el comando de tests. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 5: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): estado de cuenta en PDF

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Dashboard

**Files:**
- Create: `controllers/dashboard_controller.py`, `static/src/css/dashboard.css`, `static/src/js/dashboard.js`, `static/src/xml/dashboard.xml`, `views/dashboard_views.xml`, `tests/test_dashboard_controller.py`
- Modify: `controllers/__init__.py`, `views/menu_views.xml`, `__manifest__.py`, `tests/__init__.py`

**Interfaces:**
- Consumes: tablas `cca_withdrawal`, `cca_installment`, `cca_payment`, `cca_account`; grupo `group_cca_user`.
- Produces: acción cliente con tag `customer_checking_account.dashboard`. Rutas JSON: las mismas que `caw` con el prefijo de URL cambiado. Ver Step 3.

**REQUIRED SUB-SKILL:** Antes de tocar el dashboard, leer el skill `odoo-metrics-dashboard`. Tiene las reglas de scroll en el celular, header sticky, charts y presets de fecha en zona horaria AR.

- [ ] **Step 1: Portar el código**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
S='s/checking_account_withdrawals/customer_checking_account/g; s/caw_/cca_/g; s/caw\./cca./g; s/CawDashboard/CcaDashboard/g; s/Caw/Cca/g; s/group_cc_manager/group_cca_user/g; s/group_cc_user/group_cca_user/g'
sed -e "$S" checking_account_withdrawals/controllers/dashboard_controller.py > customer_checking_account/controllers/dashboard_controller.py
mkdir -p customer_checking_account/static/src/{css,js,xml}
for ext in css js xml; do sed -e "$S" checking_account_withdrawals/static/src/$ext/dashboard.$ext > customer_checking_account/static/src/$ext/dashboard.$ext; done
sed -e "$S" checking_account_withdrawals/views/dashboard_views.xml > customer_checking_account/views/dashboard_views.xml
sed -e "$S" checking_account_withdrawals/tests/test_dashboard_controller.py > customer_checking_account/tests/test_dashboard_controller.py
grep -rn "route(" customer_checking_account/controllers/dashboard_controller.py
grep -rn "caw\|Caw\|delivered\|group_cc\b\|payroll" customer_checking_account/controllers customer_checking_account/static customer_checking_account/views/dashboard_views.xml customer_checking_account/tests/test_dashboard_controller.py
```

- [ ] **Step 2: Ajustes manuales**

1. Rutas: cada `@http.route("/caw/...")` quedó como `/cca/...` gracias al `sed` de `caw_`, **salvo** que la URL use `caw/` sin guion bajo. Revisar la salida del primer `grep`. Cualquier `"/caw/` se cambia a `"/cca/` tanto en el controller como en `dashboard.js`. Si ambos módulos están instalados con la misma URL, uno pisa al otro.
2. En el controller, borrar `"delivered": "Entregado",` de `WITHDRAWAL_STATES`. Cambiar las dos apariciones de `('draft', 'delivered', 'cancel')` y `("draft", "delivered", "cancel")` por `('draft', 'cancel')` y `("draft", "cancel")`.
3. `_check_access` queda con `customer_checking_account.group_cca_user`.
4. En `dashboard.js` y `dashboard.xml`, borrar cualquier referencia a `delivered` o `payroll_deduction` que haya devuelto el segundo `grep`. En las etiquetas de medio de pago, los valores válidos son `cash`, `transfer`, `card` y `other`.
5. El segundo `grep` tiene que quedar vacío.
6. Test portado: usa `CawCommon`, que por el `sed` quedó como `CcaCommon`. Verificar que el import sea `from .common import CcaCommon`. El test original suma datos globales de la base, que es ruido conocido en bases compartidas. Para aislarlo, en el `setUpClass` del test crear una compañía nueva y usarla:
   ```python
       @classmethod
       def setUpClass(cls):
           super().setUpClass()
           cls.company = cls.env["res.company"].create({"name": "CCA Dashboard Test Co"})
           cls.env.user.company_ids = [(4, cls.company.id)]
           cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))
   ```
   Crear los retiros con `"company_id": cls.company.id`. Si el test portado arma sus datos con helpers que llaman `action_deliver`, `action_open_confirm_wizard`, `caw_plan` o `caw_force_limit`, reemplazarlos por `create` + `action_confirm()` del flujo nuevo, y los pagos por `cca.payment.create` sin `action_post`. Borrar los asserts sobre estados `delivered`.

`controllers/__init__.py`: `from . import dashboard_controller`.

Menú, en `views/menu_views.xml`:
```xml
    <menuitem id="menu_cca_dashboard" name="Dashboard" parent="menu_cca_root"
              action="action_cca_dashboard" sequence="5"/>
```
El `id` de la acción portada en `dashboard_views.xml` tiene que ser `action_cca_dashboard`; el `sed` lo deja así.

Manifest: agregar `"views/dashboard_views.xml"` antes de `"views/menu_views.xml"`, y:
```python
    "assets": {
        "web.assets_backend": [
            "customer_checking_account/static/src/css/dashboard.css",
            "customer_checking_account/static/src/js/dashboard.js",
            "customer_checking_account/static/src/xml/dashboard.xml",
        ],
    },
```

`tests/__init__.py`: `from . import test_dashboard_controller`.

- [ ] **Step 3: Correr los tests**

Run: el comando de tests.
Expected: `0 failed, 0 error(s)`. El test del controlador es `HttpCase`, por eso el comando usa `--workers 0 --http-port 8079`.

- [ ] **Step 4: Commit**

```bash
git add customer_checking_account
git commit -m "feat(cca): dashboard portado de caw

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Ícono, verificación en navegador y nota del vault

**Files:**
- Create: `customer_checking_account/static/description/icon.png` (reemplaza el provisorio), `/home/alexis/ObsidianVault/02-Prometeo/01-Odoo/Modulos/customer_checking_account.md`
- Modify: MOC `/home/alexis/ObsidianVault/02-Prometeo/01-Odoo/Modulos/Modulos.md`

- [ ] **Step 1: Ícono**

Seguir el skill `odoo-prometeo-modules`, sección "Module Icon": copiar `assets/cyber-glass-icon.svg` del skill, glifo `C`, acentos `#22e6ff`/`#ffb020`. Renderizar con:
```bash
google-chrome-stable --headless --disable-gpu --no-sandbox --default-background-color=00000000 \
  --window-size=512,512 --screenshot="customer_checking_account/static/description/icon.png" "file://$PWD/icon.svg"
```
Borrar el `icon.svg` temporal. Ver el PNG con Read para confirmar que se ven el glifo y el halo.

- [ ] **Step 2: Suite completa**

Run: el comando de tests.
Expected: `0 failed, 0 error(s)` con todas las clases (`TestInstall`, `TestAccount`, `TestWithdrawal`, `TestConfirm`, `TestPayment`, `TestPartner`, `TestStatement` y el test del dashboard).

- [ ] **Step 3: Verificación manual en el navegador (base `test`)**

1. `docker restart odoo-odoo-1`. Esperar ~30 s.
2. Abrir `http://localhost:8069/odoo?db=test` → app **Cuenta Corriente de Clientes** → Retiros → Nuevo.
3. Elegir cliente escribiendo el DNI. Agregar 2 productos. Poner recargo 10 % y 3 cuotas. Verificar que **la tabla de cuotas cambie en vivo** al tipear y que los montos sumen el total.
4. Confirmar y verificar el albarán `done`.
5. Registrar un pago parcial y verificar la cuota parcial.
6. Abrir el Dashboard en ancho de celular (DevTools 390px) y verificar que haga scroll.

Usar el skill `anthropic-skills:chrome-browser` para manejar el navegador y grabar un GIF del paso 3.

- [ ] **Step 4: Nota del vault**

`/home/alexis/ObsidianVault/02-Prometeo/01-Odoo/Modulos/customer_checking_account.md`:
```markdown
---
tags: [subsistema/cuenta-corriente, odoo, modulo, propio, stock]
aliases: [cca, cuenta corriente clientes]
---

# customer_checking_account (Cuenta Corriente de Clientes)

> 📁 **Carpeta:** [[Modulos]] | 🏠 [[00-Inicio]]

Retiros de mercadería de cualquier cliente con DNI, con recargo % por retiro, cuotas calculadas en vivo y pagos con imputación FIFO. Pensado para la base `kiosco`, operado por una sola persona.

- **Depende de:** `stock`, `product`, `mail`. No depende de `checking_account_withdrawals`; conviven.
- **Precio:** `list_price` del producto, sin listas de precios. En mega-erp `list_price` es basura ($0.01): no usar este módulo ahí sin agregar lista de precios.
- **Cuotas:** en borrador se regeneran del lado servidor en cada write de líneas o financiación; el onchange es solo vista previa. La última cuota absorbe el redondeo.
- **Stock:** el albarán se crea y se valida al confirmar (sudo, sin SMS ni backorder). Cancelar genera y valida la devolución.
- **Pagos:** se registran directo (sin borrador) y se imputan FIFO. El sobrante queda como saldo a favor y se aplica en `_cca_after_confirm` del próximo retiro.
- **Seguridad:** un solo grupo `group_cca_user`; reglas multi-company globales.
- **Gotchas:** el dashboard y el estado de cuenta se portaron de `caw` con `sed`; si se corrige un bug en uno, revisar el otro.

## Ver también
- [[checking_account_withdrawals]]: hermano para equipos con roles Operador/Manager, habilitación por contacto y lista de precios.
```

Agregar `- [[customer_checking_account]]` en el MOC `Modulos.md`, bajo `## #subsistema/cuenta-corriente`, en orden alfabético. Commit en el repo del vault:
```bash
cd /home/alexis/ObsidianVault && git add -A 02-Prometeo/01-Odoo/Modulos && git commit -m "nota: customer_checking_account"
```

- [ ] **Step 5: Commit del módulo**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
git add customer_checking_account
git commit -m "feat(cca): ícono definitivo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

El deploy a `kiosco` no forma parte de este plan: entra por PR, y Alexis decide cuándo instalarlo.
