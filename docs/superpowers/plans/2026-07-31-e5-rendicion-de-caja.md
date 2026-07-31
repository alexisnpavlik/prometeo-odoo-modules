# Rendición de Caja (E5) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el sistema controle el efectivo que maneja cada cobrador: cuánto debe entregar, cuánto entregó, y qué diferencia quedó.

**Architecture:** Un modelo nuevo `cvi.settlement` (rendición) que agrupa los cobros no rendidos de un cobrador hasta el cierre de un período configurable, calcula el esperado, registra lo entregado y deriva la diferencia. Los cobros ya rendidos quedan marcados con `settlement_id`, lo que los vuelve inmutables. La aprobación es del administrador.

**Tech Stack:** Odoo 18.0 Community, Python 3.12, PostgreSQL 18, `dateutil.relativedelta`, framework de tests `odoo.tests.common.TransactionCase`.

## Contexto: lo que ya existe

Este plan extiende el módulo `collections_from_vendors_installments`, cuyo MVP ya está en producción en la rama `new-muebles`. Antes de tocar nada, entendé estas piezas:

- **`cvi.payment`** — el cobro. Campos relevantes: `name`, `card_id`, `partner_id`, `date` (Date), `amount` (Monetary), `user_id` (quién cobró), `is_commission` (la primera cuota, que se lleva el vendedor), `state` (`draft`/`posted`/`cancel`), `company_id`, `currency_id`. Métodos: `action_post()`, `action_cancel()`, y un `unlink()` que impide borrar cualquier cobro que no esté en `draft` (RN-06).
- **`cvi.audit.mixin`** — provee `_cvi_log(body)`. **Nunca llames `message_post` directamente**: en Odoo 18 levanta `UserError` si el partner del usuario actuante no tiene email, y los cobradores de esta operación son personal de calle que habitualmente no lo tiene. El helper hace el post normal si hay email y cae a `sudo()` con `author_id` explícito si no, preservando la atribución real.
- **`cvi.wizard.mixin`** — provee `_cvi_group_domain(group_name)` para dominios de usuarios por grupo. **Nunca uses `env.ref` a secas dentro de un `domain=lambda`**: si el xmlid no resuelve, revienta el formulario entero con `ValueError` en vez de degradar.
- **Grupos** — `group_cvi_vendor`, `group_cvi_collector`, `group_cvi_manager`. El administrador implica a los otros dos; sus reglas de registro son permisivas por rol y combinan con OR, así que la regla del administrador (`[(1,'=',1)]`) gana. No es el antipatrón de grupo restringido.
- **Reglas de registro** — `cvi.card`, `cvi.installment`, `cvi.payment` y `cvi.allocation` tienen cada uno cuatro `ir.rule`: una global de empresa más vendedor/cobrador/administrador.

## Global Constraints

- Módulo: `collections_from_vendors_installments`, en `/home/alexis/Documents/Github/prometeo-odoo-modules/`. Rama de trabajo: partir de `new-muebles`.
- Prefijo de modelos: `cvi.`
- Versión de manifest: `18.0.2.0.0` (el MVP quedó en `18.0.1.0.0`; esta es la etapa 2).
- Alcance de este plan: **solo E5 — HU-18, HU-19, HU-20**. Las épicas E6 (supervisión), E7 (morosidad y recupero) y E8 (clientes problemáticos) tienen planes propios y **no** se implementan acá.
- **Decisión del cliente: períodos fijos configurables.** La frecuencia de rendición (diaria / semanal / mensual) se configura por empresa. Ver la sección "Cómo se arma el período" — resuelve el caso borde que esta decisión trae.
- **Decisión del cliente: sin concepto de zona ni ruta por ahora.** Vendrá de la geolocalización en una etapa posterior. No inventes un modelo de zona en este plan.
- Textos de UI y docstrings en español; nombres de campos, modelos y métodos en inglés snake_case.
- Traducciones estilo Odoo 18: `_("texto %s", arg)` con coma, nunca `%`.
- **Nunca llamar `message_post` directamente** — toda entrada de auditoría va por `self._cvi_log(body)`.
- **Nunca usar `env.ref` a secas dentro de un `domain=lambda`** — usar `_cvi_group_domain`.
- RN-06 sigue vigente: un cobro no se borra, solo se anula. Este plan **endurece** esa regla: un cobro ya rendido tampoco se anula sin antes reabrir la rendición.
- RN-07 sigue vigente: cada rol ve exclusivamente su propia información. Un cobrador ve sus rendiciones, el administrador todas.
- RN-08 sigue vigente: toda operación relevante queda auditada.
- `data` load order en el manifest: `security/*` primero, después `data/`, después `views/`.
- Base de datos de pruebas: `calidad`. Contenedor Odoo: `odoo-odoo-1` (docker corre sin sudo), Postgres en `odoo-postgres18-1`.
- Todo comando `odoo` dentro del contenedor requiere `--no-http` (el puerto 8069 ya está tomado).
- Odoo 18: las vistas usan `<list>`, no `<tree>`; `view_mode` usa `list`; el chatter es `<chatter/>`; `readonly`/`invisible` toman expresiones Python directas, no `attrs="{...}"`; las columnas auxiliares de lista usan `column_invisible="True"`.

---

## Cómo se arma el período — leé esto antes de codear

Elegiste períodos fijos configurables. Esa decisión trae un caso borde que este plan resuelve de una forma específica, y el implementador **no debe "simplificarla"**:

**El problema.** Si la rendición juntara los cobros cuya `date` cae entre `date_from` y `date_to`, un cobro cargado tarde — con fecha del martes pero registrado el viernes, cuando el período del martes ya se rindió — **no entraría en ninguna rendición**. Plata cobrada que el sistema nunca reclama. En una operación de cobranza en la calle, la carga tardía no es la excepción: es la norma.

**La solución.** La rendición junta los cobros del cobrador que cumplen las dos condiciones:

```python
[("user_id", "=", collector.id),
 ("state", "=", "posted"),
 ("settlement_id", "=", False),
 ("date", "<=", date_to)]
```

Es decir: **todos los cobros aún no rendidos con fecha hasta el cierre del período**, sin límite inferior. El `date_from` existe para etiquetar y mostrar el período, no para filtrar.

Consecuencias, todas deseadas:
- Ningún cobro queda huérfano. Uno con fecha vieja simplemente entra en la próxima rendición abierta.
- La rendición muestra explícitamente cuáles de sus cobros son de períodos anteriores (campo `late_payment_count`), para que el administrador vea la anomalía en vez de que quede tapada.
- `settlement_id` es la única fuente de verdad sobre qué se rindió. Las fechas son informativas.

---

## Estructura de archivos

```
collections_from_vendors_installments/
  models/
    cvi_settlement.py                  # la rendición: período, esperado, entregado, diferencia, estados
    cvi_payment.py                     # MODIFICAR: settlement_id + guarda en action_cancel
    res_company.py                     # MODIFICAR: cvi_settlement_frequency
    res_config_settings.py             # MODIFICAR: espejo del parámetro
  data/
    ir_sequence.xml                    # MODIFICAR: secuencia cvi.settlement, prefijo REND/
  security/
    security.xml                       # MODIFICAR: 4 ir.rule para cvi.settlement
    ir.model.access.csv                # MODIFICAR: filas de cvi.settlement
  views/
    cvi_settlement_views.xml           # form, list, search, acciones
    cvi_payment_views.xml              # MODIFICAR: mostrar settlement_id
    res_config_settings_views.xml      # MODIFICAR: ajuste de frecuencia
    menu_views.xml                     # MODIFICAR: menús de rendición
  tests/
    test_settlement_period.py          # cálculo del período por frecuencia
    test_settlement_collect.py         # recolección de cobros y monto esperado
    test_settlement_flow.py            # entregar, aprobar, diferencia, estados
    test_settlement_security.py        # visibilidad por rol
```

**Cómo correr los tests** (todas las tareas usan esta forma):

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR.*Test|AssertionError|post-tests|tests .*queries'
```

Odoo imprime DOS conteos. El de `post-tests` es el del módulo; el total mayor incluye tests de infraestructura at_install cuya cantidad varía entre corridas. **Guiate por `post-tests`.** La línea base al empezar este plan es **168 post-tests**.

---

## Máquina de estados de `cvi.settlement`

| Estado | Significado | Transición de salida |
|---|---|---|
| `draft` | El cobrador la está armando; los cobros todavía se pueden recalcular | `action_submit()` → `submitted` |
| `submitted` | Entregada, pendiente de aprobación del administrador | `action_approve()` → `approved`; `action_flag_difference()` → `difference`; `action_reset_draft()` → `draft` |
| `approved` | El administrador la aprobó, el dinero cuadra | — |
| `difference` | Aprobada con diferencia registrada y observación | — |

Un cobro queda inmutable (`settlement_id` seteado) desde que la rendición pasa a `submitted`. Volver a `draft` lo libera.

---

## Task 1: Parámetro de frecuencia y cálculo del período

Cubre la parte configurable de HU-18: sin frecuencia no hay período, y sin período no hay rendición.

**Files:**
- Modify: `collections_from_vendors_installments/models/res_company.py`
- Modify: `collections_from_vendors_installments/models/res_config_settings.py`
- Modify: `collections_from_vendors_installments/views/res_config_settings_views.xml`
- Create: `collections_from_vendors_installments/models/cvi_settlement.py`
- Modify: `collections_from_vendors_installments/models/__init__.py`
- Modify: `collections_from_vendors_installments/data/ir_sequence.xml`
- Modify: `collections_from_vendors_installments/security/ir.model.access.csv`
- Modify: `collections_from_vendors_installments/__manifest__.py` (versión a `18.0.2.0.0`)
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_settlement_period.py`

**Interfaces:**
- Consumes: `CviCommon` de `tests/common.py`; grupos existentes.
- Produces:
  - Campo `res.company.cvi_settlement_frequency` (Selection `daily`/`weekly`/`monthly`, default `weekly`, required).
  - Modelo `cvi.settlement` con `name` (Char, secuencia `REND/`), `collector_id` (Many2one `res.users`), `date_to` (Date, required), `date_from` (Date compute store), `frequency` (Selection, copiada de la empresa al crear), `state` (Selection), `company_id`, `currency_id`.
  - Método `cvi.settlement._cvi_period_start(date_to, frequency)` → `date`, un `@api.model` que dado el cierre y la frecuencia devuelve el inicio del período.
  - Secuencia `cvi.settlement` con prefijo `REND/`.

**Reglas del período** (fijadas acá, no negociables):
- `daily`: `date_from == date_to`.
- `weekly`: `date_from` es el lunes de la semana de `date_to`.
- `monthly`: `date_from` es el día 1 del mes de `date_to`.
- `date_from` es informativo — etiqueta el período. El filtro real de cobros usa `date <= date_to`, como explica "Cómo se arma el período".

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_settlement_period.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSettlementPeriod(CviCommon):

    def _settlement(self, **kwargs):
        """Rendición en borrador del cobrador de test."""
        vals = {"collector_id": self.collector_user.id, "date_to": "2026-03-18"}
        vals.update(kwargs)
        return self.env["cvi.settlement"].create(vals)

    def test_default_frequency_is_weekly(self):
        """Por defecto se rinde semanalmente."""
        self.assertEqual(self.company.cvi_settlement_frequency, "weekly")

    def test_settings_writes_frequency_through_to_company(self):
        """Cambiar el ajuste en Configuración escribe en la empresa."""
        settings = self.env["res.config.settings"].create({
            "cvi_settlement_frequency": "monthly",
        })
        settings.execute()
        self.assertEqual(self.company.cvi_settlement_frequency, "monthly")

    def test_sequence_is_assigned_on_create(self):
        """Al crear, la rendición recibe una referencia de la secuencia."""
        settlement = self._settlement()
        self.assertTrue(settlement.name.startswith("REND/"))

    def test_new_settlement_starts_in_draft(self):
        """Una rendición nueva arranca en borrador."""
        self.assertEqual(self._settlement().state, "draft")

    def test_frequency_copied_from_company_on_create(self):
        """La rendición congela la frecuencia vigente al crearse."""
        self.company.cvi_settlement_frequency = "monthly"
        self.assertEqual(self._settlement().frequency, "monthly")

    def test_changing_company_frequency_does_not_touch_existing(self):
        """Cambiar la frecuencia de la empresa no reescribe rendiciones ya creadas."""
        self.company.cvi_settlement_frequency = "weekly"
        settlement = self._settlement()
        self.company.cvi_settlement_frequency = "daily"
        self.assertEqual(settlement.frequency, "weekly")

    def test_daily_period_is_a_single_day(self):
        """Frecuencia diaria: el período empieza y termina el mismo día."""
        settlement = self._settlement(date_to="2026-03-18")
        settlement.frequency = "daily"
        self.assertEqual(str(settlement.date_from), "2026-03-18")

    def test_weekly_period_starts_on_monday(self):
        """Frecuencia semanal: el 18/03/2026 es miércoles, la semana arranca el lunes 16."""
        settlement = self._settlement(date_to="2026-03-18")
        settlement.frequency = "weekly"
        self.assertEqual(str(settlement.date_from), "2026-03-16")

    def test_weekly_period_on_a_monday_starts_that_same_day(self):
        """Si el cierre cae lunes, el período empieza ese mismo lunes."""
        settlement = self._settlement(date_to="2026-03-16")
        settlement.frequency = "weekly"
        self.assertEqual(str(settlement.date_from), "2026-03-16")

    def test_monthly_period_starts_on_the_first(self):
        """Frecuencia mensual: el período arranca el día 1 del mes del cierre."""
        settlement = self._settlement(date_to="2026-03-18")
        settlement.frequency = "monthly"
        self.assertEqual(str(settlement.date_from), "2026-03-01")

    def test_period_start_helper_is_callable_without_a_record(self):
        """El helper de período sirve para calcular sin tener una rendición creada."""
        start = self.env["cvi.settlement"]._cvi_period_start("2026-03-18", "weekly")
        self.assertEqual(str(start), "2026-03-16")
```

Registrar en `tests/__init__.py` agregando `from . import test_settlement_period`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSettlementPeriod \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `KeyError: 'cvi.settlement'`.

- [ ] **Step 3: Agregar el parámetro de frecuencia**

En `models/res_company.py`, agregar el campo junto a los que ya existen:

```python
    cvi_settlement_frequency = fields.Selection(
        selection=[
            ("daily", "Diaria"),
            ("weekly", "Semanal"),
            ("monthly", "Mensual"),
        ],
        string="Frecuencia de rendición",
        default="weekly",
        required=True,
        help="Cada cuánto rinde caja un cobrador. Define el período que etiqueta cada "
             "rendición; los cobros que entran son todos los no rendidos hasta el cierre.",
    )
```

En `models/res_config_settings.py`, agregar el espejo:

```python
    cvi_settlement_frequency = fields.Selection(
        related="company_id.cvi_settlement_frequency",
        readonly=False,
    )
```

En `views/res_config_settings_views.xml`, agregar dentro del bloque de Cobranza que ya existe:

```xml
                        <setting string="Frecuencia de rendición"
                                 help="Cada cuánto rinde caja un cobrador">
                            <field name="cvi_settlement_frequency"/>
                        </setting>
```

- [ ] **Step 4: Escribir el modelo `cvi.settlement`**

`collections_from_vendors_installments/models/cvi_settlement.py`:

```python
# -*- coding: utf-8 -*-
import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("submitted", "Entregada"),
    ("approved", "Aprobada"),
    ("difference", "Con diferencia"),
]

FREQUENCY_SELECTION = [
    ("daily", "Diaria"),
    ("weekly", "Semanal"),
    ("monthly", "Mensual"),
]


class CviSettlement(models.Model):
    _name = "cvi.settlement"
    _description = "Rendición de caja de un cobrador"
    _inherit = ["cvi.audit.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "date_to desc, id desc"

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
        related="company_id.currency_id", string="Moneda", readonly=True
    )
    collector_id = fields.Many2one(
        "res.users",
        string="Cobrador",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
    )
    date_to = fields.Date(
        string="Cierre del período",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        index=True,
        help="Hasta qué fecha se rinden los cobros. Entran todos los cobros no rendidos "
             "con fecha menor o igual a ésta, incluidos los de períodos anteriores.",
    )
    frequency = fields.Selection(
        selection=FREQUENCY_SELECTION,
        string="Frecuencia",
        required=True,
        default=lambda self: self.env.company.cvi_settlement_frequency,
        help="Se copia de la configuración al crear la rendición y no cambia después, "
             "para que un cambio de política no reescriba el pasado.",
    )
    date_from = fields.Date(
        string="Inicio del período",
        compute="_compute_date_from",
        store=True,
        help="Etiqueta el período. El filtro de cobros NO lo usa: entran todos los no "
             "rendidos hasta el cierre, para que una carga tardía no quede huérfana.",
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

    @api.model
    def _cvi_period_start(self, date_to, frequency):
        """Inicio del período que cierra en `date_to` según la frecuencia.

        Diaria: el mismo día. Semanal: el lunes de esa semana. Mensual: el día 1.
        """
        date_to = fields.Date.to_date(date_to)
        if frequency == "daily":
            return date_to
        if frequency == "weekly":
            return date_to - relativedelta(days=date_to.weekday())
        return date(date_to.year, date_to.month, 1)

    @api.depends("date_to", "frequency")
    def _compute_date_from(self):
        """Deriva el inicio del período del cierre y la frecuencia congelada."""
        for settlement in self:
            if settlement.date_to and settlement.frequency:
                settlement.date_from = settlement._cvi_period_start(
                    settlement.date_to, settlement.frequency
                )
            else:
                settlement.date_from = False

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia desde la secuencia al crear."""
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cvi.settlement") or _("Nuevo")
        return super().create(vals_list)
```

- [ ] **Step 5: Registrar el modelo, la secuencia y los accesos**

`models/__init__.py` — agregar `cvi_settlement` después de `cvi_allocation`:

```python
from . import cvi_settlement
```

`data/ir_sequence.xml` — agregar dentro del `<odoo>` existente:

```xml
    <record id="seq_cvi_settlement" model="ir.sequence">
        <field name="name">Rendición de caja</field>
        <field name="code">cvi.settlement</field>
        <field name="prefix">REND/</field>
        <field name="padding">6</field>
        <field name="company_id" eval="False"/>
    </record>
```

`security/ir.model.access.csv` — agregar. El cobrador crea y edita sus rendiciones pero no las borra; el administrador tampoco borra (una rendición es registro de dinero, igual que un cobro):

```csv
access_cvi_settlement_collector,cvi.settlement cobrador,model_cvi_settlement,collections_from_vendors_installments.group_cvi_collector,1,1,1,0
access_cvi_settlement_manager,cvi.settlement administrador,model_cvi_settlement,collections_from_vendors_installments.group_cvi_manager,1,1,1,0
```

`__manifest__.py` — subir la versión:

```python
    "version": "18.0.2.0.0",
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR.*Test|AssertionError|post-tests'
```

Esperado: sin FAIL ni AssertionError, y post-tests en 179 (168 + los 11 de esta task).

- [ ] **Step 7: Commit**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): rendición de caja con período configurable"
```

---

## Task 2: Recolección de cobros y monto esperado

Cubre HU-18: el cobrador ve cuánta plata tiene que entregar y el detalle que compone ese total.

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_settlement.py`
- Modify: `collections_from_vendors_installments/models/cvi_payment.py` (agregar `settlement_id`)
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_settlement_collect.py`

**Interfaces:**
- Consumes: `cvi.settlement` con `collector_id`, `date_to`, `state` (Task 1); `cvi.payment` con `user_id`, `date`, `amount`, `state`, `is_commission`.
- Produces:
  - Campo `cvi.payment.settlement_id` (Many2one `cvi.settlement`, readonly, copy=False, ondelete `restrict`).
  - Campo `cvi.settlement.payment_ids` (One2many inverso).
  - Campo `cvi.settlement.amount_expected` (Monetary compute store) — suma de los cobros incluidos.
  - Campo `cvi.settlement.payment_count` (Integer compute store).
  - Campo `cvi.settlement.late_payment_count` (Integer compute store) — cuántos de los cobros incluidos tienen fecha anterior a `date_from`, o sea que vienen de un período ya cerrado.
  - Método `cvi.settlement._cvi_pending_payment_domain()` → dominio de los cobros que le corresponden.
  - Método `cvi.settlement.action_collect_payments()` → engancha los cobros pendientes a la rendición en borrador.

**Reglas de recolección** (fijadas acá):
- Entran los cobros con `user_id = collector_id`, `state = 'posted'`, `settlement_id = False` y `date <= date_to`. **Sin límite inferior de fecha** — ver "Cómo se arma el período".
- Entra también el cobro de comisión si lo registró este cobrador. En la práctica la comisión la cobra el vendedor, así que no aparecerá; pero la regla se define por `user_id`, no por `is_commission`, porque quien tiene la plata en la mano es quien la rindió.
- Solo se puede recolectar en estado `draft`.
- Recolectar dos veces es idempotente: los ya enganchados no se duplican.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_settlement_collect.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSettlementCollect(CviCommon):

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650  # ~10 años, neutraliza la mora en fixtures viejos
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _pay(self, amount, date, user=None):
        """Cobro publicado sobre la tarjeta, a nombre del usuario indicado."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id,
            "amount": amount,
            "date": date,
            "user_id": (user or self.collector_user).id,
        })
        payment.action_post()
        return payment

    def _settlement(self, date_to="2026-03-18"):
        return self.env["cvi.settlement"].create({
            "collector_id": self.collector_user.id,
            "date_to": date_to,
        })

    def test_collects_posted_payments_of_the_collector(self):
        """La rendición junta los cobros publicados del cobrador (HU-18)."""
        self._pay(10000.0, "2026-02-10")
        self._pay(10000.0, "2026-03-10")
        settlement = self._settlement()
        settlement.action_collect_payments()
        self.assertEqual(settlement.payment_count, 2)

    def test_expected_amount_is_the_sum(self):
        """El monto a rendir es la suma de los cobros incluidos (HU-18)."""
        self._pay(10000.0, "2026-02-10")
        self._pay(4000.0, "2026-03-10")
        settlement = self._settlement()
        settlement.action_collect_payments()
        self.assertEqual(settlement.amount_expected, 14000.0)

    def test_payments_are_linked_back_to_the_settlement(self):
        """Cada cobro incluido queda apuntando a su rendición."""
        payment = self._pay(10000.0, "2026-02-10")
        settlement = self._settlement()
        settlement.action_collect_payments()
        self.assertEqual(payment.settlement_id, settlement)

    def test_excludes_payments_after_the_period_close(self):
        """Un cobro posterior al cierre no entra en esta rendición."""
        self._pay(10000.0, "2026-02-10")
        self._pay(9999.0, "2026-04-01")
        settlement = self._settlement(date_to="2026-03-18")
        settlement.action_collect_payments()
        self.assertEqual(settlement.amount_expected, 10000.0)

    def test_includes_late_payments_from_earlier_periods(self):
        """Un cobro viejo aún no rendido entra igual: nunca queda huérfano."""
        self._pay(10000.0, "2026-01-20")
        settlement = self._settlement(date_to="2026-03-18")
        settlement.action_collect_payments()
        self.assertEqual(settlement.amount_expected, 10000.0)

    def test_late_payments_are_counted_separately(self):
        """Los cobros de períodos anteriores se cuentan aparte, para que se vean."""
        self._pay(10000.0, "2026-01-20")   # anterior al período
        self._pay(10000.0, "2026-03-17")   # dentro del período semanal
        settlement = self._settlement(date_to="2026-03-18")
        settlement.action_collect_payments()
        self.assertEqual(settlement.payment_count, 2)
        self.assertEqual(settlement.late_payment_count, 1)

    def test_excludes_another_collectors_payments(self):
        """Cada cobrador rinde lo suyo."""
        other = self.env["res.users"].create({
            "name": "Otro Cobrador",
            "login": "cvi_collector_settle_other",
            "email": "other@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self._pay(10000.0, "2026-02-10", user=other)
        settlement = self._settlement()
        settlement.action_collect_payments()
        self.assertEqual(settlement.payment_count, 0)

    def test_excludes_cancelled_payments(self):
        """Un cobro anulado no se rinde."""
        payment = self._pay(10000.0, "2026-02-10")
        payment.action_cancel()
        settlement = self._settlement()
        settlement.action_collect_payments()
        self.assertEqual(settlement.payment_count, 0)

    def test_excludes_payments_already_settled(self):
        """Un cobro ya rendido no entra en una rendición nueva."""
        self._pay(10000.0, "2026-02-10")
        first = self._settlement(date_to="2026-02-28")
        first.action_collect_payments()
        second = self._settlement(date_to="2026-03-18")
        second.action_collect_payments()
        self.assertEqual(second.payment_count, 0)

    def test_collecting_twice_is_idempotent(self):
        """Recolectar dos veces no duplica ni suma de más."""
        self._pay(10000.0, "2026-02-10")
        settlement = self._settlement()
        settlement.action_collect_payments()
        settlement.action_collect_payments()
        self.assertEqual(settlement.payment_count, 1)
        self.assertEqual(settlement.amount_expected, 10000.0)

    def test_cannot_collect_outside_draft(self):
        """Una vez entregada, la rendición no vuelve a recolectar sola."""
        self._pay(10000.0, "2026-02-10")
        settlement = self._settlement()
        settlement.action_collect_payments()
        settlement.state = "submitted"
        with self.assertRaises(UserError):
            settlement.action_collect_payments()
```

Registrar en `tests/__init__.py` agregando `from . import test_settlement_collect`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSettlementCollect \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `AttributeError: 'cvi.settlement' object has no attribute 'action_collect_payments'`.

- [ ] **Step 3: Agregar `settlement_id` a `cvi.payment`**

En `models/cvi_payment.py`, agregar el campo después de `state`:

```python
    settlement_id = fields.Many2one(
        "cvi.settlement",
        string="Rendición",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
        help="Rendición de caja en la que este cobro fue entregado. "
             "Mientras esté vacío, el cobro sigue pendiente de rendir.",
    )
```

> `ondelete="restrict"` es deliberado: aunque nadie puede borrar una rendición (`perm_unlink=0` en todos los roles), la restricción deja el rastro en la base por si alguna vez se borra por SQL.

- [ ] **Step 4: Agregar la recolección a `cvi.settlement`**

En `models/cvi_settlement.py`, agregar el import de `UserError`:

```python
from odoo.exceptions import UserError
```

Agregar los campos después de `state`:

```python
    payment_ids = fields.One2many(
        "cvi.payment", "settlement_id", string="Cobros rendidos", readonly=True
    )
    amount_expected = fields.Monetary(
        string="A rendir",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
        help="Suma de los cobros incluidos en esta rendición.",
    )
    payment_count = fields.Integer(
        string="Cobros", compute="_compute_amounts", store=True
    )
    late_payment_count = fields.Integer(
        string="De períodos anteriores",
        compute="_compute_amounts",
        store=True,
        help="Cobros incluidos cuya fecha es anterior al inicio de este período: "
             "se cargaron tarde y se rinden ahora.",
    )
```

Y estos métodos al final de la clase:

```python
    @api.depends("payment_ids.amount", "payment_ids.date", "date_from")
    def _compute_amounts(self):
        """Resume lo que el cobrador tiene que entregar y de dónde sale (HU-18)."""
        for settlement in self:
            payments = settlement.payment_ids
            settlement.amount_expected = sum(payments.mapped("amount"))
            settlement.payment_count = len(payments)
            settlement.late_payment_count = len(
                payments.filtered(
                    lambda p: settlement.date_from and p.date < settlement.date_from
                )
            )

    def _cvi_pending_payment_domain(self):
        """Cobros que le corresponden a esta rendición.

        Sin límite inferior de fecha a propósito: un cobro cargado tarde, con fecha de
        un período ya cerrado, entra en la primera rendición abierta en vez de quedar
        huérfano. `settlement_id` es la única fuente de verdad sobre qué ya se rindió.
        """
        self.ensure_one()
        return [
            ("user_id", "=", self.collector_id.id),
            ("state", "=", "posted"),
            ("settlement_id", "=", False),
            ("date", "<=", self.date_to),
            ("company_id", "=", self.company_id.id),
        ]

    def action_collect_payments(self):
        """Engancha a la rendición todos los cobros pendientes del cobrador (HU-18)."""
        for settlement in self:
            if settlement.state != "draft":
                raise UserError(_(
                    "La rendición %(name)s ya fue entregada: no se pueden recolectar "
                    "más cobros (estado: %(state)s).",
                    name=settlement.name,
                    state=dict(STATE_SELECTION)[settlement.state],
                ))
            pending = self.env["cvi.payment"].search(
                settlement._cvi_pending_payment_domain()
            )
            if pending:
                pending.write({"settlement_id": settlement.id})
            _logger.info(
                "Rendición %s: %s cobros recolectados", settlement.name, len(pending)
            )
        return True
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR.*Test|AssertionError|post-tests'
```

Esperado: sin FAIL ni AssertionError, post-tests en 190 (179 + los 11 de esta task).

- [ ] **Step 6: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): recolección de cobros y monto a rendir"
```

---

## Task 3: Entrega, diferencia y aprobación

Cubre HU-19 (registrar la entrega y ver la diferencia) y HU-20 (aprobar o marcar con diferencia).

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_settlement.py`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_settlement_flow.py`

**Interfaces:**
- Consumes: `cvi.settlement` con `state`, `amount_expected`, `payment_ids`, `action_collect_payments` (Tasks 1 y 2); `_cvi_log` del mixin de auditoría.
- Produces, en `cvi.settlement`:
  - `amount_delivered` (Monetary) — lo que el cobrador entregó, lo carga él.
  - `amount_difference` (Monetary compute store) — `amount_delivered - amount_expected`. Negativa = falta plata.
  - `has_difference` (Boolean compute store) — si la diferencia no es cero.
  - `note` (Text) — observación del administrador.
  - `approved_by_id` (Many2one `res.users`, readonly), `approved_date` (Datetime, readonly).
  - `action_submit()` → `draft` → `submitted`, recolectando primero.
  - `action_approve()` → `submitted` → `approved`. Rechaza si hay diferencia.
  - `action_flag_difference()` → `submitted` → `difference`. Exige observación.
  - `action_reset_draft()` → `submitted` → `draft`, liberando los cobros.

**Reglas** (fijadas acá):
- `action_submit` recolecta antes de entregar, para que el esperado esté al día.
- No se entrega una rendición sin cobros: no tiene sentido rendir cero.
- `action_approve` **rechaza** si hay diferencia — para eso está `action_flag_difference`, que exige observación. Así una diferencia nunca se aprueba sin dejar rastro escrito.
- `action_reset_draft` desengancha los cobros (`settlement_id = False`), devolviéndolos al pool pendiente.
- Solo el administrador aprueba o marca diferencia. Se valida con `has_group` en el método, además del acceso por menú.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_settlement_flow.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSettlementFlow(CviCommon):

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650  # ~10 años
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()
        self.manager_user = self.env["res.users"].create({
            "name": "Administrador Rendición",
            "login": "cvi_manager_settle",
            "email": "manager.settle@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_manager").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def _pay(self, amount, date="2026-02-10"):
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id,
            "amount": amount,
            "date": date,
            "user_id": self.collector_user.id,
        })
        payment.action_post()
        return payment

    def _submitted(self, collected=10000.0, delivered=10000.0):
        """Rendición entregada, con un cobro de `collected` y `delivered` entregado."""
        self._pay(collected)
        settlement = self.env["cvi.settlement"].create({
            "collector_id": self.collector_user.id,
            "date_to": "2026-03-18",
            "amount_delivered": delivered,
        })
        settlement.action_submit()
        return settlement

    def test_submit_collects_and_moves_to_submitted(self):
        """Entregar recolecta los cobros pendientes y cambia el estado (HU-19)."""
        settlement = self._submitted()
        self.assertEqual(settlement.state, "submitted")
        self.assertEqual(settlement.payment_count, 1)

    def test_difference_is_delivered_minus_expected(self):
        """El sistema calcula la diferencia contra lo esperado (HU-19)."""
        settlement = self._submitted(collected=10000.0, delivered=9500.0)
        self.assertEqual(settlement.amount_expected, 10000.0)
        self.assertEqual(settlement.amount_difference, -500.0)
        self.assertTrue(settlement.has_difference)

    def test_no_difference_when_amounts_match(self):
        """Si entregó lo que debía, no hay diferencia."""
        settlement = self._submitted(collected=10000.0, delivered=10000.0)
        self.assertEqual(settlement.amount_difference, 0.0)
        self.assertFalse(settlement.has_difference)

    def test_surplus_is_also_a_difference(self):
        """Entregar de más también es una diferencia que hay que explicar."""
        settlement = self._submitted(collected=10000.0, delivered=10500.0)
        self.assertEqual(settlement.amount_difference, 500.0)
        self.assertTrue(settlement.has_difference)

    def test_cannot_submit_without_payments(self):
        """No se rinde una caja vacía."""
        settlement = self.env["cvi.settlement"].create({
            "collector_id": self.collector_user.id,
            "date_to": "2026-03-18",
            "amount_delivered": 0.0,
        })
        with self.assertRaises(UserError):
            settlement.action_submit()

    def test_approve_moves_to_approved(self):
        """El administrador aprueba una rendición que cuadra (HU-20)."""
        settlement = self._submitted()
        settlement.with_user(self.manager_user).action_approve()
        self.assertEqual(settlement.state, "approved")

    def test_approve_records_who_and_when(self):
        """Queda registrado quién aprobó y cuándo (RN-08)."""
        settlement = self._submitted()
        settlement.with_user(self.manager_user).action_approve()
        self.assertEqual(settlement.approved_by_id, self.manager_user)
        self.assertTrue(settlement.approved_date)

    def test_approve_rejects_a_settlement_with_difference(self):
        """Una diferencia no se aprueba a secas: hay que marcarla y explicarla (HU-20)."""
        settlement = self._submitted(collected=10000.0, delivered=9500.0)
        with self.assertRaises(UserError):
            settlement.with_user(self.manager_user).action_approve()

    def test_flag_difference_requires_a_note(self):
        """Marcar con diferencia exige una observación."""
        settlement = self._submitted(collected=10000.0, delivered=9500.0)
        with self.assertRaises(UserError):
            settlement.with_user(self.manager_user).action_flag_difference()

    def test_flag_difference_with_note_moves_state(self):
        """Con observación cargada, la rendición queda marcada con diferencia (HU-20)."""
        settlement = self._submitted(collected=10000.0, delivered=9500.0)
        settlement.note = "Faltante reconocido por el cobrador, descuenta la semana próxima."
        settlement.with_user(self.manager_user).action_flag_difference()
        self.assertEqual(settlement.state, "difference")
        self.assertEqual(settlement.approved_by_id, self.manager_user)

    def test_collector_cannot_approve(self):
        """El cobrador no aprueba su propia rendición."""
        settlement = self._submitted()
        with self.assertRaises(UserError):
            settlement.with_user(self.collector_user).action_approve()

    def test_reset_to_draft_releases_the_payments(self):
        """Volver a borrador devuelve los cobros al pool pendiente de rendir."""
        settlement = self._submitted()
        payment = settlement.payment_ids
        settlement.with_user(self.manager_user).action_reset_draft()
        self.assertEqual(settlement.state, "draft")
        self.assertFalse(payment.settlement_id)
        self.assertEqual(settlement.payment_count, 0)

    def test_released_payments_can_be_settled_again(self):
        """Un cobro liberado vuelve a estar disponible para la próxima rendición."""
        settlement = self._submitted()
        settlement.with_user(self.manager_user).action_reset_draft()
        other = self.env["cvi.settlement"].create({
            "collector_id": self.collector_user.id,
            "date_to": "2026-03-18",
        })
        other.action_collect_payments()
        self.assertEqual(other.payment_count, 1)

    def test_approved_settlement_cannot_be_reset(self):
        """Una rendición aprobada queda firme."""
        settlement = self._submitted()
        settlement.with_user(self.manager_user).action_approve()
        with self.assertRaises(UserError):
            settlement.with_user(self.manager_user).action_reset_draft()

    def test_settlement_is_logged_on_approval(self):
        """La aprobación deja constancia en el historial (RN-08)."""
        settlement = self._submitted()
        settlement.with_user(self.manager_user).action_approve()
        self.assertIn(self.manager_user.name, settlement.message_ids[0].body)
```

Registrar en `tests/__init__.py` agregando `from . import test_settlement_flow`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSettlementFlow \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA con `AttributeError: 'cvi.settlement' object has no attribute 'action_submit'`.

- [ ] **Step 3: Escribir la entrega, la diferencia y la aprobación**

En `models/cvi_settlement.py`, agregar el import de `float_is_zero`:

```python
from odoo.tools import float_is_zero
```

Agregar los campos después de `late_payment_count`:

```python
    amount_delivered = fields.Monetary(
        string="Entregado",
        currency_field="currency_id",
        tracking=True,
        help="Cuánto entregó efectivamente el cobrador en caja.",
    )
    amount_difference = fields.Monetary(
        string="Diferencia",
        compute="_compute_difference",
        store=True,
        currency_field="currency_id",
        help="Entregado menos lo que había que rendir. Negativa significa que falta plata.",
    )
    has_difference = fields.Boolean(
        string="Tiene diferencia", compute="_compute_difference", store=True
    )
    note = fields.Text(
        string="Observación",
        help="Explicación de la diferencia. Obligatoria para marcar una rendición "
             "como Con diferencia.",
    )
    approved_by_id = fields.Many2one(
        "res.users", string="Revisada por", readonly=True, copy=False
    )
    approved_date = fields.Datetime(string="Revisada el", readonly=True, copy=False)
```

Y estos métodos al final de la clase:

```python
    @api.depends("amount_delivered", "amount_expected")
    def _compute_difference(self):
        """Diferencia entre lo entregado y lo que había que rendir (HU-19)."""
        for settlement in self:
            rounding = settlement.currency_id.rounding or 0.01
            difference = settlement.amount_delivered - settlement.amount_expected
            settlement.amount_difference = difference
            settlement.has_difference = not float_is_zero(
                difference, precision_rounding=rounding
            )

    def _cvi_check_manager(self, action_label):
        """Solo el administrador revisa rendiciones (HU-20)."""
        if not self.env.user.has_group(
            "collections_from_vendors_installments.group_cvi_manager"
        ):
            raise UserError(_(
                "Solo un administrador puede %s una rendición.", action_label
            ))

    def action_submit(self):
        """El cobrador entrega la caja: recolecta y deja la rendición a revisión (HU-19)."""
        for settlement in self:
            if settlement.state != "draft":
                raise UserError(_(
                    "La rendición %(name)s ya fue entregada (estado: %(state)s).",
                    name=settlement.name,
                    state=dict(STATE_SELECTION)[settlement.state],
                ))
            settlement.action_collect_payments()
            if not settlement.payment_ids:
                raise UserError(_(
                    "La rendición %s no tiene cobros para rendir.", settlement.name
                ))
            settlement.state = "submitted"
            settlement._cvi_log(_(
                "Rendición entregada por %(user)s: %(delivered)s sobre %(expected)s "
                "a rendir (%(count)s cobros).",
                user=settlement.collector_id.name,
                delivered=settlement.amount_delivered,
                expected=settlement.amount_expected,
                count=settlement.payment_count,
            ))
        return True

    def action_approve(self):
        """El administrador aprueba una rendición que cuadra (HU-20)."""
        self._cvi_check_manager(_("aprobar"))
        for settlement in self:
            if settlement.state != "submitted":
                raise UserError(_(
                    "Solo se aprueba una rendición entregada (la rendición %(name)s "
                    "está en estado %(state)s).",
                    name=settlement.name,
                    state=dict(STATE_SELECTION)[settlement.state],
                ))
            if settlement.has_difference:
                raise UserError(_(
                    "La rendición %(name)s tiene una diferencia de %(diff)s. Usá "
                    "«Marcar con diferencia» y dejá una observación en vez de aprobarla.",
                    name=settlement.name,
                    diff=settlement.amount_difference,
                ))
            settlement.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
            settlement._cvi_log(_(
                "Rendición aprobada por %s: el dinero cuadra.", self.env.user.name
            ))
        return True

    def action_flag_difference(self):
        """El administrador registra la diferencia con su explicación (HU-20)."""
        self._cvi_check_manager(_("marcar con diferencia"))
        for settlement in self:
            if settlement.state != "submitted":
                raise UserError(_(
                    "Solo se marca una rendición entregada (la rendición %(name)s "
                    "está en estado %(state)s).",
                    name=settlement.name,
                    state=dict(STATE_SELECTION)[settlement.state],
                ))
            if not settlement.note or not settlement.note.strip():
                raise UserError(_(
                    "Cargá una observación explicando la diferencia de la rendición %s.",
                    settlement.name,
                ))
            settlement.write({
                "state": "difference",
                "approved_by_id": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
            settlement._cvi_log(_(
                "Rendición cerrada CON DIFERENCIA de %(diff)s por %(user)s: %(note)s",
                diff=settlement.amount_difference,
                user=self.env.user.name,
                note=settlement.note.strip(),
            ))
        return True

    def action_reset_draft(self):
        """Devuelve la rendición a borrador y libera sus cobros (HU-20)."""
        self._cvi_check_manager(_("reabrir"))
        for settlement in self:
            if settlement.state != "submitted":
                raise UserError(_(
                    "Solo se reabre una rendición entregada y aún no revisada "
                    "(la rendición %(name)s está en estado %(state)s).",
                    name=settlement.name,
                    state=dict(STATE_SELECTION)[settlement.state],
                ))
            released = len(settlement.payment_ids)
            settlement.payment_ids.write({"settlement_id": False})
            settlement.state = "draft"
            settlement._cvi_log(_(
                "Rendición reabierta por %(user)s: %(count)s cobros vuelven a quedar "
                "pendientes de rendir.",
                user=self.env.user.name,
                count=released,
            ))
        return True
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR.*Test|AssertionError|post-tests'
```

Esperado: sin FAIL ni AssertionError, post-tests en 205 (190 + los 15 de esta task).

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): entrega, diferencia y aprobación de rendiciones"
```

---

## Task 4: Proteger los cobros ya rendidos

Endurece RN-06: un cobro que ya fue entregado en una rendición no se anula sin reabrirla primero. Sin esto, anular un cobro rendido cambiaría el esperado de una rendición ya aprobada, y el dinero dejaría de cuadrar retroactivamente.

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_payment.py`
- Modify: `collections_from_vendors_installments/tests/test_settlement_flow.py`

**Interfaces:**
- Consumes: `cvi.payment.settlement_id` (Task 2); `cvi.settlement.state` (Task 1).
- Produces: guarda en `cvi.payment.action_cancel()` que rechaza anular un cobro cuya rendición no esté en `draft`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_settlement_flow.py`, dentro de `TestCviSettlementFlow`:

```python
    def test_cannot_cancel_a_payment_already_submitted(self):
        """Un cobro entregado en una rendición no se anula: primero hay que reabrirla."""
        settlement = self._submitted()
        payment = settlement.payment_ids
        with self.assertRaises(UserError):
            payment.action_cancel()

    def test_cannot_cancel_a_payment_in_an_approved_settlement(self):
        """Tampoco se anula si la rendición ya fue aprobada."""
        settlement = self._submitted()
        settlement.with_user(self.manager_user).action_approve()
        with self.assertRaises(UserError):
            settlement.payment_ids.action_cancel()

    def test_can_cancel_a_payment_in_a_draft_settlement(self):
        """Mientras la rendición está en borrador, el cobro todavía se puede anular."""
        self._pay(10000.0)
        settlement = self.env["cvi.settlement"].create({
            "collector_id": self.collector_user.id,
            "date_to": "2026-03-18",
        })
        settlement.action_collect_payments()
        payment = settlement.payment_ids
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")

    def test_can_cancel_after_reopening_the_settlement(self):
        """Reabrir la rendición libera el cobro y recién ahí se puede anular."""
        settlement = self._submitted()
        payment = settlement.payment_ids
        settlement.with_user(self.manager_user).action_reset_draft()
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")

    def test_cancelling_a_released_payment_keeps_it_out_of_settlements(self):
        """Un cobro anulado tras liberarse no vuelve a entrar en ninguna rendición."""
        settlement = self._submitted()
        payment = settlement.payment_ids
        settlement.with_user(self.manager_user).action_reset_draft()
        payment.action_cancel()
        settlement.action_collect_payments()
        self.assertEqual(settlement.payment_count, 0)
```

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSettlementFlow \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA en `test_cannot_cancel_a_payment_already_submitted` — hoy la anulación pasa sin control.

- [ ] **Step 3: Agregar la guarda a `action_cancel`**

En `models/cvi_payment.py`, dentro de `action_cancel`, agregar la validación **después** de la que verifica `state != "posted"` y **antes** de tocar las imputaciones:

```python
            if payment.settlement_id and payment.settlement_id.state != "draft":
                raise UserError(_(
                    "El cobro %(payment)s ya fue entregado en la rendición %(settlement)s "
                    "(estado: %(state)s). Reabrí la rendición antes de anularlo, para que "
                    "el dinero rendido siga cuadrando.",
                    payment=payment.name,
                    settlement=payment.settlement_id.name,
                    state=payment.settlement_id.state,
                ))
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR.*Test|AssertionError|post-tests'
```

Esperado: sin FAIL ni AssertionError, post-tests en 210 (205 + los 5 de esta task).

- [ ] **Step 5: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "fix(collections_from_vendors_installments): impedir anular un cobro ya rendido"
```

---

## Task 5: Visibilidad por rol

Cubre RN-07 para el modelo nuevo: el cobrador ve solo sus rendiciones, el administrador todas.

**Files:**
- Modify: `collections_from_vendors_installments/security/security.xml`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Test: `collections_from_vendors_installments/tests/test_settlement_security.py`

**Interfaces:**
- Consumes: `cvi.settlement.collector_id`, `.company_id` (Task 1); grupos existentes.
- Produces: tres `ir.rule` sobre `cvi.settlement` — una global de empresa, una de cobrador, una de administrador.

**Cómo son las reglas** (mismo patrón que los otros modelos del módulo):
- La regla de empresa es `global` (aplica a todos y combina con AND).
- Las de rol van atadas a su grupo (combinan con OR). Una regla de rol marcada `global` por error haría AND con las demás y dejaría a todos sin ver nada.
- No hay regla de vendedor: un vendedor no rinde caja. Sin fila de acceso en el CSV y sin regla, el modelo le es invisible.

- [ ] **Step 1: Escribir el test que falla**

`collections_from_vendors_installments/tests/test_settlement_security.py`:

```python
# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSettlementSecurity(CviCommon):

    def setUp(self):
        super().setUp()
        self.other_collector = self.env["res.users"].create({
            "name": "Cobrador Ajeno",
            "login": "cvi_collector_sec_settle",
            "email": "ajeno@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.manager_user = self.env["res.users"].create({
            "name": "Administrador Seg",
            "login": "cvi_manager_sec_settle",
            "email": "manager.sec@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_manager").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.mine = self.env["cvi.settlement"].create({
            "collector_id": self.collector_user.id, "date_to": "2026-03-18",
        })
        self.theirs = self.env["cvi.settlement"].create({
            "collector_id": self.other_collector.id, "date_to": "2026-03-18",
        })

    def test_collector_sees_only_own_settlements(self):
        """Un cobrador solo ve sus propias rendiciones (RN-07)."""
        visible = self.env["cvi.settlement"].with_user(self.collector_user).search([])
        self.assertIn(self.mine, visible)
        self.assertNotIn(self.theirs, visible)

    def test_other_collector_sees_only_theirs(self):
        """La aislación funciona en las dos direcciones."""
        visible = self.env["cvi.settlement"].with_user(self.other_collector).search([])
        self.assertIn(self.theirs, visible)
        self.assertNotIn(self.mine, visible)

    def test_manager_sees_every_settlement(self):
        """El administrador ve las rendiciones de todos los cobradores (RN-07)."""
        visible = self.env["cvi.settlement"].with_user(self.manager_user).search([])
        self.assertIn(self.mine, visible)
        self.assertIn(self.theirs, visible)

    def test_vendor_cannot_read_settlements(self):
        """Un vendedor no rinde caja: el modelo no le existe."""
        with self.assertRaises(AccessError):
            self.env["cvi.settlement"].with_user(self.vendor_user).search([])

    def test_nobody_can_delete_a_settlement(self):
        """Una rendición es registro de dinero: no se borra, ni siquiera el admin."""
        with self.assertRaises(AccessError):
            self.mine.with_user(self.manager_user).unlink()
```

Registrar en `tests/__init__.py` agregando `from . import test_settlement_security`.

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSettlementSecurity \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: FALLA en `test_collector_sees_only_own_settlements` — sin reglas, el cobrador ve todo.

- [ ] **Step 3: Escribir las reglas de registro**

En `security/security.xml`, agregar dentro del mismo `<data noupdate="1">`, junto a las reglas que ya existen:

```xml
        <record id="rule_cvi_settlement_company" model="ir.rule">
            <field name="name">Rendición: multi-empresa</field>
            <field name="model_id" ref="model_cvi_settlement"/>
            <field name="domain_force">[('company_id', 'in', company_ids)]</field>
            <field name="global" eval="True"/>
        </record>

        <record id="rule_cvi_settlement_collector" model="ir.rule">
            <field name="name">Rendición: el cobrador ve las suyas</field>
            <field name="model_id" ref="model_cvi_settlement"/>
            <field name="domain_force">[('collector_id', '=', user.id)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_collector'))]"/>
        </record>

        <record id="rule_cvi_settlement_manager" model="ir.rule">
            <field name="name">Rendición: el administrador ve todo</field>
            <field name="model_id" ref="model_cvi_settlement"/>
            <field name="domain_force">[(1, '=', 1)]</field>
            <field name="groups" eval="[(4, ref('group_cvi_manager'))]"/>
        </record>
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR.*Test|AssertionError|post-tests'
```

Esperado: sin FAIL ni AssertionError, post-tests en 215 (210 + los 5 de esta task).

- [ ] **Step 5: Verificar que la regla es load-bearing**

Un test de seguridad que nunca viste fallar no prueba nada. Las reglas viven en un bloque `noupdate="1"`, así que comentar el XML no borra la fila existente — hay que eliminarla en la base:

```bash
docker exec odoo-odoo-1 odoo shell -d calidad --no-http <<'PYEOF'
rule = env.ref("collections_from_vendors_installments.rule_cvi_settlement_collector")
rule.unlink()
env.cr.commit()
PYEOF
docker exec odoo-odoo-1 odoo -d calidad --test-enable \
  --test-tags /collections_from_vendors_installments:TestCviSettlementSecurity \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|AssertionError'
```

Esperado: `test_collector_sees_only_own_settlements` FALLA. Después restaurar y confirmar verde:

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSettlementSecurity \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|AssertionError|post-tests'
```

Anotá ambos resultados en el reporte.

- [ ] **Step 6: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): visibilidad por rol de las rendiciones"
```

---

## Task 6: Vistas, menús y reporte de diferencias

Cubre la interfaz de HU-18, HU-19 y HU-20, incluido el reporte de diferencias acumuladas por cobrador que pide HU-20.

**Files:**
- Create: `collections_from_vendors_installments/views/cvi_settlement_views.xml`
- Modify: `collections_from_vendors_installments/views/cvi_payment_views.xml`
- Modify: `collections_from_vendors_installments/views/menu_views.xml`
- Modify: `collections_from_vendors_installments/__manifest__.py`

**Interfaces:**
- Consumes: todos los campos y métodos de `cvi.settlement` (Tasks 1 a 3).
- Produces: acciones `action_cvi_settlement_mine`, `action_cvi_settlement_to_approve`, `action_cvi_settlement_differences`; menús bajo Cobrador y bajo Administración.

- [ ] **Step 1: Escribir las vistas de la rendición**

`collections_from_vendors_installments/views/cvi_settlement_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_cvi_settlement_form" model="ir.ui.view">
        <field name="name">cvi.settlement.form</field>
        <field name="model">cvi.settlement</field>
        <field name="arch" type="xml">
            <form string="Rendición">
                <header>
                    <button name="action_collect_payments" type="object"
                            string="Recolectar cobros" invisible="state != 'draft'"/>
                    <button name="action_submit" type="object" string="Entregar caja"
                            class="btn-primary" invisible="state != 'draft'"/>
                    <button name="action_approve" type="object" string="Aprobar"
                            class="btn-primary" invisible="state != 'submitted'"
                            groups="collections_from_vendors_installments.group_cvi_manager"/>
                    <button name="action_flag_difference" type="object"
                            string="Marcar con diferencia" invisible="state != 'submitted'"
                            groups="collections_from_vendors_installments.group_cvi_manager"/>
                    <button name="action_reset_draft" type="object" string="Reabrir"
                            invisible="state != 'submitted'"
                            groups="collections_from_vendors_installments.group_cvi_manager"/>
                    <field name="state" widget="statusbar"
                           statusbar_visible="draft,submitted,approved"/>
                </header>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <div class="alert alert-warning" role="alert"
                         invisible="late_payment_count == 0">
                        Esta rendición incluye <field name="late_payment_count" readonly="1"/>
                        cobro(s) con fecha de períodos anteriores, cargados tarde.
                    </div>
                    <group>
                        <group string="Período">
                            <field name="collector_id" readonly="state != 'draft'"/>
                            <field name="frequency" readonly="1"/>
                            <field name="date_from" readonly="1"/>
                            <field name="date_to" readonly="state != 'draft'"/>
                        </group>
                        <group string="Dinero">
                            <field name="amount_expected" readonly="1"/>
                            <field name="amount_delivered"
                                   readonly="state not in ('draft', 'submitted')"/>
                            <field name="amount_difference" readonly="1"
                                   decoration-danger="amount_difference &lt; 0"
                                   decoration-success="amount_difference &gt; 0"/>
                            <field name="payment_count" readonly="1"/>
                            <field name="has_difference" invisible="1"/>
                            <field name="currency_id" invisible="1"/>
                        </group>
                    </group>
                    <group string="Observación" invisible="not has_difference and state != 'difference'">
                        <field name="note" nolabel="1"
                               placeholder="Explicá la diferencia: faltante reconocido, error de carga, etc."
                               readonly="state in ('approved', 'difference')"/>
                    </group>
                    <group string="Revisión" invisible="state in ('draft', 'submitted')">
                        <field name="approved_by_id"/>
                        <field name="approved_date"/>
                    </group>
                    <notebook>
                        <page string="Cobros rendidos" name="payments">
                            <field name="payment_ids" readonly="1">
                                <list>
                                    <field name="name"/>
                                    <field name="date"/>
                                    <field name="partner_id"/>
                                    <field name="card_id" optional="show"/>
                                    <field name="amount" sum="Total"/>
                                    <field name="state"/>
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

    <record id="view_cvi_settlement_list" model="ir.ui.view">
        <field name="name">cvi.settlement.list</field>
        <field name="model">cvi.settlement</field>
        <field name="arch" type="xml">
            <list string="Rendiciones" decoration-danger="has_difference"
                  decoration-muted="state == 'draft'">
                <field name="name"/>
                <field name="collector_id"/>
                <field name="date_from" optional="show"/>
                <field name="date_to"/>
                <field name="payment_count" optional="show"/>
                <field name="amount_expected" sum="A rendir"/>
                <field name="amount_delivered" sum="Entregado"/>
                <field name="amount_difference" sum="Diferencia"/>
                <field name="state"/>
                <field name="has_difference" column_invisible="True"/>
                <field name="currency_id" column_invisible="True"/>
            </list>
        </field>
    </record>

    <record id="view_cvi_settlement_search" model="ir.ui.view">
        <field name="name">cvi.settlement.search</field>
        <field name="model">cvi.settlement</field>
        <field name="arch" type="xml">
            <search string="Rendiciones">
                <field name="name"/>
                <field name="collector_id"/>
                <filter name="filter_draft" string="Borrador" domain="[('state', '=', 'draft')]"/>
                <filter name="filter_submitted" string="A revisar"
                        domain="[('state', '=', 'submitted')]"/>
                <filter name="filter_approved" string="Aprobadas"
                        domain="[('state', '=', 'approved')]"/>
                <separator/>
                <filter name="filter_difference" string="Con diferencia"
                        domain="[('has_difference', '=', True)]"/>
                <filter name="filter_late" string="Con cobros tardíos"
                        domain="[('late_payment_count', '&gt;', 0)]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_by_collector" string="Cobrador"
                            context="{'group_by': 'collector_id'}"/>
                    <filter name="group_by_state" string="Estado"
                            context="{'group_by': 'state'}"/>
                    <filter name="group_by_date" string="Cierre"
                            context="{'group_by': 'date_to'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_cvi_settlement_mine" model="ir.actions.act_window">
        <field name="name">Mis rendiciones</field>
        <field name="res_model">cvi.settlement</field>
        <field name="view_mode">list,form</field>
        <field name="search_view_id" ref="view_cvi_settlement_search"/>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Todavía no rendiste caja</p>
            <p>Creá una rendición, recolectá tus cobros y registrá cuánto entregaste.</p>
        </field>
    </record>

    <record id="action_cvi_settlement_to_approve" model="ir.actions.act_window">
        <field name="name">Rendiciones a revisar</field>
        <field name="res_model">cvi.settlement</field>
        <field name="view_mode">list,form</field>
        <field name="search_view_id" ref="view_cvi_settlement_search"/>
        <field name="domain">[('state', '=', 'submitted')]</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">No hay rendiciones esperando revisión</p>
        </field>
    </record>

    <record id="action_cvi_settlement_differences" model="ir.actions.act_window">
        <field name="name">Diferencias por cobrador</field>
        <field name="res_model">cvi.settlement</field>
        <field name="view_mode">list,form</field>
        <field name="search_view_id" ref="view_cvi_settlement_search"/>
        <field name="domain">[('has_difference', '=', True)]</field>
        <field name="context">{'search_default_group_by_collector': 1}</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Ninguna rendición tuvo diferencias</p>
            <p>Acá se acumulan las diferencias de caja agrupadas por cobrador.</p>
        </field>
    </record>
</odoo>
```

> El reporte de diferencias acumuladas de HU-20 es `action_cvi_settlement_differences`: la lista suma `amount_difference` y el contexto la agrupa por cobrador, así que el total por cobrador sale del `sum` de la columna sin necesidad de un modelo de reporte aparte.

- [ ] **Step 2: Mostrar la rendición en el cobro**

En `views/cvi_payment_views.xml`, agregar el campo al formulario, en el grupo de la derecha junto a `user_id`:

```xml
                            <field name="settlement_id" readonly="1"/>
```

Y a la lista, como columna opcional:

```xml
                <field name="settlement_id" optional="hide"/>
```

- [ ] **Step 3: Agregar los menús**

En `views/menu_views.xml`, agregar bajo el menú del cobrador (después de `menu_cvi_payments`):

```xml
    <menuitem id="menu_cvi_my_settlements" name="Mis rendiciones" parent="menu_cvi_collector"
              action="action_cvi_settlement_mine" sequence="50"/>
```

Y bajo el menú de administración (después de `menu_cvi_transfer`):

```xml
    <menuitem id="menu_cvi_settlements_to_approve" name="Rendiciones a revisar"
              parent="menu_cvi_admin" action="action_cvi_settlement_to_approve" sequence="30"/>
    <menuitem id="menu_cvi_settlement_differences" name="Diferencias de caja"
              parent="menu_cvi_admin" action="action_cvi_settlement_differences" sequence="40"/>
```

- [ ] **Step 4: Registrar la vista en el manifest**

En `__manifest__.py`, agregar a la lista `data`, después de `views/cvi_payment_views.xml`:

```python
        "views/cvi_settlement_views.xml",
```

- [ ] **Step 5: Validar el XML localmente antes de actualizar**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/collections_from_vendors_installments
for f in views/*.xml data/*.xml security/*.xml; do
  python3 -c "import xml.dom.minidom as m; m.parse('$f')" || echo "ROTO: $f"
done
python3 -c "import ast; ast.parse(open('__manifest__.py').read()); print('manifest ok')"
```

Esperado: ningún "ROTO" y `manifest ok`.

- [ ] **Step 6: Correr toda la suite y verificar que carga**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR|AssertionError|post-tests'
```

Esperado: el módulo carga sin errores de vista y post-tests sigue en 215 (esta task no agrega tests). El `cuenta_corriente_retiros: not installable` de otro módulo es ruido conocido y ajeno.

- [ ] **Step 7: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): vistas, menús y reporte de diferencias de rendición"
```

---

## Task 7: Circuito completo y documentación

Cierra el plan: un test que recorre la rendición de punta a punta y la sección del README.

**Files:**
- Create: `collections_from_vendors_installments/tests/test_settlement_full_flow.py`
- Modify: `collections_from_vendors_installments/tests/__init__.py`
- Modify: `collections_from_vendors_installments/README.md`

**Interfaces:**
- Consumes: todo lo construido en las Tasks 1 a 6.

- [ ] **Step 1: Escribir el test de circuito completo**

`collections_from_vendors_installments/tests/test_settlement_full_flow.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSettlementFullFlow(CviCommon):
    """Recorre la rendición completa: cobrar -> rendir -> revisar -> cerrar."""

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650  # ~10 años
        self.company.cvi_settlement_frequency = "weekly"
        self.manager_user = self.env["res.users"].create({
            "name": "Administrador Circuito",
            "login": "cvi_manager_fullflow",
            "email": "manager.full@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_manager").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def test_full_settlement_circuit_with_a_shortfall(self):
        card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        card.action_confirm()
        card.with_user(self.collector_user).action_accept()

        # 1. El cobrador cobra dos cuotas en la calle (HU-15).
        for amount, day in [(10000.0, "2026-03-10"), (10000.0, "2026-03-17")]:
            payment = self.env["cvi.payment"].with_user(self.collector_user).create({
                "card_id": card.id, "amount": amount, "date": day,
            })
            payment.action_post()

        # 2. Arma su rendición y ve cuánto debe entregar (HU-18).
        settlement = self.env["cvi.settlement"].with_user(self.collector_user).create({
            "collector_id": self.collector_user.id,
            "date_to": "2026-03-18",
        })
        settlement.action_collect_payments()
        self.assertEqual(settlement.payment_count, 2)
        self.assertEqual(settlement.amount_expected, 20000.0)
        self.assertEqual(str(settlement.date_from), "2026-03-16")

        # 3. Entrega menos de lo que debía (HU-19).
        settlement.amount_delivered = 19500.0
        settlement.action_submit()
        self.assertEqual(settlement.state, "submitted")
        self.assertEqual(settlement.amount_difference, -500.0)
        self.assertTrue(settlement.has_difference)

        # 4. El administrador no puede aprobarla a secas (HU-20).
        with self.assertRaises(Exception):
            settlement.with_user(self.manager_user).action_approve()

        # 5. La marca con diferencia y deja constancia (HU-20).
        settlement.note = "Faltante reconocido, se descuenta la semana próxima."
        settlement.with_user(self.manager_user).action_flag_difference()
        self.assertEqual(settlement.state, "difference")
        self.assertEqual(settlement.approved_by_id, self.manager_user)

        # 6. Los cobros rendidos quedaron inmutables (RN-06 endurecida).
        with self.assertRaises(Exception):
            settlement.payment_ids[0].action_cancel()

        # 7. Un cobro cargado tarde entra en la próxima rendición, no queda huérfano.
        late = self.env["cvi.payment"].with_user(self.collector_user).create({
            "card_id": card.id, "amount": 10000.0, "date": "2026-03-12",
        })
        late.action_post()
        following = self.env["cvi.settlement"].with_user(self.collector_user).create({
            "collector_id": self.collector_user.id,
            "date_to": "2026-03-25",
        })
        following.action_collect_payments()
        self.assertEqual(following.payment_count, 1)
        self.assertEqual(following.late_payment_count, 1)
        self.assertEqual(following.amount_expected, 10000.0)
```

Registrar en `tests/__init__.py` agregando `from . import test_settlement_full_flow`.

- [ ] **Step 2: Correr el test de circuito completo**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviSettlementFullFlow \
  --stop-after-init --no-http 2>&1 | tail -30
```

Esperado: PASA. Si falla, el problema está en la integración entre tareas, no en el test: revisá el paso concreto que rompe antes de tocar la aserción.

- [ ] **Step 3: Documentar la rendición en el README**

En `README.md`, agregar una sección después de "Imputación de cobros":

```markdown
## Rendición de caja

El cobrador maneja efectivo en la calle. La rendición es el control de cuánto
tiene que entregar y cuánto entregó.

1. **Armar la rendición** — Venta en cuotas > Cobrador > *Mis rendiciones*. Se
   indica la fecha de cierre del período y se recolectan los cobros.
2. **Qué cobros entran** — todos los cobros publicados del cobrador que todavía
   no fueron rendidos, con fecha hasta el cierre. **Sin límite inferior**: un
   cobro cargado tarde, con fecha de un período ya cerrado, entra en la próxima
   rendición en vez de quedar huérfano. La rendición avisa cuántos de sus cobros
   vienen de períodos anteriores.
3. **Entregar** — se carga el monto entregado y el sistema calcula la diferencia
   contra lo esperado. La rendición queda pendiente de revisión.
4. **Revisar** — Venta en cuotas > Administración > *Rendiciones a revisar*. Si
   el dinero cuadra, se aprueba. Si no, hay que marcarla *con diferencia* y
   escribir una observación: una diferencia nunca se cierra sin explicación.
5. **Diferencias acumuladas** — *Diferencias de caja* lista todas las rendiciones
   con diferencia, agrupadas por cobrador y con el total sumado.

La frecuencia (diaria, semanal o mensual) se configura en Ajustes > Venta en
cuotas. Define el período que etiqueta cada rendición; los cobros que entran son
siempre los no rendidos hasta el cierre.

**Un cobro entregado en una rendición no se puede anular.** Para anularlo hay que
reabrir la rendición primero, lo que devuelve sus cobros al pool pendiente. Así el
dinero ya rendido no cambia retroactivamente.
```

Y en la sección "Fuera de alcance de esta versión", quitar la rendición de caja de la lista de la etapa 2, ya que ahora está implementada.

- [ ] **Step 4: Correr la suite completa**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR|AssertionError|post-tests'
```

Esperado: sin FAIL ni AssertionError, post-tests en 216.

- [ ] **Step 5: Verificar la instalación limpia**

Una actualización acumulada puede ocultar errores que solo aparecen al instalar de cero:

```bash
docker exec odoo-postgres18-1 createdb -U odoo cvi_e5_clean
docker exec odoo-odoo-1 odoo -d cvi_e5_clean -i collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http 2>&1 | grep -E 'FAIL|ERROR|AssertionError|post-tests'
docker exec odoo-postgres18-1 dropdb -U odoo cvi_e5_clean
```

Esperado: instala sin errores y los tests pasan. Si falla acá pero pasa en `calidad`, el problema es orden de carga en la lista `data` del manifest.

- [ ] **Step 6: Commit**

```bash
git add collections_from_vendors_installments
git commit -m "feat(collections_from_vendors_installments): circuito completo de rendición y documentación"
```

---

## Cobertura del spec

| Historia | Task | Nota |
|---|---|---|
| HU-18 Conocer cuánto debo rendir | 1, 2, 6 | Período configurable + recolección + detalle de cobros en la vista |
| HU-19 Registrar la entrega en caja | 3, 6 | `amount_delivered`, diferencia calculada, estado `submitted` |
| HU-20 Aprobar rendiciones | 3, 6 | Aprobar / marcar con diferencia + reporte agrupado por cobrador |
| RN-06 Cobros no se borran | 4 | Endurecida: tampoco se anulan si ya fueron rendidos |
| RN-07 Cada rol ve lo suyo | 5 | `ir.rule` sobre `cvi.settlement`; el vendedor no ve el modelo |
| RN-08 Auditoría | 3 | `_cvi_log` en entregar, aprobar, marcar diferencia y reabrir |

**Decisiones tomadas en este plan, para que no se relitiguen:**
- Períodos fijos configurables, pero el filtro de cobros no tiene límite inferior de fecha — así ninguna carga tardía queda huérfana. El `date_from` es etiqueta, no filtro.
- Una diferencia no se aprueba: se marca con observación obligatoria.
- Reabrir una rendición libera sus cobros; es el único camino para anular un cobro ya rendido.
- Sin concepto de zona ni ruta: vendrá de la geolocalización en una etapa posterior.
