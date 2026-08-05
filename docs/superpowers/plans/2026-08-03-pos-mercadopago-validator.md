# pos_mercadopago_validator — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Conciliar automáticamente los pagos del QR estático de Mercado Pago con las líneas de cobro del POS de Odoo 18, eliminando la verificación manual del cajero.

**Architecture:** Un ingestor server-side por cuenta de Mercado Pago mantiene una bandeja (`mercadopago.payment`) alimentada por webhook y por cron, ambos por el mismo camino de upsert idempotente. El POS lee la bandeja de su propia caja desde la base de Odoo — nunca habla con Mercado Pago — y al imputar toma la fila con `SELECT ... FOR UPDATE`, con una restricción `UNIQUE` en base como red final.

**Tech Stack:** Odoo 18.0, Python 3.11, PostgreSQL 18, OWL 2, `requests`, API de Mercado Pago (`/v1/payments/search`).

**Spec:** `docs/superpowers/specs/2026-08-03-pos-mercadopago-validator-design.md`

## Global Constraints

- Módulo: `pos_mercadopago_validator`, versión `18.0.1.0.0`, license `LGPL-3`, author `Alexis Medina`, depends `["point_of_sale"]`.
- Ruta en el host: `/home/alexis/Documents/Github/prometeo-odoo-modules/pos_mercadopago_validator/`. Dentro del contenedor: `/mnt/local-addons/pos_mercadopago_validator/`.
- Base de datos de pruebas: **`calidad`**. Nunca `prod`.
- Cadenas fuente en inglés, traducción en `i18n/es_AR.po`. Traducciones nuevo estilo: `_("texto %s", arg)` con coma, nunca `%`.
- `access_token` y `webhook_secret` llevan `groups="base.group_system"` y **nunca** se agregan a `_load_pos_data_fields()`.
- Importes: siempre `transaction_amount`, nunca `net_received_amount`.
- `payer.identification` y `payer.email` se persisten **sólo** cuando `source == "qr"`.
- Docstring en todo método. `_logger` para trazas, nunca `print`.
- Comando de test:
  ```bash
  docker exec odoo-odoo-1 odoo -d calidad -u pos_mercadopago_validator \
    --test-enable --test-tags /pos_mercadopago_validator --stop-after-init --no-http
  ```
- Comando de upgrade sin tests:
  ```bash
  docker exec odoo-odoo-1 odoo -d calidad -u pos_mercadopago_validator --stop-after-init --no-http
  ```

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `__manifest__.py`, `__init__.py` | Declaración del módulo |
| `services/mp_client.py` | HTTP puro contra Mercado Pago: auth, timeout, retry, clasificación de errores. No conoce modelos de Odoo |
| `services/inbox_provider.py` | Interfaz abstracta del proveedor |
| `services/inbox_provider_mercadopago.py` | Normaliza el JSON de MP → dict del modelo. Acá vive el filtro de §6.1 y la regla de §2.3 |
| `models/mercadopago_account.py` | Credenciales, validación, estado de sincronización |
| `models/mercadopago_payment.py` | La bandeja: upsert idempotente, imputación con lock, reversión |
| `models/pos_payment_method.py` | Configuración por caja y RPC que consume el POS |
| `models/pos_payment.py` | Vínculo con el pago y campos de aprobación manual |
| `models/pos_session.py` | Aviso de pagos sin imputar al cerrar |
| `controllers/webhook.py` | Endpoint público. Sólo lee `data.id` |
| `static/src/app/payment_mercadopago_validator.js` | `PaymentInterface` |
| `static/src/app/inbox_dialog.{js,xml,scss}` | Diálogo de selección |

---

## Task 1: Esqueleto del módulo y `mercadopago.account`

**Files:**
- Create: `pos_mercadopago_validator/__init__.py`, `__manifest__.py`
- Create: `pos_mercadopago_validator/models/__init__.py`, `models/mercadopago_account.py`
- Create: `pos_mercadopago_validator/security/ir.model.access.csv`, `security/security.xml`
- Create: `pos_mercadopago_validator/views/mercadopago_account_views.xml`, `views/menus.xml`
- Test: `pos_mercadopago_validator/tests/__init__.py`, `tests/test_account.py`

**Interfaces:**
- Produces: modelo `mercadopago.account` con campos `name`, `access_token`, `mp_user_id`, `mode`, `webhook_secret`, `active`, `last_validated_at`, `last_sync_at`, `last_sync_error`, `company_id`, y método `action_test_connection()`.

- [ ] **Step 1: Crear el esqueleto de archivos**

`pos_mercadopago_validator/__init__.py`:
```python
from . import models
from . import controllers
```

Crear `controllers/__init__.py` vacío por ahora (se llena en Task 8) con el contenido `# noqa` para que el import no falle:
```python
```
(archivo vacío)

`pos_mercadopago_validator/__manifest__.py`:
```python
{
    "name": "POS Mercado Pago - Validador de cobros por QR",
    "version": "18.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Concilia los pagos del QR estático de Mercado Pago con las líneas de cobro del POS",
    "description": """
Ingesta los pagos que entran a la cuenta de Mercado Pago por el QR estático del
mostrador y se los ofrece al cajero en el momento del cobro, filtrados por monto.
El cajero selecciona el pago recibido y la línea queda cobrada con el pago real
vinculado en la base, con garantía de que un pago no se imputa dos veces.

Incluye aprobación manual auditada para cuando el pago no llega, y visibilidad de
los pagos recibidos que quedaron sin imputar.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/mercadopago_account_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
```

`pos_mercadopago_validator/models/__init__.py`:
```python
from . import mercadopago_account
```

`pos_mercadopago_validator/tests/__init__.py`:
```python
from . import test_account
```

- [ ] **Step 2: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_account.py`:
```python
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMercadoPagoAccount(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta de prueba",
            "access_token": "APP_USR-fake",
            "mode": "sandbox",
        })

    def test_account_starts_inactive_until_validated(self):
        """Una cuenta nueva no puede activarse sin haber validado credenciales."""
        self.assertFalse(self.account.last_validated_at)
        with self.assertRaises(UserError):
            self.account.write({"active": True})

    def test_activation_allowed_after_validation(self):
        """Con last_validated_at cargado, la activación procede."""
        self.account.write({
            "last_validated_at": "2026-08-03 12:00:00",
            "mp_user_id": "430185252",
        })
        self.account.write({"active": True})
        self.assertTrue(self.account.active)
```

- [ ] **Step 3: Correr el test y verificar que falla**

```bash
docker exec odoo-odoo-1 odoo -d calidad -i pos_mercadopago_validator \
  --test-enable --test-tags /pos_mercadopago_validator --stop-after-init --no-http
```
Esperado: FALLA con `KeyError: 'mercadopago.account'` — el modelo no existe.

- [ ] **Step 4: Implementar el modelo**

`pos_mercadopago_validator/models/mercadopago_account.py`:
```python
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MercadoPagoAccount(models.Model):
    _name = "mercadopago.account"
    _description = "Cuenta de Mercado Pago"

    name = fields.Char(required=True)
    access_token = fields.Char(
        string="Access Token",
        groups="base.group_system",
        help="Token de producción de la cuenta. Nunca sale del servidor.",
    )
    webhook_secret = fields.Char(groups="base.group_system")
    mp_user_id = fields.Char(
        string="Collector ID",
        readonly=True,
        help="Se completa al validar las credenciales. Filtra los cobros propios.",
    )
    mode = fields.Selection(
        [("sandbox", "Sandbox"), ("production", "Producción")],
        default="sandbox",
        required=True,
    )
    active = fields.Boolean(default=False)
    last_validated_at = fields.Datetime(readonly=True)
    last_sync_at = fields.Datetime(readonly=True)
    last_sync_error = fields.Char(readonly=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True
    )

    _sql_constraints = [
        ("mp_user_id_uniq", "unique(mp_user_id, company_id)",
         "Ya existe una cuenta de Mercado Pago con ese Collector ID en esta compañía."),
    ]

    @api.constrains("active", "last_validated_at")
    def _check_validated_before_activation(self):
        """Impide activar una cuenta cuyas credenciales nunca se validaron."""
        for account in self:
            if account.active and not account.last_validated_at:
                raise UserError(_(
                    "Probá la conexión antes de activar la cuenta '%s'.", account.name
                ))

    def action_test_connection(self):
        """Valida las credenciales contra la API y guarda el collector id."""
        self.ensure_one()
        from ..services.mp_client import MercadoPagoClient

        client = MercadoPagoClient(self.sudo().access_token)
        data = client.get_me()
        self.sudo().write({
            "mp_user_id": str(data["id"]),
            "last_validated_at": fields.Datetime.now(),
            "last_sync_error": False,
        })
        _logger.info("Credenciales de Mercado Pago validadas para %s", data.get("nickname"))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _(
                    "Conexión correcta. Collector ID %(uid)s, cuenta %(nick)s.",
                    uid=data["id"], nick=data.get("nickname", ""),
                ),
            },
        }
```

`security/security.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="group_mercadopago_manager" model="res.groups">
        <field name="name">Mercado Pago - Administración de la bandeja</field>
        <field name="category_id" ref="base.module_category_usability"/>
        <field name="comment">Puede revisar la bandeja, los huérfanos y las aprobaciones manuales.</field>
        <field name="implied_ids" eval="[(4, ref('point_of_sale.group_pos_manager'))]"/>
    </record>
</odoo>
```

`security/ir.model.access.csv`:
```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_mercadopago_account_manager,mercadopago.account manager,model_mercadopago_account,group_mercadopago_manager,1,0,0,0
access_mercadopago_account_system,mercadopago.account system,model_mercadopago_account,base.group_system,1,1,1,1
```

`views/mercadopago_account_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_mercadopago_account_form" model="ir.ui.view">
        <field name="name">mercadopago.account.form</field>
        <field name="model">mercadopago.account</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_test_connection" type="object"
                            string="Probar conexión" class="btn-primary"
                            groups="base.group_system"/>
                </header>
                <sheet>
                    <group>
                        <group>
                            <field name="name"/>
                            <field name="mode"/>
                            <field name="active"/>
                            <field name="company_id" groups="base.group_multi_company"/>
                        </group>
                        <group>
                            <field name="access_token" password="True" groups="base.group_system"/>
                            <field name="webhook_secret" password="True" groups="base.group_system"/>
                            <field name="mp_user_id"/>
                            <field name="last_validated_at"/>
                        </group>
                    </group>
                    <group string="Sincronización">
                        <field name="last_sync_at"/>
                        <field name="last_sync_error"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="view_mercadopago_account_list" model="ir.ui.view">
        <field name="name">mercadopago.account.list</field>
        <field name="model">mercadopago.account</field>
        <field name="arch" type="xml">
            <list>
                <field name="name"/>
                <field name="mp_user_id"/>
                <field name="mode"/>
                <field name="last_sync_at"/>
                <field name="active"/>
            </list>
        </field>
    </record>

    <record id="action_mercadopago_account" model="ir.actions.act_window">
        <field name="name">Cuentas de Mercado Pago</field>
        <field name="res_model">mercadopago.account</field>
        <field name="view_mode">list,form</field>
        <field name="context">{'active_test': False}</field>
    </record>
</odoo>
```

`views/menus.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_mercadopago_root" name="Mercado Pago"
              parent="point_of_sale.menu_point_root" sequence="90"
              groups="pos_mercadopago_validator.group_mercadopago_manager"/>
    <menuitem id="menu_mercadopago_account" name="Cuentas"
              parent="menu_mercadopago_root" sequence="20"
              action="action_mercadopago_account"
              groups="base.group_system"/>
</odoo>
```

- [ ] **Step 5: Correr el test y verificar que pasa**

```bash
docker exec odoo-odoo-1 odoo -d calidad -i pos_mercadopago_validator \
  --test-enable --test-tags /pos_mercadopago_validator --stop-after-init --no-http
```
Esperado: `2 tests, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): esqueleto del módulo y modelo de cuenta de Mercado Pago"
```

---

## Task 2: Cliente HTTP `mp_client.py`

**Files:**
- Create: `pos_mercadopago_validator/services/__init__.py`, `services/mp_client.py`
- Test: `pos_mercadopago_validator/tests/test_mp_client.py`

**Interfaces:**
- Produces: `MercadoPagoClient(access_token)` con `get_me() -> dict`, `search_payments(begin_iso, end_iso, limit=50, offset=0) -> dict`, `get_payment(payment_id) -> dict`. Lanza `MercadoPagoAuthError` en 401/403, `MercadoPagoTransientError` en 5xx/red, `MercadoPagoError` en 4xx.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_mp_client.py`:
```python
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from ..services.mp_client import (
    MercadoPagoAuthError,
    MercadoPagoClient,
    MercadoPagoTransientError,
)


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@tagged("post_install", "-at_install")
class TestMercadoPagoClient(TransactionCase):
    def setUp(self):
        super().setUp()
        self.client = MercadoPagoClient("APP_USR-fake")

    def test_search_builds_relative_window_query(self):
        """La búsqueda usa el rango por date_created y filtra approved."""
        captured = {}

        def fake_request(method, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            captured["headers"] = kwargs.get("headers")
            return _FakeResponse(200, {"paging": {"total": 0}, "results": []})

        with patch("requests.request", side_effect=fake_request):
            self.client.search_payments("NOW-5MINUTES", "NOW")

        self.assertIn("/v1/payments/search", captured["url"])
        self.assertEqual(captured["params"]["range"], "date_created")
        self.assertEqual(captured["params"]["begin_date"], "NOW-5MINUTES")
        self.assertEqual(captured["params"]["status"], "approved")
        self.assertEqual(
            captured["headers"]["Authorization"], "Bearer APP_USR-fake"
        )

    def test_401_raises_auth_error(self):
        """Un 401 es error de configuración, no reintentable."""
        with patch("requests.request", return_value=_FakeResponse(401, {"message": "invalid"})):
            with self.assertRaises(MercadoPagoAuthError):
                self.client.get_me()

    def test_500_raises_transient_error_after_retries(self):
        """Un 5xx se reintenta y termina en error transitorio."""
        with patch("requests.request", return_value=_FakeResponse(500, {})) as mocked:
            with self.assertRaises(MercadoPagoTransientError):
                self.client.get_me()
        self.assertEqual(mocked.call_count, 3)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: comando de test del encabezado.
Expected: `ModuleNotFoundError` / `ImportError` sobre `services.mp_client`.

- [ ] **Step 3: Implementar el cliente**

`pos_mercadopago_validator/services/__init__.py`:
```python
```
(archivo vacío)

`pos_mercadopago_validator/services/mp_client.py`:
```python
import logging
import time

import requests

_logger = logging.getLogger(__name__)

API_ROOT = "https://api.mercadopago.com"
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5


class MercadoPagoError(Exception):
    """Error definitivo de la API. No se reintenta."""


class MercadoPagoAuthError(MercadoPagoError):
    """401/403: credenciales inválidas o sin permiso. Error de configuración."""


class MercadoPagoTransientError(Exception):
    """Error de red o 5xx. Reintentable."""


class MercadoPagoClient:
    """Cliente HTTP de la API de Mercado Pago.

    No conoce modelos de Odoo: recibe un token y devuelve diccionarios.
    """

    def __init__(self, access_token):
        self.access_token = access_token

    def _headers(self):
        """Arma los headers de autenticación."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def _call(self, method, path, params=None):
        """Ejecuta la llamada con reintentos y clasificación de errores."""
        url = API_ROOT + path
        last_error = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = requests.request(
                    method, url,
                    headers=self._headers(),
                    params=params,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
            except requests.exceptions.RequestException as error:
                last_error = error
                _logger.warning("Mercado Pago inalcanzable (intento %s): %s", attempt + 1, error)
                time.sleep(BACKOFF_BASE * (2 ** attempt))
                continue

            if response.status_code in (401, 403):
                raise MercadoPagoAuthError(
                    "Credenciales rechazadas por Mercado Pago (HTTP %s)" % response.status_code
                )
            if response.status_code >= 500:
                last_error = "HTTP %s" % response.status_code
                _logger.warning("Mercado Pago devolvió %s (intento %s)", response.status_code, attempt + 1)
                time.sleep(BACKOFF_BASE * (2 ** attempt))
                continue
            if response.status_code >= 400:
                raise MercadoPagoError(
                    "Mercado Pago rechazó la consulta (HTTP %s)" % response.status_code
                )
            return response.json()

        raise MercadoPagoTransientError(
            "Mercado Pago no respondió tras %s intentos: %s" % (MAX_ATTEMPTS, last_error)
        )

    def get_me(self):
        """Devuelve los datos de la cuenta dueña del token."""
        return self._call("GET", "/users/me")

    def search_payments(self, begin_date, end_date, limit=50, offset=0):
        """Busca pagos acreditados en la ventana indicada.

        `begin_date` y `end_date` aceptan la sintaxis relativa de Mercado Pago
        (``NOW-5MINUTES``, ``NOW``), verificada contra la API el 2026-08-03.
        """
        return self._call("GET", "/v1/payments/search", params={
            "sort": "date_created",
            "criteria": "desc",
            "range": "date_created",
            "begin_date": begin_date,
            "end_date": end_date,
            "status": "approved",
            "limit": limit,
            "offset": offset,
        })

    def get_payment(self, payment_id):
        """Trae un pago puntual por id."""
        return self._call("GET", "/v1/payments/%s" % payment_id)
```

Agregar a `tests/__init__.py`:
```python
from . import test_account
from . import test_mp_client
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: comando de test del encabezado.
Expected: `5 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): cliente HTTP con reintentos y clasificación de errores"
```

---

## Task 3: Modelo `mercadopago.payment` con las restricciones

**Files:**
- Create: `pos_mercadopago_validator/models/mercadopago_payment.py`
- Modify: `pos_mercadopago_validator/models/__init__.py`, `security/ir.model.access.csv`
- Test: `pos_mercadopago_validator/tests/test_inbox_model.py`

**Interfaces:**
- Produces: modelo `mercadopago.payment` con los campos de §5.2 del spec y las dos restricciones `UNIQUE`.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_inbox_model.py`:
```python
import psycopg2

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestInboxModel(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta",
            "mode": "production",
            "mp_user_id": "430185252",
        })

    def _payment(self, mp_id, amount=1500.0):
        return self.env["mercadopago.payment"].create({
            "mp_payment_id": mp_id,
            "account_id": self.account.id,
            "amount": amount,
            "date_approved": "2026-08-03 15:21:49",
            "source": "qr",
            "state": "available",
        })

    def test_mp_payment_id_is_unique(self):
        """Dos ingestas del mismo pago no pueden coexistir."""
        self._payment("170951482351")
        with self.assertRaises(psycopg2.IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self._payment("170951482351")

    def test_one_payment_per_pos_payment_line(self):
        """Un mismo pos.payment no puede recibir dos pagos de Mercado Pago."""
        first = self._payment("111")
        second = self._payment("222")
        first.write({"pos_payment_id": 1, "state": "matched"})
        with self.assertRaises(psycopg2.IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                second.write({"pos_payment_id": 1, "state": "matched"})

    def test_null_pos_payment_id_does_not_collide(self):
        """La restricción es parcial: varios pagos sin imputar conviven."""
        self._payment("333")
        self._payment("444")
        self.assertEqual(
            self.env["mercadopago.payment"].search_count([("state", "=", "available")]), 2
        )
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `KeyError: 'mercadopago.payment'`.

- [ ] **Step 3: Implementar el modelo**

`pos_mercadopago_validator/models/mercadopago_payment.py`:
```python
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MercadoPagoPayment(models.Model):
    _name = "mercadopago.payment"
    _description = "Pago recibido en Mercado Pago"
    _order = "date_approved desc"

    mp_payment_id = fields.Char(required=True, index=True, readonly=True)
    account_id = fields.Many2one("mercadopago.account", required=True, readonly=True, ondelete="restrict")

    amount = fields.Monetary(
        required=True, readonly=True,
        help="transaction_amount de Mercado Pago: lo que pagó el cliente, antes de retenciones.",
    )
    currency_id = fields.Many2one("res.currency", readonly=True)
    date_approved = fields.Datetime(required=True, readonly=True, index=True)

    source = fields.Selection(
        [("qr", "QR"), ("alias", "Alias / CVU")],
        required=True, readonly=True,
    )
    mp_pos_id = fields.Char(string="QR / Caja", readonly=True, index=True)
    payer_bank_name = fields.Char(string="Banco de origen", readonly=True)
    payer_vat = fields.Char(string="CUIT del pagador", readonly=True)
    payer_email = fields.Char(readonly=True)
    mp_payer_id = fields.Char(string="ID de pagador", readonly=True, index=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", readonly=True)
    payment_method_detail = fields.Char(readonly=True)
    raw_status = fields.Char(readonly=True)

    state = fields.Selection(
        [("available", "Disponible"), ("matched", "Imputado"), ("discarded", "Descartado")],
        default="available", required=True, index=True,
    )
    pos_payment_id = fields.Many2one("pos.payment", readonly=True, ondelete="set null")
    pos_order_id = fields.Many2one("pos.order", readonly=True)
    pos_session_id = fields.Many2one("pos.session", readonly=True)
    matched_by_user_id = fields.Many2one("res.users", readonly=True)
    matched_at = fields.Datetime(readonly=True)
    amount_difference = fields.Monetary(readonly=True)
    ambiguous_pick = fields.Boolean(
        readonly=True,
        help="Se eligió entre candidatos que no podían distinguirse entre sí.",
    )

    display_payer = fields.Char(compute="_compute_display_payer", string="Pagador")

    _sql_constraints = [
        ("mp_payment_id_uniq", "unique(mp_payment_id)",
         "Ese pago de Mercado Pago ya está en la bandeja."),
    ]

    def init(self):
        """Crea el índice único parcial que garantiza una imputación por línea."""
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mercadopago_payment_pos_payment_uniq
            ON mercadopago_payment (pos_payment_id)
            WHERE pos_payment_id IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS mercadopago_payment_window_idx
            ON mercadopago_payment (account_id, state, date_approved)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS mercadopago_payment_amount_idx
            ON mercadopago_payment (state, amount)
        """)

    @api.depends("partner_id", "payer_bank_name", "payer_vat", "source")
    def _compute_display_payer(self):
        """Elige el mejor identificador disponible según el canal del pago."""
        for payment in self:
            if payment.partner_id:
                payment.display_payer = payment.partner_id.name
            elif payment.payer_vat:
                payment.display_payer = payment.payer_vat
            elif payment.payer_bank_name:
                payment.display_payer = payment.payer_bank_name
            else:
                payment.display_payer = False
```

Agregar a `models/__init__.py`:
```python
from . import mercadopago_account
from . import mercadopago_payment
```

Agregar a `security/ir.model.access.csv`:
```csv
access_mercadopago_payment_manager,mercadopago.payment manager,model_mercadopago_payment,group_mercadopago_manager,1,1,0,0
access_mercadopago_payment_pos_user,mercadopago.payment pos user,model_mercadopago_payment,point_of_sale.group_pos_user,1,0,0,0
access_mercadopago_payment_system,mercadopago.payment system,model_mercadopago_payment,base.group_system,1,1,1,1
```

Agregar a `tests/__init__.py`: `from . import test_inbox_model`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `8 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): modelo de bandeja con unicidad de imputación en base de datos"
```

---

## Task 4: Normalización del pago — `inbox_provider_mercadopago.py`

Es la tarea con más reglas de negocio del módulo. Acá viven el filtro de §6.1 y la regla de §2.3 del spec.

**Files:**
- Create: `pos_mercadopago_validator/services/inbox_provider.py`, `services/inbox_provider_mercadopago.py`
- Test: `pos_mercadopago_validator/tests/test_normalization.py`

**Interfaces:**
- Produces: `MercadoPagoInboxProvider(client, mp_user_id)` con `is_ingestable(raw) -> bool` y `normalize(raw) -> dict` (claves del modelo de Task 3).

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_normalization.py`:
```python
from odoo.tests.common import TransactionCase, tagged

from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider

COLLECTOR = "430185252"

QR_EXTERNAL = {
    "id": 170951482351, "status": "approved", "status_detail": "accredited",
    "collector_id": 430185252, "transaction_amount": 1500, "currency_id": "ARS",
    "date_approved": "2026-08-03T11:21:49.000-04:00",
    "payment_method_id": "interop_transfer", "pos_id": "64365871",
    "metadata": {"hide_payer_information": True},
    "payer": {"id": "1893987077"},
    "transaction_details": {"net_received_amount": 1477.5},
    "point_of_interaction": {
        "type": "INSTORE", "sub_type": "INTER_PSP",
        "business_info": {"unit": "wallet", "sub_unit": "qr", "branch": "QR"},
        "transaction_data": {"bank_info": {
            "payer": {"account_id": 1893987077,
                      "long_name": "Naranja Digital Compañia Financiera S.A."}}},
    },
}

QR_INTERNAL = {
    "id": 171858334766, "status": "approved", "status_detail": "accredited",
    "collector_id": 430185252, "transaction_amount": 100, "currency_id": "ARS",
    "date_approved": "2026-08-03T12:03:02.000-04:00",
    "payment_method_id": "account_money", "pos_id": "64365871",
    "metadata": {},
    "payer": {"id": "2429168801", "email": "erojasmontealegre@gmail.com",
              "identification": {"type": "CUIT", "number": "27964493338"}},
    "transaction_details": {"net_received_amount": 97.53},
    "point_of_interaction": {
        "type": "INSTORE", "sub_type": "INTRA_PSP",
        "business_info": {"unit": "wallet", "sub_unit": "qr", "branch": "QR"},
    },
}

ALIAS = {
    "id": 170951666839, "status": "approved", "status_detail": "accredited",
    "collector_id": 430185252, "transaction_amount": 1500, "currency_id": "ARS",
    "date_approved": "2026-08-03T11:22:50.000-04:00",
    "payment_method_id": "cvu", "metadata": {},
    "payer": {"id": "430185252", "email": "elbuscado8@gmail.com",
              "identification": {"type": "CUIT", "number": "20400321737"}},
    "transaction_details": {"net_received_amount": 1500},
    "point_of_interaction": {
        "type": "PSP_TRANSFER", "sub_type": "INTER_PSP",
        "business_info": {"unit": "digital_accounts_cards",
                          "sub_unit": "money_inflows", "branch": "null"},
    },
}

OUTGOING = {
    "id": 170057310398, "status": "approved", "status_detail": "accredited",
    "payer_id": 430185252, "collector": {"id": 2052122995},
    "transaction_amount": 535923.63, "currency_id": "ARS",
    "date_approved": "2026-07-22T17:00:24.000-04:00",
    "payment_method_id": "debin_transfer", "metadata": {},
    "point_of_interaction": {"type": "CHECKOUT",
        "business_info": {"unit": "credits", "sub_unit": "collections"}},
}


@tagged("post_install", "-at_install")
class TestNormalization(TransactionCase):
    def setUp(self):
        super().setUp()
        self.provider = MercadoPagoInboxProvider(client=None, mp_user_id=COLLECTOR)

    def test_outgoing_payment_is_not_ingestable(self):
        """Las compras propias del dueño no entran a la bandeja."""
        self.assertFalse(self.provider.is_ingestable(OUTGOING))

    def test_qr_and_alias_are_ingestable(self):
        """Los cobros por QR y por alias sí entran."""
        self.assertTrue(self.provider.is_ingestable(QR_EXTERNAL))
        self.assertTrue(self.provider.is_ingestable(QR_INTERNAL))
        self.assertTrue(self.provider.is_ingestable(ALIAS))

    def test_amount_is_gross_never_net(self):
        """Se guarda transaction_amount, no net_received_amount."""
        self.assertEqual(self.provider.normalize(QR_EXTERNAL)["amount"], 1500)
        self.assertEqual(self.provider.normalize(QR_INTERNAL)["amount"], 100)

    def test_external_wallet_gives_bank_not_identity(self):
        """INTER_PSP trae banco de origen y oculta la identificación."""
        row = self.provider.normalize(QR_EXTERNAL)
        self.assertEqual(row["source"], "qr")
        self.assertEqual(row["mp_pos_id"], "64365871")
        self.assertEqual(row["payer_bank_name"], "Naranja Digital Compañia Financiera S.A.")
        self.assertFalse(row["payer_vat"])
        self.assertEqual(row["mp_payer_id"], "1893987077")

    def test_mercadopago_wallet_gives_identity_not_bank(self):
        """INTRA_PSP trae CUIT y email reales, sin banco de origen."""
        row = self.provider.normalize(QR_INTERNAL)
        self.assertEqual(row["source"], "qr")
        self.assertEqual(row["payer_vat"], "27964493338")
        self.assertEqual(row["payer_email"], "erojasmontealegre@gmail.com")
        self.assertFalse(row["payer_bank_name"])

    def test_alias_never_persists_payer_identity(self):
        """En el canal alias el payer es el receptor: se descarta entero."""
        row = self.provider.normalize(ALIAS)
        self.assertEqual(row["source"], "alias")
        self.assertFalse(row["payer_vat"])
        self.assertFalse(row["payer_email"])
        self.assertFalse(row["mp_payer_id"])
        self.assertFalse(row["mp_pos_id"])
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `ImportError` sobre `inbox_provider_mercadopago`.

- [ ] **Step 3: Implementar el provider**

`pos_mercadopago_validator/services/inbox_provider.py`:
```python
class InboxProvider:
    """Interfaz de un proveedor de pagos para la bandeja.

    Permite sumar otro procesador sin tocar el modelo de bandeja, el diálogo
    del POS ni la lógica de imputación.
    """

    def fetch_payments(self, window_start, window_end):
        """Devuelve los pagos crudos de la ventana."""
        raise NotImplementedError

    def get_payment(self, payment_id):
        """Devuelve un pago crudo puntual."""
        raise NotImplementedError

    def parse_notification(self, payload):
        """Extrae el identificador del pago de una notificación."""
        raise NotImplementedError

    def is_ingestable(self, raw):
        """Indica si el pago crudo corresponde a la bandeja."""
        raise NotImplementedError

    def normalize(self, raw):
        """Convierte el pago crudo en un dict de campos del modelo."""
        raise NotImplementedError
```

`pos_mercadopago_validator/services/inbox_provider_mercadopago.py`:
```python
import logging

from .inbox_provider import InboxProvider

_logger = logging.getLogger(__name__)

SUB_UNIT_QR = "qr"
SUB_UNIT_ALIAS = "money_inflows"
INGESTABLE_SUB_UNITS = (SUB_UNIT_QR, SUB_UNIT_ALIAS)


class MercadoPagoInboxProvider(InboxProvider):
    """Normaliza los pagos de Mercado Pago hacia el modelo de bandeja.

    Las reglas de esta clase salen de la verificación empírica del 2026-08-03
    documentada en el spec; no inferirlas de la documentación de Mercado Pago.
    """

    def __init__(self, client, mp_user_id):
        self.client = client
        self.mp_user_id = str(mp_user_id)

    # -- ingesta --------------------------------------------------------

    def fetch_payments(self, window_start, window_end):
        """Trae los pagos acreditados de la ventana, paginando."""
        results, offset = [], 0
        while True:
            page = self.client.search_payments(window_start, window_end, limit=50, offset=offset)
            batch = page.get("results", [])
            results.extend(batch)
            paging = page.get("paging", {})
            offset += len(batch)
            if not batch or offset >= paging.get("total", 0):
                break
        return results

    def get_payment(self, payment_id):
        """Trae un pago puntual con credenciales propias."""
        return self.client.get_payment(payment_id)

    def parse_notification(self, payload):
        """Extrae únicamente el identificador del pago. Todo lo demás se descarta."""
        data = (payload or {}).get("data") or {}
        return data.get("id")

    # -- clasificación --------------------------------------------------

    def _business_info(self, raw):
        """Devuelve el business_info del pago, siempre un dict."""
        poi = raw.get("point_of_interaction") or {}
        return poi.get("business_info") or {}

    def is_ingestable(self, raw):
        """Filtro de §6.1: sólo cobros acreditados propios, por QR o alias."""
        if raw.get("status") != "approved" or raw.get("status_detail") != "accredited":
            return False
        if str(raw.get("collector_id") or "") != self.mp_user_id:
            return False
        return self._business_info(raw).get("sub_unit") in INGESTABLE_SUB_UNITS

    # -- normalización --------------------------------------------------

    def normalize(self, raw):
        """Convierte un pago crudo en campos del modelo de bandeja.

        La identificación del pagador sólo se conserva en el canal QR: en el
        canal alias Mercado Pago devuelve los datos del receptor (§2.3).
        """
        poi = raw.get("point_of_interaction") or {}
        is_qr = self._business_info(raw).get("sub_unit") == SUB_UNIT_QR
        payer = raw.get("payer") or {}
        bank_payer = (
            ((poi.get("transaction_data") or {}).get("bank_info") or {}).get("payer") or {}
        )

        row = {
            "mp_payment_id": str(raw["id"]),
            "amount": raw["transaction_amount"],
            "date_approved": self._parse_datetime(raw.get("date_approved")),
            "source": "qr" if is_qr else "alias",
            "mp_pos_id": str(raw["pos_id"]) if is_qr and raw.get("pos_id") else False,
            "payer_bank_name": bank_payer.get("long_name") or False,
            "payment_method_detail": raw.get("payment_method_id"),
            "raw_status": raw.get("status_detail"),
            "payer_vat": False,
            "payer_email": False,
            "mp_payer_id": False,
        }

        if is_qr:
            payer_id = str(payer.get("id") or "")
            # Red de seguridad: si el payer es el propio collector, el dato es
            # del receptor y no se guarda.
            if payer_id and payer_id != self.mp_user_id:
                row["mp_payer_id"] = payer_id
                row["payer_email"] = payer.get("email") or False
                row["payer_vat"] = (payer.get("identification") or {}).get("number") or False

        return row

    def _parse_datetime(self, value):
        """Convierte el ISO-8601 con offset de MP a naive UTC para Odoo."""
        from datetime import datetime

        if not value:
            return False
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            from datetime import timezone

            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
```

Agregar a `tests/__init__.py`: `from . import test_normalization`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `14 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): normalización de pagos con reglas por canal QR/alias"
```

---

## Task 5: Upsert idempotente y cron del ingestor

**Files:**
- Modify: `pos_mercadopago_validator/models/mercadopago_payment.py`, `models/mercadopago_account.py`
- Create: `pos_mercadopago_validator/data/ir_cron.xml`
- Modify: `pos_mercadopago_validator/__manifest__.py`
- Test: `pos_mercadopago_validator/tests/test_ingestor.py`

**Interfaces:**
- Produces: `mercadopago.payment.ingest_raw(account, raw_list) -> recordset` y `mercadopago.account.cron_ingest_payments()`.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_ingestor.py`:
```python
from odoo.tests.common import TransactionCase, tagged

from .test_normalization import ALIAS, OUTGOING, QR_EXTERNAL, QR_INTERNAL


@tagged("post_install", "-at_install")
class TestIngestor(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        self.Inbox = self.env["mercadopago.payment"]

    def test_ingest_creates_only_ingestable_payments(self):
        """Los pagos salientes se descartan en la ingesta."""
        self.Inbox.ingest_raw(self.account, [QR_EXTERNAL, ALIAS, OUTGOING])
        self.assertEqual(self.Inbox.search_count([("account_id", "=", self.account.id)]), 2)

    def test_ingest_is_idempotent(self):
        """La misma notificación entregada tres veces produce un solo registro."""
        for _ in range(3):
            self.Inbox.ingest_raw(self.account, [QR_EXTERNAL])
        self.assertEqual(
            self.Inbox.search_count([("mp_payment_id", "=", "170951482351")]), 1
        )

    def test_ingest_resolves_partner_by_vat(self):
        """El CUIT del canal INTRA_PSP resuelve el cliente contra res.partner."""
        partner = self.env["res.partner"].create({
            "name": "Cliente Conocido", "vat": "27964493338",
        })
        self.Inbox.ingest_raw(self.account, [QR_INTERNAL])
        payment = self.Inbox.search([("mp_payment_id", "=", "171858334766")])
        self.assertEqual(payment.partner_id, partner)
        self.assertEqual(payment.display_payer, "Cliente Conocido")

    def test_ingest_does_not_reopen_matched_payment(self):
        """Un pago ya imputado no vuelve a available por una reingesta."""
        self.Inbox.ingest_raw(self.account, [QR_EXTERNAL])
        payment = self.Inbox.search([("mp_payment_id", "=", "170951482351")])
        payment.write({"state": "matched"})
        self.Inbox.ingest_raw(self.account, [QR_EXTERNAL])
        self.assertEqual(payment.state, "matched")
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `AttributeError: 'mercadopago.payment' object has no attribute 'ingest_raw'`.

- [ ] **Step 3: Implementar la ingesta**

Agregar a `models/mercadopago_payment.py`:
```python
    @api.model
    def ingest_raw(self, account, raw_payments):
        """Upsert idempotente de pagos crudos. Único camino de escritura.

        Tanto el webhook como el cron entran por acá: dos caminos distintos para
        el mismo dato es como aparecen las inconsistencias irreproducibles.
        """
        from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider

        provider = MercadoPagoInboxProvider(client=None, mp_user_id=account.mp_user_id)
        currency = account.company_id.currency_id
        created = self.browse()

        for raw in raw_payments:
            if not provider.is_ingestable(raw):
                continue
            values = provider.normalize(raw)
            existing = self.search([("mp_payment_id", "=", values["mp_payment_id"])], limit=1)
            if existing:
                # Nunca se reabre un pago ya imputado ni se pisa su vínculo.
                if existing.state == "available":
                    existing.write(self._values_without_state(values))
                continue
            values.update({
                "account_id": account.id,
                "currency_id": currency.id,
                "state": "available",
                "partner_id": self._resolve_partner(values).id,
            })
            created |= self.create(values)

        _logger.info(
            "Ingesta Mercado Pago cuenta %s: %s pagos nuevos de %s recibidos",
            account.name, len(created), len(raw_payments),
        )
        return created

    @api.model
    def _values_without_state(self, values):
        """Quita del dict las claves que no deben pisarse en una reingesta."""
        return {k: v for k, v in values.items() if k not in ("state", "mp_payment_id")}

    @api.model
    def _resolve_partner(self, values):
        """Busca el cliente por CUIT y, si no, por mapeo previo del payer id."""
        Partner = self.env["res.partner"]
        if values.get("payer_vat"):
            partner = Partner.search([("vat", "=", values["payer_vat"])], limit=1)
            if partner:
                return partner
        if values.get("mp_payer_id"):
            mapped = self.search([
                ("mp_payer_id", "=", values["mp_payer_id"]),
                ("partner_id", "!=", False),
            ], limit=1)
            if mapped:
                return mapped.partner_id
        return Partner.browse()
```

Agregar a `models/mercadopago_account.py`:
```python
    def _window_minutes(self):
        """Mayor ventana configurada entre los métodos de pago de esta cuenta."""
        methods = self.env["pos.payment.method"].search([("mp_account_id", "=", self.id)])
        return max(methods.mapped("search_window_minutes") or [5])

    def ingest_now(self):
        """Consulta la ventana y vuelca el resultado en la bandeja."""
        from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider
        from ..services.mp_client import MercadoPagoAuthError, MercadoPagoTransientError, MercadoPagoClient

        for account in self:
            provider = MercadoPagoInboxProvider(
                MercadoPagoClient(account.sudo().access_token), account.mp_user_id
            )
            try:
                raw = provider.fetch_payments("NOW-%sMINUTES" % account._window_minutes(), "NOW")
            except MercadoPagoAuthError as error:
                account.sudo().write({"last_sync_error": str(error), "active": False})
                _logger.error("Credenciales rechazadas para la cuenta %s", account.name)
                continue
            except MercadoPagoTransientError as error:
                account.sudo().write({"last_sync_error": str(error)})
                _logger.warning("Bandeja desactualizada para %s: %s", account.name, error)
                continue

            created = self.env["mercadopago.payment"].ingest_raw(account, raw)
            account.sudo().write({
                "last_sync_at": fields.Datetime.now(), "last_sync_error": False,
            })
            if created:
                created._notify_open_sessions()

    @api.model
    def cron_ingest_payments(self):
        """Cron del ingestor. Sólo corre si hay una sesión de POS abierta."""
        open_sessions = self.env["pos.session"].search_count([("state", "=", "opened")])
        if not open_sessions:
            return
        self.search([("active", "=", True)]).ingest_now()
```

`data/ir_cron.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="cron_mercadopago_ingest" model="ir.cron">
        <field name="name">Mercado Pago: ingestar pagos recibidos</field>
        <field name="model_id" ref="model_mercadopago_account"/>
        <field name="state">code</field>
        <field name="code">model.cron_ingest_payments()</field>
        <field name="interval_number">1</field>
        <field name="interval_type">minutes</field>
        <field name="active" eval="True"/>
    </record>
</odoo>
```

Agregar `"data/ir_cron.xml"` al final de `data` en el manifest.

Agregar un stub de `_notify_open_sessions` en `mercadopago_payment.py` (se completa en Task 10):
```python
    def _notify_open_sessions(self):
        """Avisa por bus a las cajas con sesión abierta. Se completa en Task 10."""
        return True
```

Agregar a `tests/__init__.py`: `from . import test_ingestor`.

- [ ] **Step 4: Correr y verificar que pasa**

Nota: `test_ingest_resolves_partner_by_vat` requiere el campo `mp_account_id` en `pos.payment.method`, que llega en Task 6. Si falla `_window_minutes`, es esperable en este punto — la llamada sólo ocurre en `ingest_now`, no en `ingest_raw`, así que los cuatro tests deben pasar igual.

Expected: `18 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): upsert idempotente y cron del ingestor"
```

---

## Task 6: Configuración por caja en `pos.payment.method`

**Files:**
- Create: `pos_mercadopago_validator/models/pos_payment_method.py`
- Create: `pos_mercadopago_validator/views/pos_payment_method_views.xml`
- Modify: `models/__init__.py`, `__manifest__.py`
- Test: `pos_mercadopago_validator/tests/test_payment_method.py`

**Interfaces:**
- Produces: campos `mp_account_id`, `mp_pos_id`, `accept_alias_payments`, `auto_impute_single_match`, `search_window_minutes`, `poll_interval_seconds`, `amount_tolerance`, `require_manager_for_manual`; terminal `mercadopago_validator`.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_payment_method.py`:
```python
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPaymentMethodConfig(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "access_token": "APP_USR-secreto",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "Mercado Pago QR",
            "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id,
            "mp_pos_id": "64365871",
        })

    def test_terminal_option_is_registered(self):
        """La opción aparece en el selector de terminal de pago."""
        selection = self.method._get_payment_terminal_selection()
        self.assertIn("mercadopago_validator", dict(selection))

    def test_defaults_match_spec(self):
        """Los defaults son los acordados: sin auto-imputación, ventana de 5 minutos."""
        self.assertFalse(self.method.auto_impute_single_match)
        self.assertFalse(self.method.accept_alias_payments)
        self.assertEqual(self.method.search_window_minutes, 5)
        self.assertEqual(self.method.amount_tolerance, 0.0)
        self.assertFalse(self.method.require_manager_for_manual)

    def test_no_credential_is_synced_to_the_browser(self):
        """RNF-002: ningún campo de credenciales entra en la carga del POS."""
        fields_sent = self.env["pos.payment.method"]._load_pos_data_fields(False)
        for forbidden in ("access_token", "webhook_secret", "mp_account_id"):
            self.assertNotIn(forbidden, fields_sent)
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `ValueError` sobre el valor `mercadopago_validator` de `use_payment_terminal`.

- [ ] **Step 3: Implementar**

`pos_mercadopago_validator/models/pos_payment_method.py`:
```python
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    mp_account_id = fields.Many2one(
        "mercadopago.account", string="Cuenta de Mercado Pago",
        help="Varias cajas pueden apuntar a la misma cuenta con QR distintos.",
    )
    mp_pos_id = fields.Char(
        string="ID del QR (caja)",
        help="pos_id del QR de esta caja. Separa la bandeja de las demás cajas.",
    )
    accept_alias_payments = fields.Boolean(
        string="Aceptar cobros por alias",
        help="Los cobros por alias no traen caja ni pagador identificable.",
    )
    auto_impute_single_match = fields.Boolean(
        string="Imputar solo cuando hay un único candidato",
        help="Desactivado, el cajero confirma siempre.",
    )
    search_window_minutes = fields.Integer(default=5, required=True)
    poll_interval_seconds = fields.Integer(default=10, required=True)
    amount_tolerance = fields.Float(
        default=0.0,
        help="0 significa sólo coincidencia exacta de monto.",
    )
    require_manager_for_manual = fields.Boolean(
        string="Exigir encargado para aprobación manual",
    )

    def _get_payment_terminal_selection(self):
        """Agrega el validador de Mercado Pago al selector de terminal."""
        return super()._get_payment_terminal_selection() + [
            ("mercadopago_validator", "Mercado Pago - Validador de QR")
        ]

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Campos que el POS sincroniza al navegador.

        Whitelist explícita: ninguna credencial entra acá. Ver RNF-002.
        """
        return super()._load_pos_data_fields(config_id) + [
            "mp_pos_id", "accept_alias_payments", "auto_impute_single_match",
            "search_window_minutes", "poll_interval_seconds", "amount_tolerance",
            "require_manager_for_manual",
        ]

    def _check_pos_access(self):
        """Verifica que quien llama por RPC sea un usuario del POS."""
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("No tenés acceso a la bandeja de Mercado Pago."))
```

`views/pos_payment_method_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_pos_payment_method_form_mp" model="ir.ui.view">
        <field name="name">pos.payment.method.form.mercadopago</field>
        <field name="model">pos.payment.method</field>
        <field name="inherit_id" ref="point_of_sale.pos_payment_method_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//group" position="after">
                <group string="Mercado Pago - Validador de QR"
                       invisible="use_payment_terminal != 'mercadopago_validator'">
                    <group>
                        <field name="mp_account_id"/>
                        <field name="mp_pos_id"/>
                        <field name="accept_alias_payments"/>
                    </group>
                    <group>
                        <field name="search_window_minutes"/>
                        <field name="poll_interval_seconds"/>
                        <field name="amount_tolerance"/>
                        <field name="auto_impute_single_match"/>
                        <field name="require_manager_for_manual"/>
                    </group>
                </group>
            </xpath>
        </field>
    </record>
</odoo>
```

Agregar `"views/pos_payment_method_views.xml"` al manifest, `from . import pos_payment_method` a `models/__init__.py`, y `from . import test_payment_method` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `21 tests, 0 failed`. El test `test_no_credential_is_synced_to_the_browser` es el que cubre RNF-002.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): configuración por caja con QR propio y sin credenciales al navegador"
```

---

## Task 7: Imputación con bloqueo de fila y prueba de concurrencia

**Criterio de salida de la fase 3 del spec. No avanzar sin el test de concurrencia en verde.**

**Files:**
- Modify: `pos_mercadopago_validator/models/mercadopago_payment.py`
- Create: `pos_mercadopago_validator/models/pos_payment.py`
- Modify: `models/__init__.py`
- Test: `pos_mercadopago_validator/tests/test_imputacion_unica.py`

**Interfaces:**
- Produces: `mercadopago.payment.impute(pos_payment, ambiguous=False)`, que lanza `UserError` si el pago ya fue imputado; y `mercadopago.payment.revert()`.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_imputacion_unica.py`:
```python
import odoo
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestImputacionUnica(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        self.payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351",
            "account_id": self.account.id,
            "amount": 1500.0,
            "date_approved": "2026-08-03 15:21:49",
            "source": "qr",
            "state": "available",
        })

    def _make_pos_payment(self, amount=1500.0):
        """Crea una línea de pago mínima sobre la que imputar."""
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        config = self.env["pos.config"].create({"name": "Caja test"})
        config.write({"payment_method_ids": [(4, method.id)]})
        config.open_ui()
        session = config.current_session_id
        order = self.env["pos.order"].create({
            "session_id": session.id, "amount_total": amount, "amount_tax": 0,
            "amount_paid": 0, "amount_return": 0,
        })
        return self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": method.id, "amount": amount,
        })

    def test_impute_links_and_locks(self):
        """Una imputación normal vincula el pago y lo saca de disponible."""
        line = self._make_pos_payment()
        self.payment.impute(line)
        self.assertEqual(self.payment.state, "matched")
        self.assertEqual(self.payment.pos_payment_id, line)
        self.assertEqual(self.payment.matched_by_user_id, self.env.user)
        self.assertTrue(self.payment.matched_at)

    def test_second_imputation_is_rejected(self):
        """Un pago ya imputado no se puede imputar de nuevo."""
        first = self._make_pos_payment()
        second = self._make_pos_payment()
        self.payment.impute(first)
        with self.assertRaises(UserError):
            self.payment.impute(second)

    def test_concurrent_imputation_yields_exactly_one(self):
        """Dos transacciones simultáneas sobre el mismo pago: una gana, una falla.

        Criterio de salida de la fase 3. Usa dos cursores reales para que el
        bloqueo de fila se ejerza de verdad, no simulado.
        """
        self.env.cr.commit()
        line_a = self._make_pos_payment()
        line_b = self._make_pos_payment()
        self.env.cr.commit()

        registry = odoo.registry(self.env.cr.dbname)
        outcomes = []
        with registry.cursor() as cr_a, registry.cursor() as cr_b:
            env_a = odoo.api.Environment(cr_a, self.env.uid, {})
            env_b = odoo.api.Environment(cr_b, self.env.uid, {})
            payment_a = env_a["mercadopago.payment"].browse(self.payment.id)
            payment_b = env_b["mercadopago.payment"].browse(self.payment.id)

            payment_a.impute(env_a["pos.payment"].browse(line_a.id))
            outcomes.append("a")
            cr_a.commit()

            try:
                with mute_logger("odoo.sql_db"):
                    payment_b.impute(env_b["pos.payment"].browse(line_b.id))
                outcomes.append("b")
                cr_b.commit()
            except Exception:
                cr_b.rollback()

        self.assertEqual(outcomes, ["a"], "Se imputó más de una vez el mismo pago")
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.pos_payment_id.id, line_a.id)
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `AttributeError: ... has no attribute 'impute'`.

- [ ] **Step 3: Implementar la imputación**

Agregar a `models/mercadopago_payment.py`:
```python
    def impute(self, pos_payment, ambiguous=False):
        """Vincula este pago con una línea de cobro del POS, de forma definitiva.

        Toma la fila con SELECT ... FOR UPDATE antes de decidir: dos cajeros
        pueden hacer clic con milisegundos de diferencia sobre la misma lista.
        El índice único parcial actúa como red final si el bloqueo falla.
        """
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state FROM mercadopago_payment WHERE id = %s FOR UPDATE", (self.id,)
        )
        row = self.env.cr.fetchone()
        if not row or row[0] != "available":
            raise UserError(_(
                "Ese pago ya fue asignado a otra venta. Actualizá la lista y elegí otro."
            ))

        order = pos_payment.pos_order_id
        difference = pos_payment.amount - self.amount
        self.write({
            "state": "matched",
            "pos_payment_id": pos_payment.id,
            "pos_order_id": order.id,
            "pos_session_id": order.session_id.id,
            "matched_by_user_id": self.env.user.id,
            "matched_at": fields.Datetime.now(),
            "amount_difference": difference,
            "ambiguous_pick": ambiguous,
        })
        pos_payment.write({"mercadopago_payment_id": self.id})
        _logger.info(
            "Pago %s imputado a la línea %s por %s",
            self.mp_payment_id, pos_payment.id, self.env.user.login,
        )
        return True

    def revert(self, reason=None):
        """Devuelve el pago a la bandeja. Queda registrado en el chatter del pedido."""
        self.ensure_one()
        if self.state != "matched":
            raise UserError(_("Sólo se puede revertir un pago imputado."))
        order = self.pos_order_id
        self.write({
            "state": "available", "pos_payment_id": False, "pos_order_id": False,
            "pos_session_id": False, "matched_by_user_id": False, "matched_at": False,
            "amount_difference": 0.0, "ambiguous_pick": False,
        })
        _logger.info(
            "Pago %s revertido por %s. Motivo: %s",
            self.mp_payment_id, self.env.user.login, reason or "sin motivo",
        )
        if order:
            order.message_post(body=_(
                "Se revirtió la imputación del pago de Mercado Pago %(mp)s. Motivo: %(reason)s",
                mp=self.mp_payment_id, reason=reason or _("sin motivo"),
            ))
        return True
```

Agregar el import de `UserError` al encabezado de `mercadopago_payment.py`:
```python
from odoo import _, api, fields, models
from odoo.exceptions import UserError
```

`pos_mercadopago_validator/models/pos_payment.py`:
```python
from odoo import fields, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    mercadopago_payment_id = fields.Many2one(
        "mercadopago.payment", string="Pago de Mercado Pago", readonly=True,
    )
    mercadopago_reference = fields.Char(
        related="mercadopago_payment_id.mp_payment_id", string="Referencia MP", store=True,
    )
    is_manual_approval = fields.Boolean(readonly=True)
    manual_reason = fields.Char(readonly=True)
    manual_approved_by_user_id = fields.Many2one("res.users", readonly=True)
    manual_approved_at = fields.Datetime(readonly=True)
```

Agregar `from . import pos_payment` a `models/__init__.py` y `from . import test_imputacion_unica` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u pos_mercadopago_validator \
  --test-enable --test-tags /pos_mercadopago_validator --stop-after-init --no-http
```
Expected: `24 tests, 0 failed`. **`test_concurrent_imputation_yields_exactly_one` debe estar en verde antes de seguir.**

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): imputación única con bloqueo de fila y prueba de concurrencia"
```

---

## Task 8: Webhook público

**Files:**
- Create: `pos_mercadopago_validator/controllers/webhook.py`
- Modify: `pos_mercadopago_validator/controllers/__init__.py`
- Test: `pos_mercadopago_validator/tests/test_webhook.py`

**Interfaces:**
- Produces: ruta `POST /pos_mercadopago_validator/notification`, `auth="public"`, `csrf=False`. Devuelve siempre `200` salvo payload ilegible.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_webhook.py`:
```python
import json
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestWebhook(HttpCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "access_token": "APP_USR-fake", "last_validated_at": "2026-08-03 12:00:00",
        })
        self.account.write({"active": True})
        self.env.cr.commit()

    def _post(self, payload):
        return self.url_open(
            "/pos_mercadopago_validator/notification",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )

    def test_malformed_payload_still_returns_200(self):
        """Un payload sin data.id no rompe: se responde 200 y se ignora."""
        response = self._post({"hola": "mundo"})
        self.assertEqual(response.status_code, 200)

    def test_only_the_id_is_read_from_the_body(self):
        """El cuerpo del webhook no es fuente de verdad: se reconsulta la API."""
        with patch.object(
            type(self.env["mercadopago.account"]), "ingest_payment_id", return_value=True
        ) as mocked:
            self._post({
                "type": "payment", "data": {"id": "170951482351"},
                "transaction_amount": 999999, "status": "approved",
            })
        self.assertTrue(mocked.called)
        self.assertEqual(mocked.call_args[0][0], "170951482351")
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: 404 en la ruta.

- [ ] **Step 3: Implementar**

Agregar a `models/mercadopago_account.py`:
```python
    def ingest_payment_id(self, payment_id):
        """Trae un pago puntual de la API y lo vuelca en la bandeja.

        Es el camino del webhook: del cuerpo de la notificación sólo se usó el
        identificador, y el dato real se resuelve con credenciales propias.
        """
        self.ensure_one()
        from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider
        from ..services.mp_client import MercadoPagoClient, MercadoPagoError, MercadoPagoTransientError

        provider = MercadoPagoInboxProvider(
            MercadoPagoClient(self.sudo().access_token), self.mp_user_id
        )
        try:
            raw = provider.get_payment(payment_id)
        except (MercadoPagoError, MercadoPagoTransientError) as error:
            _logger.warning("No se pudo resolver el pago %s: %s", payment_id, error)
            return False
        created = self.env["mercadopago.payment"].ingest_raw(self, [raw])
        if created:
            created._notify_open_sessions()
        return bool(created)
```

`pos_mercadopago_validator/controllers/webhook.py`:
```python
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MercadoPagoWebhook(http.Controller):
    """Endpoint público de notificaciones de Mercado Pago.

    En integraciones de QR no se puede validar el origen por x-Signature, así que
    el endpoint se asume alcanzable por cualquiera en internet. La defensa no es
    autenticar el origen sino desconfiar del contenido: del cuerpo se lee
    únicamente el identificador del pago, y todo lo demás se resuelve contra la
    API con credenciales propias.
    """

    @http.route(
        "/pos_mercadopago_validator/notification",
        type="http", auth="public", methods=["POST"], csrf=False, save_session=False,
    )
    def notification(self, **kwargs):
        """Responde 200 siempre; procesa sólo si el payload trae un id usable."""
        payload = request.get_json_data() if request.httprequest.data else None
        payment_id = ((payload or {}).get("data") or {}).get("id")

        if not payment_id:
            _logger.info("Notificación de Mercado Pago sin data.id, ignorada")
            return request.make_response("", status=200)

        accounts = request.env["mercadopago.account"].sudo().search([("active", "=", True)])
        for account in accounts:
            if account.ingest_payment_id(str(payment_id)):
                break

        return request.make_response("", status=200)
```

`pos_mercadopago_validator/controllers/__init__.py`:
```python
from . import webhook
```

Agregar `from . import test_webhook` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

El test de webhook necesita HTTP, así que este comando **no** lleva `--no-http`:
```bash
docker exec odoo-odoo-1 odoo -d calidad -u pos_mercadopago_validator \
  --test-enable --test-tags /pos_mercadopago_validator --stop-after-init
```
Expected: `26 tests, 0 failed`.

- [ ] **Step 5: Verificar que el módulo funciona con el webhook apagado**

Desactivar temporalmente el cron no; al revés: comprobar que sin ninguna notificación, `cron_ingest_payments` sigue poblando la bandeja. Es el criterio de aceptación 2.

```bash
docker exec odoo-odoo-1 odoo shell -d calidad --no-http <<'PY'
account = env["mercadopago.account"].search([("active", "=", True)], limit=1)
before = env["mercadopago.payment"].search_count([])
account.ingest_now()
print("pagos antes:", before, "| después:", env["mercadopago.payment"].search_count([]))
PY
```
Expected: la bandeja se puebla sin que haya llegado ningún webhook.

- [ ] **Step 6: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): webhook público que sólo lee el id del pago"
```

---

## Task 9: RPC de la bandeja para el POS

**Files:**
- Modify: `pos_mercadopago_validator/models/pos_payment_method.py`
- Test: `pos_mercadopago_validator/tests/test_inbox_rpc.py`

**Interfaces:**
- Produces: `pos.payment.method.get_mp_inbox(amount)` → `{"matching": [...], "others_count": int, "last_sync_at": str|False, "stale": bool}`, y `pos.payment.method.impute_mp_payment(inbox_line_id, pos_payment_id, ambiguous)`.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_inbox_rpc.py`:
```python
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInboxRpc(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        self.Inbox = self.env["mercadopago.payment"]

    def _payment(self, mp_id, amount, pos_id="64365871", source="qr"):
        return self.Inbox.create({
            "mp_payment_id": mp_id, "account_id": self.account.id, "amount": amount,
            "date_approved": fields_now(), "source": source, "mp_pos_id": pos_id,
            "state": "available",
        })

    def test_only_this_cash_register_qr_is_listed(self):
        """Un pago del QR de otra caja no aparece en esta bandeja."""
        self._payment("111", 1500.0, pos_id="64365871")
        self._payment("222", 1500.0, pos_id="99999999")
        result = self.method.get_mp_inbox(1500.0)
        self.assertEqual([p["mp_payment_id"] for p in result["matching"]], ["111"])

    def test_non_matching_amounts_are_counted_not_listed(self):
        """Los montos distintos no se listan pero se cuentan."""
        self._payment("111", 1500.0)
        self._payment("333", 980.0)
        result = self.method.get_mp_inbox(1500.0)
        self.assertEqual(len(result["matching"]), 1)
        self.assertEqual(result["others_count"], 1)

    def test_alias_excluded_unless_enabled(self):
        """El canal alias sólo entra si el método lo habilita."""
        self._payment("444", 1500.0, pos_id=False, source="alias")
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 0)
        self.method.accept_alias_payments = True
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 1)

    def test_stale_flag_when_never_synced(self):
        """Sin sincronización exitosa, la bandeja se reporta desactualizada."""
        self.assertTrue(self.method.get_mp_inbox(1500.0)["stale"])


def fields_now():
    from odoo import fields
    return fields.Datetime.now()
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `AttributeError: ... has no attribute 'get_mp_inbox'`.

- [ ] **Step 3: Implementar**

Agregar a `models/pos_payment_method.py`:
```python
    STALE_AFTER_SECONDS = 60

    def _inbox_domain(self):
        """Filtro de presentación: la bandeja de esta caja (§6.2 del spec)."""
        self.ensure_one()
        window_start = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=self.search_window_minutes
        )
        domain = [
            ("account_id", "=", self.mp_account_id.id),
            ("state", "=", "available"),
            ("date_approved", ">=", window_start),
        ]
        channel = ["|", ("mp_pos_id", "=", self.mp_pos_id), ("source", "=", "alias")] \
            if self.accept_alias_payments else [("mp_pos_id", "=", self.mp_pos_id)]
        return domain + channel

    def get_mp_inbox(self, amount):
        """Devuelve la bandeja de esta caja para el monto pedido.

        Nunca consulta a Mercado Pago: lee de la base de Odoo. El ingestor
        server-side es el único que habla con la API.
        """
        self.ensure_one()
        self._check_pos_access()
        Inbox = self.env["mercadopago.payment"].sudo()
        available = Inbox.search(self._inbox_domain())

        tolerance = self.amount_tolerance or 0.0
        matching = available.filtered(lambda p: abs(p.amount - amount) <= tolerance)
        account = self.mp_account_id.sudo()
        last_sync = account.last_sync_at
        stale = not last_sync or (
            fields.Datetime.now() - last_sync
        ).total_seconds() > self.STALE_AFTER_SECONDS

        return {
            "matching": [self._serialize_inbox_line(p, amount) for p in matching],
            "others": [self._serialize_inbox_line(p, amount) for p in (available - matching)],
            "others_count": len(available - matching),
            "last_sync_at": last_sync and last_sync.isoformat() or False,
            "stale": stale,
        }

    def _serialize_inbox_line(self, payment, requested_amount):
        """Arma la fila que ve el cajero. Sin datos que no correspondan."""
        return {
            "id": payment.id,
            "mp_payment_id": payment.mp_payment_id,
            "amount": payment.amount,
            "date_approved": payment.date_approved.isoformat(),
            "display_payer": payment.display_payer or "",
            "source": payment.source,
            "difference": round(requested_amount - payment.amount, 2),
        }

    def impute_mp_payment(self, inbox_line_id, pos_payment_id, ambiguous=False):
        """Imputa un pago a una línea. Devuelve el error de carrera si lo hay."""
        self.ensure_one()
        self._check_pos_access()
        payment = self.env["mercadopago.payment"].sudo().browse(inbox_line_id)
        pos_payment = self.env["pos.payment"].browse(pos_payment_id)
        try:
            payment.impute(pos_payment, ambiguous=ambiguous)
        except UserError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "mp_payment_id": payment.mp_payment_id}
```

Agregar el import de `UserError` en `pos_payment_method.py`:
```python
from odoo.exceptions import AccessError, UserError
```

Agregar `from . import test_inbox_rpc` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `30 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): RPC de bandeja filtrada por caja, tolerancia y antigüedad"
```

---

## Task 10: Notificación en vivo por bus

**Files:**
- Modify: `pos_mercadopago_validator/models/mercadopago_payment.py`
- Test: `pos_mercadopago_validator/tests/test_bus.py`

**Interfaces:**
- Produces: `mercadopago.payment._notify_open_sessions()`, que emite el evento `MERCADOPAGO_INBOX_UPDATED` en el canal privado de cada `pos.config` afectado.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_bus.py`:
```python
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBusNotification(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        self.config = self.env["pos.config"].create({"name": "Caja A"})
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()

    def test_notifies_only_configs_with_that_qr(self):
        """El bus es por pos.config: sólo se notifica a la caja dueña del QR."""
        other_config = self.env["pos.config"].create({"name": "Caja B"})
        payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": "2026-08-03 15:21:49",
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })
        notified = []
        original = type(self.env["pos.config"])._notify

        def spy(self_config, *args, **kwargs):
            notified.append(self_config.id)
            return original(self_config, *args, **kwargs)

        with patch.object(type(self.env["pos.config"]), "_notify", spy):
            payment._notify_open_sessions()

        self.assertIn(self.config.id, notified)
        self.assertNotIn(other_config.id, notified)
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: el stub de Task 5 devuelve `True` sin notificar → `assertIn` falla.

- [ ] **Step 3: Reemplazar el stub por la implementación**

En `models/mercadopago_payment.py`, reemplazar el stub `_notify_open_sessions` por:
```python
    def _notify_open_sessions(self):
        """Avisa a las cajas con sesión abierta que la bandeja cambió.

        El bus de Odoo 18 publica en el canal privado de cada pos.config
        (pos.bus.mixin, token propio por config). No hay canal global: hay que
        iterar los configs afectados y notificar a cada uno.
        """
        Config = self.env["pos.config"].sudo()
        for payment in self:
            methods = self.env["pos.payment.method"].sudo().search([
                ("mp_account_id", "=", payment.account_id.id),
                "|",
                ("mp_pos_id", "=", payment.mp_pos_id),
                "&", ("accept_alias_payments", "=", True), ("id", "!=", 0),
            ])
            if payment.source == "qr":
                methods = methods.filtered(lambda m: m.mp_pos_id == payment.mp_pos_id)
            else:
                methods = methods.filtered(lambda m: m.accept_alias_payments)

            configs = Config.search([
                ("payment_method_ids", "in", methods.ids),
                ("current_session_state", "=", "opened"),
            ])
            for config in configs:
                config._notify("MERCADOPAGO_INBOX_UPDATED", {
                    "config_id": config.id,
                    "mp_payment_id": payment.mp_payment_id,
                    "amount": payment.amount,
                    "state": payment.state,
                })
        return True
```

Agregar `from . import test_bus` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `31 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): notificación en vivo por bus a la caja dueña del QR"
```

---

## Task 11: `PaymentInterface` y diálogo de bandeja en el POS

**Files:**
- Create: `static/src/app/payment_mercadopago_validator.js`, `static/src/app/inbox_dialog.js`, `static/src/app/inbox_dialog.xml`, `static/src/app/inbox_dialog.scss`, `static/src/app/pos_store.js`
- Modify: `__manifest__.py`

**Interfaces:**
- Consumes: `pos.payment.method.get_mp_inbox(amount)` y `impute_mp_payment(...)` de Task 9; evento de bus `MERCADOPAGO_INBOX_UPDATED` de Task 10.
- Produces: terminal `mercadopago_validator` registrado en el POS.

- [ ] **Step 1: Agregar los assets al manifest**

```python
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_mercadopago_validator/static/src/app/*.js",
            "pos_mercadopago_validator/static/src/app/*.xml",
            "pos_mercadopago_validator/static/src/app/*.scss",
        ],
    },
```

- [ ] **Step 2: Escribir el `PaymentInterface`**

`static/src/app/payment_mercadopago_validator.js`:
```javascript
/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { MercadoPagoInboxDialog } from "@pos_mercadopago_validator/app/inbox_dialog";

export class PaymentMercadoPagoValidator extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.pendingResolver = null;
    }

    // El cajero fija el monto antes de que se abra la bandeja.
    get fast_payments() {
        return false;
    }

    async send_payment_request(uuid) {
        await super.send_payment_request(...arguments);
        const line = this.pos.get_order().get_selected_paymentline();
        line.set_payment_status("waitingCard");

        return new Promise((resolve) => {
            this.pendingResolver = resolve;
            this.env.services.dialog.add(MercadoPagoInboxDialog, {
                paymentMethod: line.payment_method_id,
                amount: line.amount,
                onPicked: async (inboxLine, ambiguous) => {
                    const result = await this._impute(line, inboxLine, ambiguous);
                    if (!result.ok) {
                        this.env.services.dialog.add(AlertDialog, {
                            title: _t("Pago ya asignado"),
                            body: result.error,
                        });
                        return false;
                    }
                    line.set_receipt_info(
                        _t("Mercado Pago %s", result.mp_payment_id)
                    );
                    line.transaction_id = result.mp_payment_id;
                    line.set_payment_status("done");
                    this._resolve(true);
                    return true;
                },
                onManualApproval: async (reason) => {
                    await this.env.services.orm.call(
                        "pos.payment.method", "register_manual_approval",
                        [[line.payment_method_id.id], line.uuid, reason]
                    );
                    line.set_payment_status("done");
                    this._resolve(true);
                },
                onCancel: () => this._resolve(false),
            });
        });
    }

    async _impute(line, inboxLine, ambiguous) {
        // La línea todavía no existe en el servidor: se imputa por uuid.
        return await this.env.services.orm.silent.call(
            "pos.payment.method", "impute_mp_payment_by_uuid",
            [[line.payment_method_id.id], inboxLine.id, line.uuid, ambiguous]
        );
    }

    _resolve(value) {
        this.pendingResolver?.(value);
        this.pendingResolver = null;
    }

    async send_payment_cancel(order, uuid) {
        await super.send_payment_cancel(order, uuid);
        this._resolve(false);
        return true;
    }
}
```

- [ ] **Step 3: Escribir el diálogo**

`static/src/app/inbox_dialog.js`:
```javascript
/** @odoo-module **/
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class MercadoPagoInboxDialog extends Component {
    static template = "pos_mercadopago_validator.InboxDialog";
    static components = { Dialog };
    static props = {
        paymentMethod: Object,
        amount: Number,
        onPicked: Function,
        onManualApproval: Function,
        onCancel: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.pos = useService("pos");
        this.state = useState({
            matching: [],
            others: [],
            othersCount: 0,
            showOthers: false,
            stale: true,
            lastSyncAt: false,
            loading: true,
            manualStep: 0,
            manualReason: "",
        });

        onWillStart(async () => {
            await this.refresh();
            if (this.state.matching.length === 1 &&
                this.props.paymentMethod.auto_impute_single_match) {
                await this.pick(this.state.matching[0]);
            }
        });

        this.poller = setInterval(
            () => this.refresh(),
            (this.props.paymentMethod.poll_interval_seconds || 10) * 1000
        );
        onWillUnmount(() => clearInterval(this.poller));

        this.pos.data.connectWebSocket("MERCADOPAGO_INBOX_UPDATED", () => this.refresh());
    }

    async refresh() {
        const result = await this.orm.silent.call(
            "pos.payment.method", "get_mp_inbox",
            [[this.props.paymentMethod.id], this.props.amount]
        );
        Object.assign(this.state, {
            matching: result.matching,
            others: result.others,
            othersCount: result.others_count,
            stale: result.stale,
            lastSyncAt: result.last_sync_at,
            loading: false,
        });
    }

    // Dos filas son indistinguibles si comparten monto y no tienen identificador.
    get isAmbiguous() {
        if (this.state.matching.length < 2) {
            return false;
        }
        const identified = this.state.matching.filter((l) => l.display_payer);
        return identified.length === 0;
    }

    async pick(line) {
        const accepted = await this.props.onPicked(line, this.isAmbiguous);
        if (accepted) {
            this.props.close();
        } else {
            await this.refresh();
        }
    }

    formatTime(iso) {
        return new Date(iso).toLocaleTimeString("es-AR");
    }

    startManual() {
        this.state.manualStep = 1;
    }

    async confirmManual() {
        if (!this.state.manualReason.trim()) {
            return;
        }
        if (this.state.manualStep === 1) {
            this.state.manualStep = 2;
            return;
        }
        await this.props.onManualApproval(this.state.manualReason);
        this.props.close();
    }

    cancel() {
        this.props.onCancel();
        this.props.close();
    }

    get staleLabel() {
        if (!this.state.lastSyncAt) {
            return _t("La bandeja nunca se sincronizó con Mercado Pago.");
        }
        return _t("Datos desactualizados. Última sincronización: %s",
                  this.formatTime(this.state.lastSyncAt));
    }
}
```

- [ ] **Step 4: Escribir la plantilla y el estilo**

`static/src/app/inbox_dialog.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">
    <t t-name="pos_mercadopago_validator.InboxDialog">
        <Dialog title="'Pagos recibidos'" size="'md'">
            <div class="mp-inbox">
                <div t-if="state.stale" class="mp-inbox-stale">
                    <t t-esc="staleLabel"/>
                </div>

                <div t-if="state.loading" class="mp-inbox-empty">Consultando…</div>

                <div t-elif="!state.matching.length" class="mp-inbox-empty">
                    <p>No hay pagos de <t t-esc="props.amount"/> en los últimos minutos.</p>
                    <button t-if="state.othersCount" class="btn btn-link"
                            t-on-click="() => state.showOthers = !state.showOthers">
                        Hay <t t-esc="state.othersCount"/> pago(s) de otro monto
                    </button>
                </div>

                <div t-else="" class="mp-inbox-list">
                    <div t-if="isAmbiguous" class="mp-inbox-warning">
                        Estos pagos no se pueden distinguir entre sí. Elegí el más reciente.
                    </div>
                    <button t-foreach="state.matching" t-as="line" t-key="line.id"
                            class="mp-inbox-row" t-on-click="() => this.pick(line)">
                        <span class="mp-amount"><t t-esc="line.amount"/></span>
                        <span class="mp-time"><t t-esc="formatTime(line.date_approved)"/></span>
                        <span class="mp-payer">
                            <t t-if="line.display_payer"><t t-esc="line.display_payer"/></t>
                            <t t-else="">Sin identificar</t>
                        </span>
                        <span t-if="line.difference" class="mp-diff">
                            Diferencia: <t t-esc="line.difference"/>
                        </span>
                    </button>
                </div>

                <div t-if="state.showOthers" class="mp-inbox-others">
                    <div t-foreach="state.others" t-as="line" t-key="line.id" class="mp-inbox-row-muted">
                        <t t-esc="line.amount"/> — <t t-esc="formatTime(line.date_approved)"/>
                    </div>
                </div>

                <div class="mp-inbox-manual">
                    <button t-if="!state.manualStep" class="btn btn-outline-danger"
                            t-on-click="startManual">
                        Aprobar sin verificar el pago
                    </button>
                    <div t-if="state.manualStep">
                        <p t-if="state.manualStep === 2" class="mp-inbox-warning">
                            Estás registrando un cobro SIN verificación de pago.
                            Queda auditado con tu usuario.
                        </p>
                        <input type="text" class="form-control" placeholder="Motivo (obligatorio)"
                               t-model="state.manualReason"/>
                        <button class="btn btn-danger" t-on-click="confirmManual">
                            <t t-if="state.manualStep === 1">Continuar</t>
                            <t t-else="">Confirmar cobro sin verificar</t>
                        </button>
                    </div>
                </div>
            </div>
            <t t-set-slot="footer">
                <button class="btn btn-secondary" t-on-click="cancel">Cancelar</button>
            </t>
        </Dialog>
    </t>
</templates>
```

`static/src/app/inbox_dialog.scss`:
```scss
.mp-inbox {
    .mp-inbox-stale, .mp-inbox-warning {
        background: #fff3cd;
        border: 1px solid #ffe08a;
        border-radius: 4px;
        padding: 8px 12px;
        margin-bottom: 8px;
        font-weight: 600;
    }
    .mp-inbox-row {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        gap: 8px;
        width: 100%;
        text-align: left;
        padding: 12px;
        border: 1px solid #dee2e6;
        border-radius: 6px;
        margin-bottom: 6px;
        background: #fff;
        &:hover { background: #eef5ff; }
        .mp-amount { font-size: 1.2rem; font-weight: 700; }
        .mp-time { color: #6c757d; }
        .mp-payer { text-align: right; }
        .mp-diff { grid-column: 1 / -1; color: #b45309; }
    }
    .mp-inbox-empty { padding: 16px; text-align: center; color: #6c757d; }
    .mp-inbox-manual { margin-top: 16px; border-top: 1px solid #dee2e6; padding-top: 12px; }
}
```

`static/src/app/pos_store.js`:
```javascript
/** @odoo-module **/
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { PaymentMercadoPagoValidator } from "@pos_mercadopago_validator/app/payment_mercadopago_validator";

register_payment_method("mercadopago_validator", PaymentMercadoPagoValidator);
```

- [ ] **Step 5: Agregar los RPC que consume el front**

Agregar a `models/pos_payment_method.py`:
```python
    def impute_mp_payment_by_uuid(self, inbox_line_id, pos_payment_uuid, ambiguous=False):
        """Imputa contra una línea que todavía vive sólo en el navegador.

        La línea de pago se crea en el servidor recién al confirmar la venta, así
        que se guarda el vínculo de forma diferida sobre el uuid de la línea.
        """
        self.ensure_one()
        self._check_pos_access()
        payment = self.env["mercadopago.payment"].sudo().browse(inbox_line_id)
        try:
            payment.reserve_for_uuid(pos_payment_uuid, ambiguous=ambiguous)
        except UserError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "mp_payment_id": payment.mp_payment_id}

    def register_manual_approval(self, pos_payment_uuid, reason):
        """Registra una aprobación manual sobre una línea del navegador."""
        self.ensure_one()
        self._check_pos_access()
        if not reason or not reason.strip():
            raise UserError(_("La aprobación manual necesita un motivo."))
        self.env["mercadopago.manual.approval"].sudo().create({
            "payment_method_id": self.id,
            "pos_payment_uuid": pos_payment_uuid,
            "reason": reason.strip(),
            "user_id": self.env.user.id,
        })
        return True
```

Agregar a `models/mercadopago_payment.py` el campo y el método de reserva:
```python
    pos_payment_uuid = fields.Char(readonly=True, index=True)
```
```python
    def reserve_for_uuid(self, pos_payment_uuid, ambiguous=False):
        """Reserva el pago para una línea que aún no existe en el servidor.

        Usa el mismo bloqueo de fila que impute(): la carrera entre dos cajeros
        ocurre acá, antes de que exista el pos.payment.
        """
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state FROM mercadopago_payment WHERE id = %s FOR UPDATE", (self.id,)
        )
        row = self.env.cr.fetchone()
        if not row or row[0] != "available":
            raise UserError(_(
                "Ese pago ya fue asignado a otra venta. Actualizá la lista y elegí otro."
            ))
        self.write({
            "state": "matched",
            "pos_payment_uuid": pos_payment_uuid,
            "matched_by_user_id": self.env.user.id,
            "matched_at": fields.Datetime.now(),
            "ambiguous_pick": ambiguous,
        })
        self._notify_open_sessions()
        return True
```

- [ ] **Step 6: Actualizar y probar a mano en el POS**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u pos_mercadopago_validator --stop-after-init --no-http
docker restart odoo-odoo-1
```

Abrir el POS en el navegador, configurar el método de pago con la cuenta y el `mp_pos_id`, agregar una línea de cobro y verificar: que el diálogo abre, que muestra la advertencia de bandeja desactualizada, y que el botón de aprobación manual pide dos confirmaciones y un motivo.

- [ ] **Step 7: Verificar que ninguna credencial llegó al navegador**

En la consola del navegador, con el POS abierto:
```javascript
JSON.stringify(odoo.__WOWL_DEBUG__.root.env.services.pos.models["pos.payment.method"].getAll())
  .match(/APP_USR|access_token|webhook_secret/)
```
Expected: `null`. Es el criterio de aceptación 13.

- [ ] **Step 8: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): interfaz de cobro con bandeja en vivo y aprobación manual"
```

---

## Task 11b: Cerrar la reserva al confirmar la venta

Durante el cobro, la línea de pago vive sólo en el navegador y el pago se reserva por `pos_payment_uuid` (Task 11). Cuando la orden se sincroniza, Odoo crea el `pos.payment` real: recién ahí se puede completar `pos_payment_id` y dejar que actúe el índice único. Sin esta tarea la reserva queda a medias.

**Files:**
- Modify: `pos_mercadopago_validator/models/pos_payment.py`
- Test: `pos_mercadopago_validator/tests/test_reserva_a_imputacion.py`

**Interfaces:**
- Consumes: `mercadopago.payment.reserve_for_uuid(uuid, ambiguous)` de Task 11.
- Produces: override de `pos.payment.create()` que resuelve la reserva.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_reserva_a_imputacion.py`:
```python
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReservaAImputacion(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        self.config = self.env["pos.config"].create({"name": "Caja A"})
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()
        self.session = self.config.current_session_id
        self.payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": fields.Datetime.now(),
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })

    def _order(self):
        return self.env["pos.order"].create({
            "session_id": self.session.id, "amount_total": 1500.0, "amount_tax": 0,
            "amount_paid": 0, "amount_return": 0,
        })

    def test_reserved_payment_links_on_line_creation(self):
        """Al crearse el pos.payment con ese uuid, la reserva se convierte en imputación."""
        self.payment.reserve_for_uuid("uuid-abc")
        self.assertEqual(self.payment.state, "matched")
        self.assertFalse(self.payment.pos_payment_id)

        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
            "mercadopago_uuid": "uuid-abc",
        })

        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.pos_payment_id, line)
        self.assertEqual(self.payment.pos_session_id, self.session)
        self.assertEqual(line.mercadopago_payment_id, self.payment)

    def test_line_without_reservation_is_untouched(self):
        """Una línea de otro método no toca la bandeja."""
        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
        })
        self.assertFalse(line.mercadopago_payment_id)
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, "available")
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `ValueError: Invalid field 'mercadopago_uuid' on model 'pos.payment'`.

- [ ] **Step 3: Implementar el override**

Reemplazar el contenido de `models/pos_payment.py` por:
```python
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    _inherit = "pos.payment"

    mercadopago_payment_id = fields.Many2one(
        "mercadopago.payment", string="Pago de Mercado Pago", readonly=True,
    )
    mercadopago_reference = fields.Char(
        related="mercadopago_payment_id.mp_payment_id", string="Referencia MP", store=True,
    )
    mercadopago_uuid = fields.Char(
        help="uuid de la línea en el navegador. Vincula la reserva hecha durante el cobro.",
    )
    is_manual_approval = fields.Boolean(readonly=True)
    manual_reason = fields.Char(readonly=True)
    manual_approved_by_user_id = fields.Many2one("res.users", readonly=True)
    manual_approved_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Convierte la reserva por uuid en la imputación definitiva.

        Durante el cobro la línea no existe en el servidor, así que el pago se
        reservó contra el uuid del navegador. Recién acá se puede completar
        pos_payment_id y dejar que actúe el índice único parcial.
        """
        lines = super().create(vals_list)
        Inbox = self.env["mercadopago.payment"].sudo()
        for line in lines:
            if not line.mercadopago_uuid:
                continue
            reserved = Inbox.search([
                ("pos_payment_uuid", "=", line.mercadopago_uuid),
                ("state", "=", "matched"),
                ("pos_payment_id", "=", False),
            ], limit=1)
            if not reserved:
                _logger.warning(
                    "La línea %s declara el uuid %s pero no hay reserva asociada",
                    line.id, line.mercadopago_uuid,
                )
                continue
            order = line.pos_order_id
            reserved.write({
                "pos_payment_id": line.id,
                "pos_order_id": order.id,
                "pos_session_id": order.session_id.id,
                "amount_difference": line.amount - reserved.amount,
            })
            line.mercadopago_payment_id = reserved.id
            _logger.info(
                "Reserva %s cerrada sobre la línea %s", reserved.mp_payment_id, line.id
            )
        return lines
```

También hay que exponer `mercadopago_uuid` para que el POS lo mande al sincronizar. Agregar a `models/pos_payment.py`:
```python
    @api.model
    def _load_pos_data_fields(self, config_id):
        """Incluye el uuid de vínculo en los campos que sincroniza el POS."""
        return super()._load_pos_data_fields(config_id) + ["mercadopago_uuid"]
```

Y en `static/src/app/payment_mercadopago_validator.js`, dentro de `onPicked` tras una imputación exitosa, guardar el uuid en la línea para que viaje al servidor:
```javascript
                    line.mercadopago_uuid = line.uuid;
```
(agregar inmediatamente antes de `line.set_payment_status("done");`)

Agregar `from . import test_reserva_a_imputacion` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `35 tests, 0 failed` (dos nuevos sobre los 33 de Task 12 si se ejecuta después; el orden entre 11b y 12 es indistinto).

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): cierre de la reserva al crearse la línea de pago"
```

---

## Task 12: Aprobación manual auditada

**Files:**
- Create: `pos_mercadopago_validator/models/mercadopago_manual_approval.py`
- Create: `pos_mercadopago_validator/views/manual_approval_views.xml`
- Modify: `models/__init__.py`, `security/ir.model.access.csv`, `__manifest__.py`, `views/menus.xml`
- Test: `pos_mercadopago_validator/tests/test_aprobacion_manual.py`

**Interfaces:**
- Produces: modelo `mercadopago.manual.approval` con `payment_method_id`, `pos_payment_uuid`, `pos_payment_id`, `reason`, `user_id`, `amount`, `create_date`.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_aprobacion_manual.py`:
```python
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAprobacionManual(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })

    def test_reason_is_mandatory(self):
        """Sin motivo no hay aprobación manual."""
        with self.assertRaises(UserError):
            self.method.register_manual_approval("uuid-1", "   ")

    def test_approval_records_who_and_when(self):
        """Queda registrado usuario, motivo y momento."""
        self.method.register_manual_approval("uuid-1", "El cliente ya se iba")
        approval = self.env["mercadopago.manual.approval"].search([
            ("pos_payment_uuid", "=", "uuid-1")
        ])
        self.assertEqual(len(approval), 1)
        self.assertEqual(approval.user_id, self.env.user)
        self.assertEqual(approval.reason, "El cliente ya se iba")
        self.assertTrue(approval.create_date)
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `KeyError: 'mercadopago.manual.approval'`.

- [ ] **Step 3: Implementar**

`pos_mercadopago_validator/models/mercadopago_manual_approval.py`:
```python
from odoo import fields, models


class MercadoPagoManualApproval(models.Model):
    _name = "mercadopago.manual.approval"
    _description = "Cobro aprobado sin verificación de pago"
    _order = "create_date desc"

    payment_method_id = fields.Many2one("pos.payment.method", required=True, readonly=True)
    pos_payment_uuid = fields.Char(required=True, readonly=True, index=True)
    pos_payment_id = fields.Many2one("pos.payment", readonly=True)
    pos_order_id = fields.Many2one("pos.order", readonly=True)
    pos_session_id = fields.Many2one("pos.session", readonly=True)
    amount = fields.Monetary(readonly=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, readonly=True
    )
    reason = fields.Char(required=True, readonly=True)
    user_id = fields.Many2one("res.users", required=True, readonly=True)
```

Agregar a `security/ir.model.access.csv`:
```csv
access_mercadopago_manual_approval_manager,mercadopago.manual.approval manager,model_mercadopago_manual_approval,group_mercadopago_manager,1,0,0,0
access_mercadopago_manual_approval_pos_user,mercadopago.manual.approval pos user,model_mercadopago_manual_approval,point_of_sale.group_pos_user,1,0,1,0
```

`views/manual_approval_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_manual_approval_list" model="ir.ui.view">
        <field name="name">mercadopago.manual.approval.list</field>
        <field name="model">mercadopago.manual.approval</field>
        <field name="arch" type="xml">
            <list>
                <field name="create_date" string="Fecha"/>
                <field name="user_id"/>
                <field name="pos_session_id"/>
                <field name="pos_order_id"/>
                <field name="amount" sum="Total"/>
                <field name="reason"/>
            </list>
        </field>
    </record>

    <record id="view_manual_approval_search" model="ir.ui.view">
        <field name="name">mercadopago.manual.approval.search</field>
        <field name="model">mercadopago.manual.approval</field>
        <field name="arch" type="xml">
            <search>
                <field name="user_id"/>
                <field name="reason"/>
                <filter name="today" string="Hoy"
                        domain="[('create_date','&gt;=', context_today().strftime('%Y-%m-%d'))]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="by_user" string="Usuario" context="{'group_by':'user_id'}"/>
                    <filter name="by_session" string="Sesión" context="{'group_by':'pos_session_id'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_manual_approval" model="ir.actions.act_window">
        <field name="name">Cobros sin verificación</field>
        <field name="res_model">mercadopago.manual.approval</field>
        <field name="view_mode">list</field>
    </record>

    <menuitem id="menu_manual_approval" name="Cobros sin verificación"
              parent="menu_mercadopago_root" sequence="30"
              action="action_manual_approval"/>
</odoo>
```

Agregar al manifest (después de `menus.xml` no: **antes**, porque `menus.xml` no referencia esta acción; el orden correcto es `manual_approval_views.xml` antes de `menus.xml` sólo si el menú vive ahí — acá el `menuitem` está en el mismo archivo, así que basta con agregarlo después de `views/mercadopago_account_views.xml`):
```python
        "views/manual_approval_views.xml",
```

Agregar `from . import mercadopago_manual_approval` a `models/__init__.py` y `from . import test_aprobacion_manual` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `33 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): registro auditado de cobros aprobados sin verificación"
```

---

## Task 13: Vistas de bandeja, huérfanos y aviso de cierre de sesión

**Files:**
- Create: `pos_mercadopago_validator/views/mercadopago_payment_views.xml`
- Create: `pos_mercadopago_validator/models/pos_session.py`
- Modify: `models/__init__.py`, `__manifest__.py`, `views/menus.xml`
- Test: `pos_mercadopago_validator/tests/test_orphans.py`

**Interfaces:**
- Produces: `pos.session.get_mercadopago_unmatched()` → lista de dicts para el aviso de cierre.

- [ ] **Step 1: Escribir el test que falla**

`pos_mercadopago_validator/tests/test_orphans.py`:
```python
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrphans(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        self.config = self.env["pos.config"].create({"name": "Caja A"})
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()
        self.session = self.config.current_session_id

    def test_payment_outside_window_stays_available(self):
        """Salir de la ventana no cambia el estado: sigue disponible y es huérfano."""
        old = self.env["mercadopago.payment"].create({
            "mp_payment_id": "111", "account_id": self.account.id, "amount": 1500.0,
            "date_approved": "2020-01-01 10:00:00", "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
        })
        self.assertEqual(old.state, "available")
        self.assertNotIn(
            old.id, [l["id"] for l in self.method.get_mp_inbox(1500.0)["matching"]]
        )

    def test_session_close_lists_unmatched_payments(self):
        """El cierre muestra los pagos sin imputar del período de la sesión."""
        self.env["mercadopago.payment"].create({
            "mp_payment_id": "222", "account_id": self.account.id, "amount": 900.0,
            "date_approved": fields.Datetime.now(), "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
        })
        unmatched = self.session.get_mercadopago_unmatched()
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["mp_payment_id"], "222")
```

- [ ] **Step 2: Correr y verificar que falla**

Expected: `AttributeError: ... 'get_mercadopago_unmatched'`.

- [ ] **Step 3: Implementar**

`pos_mercadopago_validator/models/pos_session.py`:
```python
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def get_mercadopago_unmatched(self):
        """Pagos recibidos durante la sesión que quedaron sin imputar.

        El cierre se permite igual: el objetivo es que el faltante se descubra
        en el momento y no una semana después.
        """
        self.ensure_one()
        methods = self.config_id.payment_method_ids.filtered(
            lambda m: m.use_payment_terminal == "mercadopago_validator"
        )
        if not methods:
            return []
        payments = self.env["mercadopago.payment"].sudo().search([
            ("account_id", "in", methods.mapped("mp_account_id").ids),
            ("mp_pos_id", "in", methods.mapped("mp_pos_id")),
            ("state", "=", "available"),
            ("date_approved", ">=", self.start_at),
        ])
        return [{
            "id": p.id,
            "mp_payment_id": p.mp_payment_id,
            "amount": p.amount,
            "date_approved": p.date_approved.isoformat(),
            "display_payer": p.display_payer or "",
        } for p in payments]
```

`views/mercadopago_payment_views.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_mercadopago_payment_list" model="ir.ui.view">
        <field name="name">mercadopago.payment.list</field>
        <field name="model">mercadopago.payment</field>
        <field name="arch" type="xml">
            <list decoration-warning="state == 'available'" decoration-muted="state == 'discarded'">
                <field name="date_approved"/>
                <field name="amount" sum="Total"/>
                <field name="source"/>
                <field name="display_payer"/>
                <field name="mp_pos_id"/>
                <field name="state"/>
                <field name="pos_order_id"/>
                <field name="matched_by_user_id"/>
                <field name="ambiguous_pick"/>
                <field name="mp_payment_id"/>
            </list>
        </field>
    </record>

    <record id="view_mercadopago_payment_search" model="ir.ui.view">
        <field name="name">mercadopago.payment.search</field>
        <field name="model">mercadopago.payment</field>
        <field name="arch" type="xml">
            <search>
                <field name="mp_payment_id"/>
                <field name="display_payer"/>
                <field name="mp_pos_id"/>
                <filter name="orphans" string="Huérfanos (sin imputar)"
                        domain="[('state','=','available')]"/>
                <filter name="matched" string="Imputados"
                        domain="[('state','=','matched')]"/>
                <filter name="ambiguous" string="Selección ambigua"
                        domain="[('ambiguous_pick','=',True)]"/>
                <filter name="alias" string="Canal alias" domain="[('source','=','alias')]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="by_state" string="Estado" context="{'group_by':'state'}"/>
                    <filter name="by_pos" string="QR / Caja" context="{'group_by':'mp_pos_id'}"/>
                    <filter name="by_day" string="Día" context="{'group_by':'date_approved:day'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_mercadopago_payment" model="ir.actions.act_window">
        <field name="name">Bandeja de pagos</field>
        <field name="res_model">mercadopago.payment</field>
        <field name="view_mode">list</field>
    </record>

    <record id="action_mercadopago_orphans" model="ir.actions.act_window">
        <field name="name">Pagos huérfanos</field>
        <field name="res_model">mercadopago.payment</field>
        <field name="view_mode">list</field>
        <field name="domain">[('state','=','available')]</field>
    </record>

    <menuitem id="menu_mercadopago_payment" name="Bandeja de pagos"
              parent="menu_mercadopago_root" sequence="10"
              action="action_mercadopago_payment"/>
    <menuitem id="menu_mercadopago_orphans" name="Pagos huérfanos"
              parent="menu_mercadopago_root" sequence="15"
              action="action_mercadopago_orphans"/>
</odoo>
```

Agregar `"views/mercadopago_payment_views.xml"` al manifest **antes** de `views/menus.xml`, `from . import pos_session` a `models/__init__.py` y `from . import test_orphans` a `tests/__init__.py`.

- [ ] **Step 4: Correr y verificar que pasa**

Expected: `35 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): vistas de bandeja, huérfanos y aviso al cerrar la sesión"
```

---

## Task 14: Traducción, icono y verificación final

**Files:**
- Create: `pos_mercadopago_validator/i18n/es_AR.po`
- Create: `pos_mercadopago_validator/static/description/icon.png`

- [ ] **Step 1: Generar el archivo de traducción**

```bash
docker exec odoo-odoo-1 odoo -d calidad --i18n-export=/tmp/es_AR.po \
  --modules=pos_mercadopago_validator --language=es_AR --stop-after-init --no-http
docker cp odoo-odoo-1:/tmp/es_AR.po \
  /home/alexis/Documents/Github/prometeo-odoo-modules/pos_mercadopago_validator/i18n/es_AR.po
```

Completar las cadenas en español rioplatense.

- [ ] **Step 2: Generar el icono**

Copiar `~/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg` a `/tmp/icon.svg`, cambiar el `<text>` GLYPH por `MP` y renderizar:

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
mkdir -p pos_mercadopago_validator/static/description
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="pos_mercadopago_validator/static/description/icon.png" \
  "file:///tmp/icon.svg"
```

No usar ImageMagick: descarta el `<text>` y los gradientes radiales.

- [ ] **Step 3: Verificar instalación limpia**

```bash
docker exec odoo-postgres18-1 createdb -U odoo -T template0 mp_clean_test
docker exec odoo-odoo-1 odoo -d mp_clean_test -i pos_mercadopago_validator \
  --stop-after-init --no-http
docker exec odoo-odoo-1 odoo shell -d mp_clean_test --no-http <<'PY'
env["ir.module.module"].search([("name","=","pos_mercadopago_validator")]).module_uninstall()
env.cr.commit()
print("desinstalado sin errores")
PY
docker exec odoo-postgres18-1 dropdb -U odoo mp_clean_test
```
Expected: instala y desinstala sin trazas de error. Criterio de aceptación 14.

- [ ] **Step 4: Correr la batería completa**

```bash
docker exec odoo-odoo-1 odoo -d calidad -u pos_mercadopago_validator \
  --test-enable --test-tags /pos_mercadopago_validator --stop-after-init
```
Expected: `35 tests, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add pos_mercadopago_validator/
git commit -m "feat(mp): traducción es_AR, icono y verificación de instalación limpia"
```

---

## Verificación contra los criterios de aceptación del spec

| # | Criterio | Cubierto por |
|---|---|---|
| 1 | Pago visible en <3 s con su identificador | Task 10 (bus) + Task 11 (diálogo) |
| 1b | Nombre por CUIT, banco, o "no identificado" | Task 5 (`_resolve_partner`) + Task 3 (`display_payer`) |
| 1c | CUIT del canal alias nunca se persiste | Task 4 `test_alias_never_persists_payer_identity` |
| 2 | Funciona con el webhook apagado | Task 8 Step 5 |
| 3 | Notificación x3 → un registro | Task 5 `test_ingest_is_idempotent` |
| 4 | Dos imputaciones simultáneas → una sola | Task 7 `test_concurrent_imputation_yields_exactly_one` |
| 5 | Aislamiento entre cajas por QR | Task 9 `test_only_this_cash_register_qr_is_listed` |
| 6 | Compras propias fuera de la bandeja | Task 4 `test_outgoing_payment_is_not_ingestable` |
| 7 | Imputa contra el monto bruto | Task 4 `test_amount_is_gross_never_net` |
| 8 | Tolerancia y contador de no coincidentes | Task 9 `test_non_matching_amounts_are_counted_not_listed` |
| 9 | `auto_impute_single_match` en ambos estados | Task 6 `test_defaults_match_spec` + Task 11 `onWillStart` |
| 10 | Doble confirmación y motivo | Task 12 + Task 11 (`manualStep`) |
| 11 | Huérfanos al cerrar sin impedir el cierre | Task 13 `test_session_close_lists_unmatched_payments` |
| 12 | Aviso de bandeja desactualizada | Task 9 `test_stale_flag_when_never_synced` + Task 11 `staleLabel` |
| 13 | Ninguna credencial en el navegador | Task 6 `test_no_credential_is_synced_to_the_browser` + Task 11 Step 7 |
| 14 | Instala y desinstala limpio | Task 14 Step 3 |
