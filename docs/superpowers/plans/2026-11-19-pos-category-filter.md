# pos_category_filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada caja del POS vende solo los productos de las categorías de producto que tiene configuradas (incluir / excluir), sin usar Categorías de PdV.

**Architecture:** Módulo nuevo `pos_category_filter`. Backend: dos campos en `pos.config`, un helper de dominio que se suma a `_get_available_product_domain` (carga), al fallback de código de barras (`pos.session.find_product_by_barcode`) y se expone al frontend para "Buscar más". Frontend: patch de `ProductScreen` (oculta `CategorySelector`, bloquea escaneo con aviso, filtra `loadProductFromDB`). Vistas: campos nuevos en Ajustes del POS, se ocultan el filtro nativo y las Categorías de PdV. `post_init_hook` apaga `limit_categories`.

**Tech Stack:** Odoo 18, Python, OWL (patch), XML.

**Spec:** `docs/superpowers/specs/2026-11-19-pos-category-filter-design.md`

## Global Constraints

- Odoo 18; manifest `version: "18.0.1.0.0"`, `license: "LGPL-3"`, `author: "Alexis Medina"`, `depends: ["point_of_sale"]` (NO depender de `pos_promotions`).
- Convenciones de la skill `odoo-prometeo-modules`: un archivo por modelo, docstring en español en cada método, `_("texto %s", arg)`.
- Modo por defecto `all` → una caja sin configurar se comporta igual que hoy.
- Subcategorías incluidas siempre: operador `child_of`.
- Textos de UI en español: selector "Productos", opciones "Todos" / "Solo estas categorías" / "Todas menos estas"; aviso "Producto no habilitado en esta caja".
- Tests: `docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d pruebas -i pos_category_filter --test-tags /pos_category_filter --stop-after-init --no-http` (la base `test` no tiene `point_of_sale`). Después de cada `-i/-u`: `docker restart odoo-odoo-1`.

## Review Focus

1. **Modo `include`/`exclude` con lista vacía** → se comporta como `all` (no deja la caja sin productos ni filtra nada raro). Test en Task 1.
2. **Producto sin categoría válida / categoría hija** → `child_of` debe incluir hijas; producto en categoría hermana queda afuera. Test en Task 1.
3. **Packs de `pos_promotions` en caja `include`** que no los cubre → siguen cargando si `pos_promotions` está instalado; si no está instalado, el módulo no rompe. Test en Task 1 (skip si el campo no existe).
4. **Escanear código de producto excluido** → no se agrega al pedido, aviso "Producto no habilitado en esta caja"; código inexistente → aviso nativo de no encontrado. Tests backend en Task 2, verificación manual en Task 4.
5. **Caja con sesión abierta al instalar** → el hook apaga `limit_categories` igual; la caja recién refleja el cambio al recargar (Ctrl+Shift+R). Verificación manual en Task 4.

---

### Task 1: Campos en `pos.config` + dominio de carga

**Files:**
- Create: `pos_category_filter/__init__.py`, `__manifest__.py`, `models/__init__.py`, `models/pos_config.py`, `hooks.py`, `tests/__init__.py`, `tests/test_category_filter.py`

**Interfaces:**
- Produces:
  - `pos.config.category_filter_mode`: `fields.Selection([("all","Todos"),("include","Solo estas categorías"),("exclude","Todas menos estas")], string="Productos", default="all", required=True)`
  - `pos.config.category_filter_ids`: `fields.Many2many("product.category", "pos_config_category_filter_rel", "config_id", "categ_id", string="Categorías")`
  - `pos.config._get_category_filter_domain(self) -> list` — `[]` si modo `all` o lista vacía; `[("categ_id","child_of",ids)]` en `include`; `["!",("categ_id","child_of",ids)]` en `exclude`.
  - `pos.config._get_available_product_domain()` override: `AND(super, filtro)`; si existe `product.template.is_promotion_pack` y el filtro no es vacío, el filtro se ensancha con `OR([filtro, [("product_tmpl_id.is_promotion_pack","=",True)], [("id","in",component_ids)]])` donde `component_ids` sale de `pos.promotion.pack.line` (sudo, `pack_tmpl_id.active`), igual que `pos_promotions/models/pos_config.py`.
  - `hooks.post_init_hook(env)`: pone `limit_categories=False` en todas las `pos.config` que lo tenían y loguea `_logger.info` con sus nombres.

- [ ] **Step 1: Escribir tests que fallan** — `TransactionCase` que crea categorías `Padre > Hija` y `Otra`, un producto en cada una (`available_in_pos=True`, `sale_ok=True`) y una `pos.config` nueva. Tests:
  - `test_mode_all_loads_everything`: los 3 productos están en `search(config._get_available_product_domain())`.
  - `test_include_parent_includes_child`: `include` + `[Padre]` → producto de Hija adentro, producto de Otra afuera.
  - `test_exclude`: `exclude` + `[Padre]` → solo el de Otra.
  - `test_empty_list_behaves_as_all`: `include` y `exclude` con lista vacía → `_get_category_filter_domain() == []`.
  - `test_promotion_pack_kept`: si `"is_promotion_pack" not in env["product.template"]._fields` → `skipTest`; si no, un pack en Otra aparece con `include + [Padre]`.
  - `test_hook_disables_native_limit`: config con `limit_categories=True` → tras `post_init_hook(self.env)` queda `False`.
- [ ] **Step 2: Correr y ver que falla** (comando de Global Constraints). Esperado: error de instalación o FAIL por campos inexistentes.
- [ ] **Step 3: Implementar** manifest (`post_init_hook: "post_init_hook"`), modelo y hook con las firmas de arriba.
- [ ] **Step 4: Correr tests** → 6 OK.
- [ ] **Step 5: Commit** `feat(pos_category_filter): filtro de productos por categoría en la caja`

### Task 2: Bloqueo del código de barras en el servidor

**Files:**
- Create: `pos_category_filter/models/pos_session.py`
- Modify: `pos_category_filter/models/pos_config.py`, `models/__init__.py`, `tests/test_category_filter.py`

**Interfaces:**
- Consumes: `pos.config._get_category_filter_domain()` (Task 1).
- Produces:
  - `pos.config.is_barcode_blocked_by_category(self, barcode: str) -> bool` — `ensure_one`; `True` solo si existe un `product.product` con ese `barcode`, `sale_ok`, `available_in_pos`, y ninguno cumple `_get_category_filter_domain()`. Código inexistente → `False`.
  - `pos.session.find_product_by_barcode(barcode, config_id)` override: si `pos.config.browse(config_id).is_barcode_blocked_by_category(barcode)` → devolver la misma forma que devuelve `super()` cuando no encuentra nada (leer el método nativo en `point_of_sale/models/pos_session.py:1855`); si no, `super()`.

- [ ] **Step 1: Tests que fallan** (reusar el setup de Task 1, productos con `barcode`):
  - `test_barcode_blocked_when_excluded`: `include + [Otra]`, barcode del producto de Padre → `True`.
  - `test_barcode_allowed`: barcode del producto de Otra → `False`.
  - `test_barcode_unknown_not_blocked`: `"0000000000000"` → `False`.
  - `test_find_product_by_barcode_hides_excluded`: con sesión abierta de la config, `find_product_by_barcode(barcode_excluido, config.id)` no trae el producto en `"product.product"`.
- [ ] **Step 2: Correr** → FAIL.
- [ ] **Step 3: Implementar** las dos firmas.
- [ ] **Step 4: Correr** → 10 OK.
- [ ] **Step 5: Commit** `feat(pos_category_filter): bloquear escaneo de productos excluidos`

### Task 3: Vistas — configuración y ocultar Categorías de PdV

**Files:**
- Create: `pos_category_filter/models/res_config_settings.py`, `views/res_config_settings_views.xml`, `views/product_views.xml`, `views/menu_views.xml`
- Modify: `__manifest__.py` (`data`), `models/__init__.py`

**Interfaces:**
- Produces: `res.config.settings.pos_category_filter_mode` y `pos_category_filter_ids` (`related="pos_config_id.category_filter_*"`, `readonly=False`).

- [ ] **Step 1: Settings** — heredar `point_of_sale.res_config_settings_view_form`: `invisible="1"` al bloque de `pos_limit_categories` (líneas 143–147 de la vista nativa) y agregar al lado `pos_category_filter_mode` (widget `radio`) + `pos_category_filter_ids` (`many2many_tags`, `invisible="pos_category_filter_mode == 'all'"`), ambos `readonly="pos_has_active_session"`.
- [ ] **Step 2: Producto** — `invisible="1"` a `pos_categ_ids` en las vistas de `point_of_sale/views/product_view.xml` (form línea 70, form/kanban línea 192, listas 160/174). No tocar los filtros de búsqueda.
- [ ] **Step 3: Menú** — `point_of_sale.menu_products_pos_category`: `groups_id` a `base.group_no_one` (no `active=False`, para no pisar `web_menu_simplify`).
- [ ] **Step 4: Verificar** — `-u pos_category_filter -d pruebas --stop-after-init --no-http` sin errores + `docker restart odoo-odoo-1`; en Ajustes > PdV se ven los campos nuevos y no el filtro nativo; la ficha de producto no muestra "Categoría de PdV".
- [ ] **Step 5: Commit** `feat(pos_category_filter): configuración en ajustes y ocultar categorías de PdV`

### Task 4: Frontend del POS

**Files:**
- Create: `pos_category_filter/static/src/js/product_screen_patch.js`, `static/src/xml/product_screen.xml`
- Modify: `__manifest__.py` (`assets: {"point_of_sale._assets_pos": [...]}`)

**Interfaces:**
- Consumes: `pos.config.category_filter_mode` / `category_filter_ids` (cargados con la config; verificar si llegan como ids o como registros y normalizar a ids), `pos.config.is_barcode_blocked_by_category` (Task 2).

- [ ] **Step 1: Ocultar barra** — `t-inherit="point_of_sale.ProductScreen"` `t-inherit-mode="extension"`, `xpath //CategorySelector` → `t-if` = `false`.
- [ ] **Step 2: "Buscar más"** — patch `loadProductFromDBDomain(word)`: `super` + leaf `["categ_id","child_of",ids]` (include) o `"!"` + leaf (exclude); sin cambios si modo `all` o sin ids.
- [ ] **Step 3: Escaneo** — patch `_barcodeProductAction(code)`: `product = await this._getProductByBarcode(code)`; si `!product` y `await this.pos.data.call("pos.config","is_barcode_blocked_by_category",[this.pos.config.id, code.base_code])` → `this.sound.play("error")` + `this.notification.add(_t("Producto no habilitado en esta caja"), {type: "warning"})` y `return`; si no, `return super._barcodeProductAction(code)`. (Para códigos no encontrados hay una búsqueda doble; aceptado.)
- [ ] **Step 4: Verificar en `pruebas`** — `-u` + `docker restart odoo-odoo-1`, abrir una caja con `include + [Almacen - Cancha]`, Ctrl+Shift+R:
  - no hay barra de categorías; la grilla muestra solo productos de esa categoría (y packs si hay);
  - escanear/tipear un código de Bijouterie → aviso "Producto no habilitado en esta caja", no se agrega línea;
  - código inexistente → aviso nativo;
  - "Buscar más" con el nombre de un producto de Bijouterie → sin resultados;
  - caja en modo `all` → igual que antes.
- [ ] **Step 5: Commit** `feat(pos_category_filter): ocultar categorías y bloquear productos en el POS`

### Task 5: Cierre

- [ ] **Step 1:** Icono `static/description/icon.png` (skill `odoo-prometeo-modules`, glyph "C").
- [ ] **Step 2:** Correr la suite completa de Task 1–2 → 10 OK.
- [ ] **Step 3:** Nota en el vault `02-Prometeo/01-Odoo/Modulos/pos_category_filter.md` (tags `subsistema/pos`, `subsistema/productos-catalogo`) + entrada en el MOC `Modulos`. Gotchas: el fallback nativo de barcode ignora categorías; el hook apaga `limit_categories`; migración manual de las 3 cajas de "Cancha".
- [ ] **Step 4:** Commit + push + PR. En la descripción del PR: paso manual post-instalación en `prod` — "Tienda de ropa", "Mega futbol Caja 1", "Mega futbol Caja 2" → "Solo estas categorías: Almacen - Cancha".
