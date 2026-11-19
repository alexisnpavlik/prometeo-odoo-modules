# pos_category_filter — productos por caja según categoría de producto

## Por qué

Los clientes tienen varias cajas por sucursal que venden productos distintos. Hoy
Odoo restringe una caja solo por **Categorías de PdV** (`pos.category`), que es una
segunda taxonomía que nadie mantiene: en `prod` hay 23 categorías de producto bien
usadas y una sola categoría de PdV ("Cancha"). Se quiere una única taxonomía —la
categoría de producto (`product.category`)— y que cada caja elija qué categorías
vende.

## Objetivos

- En la caja (`pos.config`): selector **Productos: Todos / Solo estas categorías /
  Todas menos estas** + una lista de `product.category`.
- Elegir una categoría incluye todas sus hijas (`child_of`).
- La caja **descarga** solo los productos permitidos.
- Un producto excluido **no se puede vender** desde esa caja: ni escaneando el código
  (fallback `pos.session.find_product_by_barcode`), ni con "Buscar más"
  (`ProductScreen.loadProductFromDB`). Al escanear uno excluido: aviso
  "Producto no habilitado en esta caja".
- La barra de categorías del POS desaparece.
- Las Categorías de PdV se ocultan: menú y campo `pos_categ_ids` en la ficha.

## No objetivos

- Bloquear productos excluidos en reembolsos o al reabrir pedidos viejos.
- Restringir el back-office (ventas, stock): solo el POS.
- Borrar `pos.category` ni sus datos.

## Anti-objetivos

- Que un pack de `pos_promotions` deje de aparecer en una caja filtrada (hoy se
  muestran siempre, con sus componentes).
- Que la caja sin configurar cambie de comportamiento: modo por defecto = Todos.

## Restricciones

- Odoo 18. Punto de entrada de la carga: `pos.config._get_available_product_domain`
  (lo usa `product.product._load_pos_data_domain`).
- `pos_promotions` ya overridea ese método y ensancha el dominio solo si existe la
  hoja nativa `pos_categ_ids`. El módulo nuevo no depende de `pos_promotions`.
- Multi-base: corre en `prod` del mega y en las bases del VPS multi-company.

## Enfoques considerados

1. **Filtrar al cargar + bloquear escaneo y "Buscar más"** — elegido. Es un control
   real, y además las cajas con pocas categorías abren más rápido (hoy cada caja
   descarga ~22.500 productos). Costo: un producto mal categorizado no se vende
   hasta corregirlo.
2. **Filtrar solo la vista (grilla y búsqueda)** — descartado: el escaneo vende
   cualquier cosa, no resuelve el problema.
3. **Sincronizar `product.category` → `pos.category`** — descartado al decidir ocultar
   la barra de categorías: mantener un espejo no aporta nada.

## Decisiones de diseño (de Alexis)

- Barra de categorías del POS: se oculta.
- Enfoque 1.

## Decisiones mías (corregibles)

- Un selector de modo + una sola lista, en lugar de dos listas incluir/excluir.
- El filtro nativo (`limit_categories`) queda **desactivado** por el módulo: el
  `post_init_hook` lo apaga en todas las cajas y loguea cuáles lo tenían. Si no, una
  restricción invisible seguiría filtrando.
- Migración en `prod`: "Tienda de ropa", "Mega futbol Caja 1" y "Mega futbol Caja 2"
  (hoy limitadas a "Cancha") pasan a "Solo estas: Almacen - Cancha". Se hace a mano
  al instalar, no en código (el mapeo `pos.category` → `product.category` no es
  automatizable: "Cancha" tiene productos en 5 categorías distintas).
- Los packs de `pos_promotions` siguen visibles en cajas filtradas; el módulo nuevo
  los contempla sin depender de `pos_promotions` (chequeo blando del campo
  `is_promotion_pack`).
- Ocultar Categorías de PdV: dentro del módulo nuevo, no vía `web_menu_simplify`.

## Queda para quien lo construya

- Cómo ocultar la barra (`CategorySelector` en `product_screen.xml`).
- Texto exacto del aviso al escanear y en qué momento se muestra.
- Ubicación de los campos en la vista de `pos.config` / ajustes del POS.
