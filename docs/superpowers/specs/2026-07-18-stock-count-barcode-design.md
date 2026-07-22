# stock_count_barcode — Conteo de stock por escaneo de cámara

Fecha: 2026-07-18
Estado: diseño aprobado

## Problema

Ajustar el stock de un producto hoy requiere entrar a la vista nativa de quants
desde una PC, o preparar un Excel y cargarlo con `prometeo-odoo-stock-loader`.
No hay forma de contar una góndola con el teléfono en la mano.

Este módulo permite abrir Odoo en el teléfono (o en la PC), escanear el código
de barras con la cámara, cargar la cantidad real contada, y aplicar todos los
ajustes juntos al final.

## Alcance

**Incluye:** sesiones de conteo con líneas por producto, escaneo por cámara,
aplicación en lote vía el ajuste de inventario nativo de Odoo.

**No incluye:** creación de productos desde el teléfono, conteo total con puesta
en cero de lo no contado, manejo de lotes/series/paquetes, UI móvil separada
(portal o PWA), grupos de permisos nuevos.

## Decisiones de diseño

| Decisión | Elegido | Por qué |
|---|---|---|
| Modo de ajuste | Fijar cantidad contada (inventario físico) | Es el caso de uso real; sumar/restar se modela igual |
| Persistencia | Sesión de conteo, aplicación diferida | Contar una góndola es una sesión, no un evento; permite revisar y corregir antes de mover stock |
| Productos no escaneados | Se ignoran (conteo siempre parcial) | Poner en cero lo no contado es catastrófico si se saltea un estante |
| Código repetido | Salta a la línea existente para editar | El usuario decide el total, no el sistema |
| Código sin producto | Error, sin crear nada | Crear productos desde el teléfono genera datos basura (sin precio, categoría ni empresa) |
| Permisos | Solo gerentes de inventario, sin grupo nuevo | Aplicar `inventory_quantity` ya exige `stock.group_stock_manager`; evita `sudo()` |
| Escaneo | Servicio de cámara nativo del core web de Odoo | Cero dependencias JS propias; se hereda mantenimiento y upgrades |

## Modelos

Módulo `stock_count_barcode`, depende de `stock` y `web`.

### `stock.count.session`

| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char | Secuencia `CONTEO/00001` |
| `company_id` | Many2one `res.company` | Requerido, default empresa activa |
| `location_id` | Many2one `stock.location` | Dominio: internas de `company_id`. Bloqueado si hay líneas |
| `user_id` | Many2one `res.users` | Quien cuenta, default usuario actual |
| `state` | Selection | `draft` → `applied` / `cancelled` |
| `date_start` | Datetime | Creación |
| `date_applied` | Datetime | Al aplicar |
| `line_ids` | One2many `stock.count.line` | |
| `line_count`, `diff_count` | Integer computados | Resumen para la vista |

`company_id` y `location_id` quedan de solo lectura una vez que existe la primera
línea: todo lo contado pertenece a esa ubicación y cambiarla a mitad de camino
invalidaría el conteo entero.

### `stock.count.line`

| Campo | Tipo | Notas |
|---|---|---|
| `session_id` | Many2one, ondelete cascade | |
| `product_id` | Many2one `product.product` | Requerido |
| `barcode` | Char related `product_id.barcode` | Solo lectura |
| `theoretical_qty` | Float computado, no almacenado | Stock del sistema en la ubicación, en tiempo real |
| `counted_qty` | Float | Lo cargado por el usuario |
| `difference_qty` | Float computado | `counted_qty - theoretical_qty` |
| `error` | Char | Motivo por el que la línea no se pudo aplicar |

Restricción: un producto no puede repetirse dentro de la misma sesión
(`unique(session_id, product_id)`), coherente con "el repetido salta a la línea
existente".

**El teórico se lee al aplicar, no al escanear.** Congelarlo al escanear
significa que si alguien vende ese producto durante el conteo, el ajuste se
calcula contra una foto vieja y pisa la venta. En pantalla se muestra como
referencia; el ajuste real usa el estado del momento de aplicar.

## Flujo de aplicación

`action_apply()` sobre una sesión en `draft`:

1. Validar: sesión en `draft`, con líneas, usuario en `stock.group_stock_manager`.
   El chequeo de grupo es explícito, no solo por reglas de acceso — así el fallo
   es un mensaje claro y no un ajuste silenciosamente ignorado.
2. Por cada línea, buscar los quants del producto en `location_id` con el
   contexto de empresa de la sesión:
   - **> 1 quant** (lotes, series, paquetes) → `error`, se saltea. No se
     desagrega un total entre lotes: sería inventar datos.
   - **1 quant** → escribir `inventory_quantity = counted_qty`.
   - **0 quants y `counted_qty` > 0** → crear el quant con `inventory_quantity`.
   - **0 quants y `counted_qty` == 0** → nada que ajustar, sin error.
3. Llamar `action_apply_inventory()` sobre los quants afectados. Odoo genera los
   movimientos reales con su historial y valorización.
4. `state = applied`, sellar `date_applied`, líneas de solo lectura.

**Todo o casi todo, no todo o nada.** Las líneas con error no abortan la sesión:
las demás se aplican y las fallidas quedan visibles con su motivo. Abortar todo
por un SKU con lotes obligaría a recontar la góndola entera.

**Todo el stock pasa por `inventory_quantity` + `action_apply_inventory()`.**
Nunca se escribe `quantity` a mano. Es la puerta de entrada oficial de Odoo para
ajustes y garantiza contabilidad, valorización y trazabilidad correctas — el
mismo criterio que `prometeo-odoo-stock-loader` aplica por XML-RPC.

Una sesión aplicada no se reabre ni se edita. Un conteo mal hecho se corrige con
otra sesión, igual que un asiento se corrige con otro asiento.

## Interfaz

Vista formulario de la sesión, ordenada para el ancho de un teléfono. No hay UI
móvil separada: el web responsive de Odoo alcanza, y esto lo usa gente logueada
al backend.

- **Cabecera:** empresa, ubicación, estado. Compactos.
- **Botón grande de escanear**, que abre la cámara. Al leer un código:
  - producto nuevo → crear línea y abrir el teclado numérico en `counted_qty`,
    con el teórico visible;
  - producto ya contado → saltar a esa línea, cantidad editable;
  - código sin producto → mensaje con el código leído, la sesión no se toca.
- **Lista de líneas**, más reciente primero: producto, contado, teórico,
  diferencia. Las líneas con diferencia se destacan. Editables y borrables
  mientras la sesión esté en `draft`.
- **Aplicar vive en la barra de estado, arriba.** En una lista de 200 líneas,
  "aplicar el conteo" no puede estar a un scroll de "borrar la última línea".

**En PC funciona igual sin cámara:** si el navegador no expone cámara, el mismo
botón deja tipear el código en un campo de texto — que es también donde un lector
láser USB escribe solo. La vista no se bifurca.

### Escaneo

Se usa el servicio de escaneo por cámara del core web de Odoo (la librería ZXing
que ya viene empaquetada y alimenta el botón de cámara de los campos de código de
barras). **A confirmar contra la instancia real antes de implementar:** que el
servicio exista con esa API en Odoo 18 Community. Si no estuviera, se empaqueta
ZXing o html5-qrcode como asset del módulo con un componente OWL propio — el
diseño funcional no cambia.

**La cámara del navegador exige HTTPS.** El VPS ya tiene certificado, así que
está cubierto; por IP en la red local no va a funcionar.

## Errores

- **De datos** (código desconocido, producto con lotes, cantidad negativa): se
  muestran donde ocurren. Al escanear, como mensaje; al aplicar, en el campo
  `error` de la línea. Nunca un traceback en la cara del que cuenta.
- **De sistema** (fallo al aplicar un quant): `try/except Exception as e` por
  línea con logging estructurado. La línea queda con el error, las demás siguen.

## Seguridad

- Sin grupos nuevos. Leer y crear sesiones: `stock.group_stock_user`. Aplicar:
  `stock.group_stock_manager`.
- `ir.rule` estándar por `company_id` en ambos modelos.
- Ubicaciones filtradas por la empresa de la sesión.

Dado el historial de reglas de registro en esta base (bypass por OR entre reglas
de distintos grupos), el multi-empresa se prueba con un usuario real de sucursal,
no solo con admin.

## Verificación

Sin suite de tests, como el resto del repo. Instalar en el docker local contra la
base de producción y probar a mano el ciclo completo:

1. Sesión nueva, escanear: producto con stock, producto sin stock, código
   inexistente, producto con lotes.
2. Aplicar.
3. Confirmar en los movimientos de inventario nativos que el ajuste quedó
   registrado y que el stock final es el contado.
4. Verificar la restricción de empresa con un usuario de sucursal.
5. Prueba real desde el teléfono contra el VPS — único lugar donde se prueba la
   cámara de verdad.
