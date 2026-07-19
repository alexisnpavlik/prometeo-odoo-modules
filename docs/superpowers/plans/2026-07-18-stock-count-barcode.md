# stock_count_barcode — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Módulo Odoo 18 que permite escanear códigos de barras con la cámara del teléfono para cargar un conteo de stock y aplicarlo como ajuste de inventario nativo.

**Architecture:** Dos modelos nuevos (`stock.count.session` / `stock.count.line`) con vistas backend responsive. El escaneo usa el servicio de cámara del core web de Odoo desde un view widget OWL, que llama por RPC a un método del servidor y abre un diálogo para cargar la cantidad. La aplicación escribe `inventory_quantity` en los quants y llama `action_apply_inventory()`.

**Tech Stack:** Odoo 18.0, Python, OWL 2, XML (QWeb views), ZXing vía el core de Odoo.

**Spec:** `docs/superpowers/specs/2026-07-18-stock-count-barcode-design.md`

## Global Constraints

- Odoo **18.0**. Versión del manifiesto: `18.0.1.0.0`.
- Módulo en `/home/alexis/Documents/Github/prometeo-odoo-modules/stock_count_barcode/`.
- Rama de trabajo: `stock-count-barcode` (ya creada).
- `depends = ["stock", "web"]`. Sin dependencias JS externas.
- License `LGPL-3`. Author `Alexis Medina`.
- snake_case en todo. Docstring en cada método. Textos de UI en español.
- Traducciones estilo Odoo 18: `_("texto %s", arg)` — coma, nunca `%`.
- `_logger` de módulo, nunca `print`.
- **Sin grupos nuevos.** Leer/crear: `stock.group_stock_user`. Aplicar: `stock.group_stock_manager`.
- **Nunca escribir `stock.quant.quantity` a mano.** Todo ajuste pasa por `inventory_quantity` + `action_apply_inventory()`.
- **Toda escritura/creación de `stock.quant` requiere `.with_context(inventory_mode=True)`**, si no Odoo rechaza los campos de inventario.
- En `data` del manifiesto, `security/*` siempre antes que `views/*`.
- **Sin tests automatizados** — el repo no tiene suite. Cada tarea cierra con verificación manual en el contenedor.
- Contenedor local: `odoo-odoo-1` (Postgres en `odoo-postgres18-1`). Bases disponibles: **`prod`** (producción) y `calidad`. Este plan usa **`calidad`** — nunca `prod`; `docker` corre sin `sudo`.
- **Las pruebas de shell terminan con `env.cr.rollback()`.** Se prueba contra `calidad`: no dejes datos de prueba.

---

### Task 1: Verificar la API de escaneo por cámara — ✅ HECHA

Verificado el 2026-07-18 contra el contenedor `odoo-odoo-1` (Odoo 18.0). **No hay
nada que hacer en esta tarea**; el resultado está registrado abajo y la Tarea 7
lo consume.

```
<!-- RESULTADO TAREA 1 -->
Archivos:  web/static/src/core/barcode/
             barcode_dialog.js  barcode_video_scanner.js
             ZXingBarcodeDetector.js  barcode_dialog.{xml,scss}

Imports:
  import { scanBarcode } from "@web/core/barcode/barcode_dialog";
  import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";

Firmas:
  scanBarcode(env, facingMode = "environment") -> Promise<string>
      Abre BarcodeDialog via env.services.dialog. Resuelve con el código leído.
      RECHAZA si el usuario cierra el diálogo o falla la cámara.
  isBarcodeScannerSupported() -> boolean

ZXing: presente en web/static/lib/zxing-library/zxing-library.js
<!-- FIN RESULTADO -->
```

Dos correcciones respecto de lo que asumía el spec: **no existe** un
`barcode_scanner.js` (el módulo se llama `barcode_dialog.js`), y las dos
funciones viven en **archivos distintos**, así que son dos imports, no uno.

Como `scanBarcode` **rechaza** cuando el usuario cierra el diálogo, la llamada va
envuelta en `try/catch` que trata el rechazo como cancelación normal y no como
error a mostrar.

---

### Task 2: Esqueleto del módulo instalable

**Files:**
- Create: `stock_count_barcode/__init__.py`
- Create: `stock_count_barcode/__manifest__.py`
- Create: `stock_count_barcode/models/__init__.py`
- Create: `stock_count_barcode/data/ir_sequence.xml`
- Create: `stock_count_barcode/security/ir.model.access.csv`
- Create: `stock_count_barcode/security/security.xml`

**Interfaces:**
- Produce: módulo `stock_count_barcode` instalable; secuencia `stock_count_barcode.seq_stock_count_session`; reglas de acceso para `stock.count.session` y `stock.count.line`.

Los archivos de seguridad referencian modelos que recién existen en las Tareas 3 y 4, así que esta tarea **no se instala sola**: se escribe ahora para no volver a tocar el manifiesto, y la instalación se verifica al final de la Tarea 4. Los `data` del manifiesto ya listan todos los archivos del módulo; los de vistas se crean en la Tarea 6.

- [ ] **Step 1: Crear `__init__.py`**

```python
from . import models
```

- [ ] **Step 2: Crear `models/__init__.py`**

```python
from . import stock_count_session
from . import stock_count_line
```

- [ ] **Step 3: Crear `__manifest__.py`**

```python
{
    "name": "Conteo de stock por código de barras",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Conteo de inventario escaneando códigos de barras con la cámara del teléfono",
    "description": """
Conteo de stock por código de barras
====================================

Permite contar el stock de una ubicación escaneando los códigos de barras con la
cámara del teléfono (o con un lector láser en la PC).

Flujo:
  1. Se crea una sesión de conteo con empresa y ubicación.
  2. Se escanea cada producto y se carga la cantidad real contada.
  3. Al aplicar, las cantidades contadas se escriben como ajuste de inventario
     nativo de Odoo (inventory_quantity + action_apply_inventory).

El conteo es siempre parcial: los productos que no se escanean no se tocan.
Los productos con lotes, series o múltiples quants en la ubicación se rechazan
con error en vez de producir un total incorrecto.

Crear y cargar sesiones requiere Inventario/Usuario; aplicarlas requiere
Inventario/Administrador.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["stock", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "views/stock_count_session_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "stock_count_barcode/static/src/js/scan_button.js",
            "stock_count_barcode/static/src/xml/scan_button.xml",
            "stock_count_barcode/static/src/scss/stock_count.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
```

- [ ] **Step 4: Crear `data/ir_sequence.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="seq_stock_count_session" model="ir.sequence">
        <field name="name">Sesión de conteo de stock</field>
        <field name="code">stock.count.session</field>
        <field name="prefix">CONTEO/</field>
        <field name="padding">5</field>
        <field name="company_id" eval="False"/>
    </record>
</odoo>
```

`company_id` en False hace la secuencia global: el correlativo es único en toda la base, no por empresa. Es lo que querés para poder citar un número de conteo sin ambigüedad.

- [ ] **Step 5: Crear `security/ir.model.access.csv`**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_stock_count_session_user,stock.count.session user,model_stock_count_session,stock.group_stock_user,1,1,1,1
access_stock_count_line_user,stock.count.line user,model_stock_count_line,stock.group_stock_user,1,1,1,1
```

Los usuarios de inventario tienen acceso completo a los modelos; lo que los frena es el chequeo de grupo en `action_apply()` (Tarea 5), no el ACL. Un usuario puede borrar su propio conteo en borrador, que es el comportamiento deseado.

- [ ] **Step 6: Crear `security/security.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="rule_stock_count_session_company" model="ir.rule">
            <field name="name">Sesión de conteo: multi-empresa</field>
            <field name="model_id" ref="model_stock_count_session"/>
            <field name="domain_force">
                ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]
            </field>
            <field name="global" eval="True"/>
        </record>

        <record id="rule_stock_count_line_company" model="ir.rule">
            <field name="name">Línea de conteo: multi-empresa</field>
            <field name="model_id" ref="model_stock_count_line"/>
            <field name="domain_force">
                ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]
            </field>
            <field name="global" eval="True"/>
        </record>
    </data>
</odoo>
```

Reglas **globales** (`global=True`), no atadas a un grupo. Es deliberado: las reglas por grupo se combinan con OR, y en esta base eso ya causó bypasses silenciosos. Una regla global se aplica con AND a todo el mundo salvo superusuario, que es exactamente la semántica de multi-empresa que querés.

- [ ] **Step 7: Validar sintaxis**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('stock_count_barcode/__manifest__.py').read()); print('manifest ok')"
python3 -c "import xml.dom.minidom as m; m.parse('stock_count_barcode/data/ir_sequence.xml'); m.parse('stock_count_barcode/security/security.xml'); print('xml ok')"
python3 -c "import csv; rows=list(csv.reader(open('stock_count_barcode/security/ir.model.access.csv'))); print('csv cols:', {len(r) for r in rows})"
```

Esperado: `manifest ok`, `xml ok`, `csv cols: {8}`.

- [ ] **Step 8: Commit**

```bash
git add stock_count_barcode/
git commit -m "feat(stock-count): esqueleto del módulo, secuencia y seguridad"
```

---

### Task 3: Modelo `stock.count.session`

**Files:**
- Create: `stock_count_barcode/models/stock_count_session.py`

**Interfaces:**
- Consume: secuencia `stock_count_barcode.seq_stock_count_session` (Tarea 2).
- Produce: modelo `stock.count.session` con campos `name, company_id, location_id, user_id, state, date_start, date_applied, line_ids, line_count, diff_count` y métodos `action_cancel()`, `action_reset_to_draft()`. `action_apply()` y `action_scan_barcode()` llegan en las Tareas 5 y 7.

- [ ] **Step 1: Escribir el modelo**

```python
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockCountSession(models.Model):
    _name = "stock.count.session"
    _description = "Sesión de conteo de stock"
    _order = "date_start desc, id desc"

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
    location_id = fields.Many2one(
        "stock.location",
        string="Ubicación",
        required=True,
        domain="[('usage', '=', 'internal'), ('company_id', 'in', [company_id, False])]",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Contado por",
        required=True,
        default=lambda self: self.env.user,
    )
    state = fields.Selection(
        [("draft", "Borrador"), ("applied", "Aplicado"), ("cancelled", "Cancelado")],
        string="Estado",
        default="draft",
        required=True,
        copy=False,
    )
    date_start = fields.Datetime(
        string="Inicio",
        default=fields.Datetime.now,
        readonly=True,
    )
    date_applied = fields.Datetime(string="Aplicado el", readonly=True, copy=False)
    line_ids = fields.One2many(
        "stock.count.line",
        "session_id",
        string="Líneas",
    )
    line_count = fields.Integer(string="Productos contados", compute="_compute_counts")
    diff_count = fields.Integer(string="Con diferencia", compute="_compute_counts")

    @api.depends("line_ids", "line_ids.difference_qty")
    def _compute_counts(self):
        """Resume cuántas líneas hay y cuántas difieren del stock del sistema."""
        for session in self:
            session.line_count = len(session.line_ids)
            session.diff_count = len(
                session.line_ids.filtered(
                    lambda line: not float_is_zero(
                        line.difference_qty,
                        precision_rounding=line.product_id.uom_id.rounding or 0.01,
                    )
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia desde la secuencia al crear."""
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "stock.count.session"
                ) or _("Nuevo")
        return super().create(vals_list)

    def write(self, vals):
        """Bloquea empresa y ubicación una vez que la sesión tiene líneas."""
        locked_fields = {"company_id", "location_id"}
        if locked_fields & set(vals):
            for session in self:
                if session.line_ids:
                    raise UserError(
                        _(
                            "No se puede cambiar la empresa ni la ubicación de "
                            "'%s': ya tiene líneas cargadas. Cancelá la sesión y "
                            "creá una nueva.",
                            session.name,
                        )
                    )
        return super().write(vals)

    def _check_draft(self):
        """Valida que la sesión esté en borrador antes de modificarla."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(
                _("La sesión '%s' no está en borrador.", self.name)
            )

    def action_cancel(self):
        """Cancela una sesión en borrador."""
        for session in self:
            session._check_draft()
        self.write({"state": "cancelled"})
        return True

    def action_reset_to_draft(self):
        """Devuelve a borrador una sesión cancelada. Las aplicadas no se reabren."""
        for session in self:
            if session.state != "cancelled":
                raise UserError(
                    _(
                        "Solo se pueden reabrir sesiones canceladas. "
                        "Un conteo aplicado se corrige con una sesión nueva.",
                    )
                )
        self.write({"state": "draft"})
        return True
```

- [ ] **Step 2: Agregar el import que falta**

`_compute_counts` usa `float_is_zero`. Agregalo arriba, junto a los otros imports de Odoo:

```python
from odoo.tools import float_is_zero
```

Comparar floats con `!= 0` en cantidades de stock da falsos positivos por redondeo de la unidad de medida — de ahí `float_is_zero` con el `rounding` del UoM.

- [ ] **Step 3: Validar sintaxis**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('stock_count_barcode/models/stock_count_session.py').read()); print('ok')"
```

Esperado: `ok`.

- [ ] **Step 4: Commit**

```bash
git add stock_count_barcode/models/stock_count_session.py
git commit -m "feat(stock-count): modelo stock.count.session"
```

---

### Task 4: Modelo `stock.count.line` + primera instalación

**Files:**
- Create: `stock_count_barcode/models/stock_count_line.py`

**Interfaces:**
- Consume: `stock.count.session` (Tarea 3).
- Produce: modelo `stock.count.line` con `session_id, product_id, barcode, company_id, location_id, theoretical_qty, counted_qty, difference_qty, uom_id, error` y el helper `_get_quants()` que la Tarea 5 usa.

- [ ] **Step 1: Escribir el modelo**

```python
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StockCountLine(models.Model):
    _name = "stock.count.line"
    _description = "Línea de conteo de stock"
    _order = "id desc"

    session_id = fields.Many2one(
        "stock.count.session",
        string="Sesión",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        ondelete="restrict",
    )
    barcode = fields.Char(
        string="Código de barras",
        related="product_id.barcode",
        readonly=True,
    )
    uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad",
        related="product_id.uom_id",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        related="session_id.company_id",
        store=True,
        readonly=True,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Ubicación",
        related="session_id.location_id",
        readonly=True,
    )
    state = fields.Selection(related="session_id.state", readonly=True)
    counted_qty = fields.Float(
        string="Contado",
        digits="Product Unit of Measure",
        default=0.0,
    )
    theoretical_qty = fields.Float(
        string="Sistema",
        digits="Product Unit of Measure",
        compute="_compute_theoretical_qty",
    )
    difference_qty = fields.Float(
        string="Diferencia",
        digits="Product Unit of Measure",
        compute="_compute_theoretical_qty",
    )
    error = fields.Char(string="Error", readonly=True, copy=False)

    _sql_constraints = [
        (
            "product_uniq_per_session",
            "unique(session_id, product_id)",
            "El producto ya está cargado en esta sesión de conteo.",
        ),
    ]

    def _get_quants(self):
        """Devuelve los quants del producto en la ubicación de la sesión.

        Se lee en el contexto de empresa de la sesión para no mezclar stock
        entre sucursales.
        """
        self.ensure_one()
        return (
            self.env["stock.quant"]
            .with_company(self.company_id)
            .search(
                [
                    ("product_id", "=", self.product_id.id),
                    ("location_id", "=", self.location_id.id),
                ]
            )
        )

    @api.depends("product_id", "counted_qty", "session_id.location_id")
    def _compute_theoretical_qty(self):
        """Lee el stock del sistema en tiempo real, nunca un valor congelado.

        Congelarlo al escanear haría que una venta ocurrida durante el conteo
        quede pisada por el ajuste.
        """
        for line in self:
            quants = line._get_quants() if line.product_id and line.location_id else False
            line.theoretical_qty = sum(quants.mapped("quantity")) if quants else 0.0
            line.difference_qty = line.counted_qty - line.theoretical_qty

    @api.constrains("counted_qty")
    def _check_counted_qty(self):
        """Una cantidad contada negativa siempre es un error de carga."""
        for line in self:
            if line.counted_qty < 0:
                raise ValidationError(
                    _(
                        "La cantidad contada de '%s' no puede ser negativa.",
                        line.product_id.display_name,
                    )
                )
```

- [ ] **Step 2: Validar sintaxis**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('stock_count_barcode/models/stock_count_line.py').read()); print('ok')"
```

Esperado: `ok`.

- [ ] **Step 3: Crear vistas mínimas provisorias para poder instalar**

El manifiesto ya lista `views/stock_count_session_views.xml` y `views/menu_views.xml`. Creá los dos archivos con contenido vacío válido para que el módulo instale; la Tarea 6 los llena.

```bash
mkdir -p stock_count_barcode/views
printf '<?xml version="1.0" encoding="utf-8"?>\n<odoo>\n</odoo>\n' > stock_count_barcode/views/stock_count_session_views.xml
printf '<?xml version="1.0" encoding="utf-8"?>\n<odoo>\n</odoo>\n' > stock_count_barcode/views/menu_views.xml
```

- [ ] **Step 4: Crear los assets vacíos que el manifiesto declara**

```bash
mkdir -p stock_count_barcode/static/src/js stock_count_barcode/static/src/xml stock_count_barcode/static/src/scss
printf '/** @odoo-module **/\n' > stock_count_barcode/static/src/js/scan_button.js
printf '<?xml version="1.0" encoding="UTF-8"?>\n<templates xml:space="preserve">\n</templates>\n' > stock_count_barcode/static/src/xml/scan_button.xml
printf '// estilos del conteo de stock\n' > stock_count_barcode/static/src/scss/stock_count.scss
```

Un asset declarado en el manifiesto que no existe rompe el arranque del webclient, así que los archivos tienen que existir aunque estén vacíos.

- [ ] **Step 5: Instalar el módulo**

```bash
docker exec odoo-odoo-1 odoo -i stock_count_barcode -d calidad --stop-after-init
```

Esperado: termina sin traceback, con líneas de log del tipo `loading stock_count_barcode/...` y `Modules loaded.`

- [ ] **Step 6: Verificar que los modelos y la secuencia existen**

```bash
docker exec odoo-postgres18-1 psql -U odoo -d calidad -tAc \
  "select model from ir_model where model in ('stock.count.session','stock.count.line') order by model"
docker exec odoo-postgres18-1 psql -U odoo -d calidad -tAc \
  "select prefix from ir_sequence where code='stock.count.session'"
```

Esperado: las dos filas de modelos y `CONTEO/`.

- [ ] **Step 7: Commit**

```bash
git add stock_count_barcode/
git commit -m "feat(stock-count): modelo stock.count.line, módulo instalable"
```

---

### Task 5: Aplicación del conteo

**Files:**
- Modify: `stock_count_barcode/models/stock_count_session.py` (agregar `action_apply`)
- Modify: `stock_count_barcode/models/stock_count_line.py` (agregar `_apply_line`)

**Interfaces:**
- Consume: `stock.count.line._get_quants()` (Tarea 4).
- Produce: `stock.count.session.action_apply()` → `True`; `stock.count.line._apply_line()` → `stock.quant` afectado (recordset vacío si no hubo nada que ajustar) y setea `error` si falla.

- [ ] **Step 1: Agregar `_apply_line()` a `stock_count_line.py`**

Al final de la clase `StockCountLine`:

```python
    def _apply_line(self):
        """Prepara el quant de esta línea con la cantidad contada.

        No aplica el ajuste: solo escribe inventory_quantity. El que aplica es
        action_apply_inventory() sobre el conjunto de quants, en la sesión.

        Devuelve el quant preparado, o un recordset vacío si no hay nada que
        ajustar. Si la línea no se puede aplicar, setea self.error y devuelve
        un recordset vacío.
        """
        self.ensure_one()
        self.error = False
        quants = self._get_quants()

        if len(quants) > 1:
            self.error = _(
                "El producto tiene %s quants en la ubicación (lotes, series o "
                "paquetes). Ajustalo a mano desde Inventario.",
                len(quants),
            )
            return self.env["stock.quant"]

        quant_model = (
            self.env["stock.quant"]
            .with_company(self.company_id)
            .with_context(inventory_mode=True)
        )

        if quants:
            quant = quants.with_company(self.company_id).with_context(
                inventory_mode=True
            )
            quant.inventory_quantity = self.counted_qty
            return quant

        if self.counted_qty <= 0:
            return self.env["stock.quant"]

        return quant_model.create(
            {
                "product_id": self.product_id.id,
                "location_id": self.location_id.id,
                "inventory_quantity": self.counted_qty,
            }
        )
```

`with_context(inventory_mode=True)` no es opcional: sin él Odoo rechaza escribir o crear los campos de inventario del quant.

- [ ] **Step 2: Agregar `action_apply()` a `stock_count_session.py`**

Al final de la clase `StockCountSession`:

```python
    def action_apply(self):
        """Aplica el conteo como ajuste de inventario nativo.

        Las líneas que fallan quedan marcadas con su error y no frenan a las
        demás: abortar toda la sesión por un producto con lotes obligaría a
        recontar la ubicación entera.
        """
        self.ensure_one()
        self._check_draft()

        if not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError(
                _(
                    "Solo un administrador de inventario puede aplicar un "
                    "conteo. Pedile a un responsable que la aplique."
                )
            )

        if not self.line_ids:
            raise UserError(
                _("La sesión '%s' no tiene líneas para aplicar.", self.name)
            )

        quants = self.env["stock.quant"]
        failed = 0
        for line in self.line_ids:
            try:
                quants |= line._apply_line()
                if line.error:
                    failed += 1
            except Exception as e:
                line.error = str(e)
                failed += 1
                _logger.exception(
                    "Conteo %s: falló la línea del producto %s",
                    self.name,
                    line.product_id.display_name,
                )

        if quants:
            quants.with_context(inventory_mode=True).action_apply_inventory()

        self.write({"state": "applied", "date_applied": fields.Datetime.now()})
        _logger.info(
            "Conteo %s aplicado: %s líneas ajustadas, %s con error",
            self.name,
            len(quants),
            failed,
        )
        return True
```

- [ ] **Step 3: Validar sintaxis**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['stock_count_barcode/models/stock_count_session.py','stock_count_barcode/models/stock_count_line.py']]; print('ok')"
```

Esperado: `ok`.

- [ ] **Step 4: Actualizar el módulo y probar desde el shell**

```bash
docker exec odoo-odoo-1 odoo -u stock_count_barcode -d calidad --stop-after-init
```

Esperado: sin traceback.

Ahora probá el ciclo completo en el shell de Odoo. Reemplazá `<ubicacion_id>` por el id de una ubicación interna real y `<producto_id>` por un producto **sin lotes** con stock en esa ubicación.

```bash
docker exec -i odoo-odoo-1 odoo shell -d calidad --no-http <<'PY'
session = env['stock.count.session'].create({
    'location_id': <ubicacion_id>,
})
line = env['stock.count.line'].create({
    'session_id': session.id,
    'product_id': <producto_id>,
    'counted_qty': 999.0,
})
print('teorico antes:', line.theoretical_qty)
session.action_apply()
print('estado:', session.state, '| error:', line.error)
quant = line._get_quants()
print('stock despues:', sum(quant.mapped('quantity')))
env.cr.rollback()
PY
```

Esperado: `estado: applied`, `error: False`, y `stock despues: 999.0`.

El `env.cr.rollback()` final deshace todo — es una prueba contra la base de producción, no dejes basura. Si el shell no hace commit automático igual conviene el rollback explícito.

- [ ] **Step 5: Probar el rechazo de productos con lotes**

Repetí el bloque anterior con un producto que tenga lotes o series en esa ubicación.

Esperado: `estado: applied`, y `error` con el texto de los múltiples quants. El stock del producto **no** cambió.

- [ ] **Step 6: Commit**

```bash
git add stock_count_barcode/models/
git commit -m "feat(stock-count): aplicar el conteo como ajuste de inventario nativo"
```

---

### Task 6: Vistas backend

**Files:**
- Modify: `stock_count_barcode/views/stock_count_session_views.xml`
- Modify: `stock_count_barcode/views/menu_views.xml`
- Modify: `stock_count_barcode/static/src/scss/stock_count.scss`

**Interfaces:**
- Consume: modelos y acciones de las Tareas 3-5.
- Produce: acción `stock_count_barcode.action_stock_count_session`, vista formulario `stock_count_barcode.view_stock_count_session_form` (donde la Tarea 7 inserta el widget de escaneo), menú bajo Inventario.

- [ ] **Step 1: Escribir `views/stock_count_session_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_stock_count_session_list" model="ir.ui.view">
        <field name="name">stock.count.session.list</field>
        <field name="model">stock.count.session</field>
        <field name="arch" type="xml">
            <list string="Conteos de stock">
                <field name="name"/>
                <field name="location_id"/>
                <field name="user_id"/>
                <field name="date_start"/>
                <field name="line_count"/>
                <field name="diff_count"/>
                <field name="company_id" groups="base.group_multi_company"/>
                <field name="state" widget="badge"
                       decoration-info="state == 'draft'"
                       decoration-success="state == 'applied'"
                       decoration-muted="state == 'cancelled'"/>
            </list>
        </field>
    </record>

    <record id="view_stock_count_session_form" model="ir.ui.view">
        <field name="name">stock.count.session.form</field>
        <field name="model">stock.count.session</field>
        <field name="arch" type="xml">
            <form string="Conteo de stock" class="o_stock_count_form">
                <header>
                    <button name="action_apply" type="object" string="Aplicar"
                            class="btn-primary" invisible="state != 'draft'"
                            groups="stock.group_stock_manager"
                            confirm="Se van a ajustar las cantidades contadas. ¿Aplicar el conteo?"/>
                    <button name="action_cancel" type="object" string="Cancelar"
                            invisible="state != 'draft'"/>
                    <button name="action_reset_to_draft" type="object"
                            string="Volver a borrador" invisible="state != 'cancelled'"/>
                    <field name="state" widget="statusbar"
                           statusbar_visible="draft,applied"/>
                </header>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="company_id" groups="base.group_multi_company"
                                   readonly="line_count > 0 or state != 'draft'"/>
                            <field name="location_id"
                                   readonly="line_count > 0 or state != 'draft'"/>
                        </group>
                        <group>
                            <field name="user_id" readonly="state != 'draft'"/>
                            <field name="date_start"/>
                            <field name="date_applied" invisible="state != 'applied'"/>
                            <field name="line_count"/>
                            <field name="diff_count"/>
                        </group>
                    </group>

                    <notebook>
                        <page string="Conteo" name="lines">
                            <field name="line_ids" readonly="state != 'draft'">
                                <list editable="bottom" create="0">
                                    <field name="product_id" readonly="1"/>
                                    <field name="barcode" optional="show"/>
                                    <field name="counted_qty"/>
                                    <field name="theoretical_qty" readonly="1"/>
                                    <field name="difference_qty" readonly="1"
                                           decoration-danger="difference_qty != 0"/>
                                    <field name="uom_id" optional="hide"/>
                                    <field name="error" readonly="1" optional="show"
                                           decoration-danger="error"/>
                                </list>
                            </field>
                        </page>
                    </notebook>
                </sheet>
            </form>
        </field>
    </record>

    <record id="view_stock_count_session_search" model="ir.ui.view">
        <field name="name">stock.count.session.search</field>
        <field name="model">stock.count.session</field>
        <field name="arch" type="xml">
            <search string="Conteos">
                <field name="name"/>
                <field name="location_id"/>
                <field name="user_id"/>
                <filter name="filter_draft" string="Borrador"
                        domain="[('state', '=', 'draft')]"/>
                <filter name="filter_applied" string="Aplicados"
                        domain="[('state', '=', 'applied')]"/>
                <filter name="filter_mine" string="Mis conteos"
                        domain="[('user_id', '=', uid)]"/>
                <group expand="0" string="Agrupar por">
                    <filter name="group_location" string="Ubicación"
                            context="{'group_by': 'location_id'}"/>
                    <filter name="group_user" string="Usuario"
                            context="{'group_by': 'user_id'}"/>
                    <filter name="group_state" string="Estado"
                            context="{'group_by': 'state'}"/>
                </group>
            </search>
        </field>
    </record>

    <record id="action_stock_count_session" model="ir.actions.act_window">
        <field name="name">Conteos de stock</field>
        <field name="res_model">stock.count.session</field>
        <field name="view_mode">list,form</field>
        <field name="search_view_id" ref="view_stock_count_session_search"/>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Creá tu primer conteo</p>
            <p>Elegí una ubicación, escaneá los productos con la cámara y cargá
               la cantidad real contada. Al aplicar, las diferencias se ajustan
               en el inventario.</p>
        </field>
    </record>

    <!-- Formulario de carga rápida de cantidad, abierto tras cada escaneo -->
    <record id="view_stock_count_line_quick_form" model="ir.ui.view">
        <field name="name">stock.count.line.quick.form</field>
        <field name="model">stock.count.line</field>
        <field name="arch" type="xml">
            <form string="Cantidad contada" class="o_stock_count_quick_form">
                <sheet>
                    <div class="oe_title">
                        <h2><field name="product_id" readonly="1" options="{'no_open': True}"/></h2>
                    </div>
                    <group>
                        <field name="counted_qty" class="o_stock_count_qty_input"/>
                        <field name="theoretical_qty" readonly="1"/>
                        <field name="uom_id" readonly="1"/>
                    </group>
                </sheet>
                <footer>
                    <button string="Confirmar" special="save" class="btn-primary"/>
                    <button string="Descartar" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>
</odoo>
```

El botón **Aplicar** vive en el `<header>`, no al pie de la lista: en un conteo de 200 líneas no puede quedar a un scroll de distancia de "borrar la última línea". Lleva `confirm` porque mueve stock.

`create="0"` en la lista de líneas es deliberado: las líneas se crean escaneando, no tipeando un producto a mano. Editar y borrar sí se puede.

- [ ] **Step 2: Escribir `views/menu_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_stock_count_session"
              name="Conteos de stock"
              parent="stock.menu_stock_warehouse_mgmt"
              action="action_stock_count_session"
              groups="stock.group_stock_user"
              sequence="95"/>
</odoo>
```

- [ ] **Step 3: Escribir `static/src/scss/stock_count.scss`**

```scss
// Conteo de stock — ajustes para pantalla de teléfono
.o_stock_count_form {
    .o_stock_count_scan_button {
        width: 100%;
        min-height: 3.5rem;
        font-size: 1.25rem;
        font-weight: 600;
        margin-bottom: 1rem;
    }
}

.o_stock_count_quick_form {
    .o_stock_count_qty_input input {
        font-size: 1.5rem;
        text-align: right;
    }
}
```

- [ ] **Step 4: Validar sintaxis y actualizar**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; m.parse('stock_count_barcode/views/stock_count_session_views.xml'); m.parse('stock_count_barcode/views/menu_views.xml'); print('xml ok')"
docker exec odoo-odoo-1 odoo -u stock_count_barcode -d calidad --stop-after-init
```

Esperado: `xml ok` y actualización sin traceback.

- [ ] **Step 5: Verificar en el navegador**

Abrí Odoo → **Inventario → Configuración → Conteos de stock** (o donde haya quedado bajo `menu_stock_warehouse_mgmt`). Creá una sesión, elegí ubicación, guardá.

Esperado: la referencia queda `CONTEO/00001`, el botón Aplicar aparece en el header, y la lista de líneas está vacía y sin botón "Agregar línea".

- [ ] **Step 6: Commit**

```bash
git add stock_count_barcode/views/ stock_count_barcode/static/
git commit -m "feat(stock-count): vistas de sesión, línea rápida y menú"
```

---

### Task 7: Escaneo por cámara

**Files:**
- Modify: `stock_count_barcode/models/stock_count_session.py` (agregar `action_scan_barcode`)
- Modify: `stock_count_barcode/static/src/js/scan_button.js`
- Modify: `stock_count_barcode/static/src/xml/scan_button.xml`
- Modify: `stock_count_barcode/views/stock_count_session_views.xml` (insertar el widget)

**Interfaces:**
- Consume: el resultado de la **Tarea 1** (ruta de import y firma de `scanBarcode`); `view_stock_count_line_quick_form` (Tarea 6).
- Produce: `stock.count.session.action_scan_barcode(barcode)` → dict con `{"action": <act_window>}` en éxito o `{"error": "<texto>"}` si el código no corresponde a ningún producto; view widget registrado como `stock_count_scan_button`.

- [ ] **Step 1: Agregar `action_scan_barcode()` a `stock_count_session.py`**

Al final de la clase `StockCountSession`:

```python
    def action_scan_barcode(self, barcode):
        """Procesa un código escaneado y devuelve la acción para cargar cantidad.

        Si el producto ya está en la sesión, se reutiliza su línea en vez de
        crear una nueva: el usuario ve el total cargado y decide.
        """
        self.ensure_one()
        self._check_draft()

        barcode = (barcode or "").strip()
        if not barcode:
            return {"error": _("No se leyó ningún código.")}

        product = (
            self.env["product.product"]
            .with_company(self.company_id)
            .search([("barcode", "=", barcode)], limit=1)
        )
        if not product:
            return {
                "error": _("No hay ningún producto con el código %s.", barcode)
            }

        line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if not line:
            line = self.env["stock.count.line"].create(
                {
                    "session_id": self.id,
                    "product_id": product.id,
                    "counted_qty": 0.0,
                }
            )

        return {
            "action": {
                "type": "ir.actions.act_window",
                "res_model": "stock.count.line",
                "res_id": line.id,
                "views": [
                    (
                        self.env.ref(
                            "stock_count_barcode.view_stock_count_line_quick_form"
                        ).id,
                        "form",
                    )
                ],
                "target": "new",
                "name": product.display_name,
            }
        }
```

- [ ] **Step 2: Escribir `static/src/js/scan_button.js`**

Los imports de abajo ya son los verificados en la Tarea 1 — las dos funciones viven en archivos distintos.

```javascript
/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";

export class StockCountScanButton extends Component {
    static template = "stock_count_barcode.ScanButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            cameraSupported: isBarcodeScannerSupported(),
            manual: "",
            busy: false,
        });
    }

    get disabled() {
        return this.state.busy || this.props.record.data.state !== "draft";
    }

    /**
     * Abre la cámara, lee un código y lo procesa.
     */
    async onScanClick() {
        let barcode;
        try {
            barcode = await scanBarcode(this.env);
        } catch {
            // El usuario cerró el escáner o denegó la cámara: no es un error.
            return;
        }
        await this.processBarcode(barcode);
    }

    /**
     * Procesa el código tipeado a mano (PC sin cámara o lector láser USB).
     */
    async onManualSubmit(ev) {
        if (ev.key && ev.key !== "Enter") {
            return;
        }
        const barcode = this.state.manual;
        this.state.manual = "";
        await this.processBarcode(barcode);
    }

    /**
     * Guarda la sesión, manda el código al servidor y abre la carga de cantidad.
     */
    async processBarcode(barcode) {
        if (!barcode || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            // La sesión tiene que estar guardada: el servidor crea la línea.
            await this.props.record.save();
            const result = await this.orm.call(
                "stock.count.session",
                "action_scan_barcode",
                [this.props.record.resId, barcode]
            );
            if (result.error) {
                this.notification.add(result.error, {
                    type: "warning",
                    title: _t("Código no reconocido"),
                });
                return;
            }
            await this.action.doAction(result.action, {
                onClose: () => this.props.record.load(),
            });
        } finally {
            this.state.busy = false;
        }
    }
}

export const stockCountScanButton = {
    component: StockCountScanButton,
};

registry.category("view_widgets").add("stock_count_scan_button", stockCountScanButton);
```

- [ ] **Step 3: Escribir `static/src/xml/scan_button.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

    <t t-name="stock_count_barcode.ScanButton">
        <div class="o_stock_count_scan">
            <button type="button"
                    class="btn btn-primary o_stock_count_scan_button"
                    t-if="state.cameraSupported"
                    t-att-disabled="disabled"
                    t-on-click="onScanClick">
                <i class="fa fa-camera me-2"/>Escanear producto
            </button>
            <div class="input-group">
                <input type="text"
                       class="form-control"
                       placeholder="Código de barras"
                       t-att-disabled="disabled"
                       t-model="state.manual"
                       t-on-keydown="onManualSubmit"/>
                <button type="button"
                        class="btn btn-secondary"
                        t-att-disabled="disabled"
                        t-on-click="onManualSubmit">
                    Cargar
                </button>
            </div>
        </div>
    </t>

</templates>
```

El campo de texto está siempre visible, no solo cuando falta la cámara: es donde un lector láser USB escribe solo, y es la salida cuando la cámara falla en el momento menos oportuno.

- [ ] **Step 4: Insertar el widget en el formulario**

En `views/stock_count_session_views.xml`, dentro de `view_stock_count_session_form`, justo **antes** del `<notebook>`:

```xml
                    <widget name="stock_count_scan_button" invisible="state != 'draft'"/>
```

- [ ] **Step 5: Validar y actualizar**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import xml.dom.minidom as m; m.parse('stock_count_barcode/views/stock_count_session_views.xml'); m.parse('stock_count_barcode/static/src/xml/scan_button.xml'); print('xml ok')"
python3 -c "import ast; ast.parse(open('stock_count_barcode/models/stock_count_session.py').read()); print('py ok')"
docker exec odoo-odoo-1 odoo -u stock_count_barcode -d calidad --stop-after-init
```

Esperado: `xml ok`, `py ok`, actualización sin traceback.

- [ ] **Step 6: Verificar en el navegador de la PC**

Abrí una sesión en borrador. Tipeá el código de barras de un producto real en el campo de texto y dale Enter.

Esperado: se abre el diálogo con el nombre del producto, `counted_qty` en 0 y el teórico correcto. Confirmás, el diálogo cierra y la línea aparece en la lista.

Repetí con el **mismo** código.

Esperado: se abre el diálogo de la **misma** línea con la cantidad ya cargada — no se crea una segunda línea.

Probá con un código inventado.

Esperado: notificación naranja "No hay ningún producto con el código X", sin línea nueva.

- [ ] **Step 7: Commit**

```bash
git add stock_count_barcode/
git commit -m "feat(stock-count): escaneo por cámara y carga rápida de cantidad"
```

---

### Task 8: Icono del módulo

**Files:**
- Create: `stock_count_barcode/static/description/icon.png`
- Create (temporal): `/tmp/claude-1000/-home-alexis-Documents-Github/84813814-b60b-47e9-8c84-b5e2b6bc1f65/scratchpad/icon.svg`

**Interfaces:** ninguna.

- [ ] **Step 1: Copiar y re-skinear la plantilla**

```bash
mkdir -p /home/alexis/Documents/Github/prometeo-odoo-modules/stock_count_barcode/static/description
cp /home/alexis/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg \
   /tmp/claude-1000/-home-alexis-Documents-Github/84813814-b60b-47e9-8c84-b5e2b6bc1f65/scratchpad/icon.svg
```

Editá el `<text>` del glifo y poné `C` (de Conteo). Dejá los acentos cyan/magenta.

- [ ] **Step 2: Renderizar a PNG con Chrome headless**

```bash
cd /tmp/claude-1000/-home-alexis-Documents-Github/84813814-b60b-47e9-8c84-b5e2b6bc1f65/scratchpad
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="/home/alexis/Documents/Github/prometeo-odoo-modules/stock_count_barcode/static/description/icon.png" \
  "file://$PWD/icon.svg"
```

No uses ImageMagick: su renderer interno descarta el `<text>` y los gradientes radiales, y el icono sale sin glifo ni brillo.

- [ ] **Step 3: Verificar el PNG**

```bash
file /home/alexis/Documents/Github/prometeo-odoo-modules/stock_count_barcode/static/description/icon.png
```

Esperado: `PNG image data, 512 x 512`.

- [ ] **Step 4: Commit**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
git add stock_count_barcode/static/description/icon.png
git commit -m "feat(stock-count): icono del módulo"
```

---

### Task 9: Verificación end-to-end

Esta tarea no escribe código: recorre el checklist de verificación del spec. Cualquier fallo abre una corrección antes de dar el módulo por terminado.

**Files:** ninguno (salvo correcciones que surjan).

- [ ] **Step 1: Ciclo completo desde la PC**

Creá una sesión nueva y cargá, en una sola sesión, los cuatro casos:

1. Producto **con stock** en la ubicación, contado distinto al teórico.
2. Producto **sin stock** en la ubicación, contado > 0.
3. Código **inexistente** → tiene que rebotar con notificación, sin línea.
4. Producto **con lotes** en la ubicación.

Aplicá la sesión.

Esperado: estado `Aplicado`. Los casos 1 y 2 con `error` vacío; el caso 4 con el error de múltiples quants y **sin** haber movido stock.

- [ ] **Step 2: Confirmar los ajustes en el inventario nativo**

Inventario → Informes → Movimientos de inventario, filtrando por los productos de los casos 1 y 2.

Esperado: un movimiento de ajuste por cada uno, con fecha de ahora, y el stock actual igual a lo contado.

- [ ] **Step 3: Confirmar el bloqueo de ubicación**

En una sesión en borrador **con líneas**, intentá cambiar la ubicación.

Esperado: `UserError` con el texto de que ya tiene líneas cargadas.

- [ ] **Step 4: Confirmar el permiso de aplicar**

Entrá con un usuario que tenga Inventario/Usuario pero **no** Inventario/Administrador. Abrí una sesión en borrador con líneas.

Esperado: el botón Aplicar no se ve (el `groups` del botón lo oculta). Si se lo fuerza por RPC, salta el `UserError` del chequeo explícito.

- [ ] **Step 5: Confirmar el aislamiento multi-empresa**

Con un usuario de sucursal (una sola empresa activa), listá los conteos.

Esperado: solo aparecen los de su empresa. El selector de ubicación solo ofrece ubicaciones de esa empresa.

Este paso se hace con un usuario real de sucursal, no con admin: las reglas de registro de esta base ya escondieron bypasses que con admin no se ven.

- [ ] **Step 6: Prueba real desde el teléfono**

Desde el celular, entrá al Odoo del VPS **por HTTPS** (por IP en red local la cámara no funciona: el navegador exige contexto seguro). Creá una sesión y escaneá tres productos reales con la cámara.

Esperado: el botón abre la cámara, el código se lee, se abre el diálogo de cantidad, el teclado numérico es usable con una mano, y las líneas se cargan. Aplicar funciona.

- [ ] **Step 7: Anotar los resultados y cerrar**

Si todo pasó, el módulo está listo para merge. Si algo falló, corregilo y volvé a correr el paso que falló antes de dar por terminado.

```bash
git log --oneline stock-count-barcode ^main
```

Esperado: los commits de las Tareas 1 a 8.

---

## Notas de desvío respecto de la plantilla de planes

- **Sin TDD ni tests automatizados.** El repo `prometeo-odoo-modules` no tiene suite de tests y el perfil del usuario dice explícitamente no agregarlos salvo pedido. Cada tarea cierra con verificación manual reproducible (comandos de shell de Odoo o pasos de navegador con resultado esperado) en lugar de un ciclo red-green.
- **Commit por tarea, no por paso.** Coherente con el historial del repo.
