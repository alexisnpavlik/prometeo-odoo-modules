# product_main_vendor

Módulo de Odoo 18 que agrega el campo **Proveedor** en la pestaña Información
general de la ficha de producto, debajo de Categoría. No es un dato aparte: lee
y escribe la primera línea de proveedores de la pestaña **Compras**
(`seller_ids`), así las órdenes de compra y el recomendador de compras usan el
mismo proveedor que se ve en la ficha.

## Uso

El campo aparece solo si el producto tiene tildado **Puede ser comprado**.

- **Elegir un proveedor ya cargado** en la pestaña Compras lo sube a la primera
  posición. El resto de las líneas conserva su orden.
- **Elegir un proveedor nuevo** crea su línea con el costo del producto como
  precio y la compañía activa.
- **Vaciar el campo no borra ninguna línea.** Es a propósito: un clic no puede
  llevarse un precio negociado. Las líneas se borran desde la pestaña Compras.

## Cómo funciona

`product.template.main_vendor_id` es un campo computado, no almacenado, con
`inverse`.

- **Lectura:** proveedor de la línea con menor `(sequence, id)` entre las que
  aplican a todas las variantes. Las líneas atadas a una variante
  (`product_id`) se ignoran.
- **Escritura:** renumera `sequence` de 1 a n con la línea elegida primero, en
  vez de usar una secuencia menor al mínimo. Así no aparecen secuencias
  negativas.
- Si el proveedor tiene líneas en varias compañías, se prefiere la de la
  compañía activa.

## Dependencias

- `purchase`

## Tests

```bash
sudo docker exec odoo-odoo-1 odoo -d <base> -i product_main_vendor \
  --test-tags /product_main_vendor --stop-after-init --no-http
```

Cubren lectura por secuencia, líneas de variante ignoradas, proveedor existente
que sube, proveedor nuevo que crea línea, alta de producto con proveedor y
vaciado sin borrar líneas.
