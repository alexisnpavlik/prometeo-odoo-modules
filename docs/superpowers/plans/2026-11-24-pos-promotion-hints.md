# Burbujas de promociones disponibles (pos_promotions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En la pantalla de productos del POS, mostrar burbujas flotantes con las promociones que la orden arrancó pero no completó ("Sumá 1 Vaso más, ahorra $300"). Solo informan.

**Architecture:** Un método nuevo `PosOrder.getPromotionHints()` en `promotion_packs.js` calcula, a partir de las unidades que quedaron fuera de los packs ya aplicados, qué promos están incompletas y qué les falta. Un componente OWL `PromotionHints` se monta dentro del panel derecho de `ProductScreen` y renderiza esos hints de forma reactiva. La burbuja abierta y las descartadas viven en `order.uiState` (en memoria, por orden).

**Tech Stack:** Odoo 18, OWL, POS assets (`point_of_sale._assets_pos`), tours POS (`TestPointOfSaleHttpCommon` + `web.assets_tests`).

**Spec:** `docs/superpowers/specs/2026-11-24-pos-promotion-hints-design.md`

## Global Constraints

- La burbuja **solo informa**: ningún click en ella agrega líneas a la orden.
- Sin cambios de modelos ni de datos en el servidor (solo JS/XML/SCSS + tests + manifest).
- Mismas promos que `applyPromotionPacks()`: sucursal de la caja (`pack.data.companies` incluye la empresa) y vigentes hoy (`date_start`/`date_end` contra `_getPromotionToday()`).
- Precio normal = precio de lista de la orden; precio de la promo = `_getPromotionPackPrice(pack, regular)`. Solo hints con ahorro > 0.
- Máximo **3** hints, orden: mayor ahorro primero.
- Círculo: 54 px, naranja `#e8590c`, animación suave de subir/bajar, pastilla verde (`#2b8a3e`) con "−$ahorro" debajo.
- Sin imagen del producto que falta → **2 iniciales** en mayúscula del nombre ("Coca-Cola" → "CO", "Vaso" → "VA").
- Burbuja abierta: "PROMO DISPONIBLE" / "Sumá 1 Coca-Cola" / "Fernet + Coca-Cola a $9.000" / "Ahorra $1.200" + ✕.
- Ubicación: esquina superior derecha del área de productos (`.rightpane`).
- Versión del módulo: `18.0.2.4.0` → `18.0.2.5.0`.
- Textos en español; nombres de código en inglés.

## Review Focus

1. **Cantidad > 1 en el pack** (2 Vasos): con 3 Vasos la promo aplica a 2 y el hint debe decir "Sumá 1 Vaso más"; con 2 no hay hint. → test en Task 1.
2. **Pack completo pero sin ahorro** (precio del pack ≥ precio normal): no mostrar hint aunque falte algo. → test en Task 1.
3. **Línea con descuento manual del cajero** (no candidata): no cuenta para el hint, igual que en `applyPromotionPacks()`. → test en Task 1.
4. **Producto que falta sin precio en la lista** (`get_price` → 0 o NaN): no romper; hint sin ese producto o descartado si el regular no es finito. → cubierto por la guarda en Step 3 de Task 1.
5. **Cambio de orden** (orden nueva / otra orden de la lista): las descartadas y la abierta no se arrastran. → test en Task 2.

---

### Task 1: Cálculo de hints en la orden

**Files:**
- Modify: `pos_promotions/static/src/js/promotion_packs.js`
- Create: `pos_promotions/tests/__init__.py`, `pos_promotions/tests/test_promotion_hints_tour.py`
- Create: `pos_promotions/static/tests/tours/promotion_hints_tour.js`
- Modify: `pos_promotions/__manifest__.py` (asset `web.assets_tests` → `pos_promotions/static/tests/tours/*.js`)

**Interfaces:**
- Produces:
  - `PosOrder._getActivePromotionPacks(): Pack[]` — `getPromotionPacks()` filtrado por sucursal y vigencia (extraído de `applyPromotionPacks()`, que pasa a usarlo).
  - `PosOrder.getPromotionHints(): Hint[]` con
    `Hint = { tmplId: number, name: string, product: product.product /* el pack */, missing: [{ product, qty }], price: number, regular: number, saving: number }`,
    orden por `saving` desc, sin los de `order.uiState.dismissedPromotionHints`, máximo 3.
  - `order.uiState.dismissedPromotionHints: number[]` (tmplIds), `order.uiState.openPromotionHintTmplId: number|false`.
  - En `PosStore.addLineToOrder`, después de `applyPromotionPacks()`: si algún hint contiene el producto agregado (en sus componentes), `uiState.openPromotionHintTmplId = ese tmplId`; si no, no se toca.

- [ ] **Step 1: Escribir el test Python del tour**

`TestPromotionHintsTour(TestPointOfSaleHttpCommon)`, `@tagged("post_install", "-at_install")`. En `setUpClass` crear (sin impuestos, `available_in_pos=True`):
- Productos: `PH Vaso` $900, `PH Fernet` $7.000, `PH Coca` $3.200 (con `image_1920` = PNG 1×1 en base64), `PH Agua` $1.000.
- Packs (`product.template` con `is_promotion_pack=True`, `available_in_pos=True`, `promotion_company_ids=[main_pos_config.company_id]`, `promotion_price_mode="fixed"`):
  - `PH 2 Vasos` list_price 1.500, línea `PH Vaso` qty 2.
  - `PH Fernet + Coca` list_price 9.000, líneas `PH Fernet` 1 + `PH Coca` 1.
  - `PH Agua cara` list_price 2.500, línea `PH Agua` qty 2 (más caro que 2 × 1.000: sin ahorro).

`test_promotion_hints_tour`: `self.start_pos_tour("pos_promotion_hints_tour")`.

- [ ] **Step 2: Escribir el tour `pos_promotion_hints_tour` (parte cálculo)**

Pasos con `Chrome.startPoS()`, `Dialog.confirm("Open Register")`, `ProductScreen.clickDisplayedProduct(...)` y pasos `run` que leen `window.posmodel.get_order().getPromotionHints()` y lanzan `Error("pos_promotions: ...")` si no coincide:
1. Click `PH Vaso` → 1 hint: `name` contiene "PH 2 Vasos", `missing` = `[{PH Vaso, 1}]`, `saving` = 300.
2. Click `PH Vaso` → 0 hints (promo aplicada).
3. Click `PH Vaso` → 1 hint "PH 2 Vasos", falta 1 `PH Vaso`.
4. Click `PH Fernet` → 2 hints; el primero es "PH Fernet + Coca" (`saving` 1.200), falta 1 `PH Coca`; `uiState.openPromotionHintTmplId` = tmpl de "PH Fernet + Coca".
5. Click `PH Agua` → sigue habiendo 2 hints (Agua cara no ahorra) y `openPromotionHintTmplId` no cambió.
6. Poner descuento manual 10% en la línea de `PH Fernet` (`ProductScreen.clickLine("PH Fernet")`, numpad "% Disc" → "1","0") → ya no hay hint de "PH Fernet + Coca".

- [ ] **Step 3: Correr el test y verificar que falla**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules/.superpowers/wt/promo-hints
docker run --rm --network odoo_odoo-net --entrypoint odoo \
  -v "$PWD":/mnt/wt -v ph_test_data:/var/lib/odoo \
  -v /home/alexis/Documents/Github/prometeo-odoo-modules/.superpowers/sdd/2026-11-22-single-company/odoo.conf:/etc/odoo/odoo.conf:ro \
  odoo-test-chrome:18 -c /etc/odoo/odoo.conf -d ph_test -i pos_promotions \
  --test-tags /pos_promotions --stop-after-init --no-http 2>&1 | tail -40
```
(`--no-http` no aplica a tours HttpCase: si el runner lo rechaza, quitarlo. La base `ph_test` se crea sola.)
Expected: FAIL — `getPromotionHints is not a function`.

- [ ] **Step 4: Implementar `_getActivePromotionPacks()` y `getPromotionHints()`**

`applyPromotionPacks()` usa `_getActivePromotionPacks()` en lugar de los dos `.filter` de sucursal y vigencia (sin cambio de comportamiento).

Algoritmo de `getPromotionHints()` (correr sobre el estado ya aplicado; no llama a `applyPromotionPacks()`):
```text
leftover[productId] = Σ qty de líneas candidatas (_isPromotionPackCandidate) SIN promotion_pack_tmpl_id
unitPrice[productId] = get_unit_price() de la primera de esas líneas
para cada pack de _getActivePromotionPacks():
    si ningún componente tiene leftover > 0 → saltar
    missing = [{product, qty: c.qty - leftover}] para componentes con leftover < c.qty
    si missing vacío → saltar (completo pero no aplicado = no ahorra)
    precio de cada componente = unitPrice si está, si no product.get_price(this.pricelist_id, c.qty)
    regular = Σ precio × c.qty ; si !Number.isFinite(regular) || regular <= 0 → saltar
    price = _getPromotionPackPrice(pack, regular) ; saving = regular − price ; si saving <= 0 → saltar
filtrar dismissed, ordenar por saving desc, slice(0, 3)
```
`name` = `pack.product.display_name`. Inicializar `uiState.dismissedPromotionHints ??= []` donde se lea.

En `addLineToOrder` (después de `order.applyPromotionPacks()`): actualizar `openPromotionHintTmplId` según Interfaces.

- [ ] **Step 5: Correr el test y verificar que pasa**

Mismo comando del Step 3 (con `-u pos_promotions` en vez de `-i` si la base ya existe). Expected: `0 failed, 0 error(s)`.

- [ ] **Step 6: Commit**

```bash
git add pos_promotions/static/src/js/promotion_packs.js pos_promotions/tests pos_promotions/static/tests pos_promotions/__manifest__.py
git commit -m "pos_promotions: calcula las promos incompletas de la orden"
```

---

### Task 2: Componente de burbujas en la pantalla de productos

**Files:**
- Create: `pos_promotions/static/src/js/promotion_hints.js`, `pos_promotions/static/src/xml/promotion_hints.xml`, `pos_promotions/static/src/scss/promotion_hints.scss`
- Modify: `pos_promotions/static/src/js/product_screen_patch.js` (registrar el componente en `ProductScreen.components`), `pos_promotions/__manifest__.py` (assets + versión `18.0.2.5.0`)
- Modify: `pos_promotions/static/tests/tours/promotion_hints_tour.js` (pasos de DOM)

**Interfaces:**
- Consumes: `order.getPromotionHints()`, `order.uiState.openPromotionHintTmplId`, `order.uiState.dismissedPromotionHints` (Task 1).
- Produces: componente `PromotionHints` (sin props; usa `usePos()`), template `pos_promotions.PromotionHints`, extensión de `point_of_sale.ProductScreen` que lo agrega como último hijo de `//div[hasclass('rightpane')]/div[hasclass('position-relative')]`.
- Clases DOM (los tests dependen de ellas): `.o_promotion_hints` (contenedor), `.o_promotion_hint_dot` (círculo; `.o_promotion_hint_dot_active` el abierto), `.o_promotion_hint_initials` (texto de iniciales), `.o_promotion_hint_dot img` (foto), `.o_promotion_hint_saving` (pastilla), `.o_promotion_hint_card` (burbuja abierta), `.o_promotion_hint_close` (✕).

- [ ] **Step 1: Agregar al tour los pasos de DOM** (intercalados con los de Task 1)

- Tras paso 1: existe `.o_promotion_hint_dot .o_promotion_hint_initials` con texto `PH` ("PH Vaso" → "PH"), `.o_promotion_hint_saving` contiene "300", `.o_promotion_hint_card` contiene "Sumá 1 PH Vaso" y "Ahorra".
- Tras paso 2: no existe `.o_promotion_hint_dot`.
- Tras paso 4: 2 `.o_promotion_hint_dot`; el activo tiene `img`; la card contiene "Sumá 1 PH Coca" y "PH Fernet + Coca".
- Click en el círculo inactivo → la card pasa a "PH 2 Vasos"; la orden sigue con las mismas líneas (contar `get_orderlines().length` antes y después).
- Click `.o_promotion_hint_close` → queda 1 círculo y `getPromotionHints()` ya no trae ese tmplId.
- Orden nueva (`Chrome.createFloatingOrder()`) → no hay `.o_promotion_hint_dot`; click `PH Vaso` → vuelve a aparecer (las descartadas no pasan de orden).

- [ ] **Step 2: Correr el test y verificar que falla**

Comando del Task 1 Step 3 con `-u pos_promotions`. Expected: FAIL en el primer trigger `.o_promotion_hint_dot`.

- [ ] **Step 3: Implementar el componente**

- `get hints()` → `this.pos.get_order()?.getPromotionHints() || []`.
- `get openHint()` → el de `uiState.openPromotionHintTmplId` si está en `hints`; si no, ninguno.
- `onClickDot(hint)` → `uiState.openPromotionHintTmplId = hint.tmplId`. `onClose(hint)` → push a `dismissedPromotionHints` y, si era el abierto, `openPromotionHintTmplId = false`.
- Imagen: `hint.missing[0].product.getImageUrl()` (vacío si no tiene `image_128`). Iniciales: primeras 2 letras/dígitos del nombre en mayúscula.
- Texto de "Sumá": `missing` unido con " y " → "Sumá 1 PH Coca y 2 PH Hielo"; un solo producto del mismo pack (Vaso) → "Sumá 1 PH Vaso más".
- Montos con `this.env.utils.formatCurrency`.
- Click en la card o en el círculo **no** llama a `addLineToOrder`.
- SCSS según Global Constraints; `position:absolute; top:12px; right:14px; z-index` por encima de `.product-list`; `pointer-events:none` en el contenedor y `auto` en círculos/card para no bloquear clicks en productos debajo de los huecos; animación `@keyframes` de 3 s con delay escalonado por círculo; `prefers-reduced-motion` sin animación.

- [ ] **Step 4: Correr el test y verificar que pasa**

Mismo comando. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 5: Commit**

```bash
git add pos_promotions
git commit -m "pos_promotions: burbujas flotantes con las promos que le faltan a la orden"
```

---

### Task 3: Verificación manual en `pruebas` y nota del vault

**Files:**
- Modify: nota del módulo en `/home/alexis/ObsidianVault/02-Prometeo/01-Odoo/Modulos/pos_promotions.md` (o crearla si no existe, con tag `subsistema/pos` y entrada en el MOC `Modulos`).

- [ ] **Step 1:** Instalar en `pruebas` (symlink del módulo desde el checkout compartido al worktree, como en [[pos_category_filter]]; o `-u` desde la rama), `docker restart odoo-odoo-1`, abrir una caja y repetir el caso Vaso / Fernet en el navegador. Captura en el PR.
- [ ] **Step 2:** Nota del vault: qué hace la burbuja, que solo informa, que usa las unidades sobrantes de `applyPromotionPacks()`, y el gotcha de `pointer-events`.
- [ ] **Step 3:** Push de la rama y PR contra `main` (sin merge).
