# stock_intercompany — Sync 1 a 1 y edición de validados — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la entrega de una compañía y su recepción espejo en la otra queden amarradas en contenido de forma bidireccional, que un rol nuevo pueda corregirlas después de validadas, y que toda corrección quede registrada en el chatter de las dos puntas.

**Architecture:** Sincronización síncrona en los overrides de `write`/`create`/`unlink` de `stock.picking`, `stock.move` y `stock.move.line`. La propagación corre en `sudo()` con el flag de contexto `skip_intercompany_sync`, que hace que el override de la contraparte salga temprano y corte el eco en un solo salto. Todo en la misma transacción: si la contraparte falla, la edición local no se guarda. Helpers compartidos en un archivo nuevo `models/intercompany_sync.py`, sin clase mixin.

**Tech Stack:** Odoo 18.0, Python 3.12, tests con `odoo.addons.base.tests.common.BaseCommon`, contenedor local `odoo-odoo-1`.

**Spec:** [`docs/superpowers/specs/2026-08-05-stock-intercompany-sync-design.md`](../specs/2026-08-05-stock-intercompany-sync-design.md)

## Global Constraints

- Odoo 18.0. Módulo `stock_intercompany`, licencia **AGPL-3** (extiende un módulo OCA) — mantener las cabeceras de copyright existentes y agregar `# Copyright 2026 Alexis Medina` en los archivos que se toquen.
- Versión del manifest: subir a `18.0.2.0.0` (cambio funcional mayor).
- `data` en el manifest: `security/` **antes** de `views/`.
- Traducciones con la forma nueva: `_("texto %(x)s", x=valor)`. Nunca `%`.
- Docstring en castellano en cada método nuevo.
- Flag de contexto único en todo el módulo: `skip_intercompany_sync`.
- Ningún modelo nuevo. La auditoría va al chatter.
- Los pickings **sin** contraparte no cambian de comportamiento en ningún punto: ni guard, ni sync, ni supresión de backorder.
- Comando de tests (confirmar el nombre de la base antes de la primera corrida):

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

- Validación de sintaxis sin base:

```bash
python3 -c "import ast; ast.parse(open('stock_intercompany/__manifest__.py').read())"
python3 -c "import xml.dom.minidom as m; m.parse('stock_intercompany/security/security.xml')"
```

## Mapa de archivos

| Archivo | Responsabilidad | Tareas |
|---|---|---|
| `models/intercompany_sync.py` | **Nuevo.** Constantes, resolución de contraparte, flag de propagación, mapeo de lotes, notas de chatter | 2 |
| `models/stock_picking.py` | Creación del espejo, sync de cabecera, `can_edit_done`, guard, supresión de backorder | 1, 3, 4, 6, 9 |
| `models/stock_move.py` | Sync de demanda, alta y baja de líneas | 7, 8 |
| `models/stock_move_line.py` | Sync de cantidad hecha y lote | 7, 10 |
| `security/security.xml` | **Nuevo.** `group_intercompany_manager` | 4 |
| `views/stock_picking_views.xml` | Readonly condicionado, botón a la contraparte | 5 |
| `tests/test_intercompany_sync.py` | **Nuevo.** Todo lo de sync, guard y edición de validados | 3 en adelante |
| `tests/test_intercompany_picking.py` | Existente. Se extiende en la tarea 1 | 1 |

Orden de dependencias: **0 → 1 → 2 → 3 → 4 → 5** y de ahí en adelante 6, 7, 8, 9, 10 en orden.

---

### Task 0: Fase 0 — verificar el comportamiento real de Odoo

Sin base de datos no se puede afirmar nada de lo que sigue. **0.1 es bloqueante**: si las líneas del espejo quedan huérfanas, la tarea 1 cambia de forma.

**Files:**
- Ninguno. Esta tarea solo produce hallazgos, que se anotan en el spec.

**Interfaces:**
- Consumes: nada.
- Produces: tres respuestas de sí/no que condicionan las tareas 1 y 10.

- [ ] **Step 1: Levantar el entorno y confirmar el nombre de la base**

```bash
sudo docker ps --format '{{.Names}}'
sudo docker exec odoo-odoo-1 psql -l 2>/dev/null || \
  sudo docker exec $(sudo docker ps --format '{{.Names}}' | grep -i db) psql -U odoo -l
```

Anotar el nombre de la base a usar (se espera `calidad`). Si el contenedor no está levantado, arrancarlo antes de seguir.

- [ ] **Step 2: Verificar 4.1 — si las move lines del espejo quedan sin move**

```bash
sudo docker exec odoo-odoo-1 odoo shell -d calidad --no-http
```

En el shell:

```python
pickings = env["stock.picking"].sudo().search([("counterpart_of_picking_id", "!=", False)], limit=5)
for p in pickings:
    print(p.name, p.company_id.name,
          "moves:", len(p.move_ids),
          "lines:", len(p.move_line_ids),
          "lines sin move:", len(p.move_line_ids.filtered(lambda l: not l.move_id)))
```

Si `lines sin move` es mayor que cero, 4.1 queda **confirmado**. Si no hay pickings espejo en la base, replicarlo con el test existente:

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

y leer el resultado del assert de `test_picking_creation`, que compara `len(move_line_ids)`.

- [ ] **Step 3: Verificar 4.2 — nota en chatter y ajuste de quants al editar una línea validada**

En el mismo shell, sobre un picking validado cualquiera **de prueba** (no de producción):

```python
p = env["stock.picking"].sudo().search([("state", "=", "done")], limit=1)
line = p.move_line_ids[0]
before_msgs = len(p.message_ids)
before_qty = line.quantity
line.write({"quantity": before_qty + 1})
env.cr.flush()
print("mensajes nuevos:", len(p.message_ids) - before_msgs)
for m in p.message_ids[:2]:
    print(m.body)
print("quant:", env["stock.quant"]._gather(line.product_id, line.location_dest_id).mapped("quantity"))
env.cr.rollback()
```

Anotar si Odoo postea nota y si el quant se movió. **Terminar siempre con `env.cr.rollback()`.**

- [ ] **Step 4: Verificar 4.3 — compañía de los lotes copiados**

```python
lines = env["stock.move.line"].sudo().search(
    [("counterpart_of_line_id", "!=", False), ("lot_id", "!=", False)], limit=10)
for l in lines:
    print(l.picking_id.name, l.company_id.name, "| lote:", l.lot_id.name, l.lot_id.company_id.name)
```

Si la compañía del lote no coincide con la de la línea, 4.3 queda confirmado.

- [ ] **Step 5: Verificar si `account_invoice_inter_company` sigue instalado en la base**

```python
print(env["ir.module.module"].sudo().search([
    ("name", "=", "account_invoice_inter_company")]).mapped("state"))
```

- [ ] **Step 6: Anotar los hallazgos en el spec y commitear**

Editar la sección 4 de `docs/superpowers/specs/2026-08-05-stock-intercompany-sync-design.md`, cambiando cada punto por `confirmado` o `refutado` con la evidencia y la fecha.

```bash
git add docs/superpowers/specs/2026-08-05-stock-intercompany-sync-design.md
git commit -m "docs: resultado de Fase 0 en el spec de stock_intercompany"
```

---

### Task 1: Las líneas del espejo cuelgan de su move

Sin esto no hay mapeo línea a línea y ninguna de las tareas de sync funciona. Hoy [`stock_picking.py:94-105`](../../../stock_intercompany/models/stock_picking.py#L94-L105) crea las líneas al nivel del picking con `move_id=False`.

**Files:**
- Modify: `stock_intercompany/models/stock_picking.py:24-107`
- Test: `stock_intercompany/tests/test_intercompany_picking.py`

**Interfaces:**
- Consumes: nada.
- Produces: `_get_counterpart_move_commands(company, picking_type)` en `stock.picking`, que reemplaza a `_check_company_consistency`. Devuelve una lista de `Command.create` de moves, cada uno con sus `move_line_ids` anidadas. La tarea 8 la vuelve a usar para armar líneas nuevas.

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_intercompany_picking.py`, dentro de la clase `TestIntercompanyDelivery`:

```python
    def test_counterpart_lines_belong_to_their_move(self):
        """Cada línea del espejo debe colgar del move espejo correspondiente."""
        stock_location = self.env["stock.location"].search(
            [("usage", "=", "internal"), ("company_id", "=", self.company1.id)]
        )
        custs_location = self.env.ref("stock.stock_location_customers")
        custs_location.company_id = False
        self.product1.company_id = False
        picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_demo)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": stock_location.id,
                    "location_dest_id": custs_location.id,
                    "picking_type_id": self.company1.intercompany_in_type_id.id,
                }
            )
        )
        self.env["stock.move.line"].create(
            {
                "location_id": stock_location.id,
                "location_dest_id": custs_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 1.0,
                "picking_id": picking.id,
            }
        )
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.action_confirm()
            picking.button_validate()

        counterpart = rc.records
        self.assertTrue(counterpart.move_line_ids)
        for line in counterpart.move_line_ids:
            self.assertTrue(
                line.move_id,
                "La línea %s del espejo quedó sin move asociado" % line.id,
            )
            self.assertEqual(
                line.move_id.counterpart_of_move_id,
                line.counterpart_of_line_id.move_id,
                "La línea del espejo cuelga de un move que no es el espejo del suyo",
            )
```

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestIntercompanyDelivery.test_counterpart_lines_belong_to_their_move \
  --stop-after-init --no-http
```

Esperado: FAIL en `La línea ... del espejo quedó sin move asociado`.

- [ ] **Step 3: Reemplazar `_check_company_consistency` por la construcción anidada**

En `models/stock_picking.py`, borrar el método `_check_company_consistency` completo y agregar:

```python
    def _get_counterpart_move_commands(self, company, picking_type):
        """Construye los moves espejo con sus líneas anidadas dentro de cada move."""
        supplier_location = self.env.ref("stock.stock_location_suppliers")
        if supplier_location.company_id:
            supplier_location.sudo().company_id = False

        location_dest = picking_type.default_location_dest_id
        if not location_dest:
            warehouse = (
                self.env["stock.warehouse"]
                .sudo()
                .search([("company_id", "=", company.id)], limit=1)
            )
            location_dest = warehouse.lot_stock_id

        common_vals = {
            "company_id": company.id,
            "location_id": supplier_location.id,
            "location_dest_id": location_dest.id,
            "picking_type_id": picking_type.id,
        }

        move_commands = []
        for move in self.move_ids.sudo():
            line_commands = []
            for line in move.move_line_ids:
                line_vals = line.with_company(company).copy_data(
                    dict(
                        common_vals,
                        move_id=False,
                        picking_id=False,
                        counterpart_of_line_id=line.id,
                    )
                )[0]
                line_commands.append(Command.create(line_vals))
            move_vals = move.with_company(company).copy_data(
                dict(
                    common_vals,
                    counterpart_of_move_id=move.id,
                    move_line_ids=line_commands,
                )
            )[0]
            move_commands.append(Command.create(move_vals))
        return move_commands
```

Y en `_get_counterpart_picking_vals`, cambiar:

```python
        move_ids, move_line_ids = self._check_company_consistency(company, ptype)
```

por:

```python
        move_ids = self._get_counterpart_move_commands(company, ptype)
```

y quitar la clave `"move_line_ids": move_line_ids,` del diccionario que retorna, dejando solo `"move_ids": move_ids,`.

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

Esperado: PASS en los dos tests, incluido el `test_picking_creation` existente, que sigue comparando `len(counterpart.move_line_ids)` contra el origen.

- [ ] **Step 5: Commit**

```bash
git add stock_intercompany/models/stock_picking.py stock_intercompany/tests/test_intercompany_picking.py
git commit -m "fix: las líneas del picking espejo cuelgan de su move"
```

---

### Task 2: Helpers compartidos de sincronización

**Files:**
- Create: `stock_intercompany/models/intercompany_sync.py`
- Modify: `stock_intercompany/models/__init__.py`

**Interfaces:**
- Consumes: nada.
- Produces, todas funciones a nivel de módulo:
  - `SYNC_CONTEXT_KEY: str` = `"skip_intercompany_sync"`
  - `is_propagation(env) -> bool`
  - `as_propagation(records) -> recordset` (sudo + flag)
  - `get_counterpart(record, field_name: str) -> recordset` (vacío si no hay)
  - `map_lot(lot, company) -> recordset | False`
  - `post_sync_note(picking, body: str, source_picking=None) -> None`

  Las usan las tareas 3, 4, 6, 7, 8, 9 y 10.

- [ ] **Step 1: Escribir el archivo**

```python
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Helpers compartidos por los tres modelos que participan del espejo intercompany."""

import logging

from odoo import _

_logger = logging.getLogger(__name__)

# Marca una escritura como "ya propagada": el override de la contraparte la ve
# y sale temprano, cortando el eco en un solo salto.
SYNC_CONTEXT_KEY = "skip_intercompany_sync"


def is_propagation(env):
    """Verdadero si la escritura en curso ya viene propagada desde la contraparte."""
    return bool(env.context.get(SYNC_CONTEXT_KEY))


def as_propagation(records):
    """Devuelve el recordset listo para recibir la propagación: sudo y con el flag."""
    return records.sudo().with_context(**{SYNC_CONTEXT_KEY: True})


def get_counterpart(record, field_name):
    """Resuelve la contraparte en cualquiera de los dos sentidos del vínculo.

    El campo `field_name` solo lo llena el registro espejo apuntando al origen,
    así que desde el origen hay que buscarlo al revés.
    """
    record.ensure_one()
    counterpart = record[field_name]
    if counterpart:
        return counterpart
    if not record.id:
        return record.browse()
    return record.sudo().search([(field_name, "=", record.id)], limit=1)


def map_lot(lot, company):
    """Devuelve el lote equivalente en `company`, creándolo si no existe.

    `stock.lot` es por compañía: el lote de la entrega no sirve en la recepción.
    El equivalente se identifica por nombre y producto.
    """
    if not lot:
        return False
    if lot.company_id == company:
        return lot
    lot_model = lot.sudo().with_company(company)
    existing = lot_model.search(
        [
            ("name", "=", lot.name),
            ("product_id", "=", lot.product_id.id),
            ("company_id", "=", company.id),
        ],
        limit=1,
    )
    if existing:
        return existing
    _logger.info(
        "Intercompany: creando lote %s del producto %s en la compañía %s",
        lot.name,
        lot.product_id.display_name,
        company.name,
    )
    return lot_model.create(
        {
            "name": lot.name,
            "product_id": lot.product_id.id,
            "company_id": company.id,
        }
    )


def post_sync_note(picking, body, source_picking=None):
    """Postea la nota de auditoría en el chatter del picking.

    Cuando el cambio llega propagado, la nota nombra el picking de origen y el
    usuario que lo originó, que puede ser de la otra compañía.
    """
    if source_picking:
        body = _(
            "%(body)s — propagado desde %(origin)s (%(company)s) por %(user)s",
            body=body,
            origin=source_picking.name,
            company=source_picking.company_id.name,
            user=picking.env.user.name,
        )
    picking.sudo().message_post(body=body)
```

- [ ] **Step 2: Registrar el archivo**

`models/__init__.py` queda:

```python
from . import intercompany_sync
from . import res_company
from . import res_config_settings
from . import stock_move
from . import stock_move_line
from . import stock_picking
```

- [ ] **Step 3: Verificar que el módulo carga**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany --stop-after-init --no-http
```

Esperado: termina sin traceback y con `Modules loaded.` en el log.

- [ ] **Step 4: Commit**

```bash
git add stock_intercompany/models/intercompany_sync.py stock_intercompany/models/__init__.py
git commit -m "feat: helpers compartidos de sincronización intercompany"
```

---

### Task 3: Resolución bidireccional de la contraparte

**Files:**
- Modify: `stock_intercompany/models/stock_picking.py`
- Create: `stock_intercompany/tests/test_intercompany_sync.py`

**Interfaces:**
- Consumes: `get_counterpart` de la tarea 2.
- Produces:
  - `stock.picking.counterpart_picking_id` — Many2one computado, no almacenado, `check_company=False`.
  - `SyncCommon`, la clase base de tests con `setUpClass` y el helper `_create_delivery(qty=10.0)` que devuelve `(delivery, reception)` ya validada la entrega. La usan todas las tareas siguientes.

- [ ] **Step 1: Escribir el archivo de tests con la base común y el primer test que falla**

```python
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.tests.common import RecordCapturer

from odoo.addons.base.tests.common import BaseCommon


class SyncCommon(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company_obj = cls.env["res.company"]
        cls.company1 = company_obj.create({"name": "Sync Company A"})
        cls.company2 = company_obj.create({"name": "Sync Company B"})
        cls.group_stock_user = cls.env.ref("stock.group_stock_user")
        cls.group_manager = cls.env.ref(
            "stock_intercompany.group_intercompany_manager"
        )
        cls.user_operator = cls.env["res.users"].create(
            {
                "login": "sync_operator",
                "name": "Operador",
                "email": "sync_operator@example.org",
                "company_id": cls.company1.id,
                "company_ids": [
                    Command.link(cls.company1.id),
                    Command.link(cls.company2.id),
                ],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.group_stock_user.id),
                ],
            }
        )
        cls.picking_type_out = (
            cls.env["stock.picking.type"]
            .sudo()
            .search(
                [
                    ("company_id", "=", cls.company1.id),
                    ("name", "=", "Delivery Orders"),
                ],
                limit=1,
            )
        )
        cls.picking_type_in = (
            cls.env["stock.picking.type"]
            .sudo()
            .search(
                [("company_id", "=", cls.company2.id), ("name", "=", "Receipts")],
                limit=1,
            )
        )
        cls.company1.intercompany_in_type_id = cls.picking_type_out.id
        cls.company2.intercompany_in_type_id = cls.picking_type_in.id
        cls.product = cls.env["product.product"].create(
            {
                "name": "Sync Product",
                "type": "consu",
                "is_storable": True,
                "categ_id": cls.env.ref("product.product_category_all").id,
            }
        )
        cls.product.company_id = False
        cls.product2 = cls.env["product.product"].create(
            {
                "name": "Sync Product 2",
                "type": "consu",
                "is_storable": True,
                "categ_id": cls.env.ref("product.product_category_all").id,
            }
        )
        cls.product2.company_id = False
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.stock_location = cls.env["stock.location"].search(
            [("usage", "=", "internal"), ("company_id", "=", cls.company1.id)],
            limit=1,
        )
        cls.custs_location = cls.env.ref("stock.stock_location_customers")
        cls.custs_location.company_id = False

    def _create_delivery(self, qty=10.0, product=None):
        """Crea y valida una entrega intercompany. Devuelve (entrega, recepción)."""
        product = product or self.product
        picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_operator)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.company1.intercompany_in_type_id.id,
                }
            )
        )
        self.env["stock.move.line"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "product_id": product.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": qty,
                "picking_id": picking.id,
            }
        )
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.action_confirm()
            picking.button_validate()
        return picking, rc.records


class TestCounterpartResolution(SyncCommon):
    def test_counterpart_resolves_in_both_directions(self):
        """La contraparte se resuelve desde la entrega y desde la recepción."""
        delivery, reception = self._create_delivery()
        self.assertEqual(reception.counterpart_picking_id, delivery)
        self.assertEqual(delivery.counterpart_picking_id, reception)

    def test_no_counterpart_is_empty(self):
        """Un picking sin espejo devuelve un recordset vacío, no un error."""
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        self.assertFalse(picking.counterpart_picking_id)
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestCounterpartResolution \
  --stop-after-init --no-http
```

Esperado: FAIL. Primero por `ValueError: External ID not found: stock_intercompany.group_intercompany_manager` (el grupo llega en la tarea 4) — para esta tarea, comentar temporalmente la línea `cls.group_manager = ...` y descomentarla en la tarea 4. Con eso, el fallo esperado pasa a ser `Invalid field 'counterpart_picking_id'`.

- [ ] **Step 3: Agregar el campo computado**

En `models/stock_picking.py`, cambiar los imports de cabecera a:

```python
# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command, api, fields, models

from .intercompany_sync import get_counterpart
```

Y agregar debajo del campo `counterpart_of_picking_id`:

```python
    counterpart_picking_id = fields.Many2one(
        "stock.picking",
        string="Contraparte intercompany",
        compute="_compute_counterpart_picking_id",
        check_company=False,
    )

    @api.depends("counterpart_of_picking_id")
    def _compute_counterpart_picking_id(self):
        """Resuelve el espejo en los dos sentidos: hacia el origen y hacia la copia."""
        for picking in self:
            picking.counterpart_picking_id = get_counterpart(
                picking, "counterpart_of_picking_id"
            )
```

- [ ] **Step 4: Correr y verificar que pasa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestCounterpartResolution \
  --stop-after-init --no-http
```

Esperado: PASS en los dos tests.

- [ ] **Step 5: Commit**

```bash
git add stock_intercompany/models/stock_picking.py stock_intercompany/tests/test_intercompany_sync.py
git commit -m "feat: resolución bidireccional de la contraparte intercompany"
```

---

### Task 4: Grupo manager, `can_edit_done` y guard de edición

**Files:**
- Create: `stock_intercompany/security/security.xml`
- Modify: `stock_intercompany/models/stock_picking.py`
- Modify: `stock_intercompany/models/stock_move.py`
- Modify: `stock_intercompany/models/stock_move_line.py`
- Modify: `stock_intercompany/__manifest__.py`
- Test: `stock_intercompany/tests/test_intercompany_sync.py`

**Interfaces:**
- Consumes: `counterpart_picking_id` (tarea 3), `is_propagation` (tarea 2).
- Produces:
  - Grupo `stock_intercompany.group_intercompany_manager`.
  - `stock.picking.can_edit_done` — Boolean computado, no almacenado.
  - `stock.picking._check_intercompany_edit_allowed()` — lanza `AccessError` o no hace nada.
  - Constantes `GUARDED_PICKING_FIELDS`, `GUARDED_MOVE_FIELDS`, `GUARDED_LINE_FIELDS`.

  El guard lo llaman los `write` de las tareas 6, 7 y 10 y los `create`/`unlink` de la tarea 8.

- [ ] **Step 1: Escribir los tests que fallan**

Descomentar `cls.group_manager` en `SyncCommon` y agregar al final de `setUpClass`, antes del cierre:

```python
        cls.user_manager_both = cls.env["res.users"].create(
            {
                "login": "sync_manager_both",
                "name": "Manager Ambas",
                "email": "sync_manager_both@example.org",
                "company_id": cls.company1.id,
                "company_ids": [
                    Command.link(cls.company1.id),
                    Command.link(cls.company2.id),
                ],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.group_stock_user.id),
                    Command.link(cls.group_manager.id),
                ],
            }
        )
        cls.user_manager_one = cls.env["res.users"].create(
            {
                "login": "sync_manager_one",
                "name": "Manager Una",
                "email": "sync_manager_one@example.org",
                "company_id": cls.company1.id,
                "company_ids": [Command.link(cls.company1.id)],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.group_stock_user.id),
                    Command.link(cls.group_manager.id),
                ],
            }
        )
```

Y agregar la clase de tests:

```python
class TestEditGuard(SyncCommon):
    def test_operator_cannot_edit_validated(self):
        """El operador no puede tocar una entrega intercompany ya validada."""
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        with self.assertRaises(AccessError):
            line.with_user(self.user_operator).write({"quantity": 5.0})

    def test_manager_with_one_company_cannot_edit(self):
        """El manager sin acceso a las dos compañías tampoco puede."""
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        with self.assertRaises(AccessError):
            line.with_user(self.user_manager_one).write({"quantity": 5.0})

    def test_manager_with_both_companies_can_edit(self):
        """El manager con las dos compañías sí puede."""
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        line.with_user(self.user_manager_both).write({"quantity": 5.0})
        self.assertEqual(line.quantity, 5.0)

    def test_can_edit_done_flag(self):
        """El campo que gobierna el readonly de la vista refleja las dos condiciones."""
        delivery, _reception = self._create_delivery()
        self.assertFalse(delivery.with_user(self.user_operator).can_edit_done)
        self.assertFalse(delivery.with_user(self.user_manager_one).can_edit_done)
        self.assertTrue(delivery.with_user(self.user_manager_both).can_edit_done)

    def test_plain_picking_is_untouched(self):
        """Un picking sin contraparte no queda sujeto al guard."""
        picking = (
            self.env["stock.picking"]
            .with_user(self.user_operator)
            .create(
                {
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        self.env["stock.move.line"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "product_id": self.product.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 3.0,
                "picking_id": picking.id,
            }
        )
        picking.action_confirm()
        picking.button_validate()
        line = picking.move_line_ids[0]
        line.with_user(self.user_operator).write({"quantity": 2.0})
        self.assertEqual(line.quantity, 2.0)
```

Y agregar el import arriba del archivo de tests:

```python
from odoo.exceptions import AccessError
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestEditGuard --stop-after-init --no-http
```

Esperado: FAIL — `External ID not found: stock_intercompany.group_intercompany_manager`.

- [ ] **Step 3: Crear el grupo**

`security/security.xml`:

```xml
<?xml version="1.0" encoding="utf-8" ?>
<!-- Copyright 2026 Alexis Medina
     License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html). -->
<odoo>
    <record id="group_intercompany_manager" model="res.groups">
        <field name="name">Intercompany: editar transferencias validadas</field>
        <field name="category_id" ref="base.module_category_usability" />
        <field name="implied_ids" eval="[(4, ref('stock.group_stock_user'))]" />
        <field
            name="comment"
        >Permite corregir cantidades y agregar o quitar productos en transferencias intercompany ya validadas. Además del grupo, el usuario debe tener habilitadas las dos compañías involucradas.</field>
    </record>
</odoo>
```

Registrarlo en el manifest, antes de `views/`:

```python
    "data": [
        "security/security.xml",
        "views/res_config_settings.xml",
        "views/stock_picking_views.xml",
    ],
```

- [ ] **Step 4: Agregar `can_edit_done` y el guard en `stock.picking`**

En `models/stock_picking.py`, ampliar los imports:

```python
from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError

from .intercompany_sync import get_counterpart, is_propagation
```

Agregar la constante arriba de la clase:

```python
# Campos cuya escritura sobre un picking validado exige el rol de manager.
GUARDED_PICKING_FIELDS = (
    "scheduled_date",
    "priority",
    "move_ids",
    "move_ids_without_package",
    "move_line_ids",
)
```

Y dentro de la clase:

```python
    can_edit_done = fields.Boolean(
        string="Puede editar validado",
        compute="_compute_can_edit_done",
        help="Verdadero si el usuario es manager intercompany y tiene "
        "habilitadas las dos compañías del espejo.",
    )

    @api.depends("counterpart_picking_id", "company_id")
    @api.depends_context("uid")
    def _compute_can_edit_done(self):
        """Gobierna el readonly de la vista y respalda el guard del modelo."""
        is_manager = self.env.user.has_group(
            "stock_intercompany.group_intercompany_manager"
        )
        allowed = self.env.user.company_ids
        for picking in self:
            counterpart = picking.counterpart_picking_id
            picking.can_edit_done = bool(
                is_manager
                and counterpart
                and picking.company_id in allowed
                and counterpart.company_id in allowed
            )

    def _check_intercompany_edit_allowed(self):
        """Bloquea la edición de un picking intercompany validado sin el rol.

        No aplica a las escrituras propagadas: esas ya vienen en sudo desde la
        contraparte, y son las que permiten que el operador destino reciba de
        menos sin necesitar el rol.
        """
        if is_propagation(self.env):
            return
        for picking in self:
            if picking.state != "done" or not picking.counterpart_picking_id:
                continue
            if picking.can_edit_done:
                continue
            if not self.env.user.has_group(
                "stock_intercompany.group_intercompany_manager"
            ):
                raise AccessError(
                    _(
                        "La transferencia %(name)s ya está validada. Editarla "
                        "requiere el rol «Intercompany: editar transferencias "
                        "validadas».",
                        name=picking.name,
                    )
                )
            raise AccessError(
                _(
                    "Para editar la transferencia validada %(name)s necesitás "
                    "tener habilitadas las dos compañías: %(a)s y %(b)s.",
                    name=picking.name,
                    a=picking.company_id.name,
                    b=picking.counterpart_picking_id.company_id.name,
                )
            )
```

- [ ] **Step 5: Llamar al guard desde los tres `write`**

En `models/stock_picking.py`, dentro de la clase:

```python
    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_PICKING_FIELDS):
            self._check_intercompany_edit_allowed()
        return super().write(vals)
```

`models/stock_move.py` pasa a ser:

```python
# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

# Campos cuya escritura sobre un move de un picking validado exige el rol.
GUARDED_MOVE_FIELDS = ("product_uom_qty", "quantity", "product_id", "picked")


class StockMove(models.Model):
    _inherit = "stock.move"

    counterpart_of_move_id = fields.Many2one("stock.move", check_company=False)

    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_MOVE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        return super().write(vals)
```

`models/stock_move_line.py`:

```python
# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

# Campos cuya escritura sobre una línea de un picking validado exige el rol.
GUARDED_LINE_FIELDS = ("quantity", "lot_id", "lot_name", "product_id")


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    counterpart_of_line_id = fields.Many2one("stock.move.line", check_company=False)

    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_LINE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        return super().write(vals)
```

- [ ] **Step 6: Correr y verificar que pasa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

Esperado: PASS en las tres clases. Si `test_plain_picking_is_untouched` falla, el guard se está aplicando a pickings sin contraparte: revisar la condición `not picking.counterpart_picking_id`.

- [ ] **Step 7: Commit**

```bash
git add stock_intercompany/security stock_intercompany/models stock_intercompany/__manifest__.py stock_intercompany/tests
git commit -m "feat: rol manager intercompany y guard de edición de validados"
```

---

### Task 5: Vista — readonly condicionado y botón a la contraparte

**Files:**
- Modify: `stock_intercompany/views/stock_picking_views.xml`

**Interfaces:**
- Consumes: `can_edit_done` y `counterpart_picking_id` (tareas 3 y 4).
- Produces: nada que consuman otras tareas.

- [ ] **Step 1: Inspeccionar el arch real del form de picking**

El nombre exacto de los atributos `readonly` varía entre builds. Antes de escribir el xpath, mirar el arch vigente:

```bash
sudo docker exec odoo-odoo-1 odoo shell -d calidad --no-http
```

```python
view = env.ref("stock.view_picking_form")
arch = view.arch_db
import re
for m in re.finditer(r'<field name="(move_ids_without_package|scheduled_date|priority)"[^>]*>', arch):
    print(m.group(0))
print(re.findall(r'readonly="[^"]*state[^"]*"', arch)[:10])
```

Anotar los atributos reales. Si el arch difiere de lo que asume el paso 2, ajustar el xpath a lo observado.

- [ ] **Step 2: Escribir la vista**

`views/stock_picking_views.xml` queda:

```xml
<?xml version="1.0" encoding="utf-8" ?>
<odoo>
    <record id="view_picking_form_hide_return" model="ir.ui.view">
        <field name="name">stock.picking.form.hide.return</field>
        <field name="model">stock.picking</field>
        <field name="inherit_id" ref="stock.view_picking_form" />
        <field name="arch" type="xml">
            <button name="%(stock.act_stock_return_picking)d" position="attributes">
                <attribute name="invisible">True</attribute>
            </button>
        </field>
    </record>

    <record id="view_picking_form_intercompany_edit" model="ir.ui.view">
        <field name="name">stock.picking.form.intercompany.edit</field>
        <field name="model">stock.picking</field>
        <field name="inherit_id" ref="stock.view_picking_form" />
        <field name="arch" type="xml">
            <field name="name" position="before">
                <field name="can_edit_done" invisible="1" />
                <field name="counterpart_picking_id" invisible="1" />
            </field>
            <xpath expr="//div[@name='button_box']" position="inside">
                <button
                    type="object"
                    name="action_open_counterpart_picking"
                    class="oe_stat_button"
                    icon="fa-exchange"
                    invisible="not counterpart_picking_id"
                >
                    <span class="o_stat_text">Contraparte</span>
                </button>
            </xpath>
            <xpath
                expr="//field[@name='move_ids_without_package']"
                position="attributes"
            >
                <attribute name="readonly">state == 'done' and not can_edit_done</attribute>
            </xpath>
            <field name="scheduled_date" position="attributes">
                <attribute name="readonly">state == 'done' and not can_edit_done</attribute>
            </field>
            <field name="priority" position="attributes">
                <attribute name="readonly">state == 'done' and not can_edit_done</attribute>
            </field>
        </field>
    </record>
</odoo>
```

- [ ] **Step 3: Agregar la acción del botón**

En `models/stock_picking.py`:

```python
    def action_open_counterpart_picking(self):
        """Abre el picking espejo en la otra compañía."""
        self.ensure_one()
        counterpart = self.counterpart_picking_id
        if not counterpart:
            raise UserError(
                _("La transferencia %(name)s no tiene contraparte intercompany.",
                  name=self.name)
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": counterpart.id,
            "view_mode": "form",
            "context": dict(self.env.context, allowed_company_ids=[counterpart.company_id.id]),
        }
```

Agregar `UserError` al import de excepciones:

```python
from odoo.exceptions import AccessError, UserError
```

- [ ] **Step 4: Validar el XML y actualizar el módulo**

```bash
python3 -c "import xml.dom.minidom as m; m.parse('stock_intercompany/views/stock_picking_views.xml')"
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany --stop-after-init --no-http
```

Esperado: sin traceback. Un `ParseError: Element ... cannot be located` significa que el xpath del paso 2 no coincide con el arch observado en el paso 1: corregirlo.

- [ ] **Step 5: Verificar a mano en la UI**

Abrir una transferencia intercompany validada con un usuario operador y confirmar que las operaciones siguen en readonly. Repetir con un usuario manager con las dos compañías y confirmar que se pueden editar y que el botón "Contraparte" abre el otro picking.

- [ ] **Step 6: Commit**

```bash
git add stock_intercompany/views/stock_picking_views.xml stock_intercompany/models/stock_picking.py
git commit -m "feat: form de picking con edición condicionada y botón a la contraparte"
```

---

### Task 6: Sync de cabecera — fecha programada y prioridad

**Files:**
- Modify: `stock_intercompany/models/stock_picking.py`
- Test: `stock_intercompany/tests/test_intercompany_sync.py`

**Interfaces:**
- Consumes: `as_propagation`, `is_propagation`, `post_sync_note` (tarea 2); el guard (tarea 4).
- Produces:
  - `SYNCED_PICKING_FIELDS = ("scheduled_date", "priority")`
  - `stock.picking._propagate_picking_changes(previous: dict)` — patrón que replican las tareas 7 y 10.

- [ ] **Step 1: Escribir los tests que fallan**

```python
class TestHeaderSync(SyncCommon):
    def test_scheduled_date_propagates_to_reception(self):
        """Cambiar la fecha en la entrega la cambia en la recepción."""
        delivery, reception = self._create_delivery()
        new_date = "2030-01-15 10:00:00"
        delivery.with_user(self.user_manager_both).write({"scheduled_date": new_date})
        self.assertEqual(
            fields.Datetime.to_string(reception.scheduled_date), new_date
        )

    def test_priority_propagates_from_reception(self):
        """La propagación también va de la recepción hacia la entrega."""
        delivery, reception = self._create_delivery()
        reception.with_user(self.user_manager_both).write({"priority": "1"})
        self.assertEqual(delivery.priority, "1")

    def test_no_infinite_echo(self):
        """La propagación no rebota: una escritura, un salto."""
        delivery, reception = self._create_delivery()
        delivery.with_user(self.user_manager_both).write({"priority": "1"})
        self.assertEqual(reception.priority, "1")
        self.assertEqual(delivery.priority, "1")

    def test_note_posted_on_both_sides(self):
        """El cambio deja nota en las dos puntas, y la de destino nombra el origen."""
        delivery, reception = self._create_delivery()
        before_delivery = len(delivery.message_ids)
        before_reception = len(reception.message_ids)
        delivery.with_user(self.user_manager_both).write({"priority": "1"})
        self.assertGreater(len(delivery.message_ids), before_delivery)
        self.assertGreater(len(reception.message_ids), before_reception)
        self.assertIn(delivery.name, reception.message_ids[0].body)
```

Agregar `fields` al import de arriba del archivo de tests:

```python
from odoo import Command, fields
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestHeaderSync --stop-after-init --no-http
```

Esperado: FAIL — la recepción conserva su fecha y prioridad originales.

- [ ] **Step 3: Implementar la propagación**

En `models/stock_picking.py`, agregar la constante junto a `GUARDED_PICKING_FIELDS`:

```python
# Campos de cabecera que viajan al espejo.
SYNCED_PICKING_FIELDS = ("scheduled_date", "priority")
```

Ampliar el import de helpers:

```python
from .intercompany_sync import (
    as_propagation,
    get_counterpart,
    is_propagation,
    post_sync_note,
)
```

Reemplazar el `write` de la tarea 4 por:

```python
    def write(self, vals):
        """Corta la edición de validados sin rol y propaga la cabecera al espejo."""
        if any(field in vals for field in GUARDED_PICKING_FIELDS):
            self._check_intercompany_edit_allowed()
        if is_propagation(self.env):
            return super().write(vals)
        previous = {
            picking.id: {field: picking[field] for field in SYNCED_PICKING_FIELDS}
            for picking in self
        }
        res = super().write(vals)
        self._propagate_picking_changes(previous)
        return res

    def _propagate_picking_changes(self, previous):
        """Lleva al espejo los campos de cabecera que efectivamente cambiaron."""
        for picking in self:
            counterpart = picking.counterpart_picking_id
            if not counterpart:
                continue
            old = previous.get(picking.id, {})
            changed = {
                field: picking[field]
                for field in SYNCED_PICKING_FIELDS
                if field in old and picking[field] != old[field]
            }
            if not changed:
                continue
            as_propagation(counterpart).write(changed)
            for field, value in changed.items():
                body = _(
                    "%(label)s: %(old)s → %(new)s",
                    label=picking._fields[field].string,
                    old=old[field],
                    new=value,
                )
                post_sync_note(picking, body)
                post_sync_note(counterpart, body, source_picking=picking)
```

- [ ] **Step 4: Correr y verificar que pasa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

Esperado: PASS en todas las clases. Si `test_no_infinite_echo` cuelga o desborda el stack, el flag no está cortando: revisar que `as_propagation` se use en **todas** las escrituras hacia la contraparte.

- [ ] **Step 5: Commit**

```bash
git add stock_intercompany/models/stock_picking.py stock_intercompany/tests/test_intercompany_sync.py
git commit -m "feat: sincronización de fecha programada y prioridad entre espejos"
```

---

### Task 7: Sync de cantidades

**Files:**
- Modify: `stock_intercompany/models/stock_move.py`
- Modify: `stock_intercompany/models/stock_move_line.py`
- Test: `stock_intercompany/tests/test_intercompany_sync.py`

**Interfaces:**
- Consumes: helpers de la tarea 2, guard de la tarea 4.
- Produces:
  - `stock.move._get_counterpart_move()` y `stock.move.line._get_counterpart_line()`, ambos devuelven recordset (vacío si no hay espejo). Los usan las tareas 8 y 10.
  - `SYNCED_MOVE_FIELDS = ("product_uom_qty",)`, `SYNCED_LINE_FIELDS = ("quantity",)`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
class TestQuantitySync(SyncCommon):
    def test_demand_propagates_delivery_to_reception(self):
        """La demanda editada en la entrega viaja a la recepción."""
        delivery, reception = self._create_delivery(qty=10.0)
        delivery.move_ids[0].with_user(self.user_manager_both).write(
            {"product_uom_qty": 8.0}
        )
        self.assertEqual(reception.move_ids[0].product_uom_qty, 8.0)

    def test_done_quantity_propagates_reception_to_delivery(self):
        """La cantidad hecha editada en la recepción viaja a la entrega."""
        delivery, reception = self._create_delivery(qty=10.0)
        reception.move_line_ids[0].with_user(self.user_manager_both).write(
            {"quantity": 7.0}
        )
        self.assertEqual(delivery.move_line_ids[0].quantity, 7.0)

    def test_operator_partial_receipt_adjusts_delivery(self):
        """El operador recibe 9 de 10 y la entrega queda en 9, sin pedirle el rol."""
        delivery, reception = self._create_delivery(qty=10.0)
        reception = reception.with_user(self.user_operator)
        reception.move_line_ids[0].write({"quantity": 9.0})
        reception.button_validate()
        self.assertEqual(reception.state, "done")
        self.assertEqual(delivery.move_line_ids[0].quantity, 9.0)

    def test_partial_receipt_creates_no_backorder(self):
        """La recepción espejo nunca genera backorder."""
        delivery, reception = self._create_delivery(qty=10.0)
        reception = reception.with_user(self.user_operator)
        reception.move_line_ids[0].write({"quantity": 9.0})
        reception.button_validate()
        backorders = self.env["stock.picking"].sudo().search(
            [("backorder_id", "=", reception.id)]
        )
        self.assertFalse(backorders)
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestQuantitySync --stop-after-init --no-http
```

Esperado: FAIL en los cuatro.

- [ ] **Step 3: Propagar la demanda en `stock.move`**

`models/stock_move.py` queda:

```python
# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

from .intercompany_sync import as_propagation, get_counterpart, is_propagation

# Campos cuya escritura sobre un move de un picking validado exige el rol.
GUARDED_MOVE_FIELDS = ("product_uom_qty", "quantity", "product_id", "picked")

# Campos del move que viajan al espejo.
SYNCED_MOVE_FIELDS = ("product_uom_qty",)


class StockMove(models.Model):
    _inherit = "stock.move"

    counterpart_of_move_id = fields.Many2one("stock.move", check_company=False)

    def _get_counterpart_move(self):
        """Resuelve el move espejo en cualquiera de los dos sentidos."""
        return get_counterpart(self, "counterpart_of_move_id")

    def write(self, vals):
        """Corta la edición de validados sin rol y propaga la demanda al espejo."""
        if any(field in vals for field in GUARDED_MOVE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        if is_propagation(self.env):
            return super().write(vals)
        previous = {
            move.id: {field: move[field] for field in SYNCED_MOVE_FIELDS}
            for move in self
        }
        res = super().write(vals)
        for move in self:
            counterpart = move._get_counterpart_move()
            if not counterpart:
                continue
            old = previous.get(move.id, {})
            changed = {
                field: move[field]
                for field in SYNCED_MOVE_FIELDS
                if field in old and move[field] != old[field]
            }
            if changed:
                as_propagation(counterpart).write(changed)
        return res
```

- [ ] **Step 4: Propagar la cantidad hecha en `stock.move.line`**

`models/stock_move_line.py` queda:

```python
# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, fields, models

from .intercompany_sync import (
    as_propagation,
    get_counterpart,
    is_propagation,
    post_sync_note,
)

# Campos cuya escritura sobre una línea de un picking validado exige el rol.
GUARDED_LINE_FIELDS = ("quantity", "lot_id", "lot_name", "product_id")

# Campos de la línea que viajan al espejo.
SYNCED_LINE_FIELDS = ("quantity",)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    counterpart_of_line_id = fields.Many2one("stock.move.line", check_company=False)

    def _get_counterpart_line(self):
        """Resuelve la línea espejo en cualquiera de los dos sentidos."""
        return get_counterpart(self, "counterpart_of_line_id")

    def write(self, vals):
        """Corta la edición de validados sin rol y propaga la cantidad al espejo."""
        if any(field in vals for field in GUARDED_LINE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        if is_propagation(self.env):
            return super().write(vals)
        previous = {
            line.id: {field: line[field] for field in SYNCED_LINE_FIELDS}
            for line in self
        }
        res = super().write(vals)
        for line in self:
            counterpart = line._get_counterpart_line()
            if not counterpart:
                continue
            old = previous.get(line.id, {})
            changed = {
                field: line[field]
                for field in SYNCED_LINE_FIELDS
                if field in old and line[field] != old[field]
            }
            if not changed:
                continue
            as_propagation(counterpart).write(changed)
            if "quantity" in changed and line.picking_id and counterpart.picking_id:
                body = _(
                    "%(product)s: cantidad %(old)s → %(new)s",
                    product=line.product_id.display_name,
                    old=old["quantity"],
                    new=changed["quantity"],
                )
                post_sync_note(counterpart.picking_id, body, source_picking=line.picking_id)
        return res
```

La nota solo se postea del lado que recibe: del lado que edita ya la postea Odoo con `stock.track_move_template` cuando el picking está validado. Si la Fase 0 refutó eso, agregar acá también `post_sync_note(line.picking_id, body)`.

- [ ] **Step 5: Suprimir el backorder de la recepción espejo**

En `models/stock_picking.py`:

```python
    def button_validate(self):
        """La recepción espejo no genera backorder: la diferencia ajusta la entrega."""
        counterparts = self.filtered(lambda p: p.counterpart_picking_id)
        record = self
        if counterparts:
            record = self.with_context(
                skip_backorder=True,
                picking_ids_not_to_backorder=counterparts.ids,
            )
        return super(StockPicking, record).button_validate()
```

- [ ] **Step 6: Correr y verificar que pasa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

Esperado: PASS en todas las clases.

Si `test_operator_partial_receipt_adjusts_delivery` falla con `AccessError`, el guard se está disparando sobre la entrega: verificar que la propagación desde `stock.move.line.write` use `as_propagation`, que es lo que hace que `is_propagation` devuelva verdadero en el otro lado.

- [ ] **Step 7: Commit**

```bash
git add stock_intercompany/models stock_intercompany/tests
git commit -m "feat: sincronización de cantidades y supresión de backorder en el espejo"
```

---

### Task 8: Alta de líneas, también en pickings validados

**Files:**
- Modify: `stock_intercompany/models/stock_move.py`
- Test: `stock_intercompany/tests/test_intercompany_sync.py`

**Interfaces:**
- Consumes: `_get_counterpart_move_commands` (tarea 1), helpers (tarea 2), `_get_counterpart_move` (tarea 7).
- Produces:
  - `stock.move._bring_to_done()` — lleva un move a `done` por la vía normal de Odoo.
  - `stock.move._create_counterpart_move()` — devuelve el move espejo creado, o un recordset vacío si ya existía.

  La tarea 10 usa `_get_counterpart_move()` de la tarea 7 para encontrar lo que esta tarea creó.

- [ ] **Step 1: Escribir los tests que fallan**

```python
class TestLineAddition(SyncCommon):
    def test_new_line_on_validated_picking_mirrors_and_moves_stock(self):
        """Agregar un producto a una entrega validada lo replica y mueve stock."""
        delivery, reception = self._create_delivery(qty=10.0)
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        new_move = delivery.move_ids.filtered(
            lambda m: m.product_id == self.product2
        )
        self.assertEqual(len(new_move), 1)
        self.assertEqual(new_move.state, "done")
        self.assertEqual(new_move.quantity, 4.0)

        mirrored = reception.move_ids.filtered(
            lambda m: m.product_id == self.product2
        )
        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored.counterpart_of_move_id, new_move)
        self.assertEqual(mirrored.product_uom_qty, 4.0)

    def test_addition_posts_note_on_both_sides(self):
        """El alta deja nota en las dos puntas."""
        delivery, reception = self._create_delivery(qty=10.0)
        before_delivery = len(delivery.message_ids)
        before_reception = len(reception.message_ids)
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        self.assertGreater(len(delivery.message_ids), before_delivery)
        self.assertGreater(len(reception.message_ids), before_reception)

    def test_operator_cannot_add_line_to_validated(self):
        """El operador no puede agregar productos a un picking validado."""
        delivery, _reception = self._create_delivery(qty=10.0)
        with self.assertRaises(AccessError):
            self.env["stock.move"].with_user(self.user_operator).create(
                {
                    "picking_id": delivery.id,
                    "product_id": self.product2.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": delivery.location_id.id,
                    "location_dest_id": delivery.location_dest_id.id,
                    "name": self.product2.name,
                }
            )
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestLineAddition --stop-after-init --no-http
```

Esperado: FAIL — el move queda en `draft` y no hay espejo.

- [ ] **Step 3: Implementar el `create` de `stock.move`**

Agregar a `models/stock_move.py`, dentro de la clase, y ampliar el import a `from odoo import Command, _, api, fields, models` más `from .intercompany_sync import as_propagation, get_counterpart, is_propagation, map_lot, post_sync_note`:

```python
    @api.model_create_multi
    def create(self, vals_list):
        """Lleva a done los moves agregados a un picking validado y los replica."""
        moves = super().create(vals_list)
        if is_propagation(self.env):
            return moves
        for move in moves:
            picking = move.picking_id
            if not picking or not picking.counterpart_picking_id:
                continue
            if picking.state == "done":
                picking._check_intercompany_edit_allowed()
                move._bring_to_done()
            move._create_counterpart_move()
            body = _(
                "Línea agregada: %(product)s x %(qty)s",
                product=move.product_id.display_name,
                qty=move.product_uom_qty,
            )
            post_sync_note(picking, body)
            post_sync_note(
                picking.counterpart_picking_id, body, source_picking=picking
            )
        return moves

    def _bring_to_done(self):
        """Lleva el move a `done` por la vía normal de Odoo, sin tocar quants."""
        for move in self:
            move._action_confirm()
            move._action_assign()
            move.quantity = move.product_uom_qty
            move.picked = True
            move._action_done()

    def _create_counterpart_move(self):
        """Crea el move espejo en la contraparte, replicando su estado."""
        self.ensure_one()
        counterpart_picking = self.picking_id.counterpart_picking_id
        if not counterpart_picking or self._get_counterpart_move():
            return self.browse()
        company = counterpart_picking.company_id
        line_commands = []
        for line in self.move_line_ids:
            lot = map_lot(line.lot_id, company)
            line_commands.append(
                Command.create(
                    {
                        "product_id": line.product_id.id,
                        "product_uom_id": line.product_uom_id.id,
                        "quantity": line.quantity,
                        "lot_id": lot.id if lot else False,
                        "location_id": counterpart_picking.location_id.id,
                        "location_dest_id": counterpart_picking.location_dest_id.id,
                        "company_id": company.id,
                        "counterpart_of_line_id": line.id,
                    }
                )
            )
        counterpart = as_propagation(self.env["stock.move"]).with_company(company).create(
            {
                "picking_id": counterpart_picking.id,
                "product_id": self.product_id.id,
                "product_uom": self.product_uom.id,
                "product_uom_qty": self.product_uom_qty,
                "name": self.name,
                "company_id": company.id,
                "location_id": counterpart_picking.location_id.id,
                "location_dest_id": counterpart_picking.location_dest_id.id,
                "picking_type_id": counterpart_picking.picking_type_id.id,
                "counterpart_of_move_id": self.id,
                "move_line_ids": line_commands,
            }
        )
        if counterpart_picking.state == "done":
            as_propagation(counterpart)._bring_to_done()
        else:
            as_propagation(counterpart)._action_confirm()
        return counterpart
```

- [ ] **Step 4: Correr y verificar que pasa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

Esperado: PASS en todas las clases.

Si el move nuevo queda en `assigned` en vez de `done`, la causa más probable es que `move.quantity = ...` no haya impactado por falta de líneas reservadas: agregar antes de la asignación de cantidad un `move._set_quantity_done_prepare_vals` no es necesario — en su lugar, crear la `stock.move.line` explícitamente con `location_id`, `location_dest_id`, `product_id`, `product_uom_id` y `quantity`, y recién después `picked = True` y `_action_done()`.

- [ ] **Step 5: Verificar el impacto en stock de las dos compañías**

```bash
sudo docker exec odoo-odoo-1 odoo shell -d calidad --no-http
```

```python
# Reemplazar por los nombres reales del picking de prueba
d = env["stock.picking"].sudo().search([("name", "=", "WH/OUT/00001")])
r = d.counterpart_picking_id
for p in (d, r):
    print(p.name, p.company_id.name, p.state)
    for m in p.move_ids:
        print("  ", m.product_id.display_name, m.state, m.product_uom_qty, m.quantity)
env.cr.rollback()
```

Confirmar que el producto agregado aparece en `done` en las dos puntas con la misma cantidad.

- [ ] **Step 6: Commit**

```bash
git add stock_intercompany/models/stock_move.py stock_intercompany/tests/test_intercompany_sync.py
git commit -m "feat: alta de líneas replicada, también en pickings validados"
```

---

### Task 9: Sync de lotes

**Files:**
- Modify: `stock_intercompany/models/stock_move_line.py`
- Test: `stock_intercompany/tests/test_intercompany_sync.py`

**Interfaces:**
- Consumes: `map_lot` (tarea 2).
- Produces: nada nuevo. Extiende `SYNCED_LINE_FIELDS` con el tratamiento especial de `lot_id`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `SyncCommon.setUpClass`, antes del cierre:

```python
        cls.product_lot = cls.env["product.product"].create(
            {
                "name": "Sync Product Lot",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": cls.env.ref("product.product_category_all").id,
            }
        )
        cls.product_lot.company_id = False
```

Y la clase:

```python
class TestLotSync(SyncCommon):
    def test_lot_mapped_to_destination_company(self):
        """El lote de la entrega se resuelve como lote propio de la otra compañía."""
        lot_a = self.env["stock.lot"].create(
            {
                "name": "LOTE-001",
                "product_id": self.product_lot.id,
                "company_id": self.company1.id,
            }
        )
        delivery, reception = self._create_delivery(
            qty=5.0, product=self.product_lot
        )
        delivery.move_line_ids[0].with_user(self.user_manager_both).write(
            {"lot_id": lot_a.id}
        )
        mirrored_lot = reception.move_line_ids[0].lot_id
        self.assertTrue(mirrored_lot)
        self.assertEqual(mirrored_lot.name, "LOTE-001")
        self.assertEqual(mirrored_lot.company_id, self.company2)
        self.assertNotEqual(mirrored_lot, lot_a)

    def test_existing_lot_is_reused(self):
        """Si el lote ya existe en la compañía destino, no se duplica."""
        lot_a = self.env["stock.lot"].create(
            {
                "name": "LOTE-002",
                "product_id": self.product_lot.id,
                "company_id": self.company1.id,
            }
        )
        lot_b = self.env["stock.lot"].create(
            {
                "name": "LOTE-002",
                "product_id": self.product_lot.id,
                "company_id": self.company2.id,
            }
        )
        delivery, reception = self._create_delivery(
            qty=5.0, product=self.product_lot
        )
        delivery.move_line_ids[0].with_user(self.user_manager_both).write(
            {"lot_id": lot_a.id}
        )
        self.assertEqual(reception.move_line_ids[0].lot_id, lot_b)
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestLotSync --stop-after-init --no-http
```

Esperado: FAIL — la línea espejo queda sin lote, o con el lote de la compañía equivocada.

- [ ] **Step 3: Tratar `lot_id` en el `write` de la línea**

En `models/stock_move_line.py`, dentro del bucle de propagación del `write`, después de calcular `changed` y antes del `if not changed: continue`, insertar:

```python
            if "lot_id" in vals and line.lot_id != counterpart.lot_id:
                mapped = map_lot(line.lot_id, counterpart.company_id)
                changed["lot_id"] = mapped.id if mapped else False
```

Y ampliar el import de helpers con `map_lot`:

```python
from .intercompany_sync import (
    as_propagation,
    get_counterpart,
    is_propagation,
    map_lot,
    post_sync_note,
)
```

- [ ] **Step 4: Aplicar el mapeo también en la creación del espejo**

En `models/stock_picking.py`, dentro de `_get_counterpart_move_commands`, después de armar `line_vals` y antes del `Command.create`:

```python
                lot = map_lot(line.lot_id, company)
                line_vals["lot_id"] = lot.id if lot else False
```

Y agregar `map_lot` al import de helpers de ese archivo.

- [ ] **Step 5: Correr y verificar que pasa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

Esperado: PASS en todas las clases.

- [ ] **Step 6: Commit**

```bash
git add stock_intercompany/models stock_intercompany/tests
git commit -m "feat: mapeo de lotes entre compañías en el espejo intercompany"
```

---

### Task 10: Baja de líneas

En un picking sin validar la baja es `unlink` real. En uno validado, un move en `done` no se borra: "eliminar" pasa a ser cantidad y demanda en cero, con la línea visible como registro histórico.

**Files:**
- Modify: `stock_intercompany/models/stock_move.py`
- Test: `stock_intercompany/tests/test_intercompany_sync.py`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: `stock.move.action_intercompany_void()`, el método que la UI y el `unlink` usan para anular una línea de un picking validado.

- [ ] **Step 1: Escribir los tests que fallan**

```python
class TestLineRemoval(SyncCommon):
    def test_unlink_on_draft_removes_both_sides(self):
        """En un picking sin validar, borrar la línea la borra en las dos puntas."""
        delivery, reception = self._create_delivery(qty=10.0)
        extra = self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": reception.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 2.0,
                "location_id": reception.location_id.id,
                "location_dest_id": reception.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        mirrored = extra._get_counterpart_move()
        self.assertTrue(mirrored)
        extra.with_user(self.user_manager_both).unlink()
        self.assertFalse(mirrored.exists())

    def test_void_on_validated_zeroes_both_sides(self):
        """En un picking validado, anular deja la línea en cero en las dos puntas."""
        delivery, reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        mirrored = move._get_counterpart_move()
        move.with_user(self.user_manager_both).action_intercompany_void()
        self.assertTrue(move.exists())
        self.assertEqual(move.quantity, 0.0)
        self.assertEqual(move.product_uom_qty, 0.0)
        self.assertEqual(mirrored.quantity, 0.0)
        self.assertEqual(mirrored.product_uom_qty, 0.0)

    def test_unlink_on_validated_voids_instead(self):
        """Borrar una línea de un picking validado la anula en vez de borrarla."""
        delivery, _reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        move.with_user(self.user_manager_both).unlink()
        self.assertTrue(move.exists())
        self.assertEqual(move.quantity, 0.0)

    def test_operator_cannot_remove_from_validated(self):
        """El operador no puede anular líneas de un picking validado."""
        delivery, _reception = self._create_delivery(qty=10.0)
        with self.assertRaises(AccessError):
            delivery.move_ids[0].with_user(self.user_operator).unlink()
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany:TestLineRemoval --stop-after-init --no-http
```

Esperado: FAIL — `action_intercompany_void` no existe, y el `unlink` sobre validados revienta con el error de Odoo.

- [ ] **Step 3: Implementar la anulación y el `unlink`**

Agregar a `models/stock_move.py`, dentro de la clase:

```python
    def action_intercompany_void(self):
        """Anula la línea dejándola en cero, en las dos puntas.

        Un move en `done` no se puede borrar sin perder la trazabilidad del
        movimiento original, así que "eliminar" es poner demanda y cantidad en
        cero: Odoo revierte los quants y la línea queda como registro.
        """
        for move in self:
            picking = move.picking_id
            picking._check_intercompany_edit_allowed()
            counterpart = move._get_counterpart_move()
            move.move_line_ids.write({"quantity": 0.0})
            move.write({"product_uom_qty": 0.0})
            if counterpart:
                as_propagation(counterpart.move_line_ids).write({"quantity": 0.0})
                as_propagation(counterpart).write({"product_uom_qty": 0.0})
            body = _(
                "Línea anulada: %(product)s",
                product=move.product_id.display_name,
            )
            post_sync_note(picking, body)
            if counterpart and counterpart.picking_id:
                post_sync_note(
                    counterpart.picking_id, body, source_picking=picking
                )
        return True

    def unlink(self):
        """Borra en cascada al espejo; en pickings validados anula en vez de borrar."""
        if is_propagation(self.env):
            return super().unlink()
        to_void = self.filtered(
            lambda m: m.picking_id.state == "done" and m.picking_id.counterpart_picking_id
        )
        if to_void:
            to_void.action_intercompany_void()
        to_delete = self - to_void
        counterparts = self.env["stock.move"]
        for move in to_delete:
            if not move.picking_id.counterpart_picking_id:
                continue
            counterparts |= move._get_counterpart_move()
            body = _(
                "Línea eliminada: %(product)s",
                product=move.product_id.display_name,
            )
            post_sync_note(move.picking_id, body)
            post_sync_note(
                move.picking_id.counterpart_picking_id,
                body,
                source_picking=move.picking_id,
            )
        res = super(StockMove, to_delete).unlink()
        if counterparts:
            as_propagation(counterparts).unlink()
        return res
```

- [ ] **Step 4: Correr y verificar que pasa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http
```

Esperado: PASS en todas las clases.

- [ ] **Step 5: Verificar la reversión de quants en las dos compañías**

```bash
sudo docker exec odoo-odoo-1 odoo shell -d calidad --no-http
```

```python
d = env["stock.picking"].sudo().search([("state", "=", "done"), ("counterpart_of_picking_id", "!=", False)], limit=1)
o = d.counterpart_picking_id
move = o.move_ids[0]
prod, loc = move.product_id, move.location_dest_id
before = sum(env["stock.quant"]._gather(prod, loc).mapped("quantity"))
move.action_intercompany_void()
after = sum(env["stock.quant"]._gather(prod, loc).mapped("quantity"))
print("quant antes:", before, "después:", after)
env.cr.rollback()
```

Confirmar que el stock volvió atrás en las dos compañías. **Terminar siempre con `env.cr.rollback()`.**

- [ ] **Step 6: Commit**

```bash
git add stock_intercompany/models/stock_move.py stock_intercompany/tests/test_intercompany_sync.py
git commit -m "feat: baja de líneas replicada, con anulación en pickings validados"
```

---

### Task 11: Cierre — manifest, README y verificación completa

**Files:**
- Modify: `stock_intercompany/__manifest__.py`
- Modify: `stock_intercompany/README.rst`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: el módulo listo para instalar en calidad.

- [ ] **Step 1: Actualizar el manifest**

```python
{
    "name": "Stock Intercompany Delivery-Reception",
    "Summary": "Module that adds possibility for intercompany Delivery-Reception",
    "version": "18.0.2.0.0",
    "author": "Camptocamp, Alexis Medina, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/multi-company",
    "category": "Warehouse Management",
    "depends": ["stock"],
    "installable": True,
    "license": "AGPL-3",
    "data": [
        "security/security.xml",
        "views/res_config_settings.xml",
        "views/stock_picking_views.xml",
    ],
}
```

- [ ] **Step 2: Documentar el comportamiento nuevo en el README**

Agregar al final de `README.rst`:

```rst
Sincronización 1 a 1 y edición de validados
===========================================

La entrega y su recepción espejo quedan amarradas en contenido: cantidades,
alta y baja de productos, lotes, fecha programada y prioridad se propagan en
los dos sentidos.

Corregir una transferencia intercompany ya validada requiere el grupo
**Intercompany: editar transferencias validadas** y tener habilitadas las dos
compañías involucradas. Toda corrección queda registrada en el chatter de las
dos puntas, indicando el picking de origen y el usuario que la hizo.

Dos consecuencias a tener presentes:

* La recepción espejo no genera backorder. Recibir de menos ajusta la entrega.
* En un picking validado, eliminar una línea la deja en cantidad cero en vez de
  borrarla, para no perder la trazabilidad del movimiento original.
```

- [ ] **Step 3: Correr la suite completa**

```bash
sudo docker exec odoo-odoo-1 odoo -d calidad -u stock_intercompany \
  --test-enable --test-tags /stock_intercompany --stop-after-init --no-http 2>&1 | tail -40
```

Esperado: `0 failed, 0 error` en el resumen. Pegar el resumen real en el mensaje de cierre — no declarar que pasa sin haber leído la salida.

- [ ] **Step 4: Prueba manual del circuito completo en calidad**

1. Con el operador: crear una entrega a la otra compañía, validarla, confirmar que aparece la recepción.
2. Con el operador en la compañía destino: recibir de menos y validar. Confirmar que la entrega quedó ajustada y que no se creó backorder.
3. Con el manager: agregar un producto a la entrega ya validada. Confirmar que aparece en la recepción y que el stock se movió en las dos compañías.
4. Con el manager: anular una línea. Confirmar el cero en las dos puntas y las notas en los dos chatters.
5. Con el operador: intentar editar la entrega validada. Confirmar el mensaje de error.

- [ ] **Step 5: Commit**

```bash
git add stock_intercompany/__manifest__.py stock_intercompany/README.rst
git commit -m "chore: bump a 18.0.2.0.0 y documentación del sync intercompany"
```

---

## Cobertura del spec

| Sección del spec | Tarea |
|---|---|
| 4.1 / 4.2 / 4.3 — Fase 0 | 0 |
| 5 — vínculo bidireccional y archivos | 1, 2, 3 |
| 6.1 — grupo | 4 |
| 6.2 — `can_edit_done` | 4 |
| 6.3 — vista y guard de modelo | 4, 5 |
| 7.1 / 7.2 — campos y mecánica del sync | 6, 7 |
| 7.3 — errores presentables | 5 (`UserError` del botón), 8 |
| 8.1 — alta en validados | 8 |
| 8.2 — baja en validados | 10 |
| 8.3 — mapeo de lotes | 9 |
| 9 — auditoría en chatter | 6, 7, 8, 10 |
| 3.1 — sin backorder en el espejo | 7 |
| 11 — tests | todas |
