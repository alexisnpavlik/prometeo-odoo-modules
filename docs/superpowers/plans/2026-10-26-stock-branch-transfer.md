# stock_branch_transfer (app "Traslados") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App "Traslados" para mover mercadería entre sucursales (empresas) con envío, recepción (con o sin diferencias), cierre y edición/anulación por manager, más un contador sobre el ícono de la app.

**Architecture:** Un modelo `stock.branch.transfer` con líneas guarda cantidades enviadas/recibidas y estado. El stock nunca se "edita": cada acción fija un **objetivo** de stock por ubicación (origen, tránsito, destino) según estado y cantidades, y `_reconcile_stock()` compara contra lo ya movido por los pickings del traslado y genera pickings de corrección validados al instante (con `sudo()`), siempre pasando por una ubicación de tránsito propia. Enviar, recibir, cerrar, editar y anular son todos "cambiar estado/cantidades + reconciliar".

**Tech Stack:** Odoo 18.0 (Python ORM, QWeb views, OWL/JS service), `mail.thread`.

**Spec:** `docs/superpowers/specs/2026-10-26-stock-branch-transfer-design.md`

## Global Constraints

- Odoo 18.0; versión de manifest `18.0.1.0.0`; `license` `LGPL-3`; `author` `Alexis Medina`; `website` `alexis.medn@gmail.com`; `application: True`.
- `depends`: `["stock", "mail"]`. **No** depender de `stock_intercompany` (conviven; más adelante se migra).
- Textos de UI y mensajes en español; `_("texto %s", arg)` (sin `%`).
- Un archivo Python por modelo; docstring en cada método.
- Nunca modificar ni borrar `stock.move` hechos: toda corrección es un picking nuevo enlazado al traslado.
- Los pickings del módulo **no llevan `partner_id`** (así `stock_intercompany._create_counterpart_picking` no reconoce una empresa propia y no crea recepción duplicada).
- Se permite stock negativo en origen (sin bloqueo). Sin lotes/series.
- Todos los nombres de estado, menús y botones tal como en el spec: Borrador, En camino, Recibido, Con diferencias, Cerrado, Anulado; menús "Enviados" y "Por recibir"; botones "Enviar", "Recibido", "Recibido con diferencias", "Cerrar", "Anular".

## Review Focus

1. **Doble recepción con `stock_intercompany` instalado** — validar un envío del módulo no debe crear ningún picking con `counterpart_of_picking_id`. Test en Task 2 (se saltea si el módulo no está instalado en la base de test).
2. **Usuario con varias empresas** — origen = empresa activa (`env.company`), y puede recibir cualquier traslado cuyo destino esté en su `company_ids`, aunque no sea la empresa activa. Test en Task 2.
3. **Producto que llega sin haberse enviado** (línea nueva cargada en "con diferencias") — sale del origen y entra al destino; tránsito queda en 0 para ese producto. Test en Task 2.
4. **Manager cambia el destino de un traslado ya recibido** — el destino viejo vuelve a 0 y el nuevo recibe. Test en Task 3.
5. **Doble clic / acción sobre estado equivocado** (recibir algo en Borrador, enviar dos veces) — `UserError`, sin movimientos extra. Test en Task 2.

---

## Modelo de stock (decisión central — leer antes de cualquier task)

Ubicación de tránsito propia: xmlid `stock_branch_transfer.location_branch_transit`, nombre "Traslados en camino", `usage='transit'`, `company_id=False`, padre `stock.stock_location_locations_virtual`.

Para cada producto, objetivo neto por ubicación (s = enviado, r = recibido; origen = `company_id.` stock del almacén, destino = ídem de `dest_company_id`):

| Estado | Origen | Tránsito | Destino |
|---|---|---|---|
| draft, cancel | 0 | 0 | 0 |
| in_transit | −s | +s | 0 |
| with_diff | −max(s, r) | max(s, r) − r | +r |
| received, closed | −r | 0 | +r |

Neto actual = suma de `stock.move` en estado `done` de los pickings del traslado (entradas − salidas por ubicación). Toda ubicación que aparece en el neto actual o en el objetivo entra en la reconciliación (eso cubre cambio de destino). Por cada ubicación no-tránsito con delta ≠ 0: si delta < 0, picking ubicación→tránsito; si > 0, tránsito→ubicación. Un picking por (ubicación, dirección) por llamada, en la empresa de la ubicación, tipo `warehouse.out_type_id` (sale de stock) o `warehouse.in_type_id` (entra a stock), `branch_transfer_id` seteado, sin `partner_id`, validado en el acto con `move.quantity = qty` y `picked = True`.

En "Recibido" r = s por definición (se copia s en r al recibir).

---

### Task 1: Esqueleto, modelos, seguridad y datos

**Files:**
- Create: `stock_branch_transfer/__init__.py`, `__manifest__.py`
- Create: `stock_branch_transfer/models/__init__.py`, `models/stock_branch_transfer.py`, `models/stock_branch_transfer_line.py`, `models/stock_picking.py`
- Create: `stock_branch_transfer/security/security.xml`, `security/ir.model.access.csv`
- Create: `stock_branch_transfer/data/ir_sequence.xml`, `data/stock_location.xml`
- Create: `stock_branch_transfer/tests/__init__.py`, `tests/common.py`, `tests/test_transfer_base.py`

**Interfaces:**
- Produces:
  - `stock.branch.transfer` (`_inherit = ["mail.thread"]`, `_order = "id desc"`): `name` (Char, default `"Nuevo"`, secuencia `stock.branch.transfer` prefijo `TRS/` padding 5 en `create`), `company_id` (M2O `res.company`, "Origen", required, default `env.company`), `dest_company_id` (M2O `res.company`, "Destino", required), `state` (Selection `draft/in_transit/received/with_diff/closed/cancel`, default `draft`, `tracking=True`), `user_id` (default `env.user`), `date_sent`, `date_received` (Datetime), `diff_note` (Text), `line_ids` (O2M), `picking_ids` (O2M `stock.picking`, inverse `branch_transfer_id`).
  - `stock.branch.transfer.line`: `transfer_id` (required, `ondelete="cascade"`), `product_id` (required, domain `[("company_id", "=", False), ("type", "=", "consu"), ("is_storable", "=", True)]`), `uom_id` (related `product_id.uom_id`), `qty_sent` (Float), `qty_received` (Float).
  - `stock.picking.branch_transfer_id` (M2O, `index=True`, `copy=False`).
  - Grupos `stock_branch_transfer.group_branch_transfer_user` ("Traslados / Usuario") y `group_branch_transfer_manager` ("Traslados / Manager", implica user). `base.group_user` implica `group_branch_transfer_user`.
  - Record rules: user → `['|', ('company_id', 'in', user.company_ids.ids), ('dest_company_id', 'in', user.company_ids.ids)]`; manager → `[(1, '=', 1)]`; líneas igual vía `transfer_id.`.
  - `tests/common.py`: `BranchTransferCommon(TransactionCase)` con `company_a`, `company_b`, `company_c` (creadas en el test → cada una con su almacén), `product` (storable, sin empresa), `user_a` (solo company A, grupo user), `user_b` (solo company B), `manager` (A+B+C, grupo manager), helper `qty(product, company) -> float` (cantidad en `lot_stock_id` del almacén) y `transit_qty(product) -> float`, helper `make_transfer(user, qty=10.0) -> record` (A→B, una línea).

- [ ] **Step 1: Escribir tests** `tests/test_transfer_base.py`:
  - `test_sequence_name`: `make_transfer(user_a).name.startswith("TRS/")`.
  - `test_dest_cannot_equal_origin`: crear con `dest_company_id = company_a` → `ValidationError`.
  - `test_record_rule_hides_foreign`: un traslado A→B no aparece en `search([])` con `with_user(user_c)` (usuario solo en C, se crea en el test); sí aparece para `user_b`.
  - `test_internal_user_has_group`: un usuario interno nuevo tiene `group_branch_transfer_user`.
  - `test_transit_location`: `location_branch_transit.usage == "transit"` y `company_id` vacío.
  - `test_unlink_draft_ok`: `user_a` borra su borrador sin error.
- [ ] **Step 2: Crear base de test y verificar que fallan**

```bash
docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d sbt_test -i stock,mail,stock_intercompany --stop-after-init --no-http
docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d sbt_test -i stock_branch_transfer --test-enable --test-tags /stock_branch_transfer --stop-after-init --no-http
```
Expected: falla (módulo inexistente o tests en rojo).
- [ ] **Step 3: Implementar** manifest (`data`: security.xml, ir.model.access.csv, data/*), modelos, `_check_dest_company` (`@api.constrains`), grupos, ACL (user: read/write/create/unlink en ambos modelos; unlink se limita en código en Task 3), reglas, secuencia, ubicación.
- [ ] **Step 4: Correr** el segundo comando con `-u` en lugar de `-i`. Expected: `0 failed, 0 error(s)` en el log.
- [ ] **Step 5: Commit** `feat(stock_branch_transfer): modelos, seguridad y datos base`.

---

### Task 2: Motor de stock, envío, recepción y cierre

**Files:**
- Modify: `stock_branch_transfer/models/stock_branch_transfer.py`
- Create: `stock_branch_transfer/wizards/__init__.py`, `wizards/branch_transfer_receive_diff.py` (+ import en `__init__.py` raíz, ACL para el wizard)
- Create: `stock_branch_transfer/tests/test_transfer_flow.py`

**Interfaces:**
- Consumes: modelos, `BranchTransferCommon` de Task 1.
- Produces:
  - `_target_quantities() -> dict[(product_id:int, location_id:int), float]` según la tabla del modelo de stock.
  - `_current_quantities() -> dict[(product_id, location_id), float]` desde moves `done` de `picking_ids`.
  - `_reconcile_stock() -> None` (sudo, crea y valida pickings de corrección).
  - `action_send()` (draft→in_transit; exige ≥1 línea con `qty_sent > 0`; exige `company_id in env.user.company_ids`; setea `date_sent`).
  - `action_receive()` (in_transit→received; copia `qty_sent` a `qty_received`; exige `dest_company_id in user.company_ids` o grupo manager; setea `date_received`).
  - `action_open_receive_diff()` → abre wizard `stock.branch.transfer.receive.diff` con líneas precargadas (`product_id`, `qty_sent`, `qty_received = qty_sent`) y campo `note`; el wizard permite agregar productos. `action_confirm()` del wizard escribe `qty_received` (crea líneas nuevas con `qty_sent = 0` para productos agregados), `diff_note`, estado `with_diff` (o `received` si todo coincide), y reconcilia.
  - `action_close()` (with_diff→closed, solo manager).
  - Cada acción valida el estado de partida y lanza `UserError` si no corresponde.
  - `@api.model get_pending_count() -> int`: traslados `in_transit` con `dest_company_id in user.company_ids` + `with_diff` con origen o destino en `user.company_ids` (usa `sudo()` para contar, filtra por `company_ids` del usuario).

- [ ] **Step 1: Escribir tests** `tests/test_transfer_flow.py` (stock inicial 50 en A con `stock.quant._update_available_quantity` en sudo):
  - `test_send_moves_to_transit`: tras `action_send` → `qty(A) == 40`, `transit_qty == 10`, `qty(B) == 0`, estado `in_transit`.
  - `test_receive_full`: + `with_user(user_b).action_receive()` → A 40, tránsito 0, B 10, estado `received`.
  - `test_receive_with_shortage_then_close`: recibe 8 de 10 → B 8, tránsito 2, estado `with_diff`; `manager.action_close()` → A 42, tránsito 0, B 8, estado `closed`.
  - `test_receive_with_excess`: recibe 12 de 10 → A 38, tránsito 0, B 12.
  - `test_receive_unsent_product`: wizard agrega `product2` qty 3 → A de product2 = −3, B = 3, tránsito 0.
  - `test_user_a_cannot_receive`: `with_user(user_a).action_receive()` → `UserError`/`AccessError`.
  - `test_multi_company_user_receives`: usuario con A y B, `env.company = A`, recibe traslado C→B sin error.
  - `test_wrong_state_actions`: `action_receive` en draft → `UserError`; `action_send` dos veces → segunda `UserError` y `len(picking_ids)` no cambia.
  - `test_no_intercompany_counterpart`: `skipTest` si `stock_intercompany` no está instalado; tras enviar, `search_count([("counterpart_of_picking_id", "!=", False), ("origin", "in", picking_ids.mapped("name"))]) == 0`.
  - `test_pending_count`: `get_pending_count()` como `user_b` = 1 tras enviar, 0 tras recibir completo; con diferencias = 1 para `user_a` y `user_b`.
- [ ] **Step 2: Correr** (`-u stock_branch_transfer ... --test-tags /stock_branch_transfer`). Expected: estos tests fallan.
- [ ] **Step 3: Implementar** lo listado en Interfaces. Ubicación de stock de una empresa: `self.env["stock.warehouse"].sudo().search([("company_id", "=", company.id)], limit=1).lot_stock_id`; `UserError` si no hay almacén. Chatter: `message_post` con el resumen de diferencias al confirmar el wizard.
- [ ] **Step 4: Correr tests.** Expected: todos verdes (Task 1 + 2).
- [ ] **Step 5: Commit** `feat(stock_branch_transfer): envío, recepción con diferencias y cierre`.

---

### Task 3: Edición y anulación por manager

**Files:**
- Modify: `stock_branch_transfer/models/stock_branch_transfer.py`, `models/stock_branch_transfer_line.py`
- Create: `stock_branch_transfer/tests/test_transfer_manager.py`

**Interfaces:**
- Consumes: `_reconcile_stock()` de Task 2.
- Produces:
  - `write()` del traslado y `write()/create()/unlink()` de la línea: si el traslado no está en `draft` y cambian `dest_company_id`, `company_id`, `line_ids`, `qty_sent` o `qty_received`, exige grupo manager (`UserError` "Solo un manager puede editar un traslado ya enviado.") y llama `_reconcile_stock()` después de escribir. Las escrituras internas de las acciones de Task 2 pasan con contexto `branch_transfer_internal=True` para no disparar este chequeo.
  - Un traslado `received` editado por manager con `qty_received != qty_sent` se mantiene `received` (el objetivo usa r; s queda documental). Spec: editar → queda validado.
  - `action_cancel()` ("Anular", solo manager, cualquier estado ≠ draft/cancel): estado `cancel` + reconciliar (todo vuelve a 0).
  - `unlink()` del traslado: solo en `draft`; si no, `UserError` "Usá Anular para revertir un traslado ya enviado."
  - Mensaje en chatter con usuario y resumen en cada edición post-envío.

- [ ] **Step 1: Escribir tests** `tests/test_transfer_manager.py`:
  - `test_manager_edits_in_transit`: enviado 10, manager pone `qty_sent = 6` → A 44, tránsito 6.
  - `test_manager_edits_after_received`: recibido 10, manager pone `qty_received = 7` → A 43, B 7, tránsito 0.
  - `test_manager_changes_dest_after_received`: recibido en B, manager cambia destino a C → B 0, C 10.
  - `test_manager_edits_with_diff_then_close`: con diferencias (8/10), manager pone `qty_received = 9` y cierra → A 41, B 9.
  - `test_cancel_reverts_all`: recibido 10, `action_cancel()` → A 50, B 0, tránsito 0, estado `cancel`, pickings anteriores siguen en `done`.
  - `test_user_cannot_edit_sent`: `user_a` escribe `qty_sent` en traslado `in_transit` → `UserError`.
  - `test_unlink_sent_blocked`: `unlink()` de un `in_transit` (incluso manager) → `UserError`.
- [ ] **Step 2: Correr.** Expected: fallan.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Correr.** Expected: los tests de Task 1–3 en verde.
- [ ] **Step 5: Commit** `feat(stock_branch_transfer): edición y anulación por manager`.

---

### Task 4: Vistas, menús e ícono

**Files:**
- Create: `stock_branch_transfer/views/stock_branch_transfer_views.xml`, `views/branch_transfer_receive_diff_views.xml`, `views/menu_views.xml`
- Create: `stock_branch_transfer/static/description/icon.svg` → `icon.png` (skill `odoo-prometeo-modules`, glyph "T")
- Modify: `__manifest__.py` (`data` después de security y data)

**Interfaces:**
- Produces: menú raíz xmlid `stock_branch_transfer.menu_branch_transfer_root` ("Traslados", `web_icon="stock_branch_transfer,static/description/icon.png"`, grupo user), submenús "Enviados" (acción con `domain [("company_id", "in", allowed_company_ids)]`) y "Por recibir" (`domain [("dest_company_id", "in", allowed_company_ids)]`, filtro por defecto estado `in_transit`/`with_diff`).

- [ ] **Step 1: Vistas.** List (name, origen, destino, fecha envío, estado con `decoration-warning` en with_diff, `decoration-info` en in_transit, `decoration-muted` en cancel). Form estilo pedido de compra: header con botones por estado/grupo (`Enviar` en draft; `Recibido` y `Recibido con diferencias` en in_transit; `Cerrar` en with_diff solo manager; `Anular` solo manager en estados ≠ draft/cancel) + `statusbar` (draft,in_transit,received,closed); líneas editables `list editable="bottom"` con product_id (búsqueda por nombre/código de barras = comportamiento nativo de `product.product` name_search), `qty_sent`, `qty_received` (visible desde in_transit); campos readonly fuera de draft salvo para manager (`readonly="state != 'draft' and not context.get('is_manager')"` — implementar con un campo computado `is_manager` en el modelo); chatter. Search: filtros por estado y "Mis sucursales". Wizard form con líneas editables y nota. Aviso no bloqueante: columna computada `qty_available_origin` en la línea con `decoration-danger="qty_available_origin < qty_sent"`.
- [ ] **Step 2: Ícono** PNG 512 con Chrome headless según el skill.
- [ ] **Step 3: Verificar** `-u stock_branch_transfer -d sbt_test --test-enable --test-tags /stock_branch_transfer` sin errores de parseo y todos los tests en verde.
- [ ] **Step 4: Commit** `feat(stock_branch_transfer): vistas, menús e ícono`.

---

### Task 5: Contador sobre el ícono de la app

**Files:**
- Create: `stock_branch_transfer/static/src/js/transfer_badge_service.js`, `static/src/scss/transfer_badge.scss`
- Modify: `__manifest__.py` (`assets["web.assets_backend"]`)

**Interfaces:**
- Consumes: `stock.branch.transfer.get_pending_count()` de Task 2, xmlid de menú de Task 4.
- Produces: servicio `stock_branch_transfer_badge` (registry `services`, deps `["orm"]`): pide el conteo al arrancar y cada 60 s; un `MutationObserver` sobre `document.body` agrega/actualiza `<span class="o_branch_transfer_badge badge rounded-pill text-bg-danger">N</span>` dentro de cada elemento `[data-menu-xmlid="stock_branch_transfer.menu_branch_transfer_root"]` (cubre el dropdown de apps nativo, el sidebar móvil y `web_fullscreen_apps_menu`, que usan ese atributo). Sin badge si N = 0. Elegido observer en vez de patch de templates para no acoplarse a cuál menú de apps está instalado.

- [ ] **Step 1: Implementar** servicio + estilos (badge absoluto arriba a la derecha del ícono en el fullscreen; inline al lado del nombre en el dropdown).
- [ ] **Step 2: Instalar en `pruebas`** y `docker restart odoo-odoo-1` (asset nuevo no entra con `-u`):
  `docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d pruebas -i stock_branch_transfer --stop-after-init --no-http`
- [ ] **Step 3: Verificar en navegador** (Ctrl+Shift+R): como usuario de la sucursal destino, crear y enviar un traslado desde otra → el ícono de Traslados muestra 1; recibir → desaparece. Sin errores en consola.
- [ ] **Step 4: Commit** `feat(stock_branch_transfer): contador de pendientes en el ícono`.

---

### Task 6: Nota en el vault y PR

**Files:**
- Create: `/home/alexis/ObsidianVault/02-Prometeo/01-Odoo/Modulos/stock_branch_transfer.md` (plantilla del AGENTS.md, tag `subsistema/inventario-compras-ventas` primero)
- Modify: MOC `Modulos.md` (sección `## #subsistema/inventario-compras-ventas`)

- [ ] **Step 1: Escribir la nota**: modelo de objetivo + reconciliación, ubicación de tránsito propia, convivencia con `stock_intercompany` por `partner_id` vacío, gotcha del observer del badge, tests en `sbt_test`.
- [ ] **Step 2: Commit en el vault** y push de la rama `feat/stock-branch-transfer`; abrir PR contra `main` (nunca push a main).
