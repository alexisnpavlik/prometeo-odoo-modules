# product_pricelist_lines

Módulo de Odoo 18 que agrega en la pestaña Información general de la ficha de
producto una tabla editable con las listas de precios que aplican al producto y
su precio. No es un dato aparte: cada fila es una regla de precio fijo de la
lista (`product.pricelist.item`), la misma que se ve desde **Ventas → Listas de
precios** y la que usa el POS.

## Uso

La sección **Listas de precios** aparece para usuarios con el grupo de listas
de precios activo (`product.group_product_pricelist`).

- **Agregar una fila** crea la regla de precio fijo en la lista elegida.
- **Editar el precio** cambia la regla de la lista.
- **Borrar una fila** elimina la regla.
- Columnas opcionales: fecha de inicio, fecha de fin y empresa.

## Qué muestra y qué no

- Solo reglas de **precio fijo** aplicadas al **producto completo**
  (`applied_on = 1_product`). Las de variante, categoría, globales o por
  fórmula se gestionan desde la propia lista.
- Las listas de **todas las empresas del usuario**, no solo las tildadas en el
  selector de empresas.
- Excluye las listas llamadas **Predeterminado** (la que Odoo crea en cada
  empresa).

## Cómo funciona

`product.template.pricelist_line_ids` es un One2many sobre
`product.pricelist.item` filtrado por dominio.

Para ver las listas de todas las empresas se pasa el contexto
`{"allowed_company_ids": False}`: sin ese valor Odoo usa todas las empresas del
usuario en `env.companies`, sin `sudo` y sin salirse de sus empresas
permitidas. Tiene que estar **en el campo Python y en el `context` de la
vista**: `web_read` usa el de la vista para leer las sub-filas.

## Dependencias

- `product`

## Tests

```bash
sudo docker exec odoo-odoo-1 odoo -d <base> -i product_pricelist_lines \
  --test-tags /product_pricelist_lines --stop-after-init --no-http
```

Cubren alta desde la ficha, reglas ocultas (fórmula y variante), lista
Predeterminado oculta, listas de todas las empresas y borrado desde la ficha.
