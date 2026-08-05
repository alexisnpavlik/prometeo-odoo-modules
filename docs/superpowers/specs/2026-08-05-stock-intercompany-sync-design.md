# stock_intercompany — Sincronización 1 a 1 y edición de validados

**Fecha:** 2026-08-05
**Odoo:** 18.0
**Módulo:** `stock_intercompany` (base OCA `multi-company`, ya modificado en este repo)
**Rama:** `mejorar-inter`
**Estado:** Diseño aprobado. Fase 0 pendiente de ejecutar contra el contenedor.

---

## 1. Objetivo

Hoy la entrega de una compañía y la recepción espejo de la otra se crean juntas y después viven vidas separadas: una vez creada la recepción, nada garantiza que su contenido siga coincidiendo con el de la entrega, y ninguna de las dos se puede corregir después de validada.

Este trabajo cubre tres cosas:

1. **Espejo permanente.** Entrega y recepción quedan amarradas en contenido: cambiar una cambia la otra, en cualquiera de los dos sentidos.
2. **Edición después de validar.** Un picking validado se puede corregir —cantidades y alta/baja de productos— y toda corrección queda registrada en el chatter de las dos puntas.
3. **Dos roles.** El operador trabaja como hoy. Un rol nuevo, el manager intercompany, es el único que puede corregir lo ya validado.

La recepción se sigue validando a mano en la compañía destino. No se auto-valida.

---

## 2. Estado actual del módulo

`stock.picking._action_done()` detecta los pickings cuyo destino es `customer` o `transit` y, si el `partner_id` corresponde al partner de otra compañía, crea la recepción espejo en esa compañía y la deja en estado confirmado.

Los vínculos existentes, todos `check_company=False` y apuntando desde la contraparte hacia el origen:

| Modelo | Campo |
|---|---|
| `stock.picking` | `counterpart_of_picking_id` |
| `stock.move` | `counterpart_of_move_id` |
| `stock.move.line` | `counterpart_of_line_id` |

`res.company.intercompany_in_type_id` define el tipo de operación de entrada a usar en la compañía destino. La vista oculta el botón de devolución.

No hay grupos propios, no hay sincronización posterior a la creación, y el vínculo solo se puede recorrer en un sentido.

---

## 3. Decisiones tomadas

| Tema | Decisión |
|---|---|
| Qué significa "1 a 1" | Espejo en contenido; la recepción se valida a mano |
| Dirección del sync | Bidireccional |
| Qué se sincroniza | Cantidades (demanda y hecha), alta/baja de líneas, lotes, fecha programada y prioridad |
| Mecanismo | Síncrono, en `write`/`create`/`unlink`, misma transacción, con guard de recursión |
| Auditoría | Chatter nativo de Odoo para cantidades + notas propias para alta/baja de líneas y para todo lo propagado. Sin modelos nuevos |
| Rol | Grupo nuevo `group_intercompany_manager`, y además el usuario debe tener ambas compañías habilitadas |
| Alcance de edición en validados | Cantidades y alta/baja de líneas |
| Recepción parcial | Recibir de menos ajusta la entrega automáticamente, sin exigirle el grupo al operador |

### 3.1 Consecuencia derivada: la recepción espejo no genera backorder

Se decidió que recibir 9 de 10 corrige la entrega a 9. Si además Odoo creara el backorder habitual, quedarían dos recepciones para una entrega y se rompería el 1 a 1 que es el objetivo del trabajo.

Por lo tanto, al validar una recepción que tiene contraparte, **no se crea backorder**: la diferencia se propaga a la entrega y el asunto se cierra ahí. Si más adelante llega el faltante, es una transferencia nueva.

Esto no afecta a los pickings sin contraparte, que siguen con el comportamiento estándar de Odoo.

### 3.2 Riesgo aceptado

Con la decisión de recepción parcial, un operador de la compañía B modifica stock ya validado y valorizado de la compañía A sin tener el rol de manager ni acceso a esa compañía. Es deliberado: es el flujo diario y trabarlo obligaría a escalar cada diferencia de conteo. La contención es la auditoría de la sección 9, que deja constancia en el chatter de las dos puntas indicando quién lo originó.

---

## 4. Fase 0 — verificar antes de escribir código

El contenedor no estaba levantado durante el diseño. Tres cosas se afirmaron por lectura de código y hay que confirmarlas contra Odoo real; la primera es bloqueante.

**[BLOQUEANTE] 4.1 — Las move lines de la recepción espejo quedan sin move asociado.**
En [`stock_picking.py:96-105`](../../../stock_intercompany/models/stock_picking.py#L96-L105) las líneas se copian con `move_id=False`. Si en runtime quedan efectivamente huérfanas, no hay sobre qué mapear línea a línea y hay que corregir la creación antes de todo lo demás: las líneas deben crearse colgando del move espejo correspondiente.

**4.2 — Odoo 18 postea nota y reajusta quants al editar la cantidad de una línea validada.**
`stock.move.line.write()` tiene una rama para registros en `done` que corrige los quants y postea usando `stock.track_move_template`. Confirmar que ocurre y con qué texto, porque de eso depende cuánto tiene que cubrir la auditoría propia.

**4.3 — Los lotes copiados quedan con la compañía equivocada.**
`stock.lot` tiene `company_id`. La copia actual arrastra el lote de la compañía origen a la recepción de la destino. Confirmar y corregir con el mapeo de la sección 8.

---

## 5. Arquitectura

Se conservan los tres campos `counterpart_of_*` tal como están. Lo que falta es poder recorrerlos en el sentido inverso:

```
_get_counterpart()  ->  counterpart_of_X_id
                        or  sudo().search([('counterpart_of_X_id', '=', self.id)], limit=1)
```

Expuesto en `stock.picking` como campo computado no almacenado `counterpart_picking_id`, que además alimenta un botón "Ver contraparte" en el form.

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `models/intercompany_sync.py` | **Nuevo.** Resolución de contraparte, guard de contexto, mapeo de lotes, posteo de notas |
| `models/stock_picking.py` | Creación del espejo (existente) + sync de cabecera + `can_edit_done` + guard |
| `models/stock_move.py` | Sync de demanda, alta y baja de líneas |
| `models/stock_move_line.py` | Sync de cantidad hecha y lote |
| `security/stock_intercompany_groups.xml` | **Nuevo.** Grupo manager |
| `views/stock_picking_views.xml` | Readonly condicionado, botón a la contraparte |

Sin clase mixin: helpers a nivel de módulo que cada modelo llama desde sus overrides.

---

## 6. Seguridad y roles

### 6.1 Grupo

`stock_intercompany.group_intercompany_manager` — "Intercompany: editar transferencias validadas", con `implied_ids = stock.group_stock_user`.

El operador no lleva grupo nuevo: es el `stock.group_stock_user` de hoy y su comportamiento no cambia en nada.

### 6.2 Campo `can_edit_done`

Computado, no almacenado, en `stock.picking`. Verdadero cuando se cumplen las dos condiciones:

- el usuario pertenece a `group_intercompany_manager`;
- `env.user.company_ids` contiene tanto `picking.company_id` como la compañía de su contraparte.

### 6.3 Dos capas

**Vista.** Xpath sobre `stock.view_picking_form` reemplazando los `readonly="state == 'done'"` por `readonly="state == 'done' and not can_edit_done"` en la lista de operaciones y en fecha programada y prioridad.

**Modelo.** En `write`, `create` y `unlink` de picking, move y move line: si el registro está en `done` y tiene contraparte, se exige grupo más doble compañía; si no se cumple, `AccessError` explicando cuál de las dos condiciones falta.

El guard no se aplica cuando la escritura viene propagada, que se reconoce por el flag de contexto de la sección 7. Esa excepción es la que hace posible la decisión de recepción parcial: el operador destino no toca la entrega directamente, la toca el sync en sudo.

Efecto lateral buscado: hoy cualquier `stock.group_stock_user` puede corregir la cantidad de una línea validada, porque Odoo lo permite de fábrica. Con este guard, en pickings intercompany pasa a requerir el grupo nuevo. Los pickings sin contraparte quedan intactos.

---

## 7. Motor de sincronización

### 7.1 Qué se propaga

| Modelo | Campos |
|---|---|
| `stock.picking` | `scheduled_date`, `priority` |
| `stock.move` | `product_uom_qty`, creación y baja de líneas |
| `stock.move.line` | `quantity`, `lot_id` |

No se propagan: `state`, `name`, `partner_id`, ubicaciones, tipo de operación ni compañía.

### 7.2 Mecánica

La propagación corre después del `super()`, solo si el valor efectivo del campo cambió —comparado contra el valor previo, no contra `vals`, para no propagar escrituras que no cambian nada— y siempre como:

```python
counterpart.sudo().with_context(skip_intercompany_sync=True).write(mapped_vals)
```

El override sale temprano si `skip_intercompany_sync` está en contexto. Eso corta el eco en un solo salto: A escribe, B recibe con el flag, B no devuelve nada.

Si el registro no tiene contraparte, no hay nada que hacer. Es el caso normal mientras la entrega todavía no se validó.

Si la contraparte está en `done`, la escritura de cantidad dispara el reajuste de quants nativo de Odoo. Si está en `confirmed` o `assigned`, es una escritura común.

### 7.3 Errores

Todo ocurre en la misma transacción: si la propagación falla, la edición local no se guarda. Los fallos previsibles del entorno —producto sin configurar en la otra compañía, ubicación faltante, lote imposible de crear— se capturan y se presentan como `UserError` con el motivo concreto y el nombre del picking contraparte, no como traceback.

---

## 8. Alta y baja de líneas, y lotes

### 8.1 Alta en un picking validado

El move nuevo se lleva a `done` por la vía normal de Odoo, sin tocar quants a mano:

```
create(draft) -> _action_confirm() -> _action_assign() -> quantity + picked=True -> _action_done()
```

Así el movimiento de stock y la valorización los hace Odoo. El picking permanece en `done` porque todos sus moves lo están.

En la contraparte se replica igual si también está validada; si está en `confirmed`, alcanza con crear y confirmar.

### 8.2 Baja en un picking validado

Un move en `done` no se puede borrar. "Eliminar" pasa a significar `quantity` y `product_uom_qty` en cero: Odoo revierte los quants y la línea queda visible con cero como registro histórico, con nota en el chatter.

En pickings no validados sigue siendo `unlink` real, y se propaga como `unlink`.

Queda explícito que la UI no hace lo que el usuario espera: la línea no desaparece de la pantalla. Es el precio de mantener la trazabilidad del movimiento original.

### 8.3 Mapeo de lotes

`stock.lot` es por compañía, así que el lote de la entrega no sirve en la recepción. El mapeo busca en la compañía destino un lote con el mismo `name` para el mismo `product_id`, y lo crea en sudo si no existe.

Se aplica en los dos momentos: al crear la recepción espejo —que es donde hoy está el problema de 4.3— y en cada propagación posterior de `lot_id`.

---

## 9. Auditoría

Sin modelos nuevos. Tres fuentes:

1. **Cantidades en líneas validadas:** chatter nativo de Odoo vía `stock.track_move_template`. El alcance exacto se confirma en 4.2.
2. **Alta y baja de líneas:** nota propia con producto, cantidad y usuario.
3. **Cabecera:** nota propia para fecha programada y prioridad, que no tienen tracking en core.

Todo lo que se propaga deja nota en **las dos** puntas. La de la contraparte nombra el origen:

> Actualizado desde WH/OUT/00012 (Compañía A) por Alexis Medina — Producto X: 10 → 9

Esa es la contención del riesgo de 3.2: cuando un operador de B corrige una entrega de A, la entrega de A lo dice.

---

## 10. Fuera de alcance

- **Auto-validación de la recepción.** Se valida a mano, por decisión.
- **Propagación de cancelaciones.** Cancelar un picking no cancela su contraparte.
- **Rutas multi-paso** (pick + pack + ship) en cualquiera de las dos compañías.
- **Devoluciones.** El módulo ya oculta el botón y eso no cambia.
- **Coherencia con facturas intercompany.** `account_invoice_inter_company` está instalado en el mismo entorno: corregir un picking validado que ya tiene factura emitida desincroniza stock contra factura. El módulo no lo detecta ni lo corrige. Si esto aparece en la operación real, es un trabajo aparte.

---

## 11. Tests

En `tests/`, extendiendo lo existente:

| Caso | Verifica |
|---|---|
| Cantidad editada en la entrega | La recepción refleja el cambio |
| Cantidad editada en la recepción | La entrega refleja el cambio |
| Ida y vuelta | No hay recursión infinita ni doble escritura |
| Alta de línea en validado | Move en `done` en ambas compañías y quants correctos en las dos |
| Baja de línea en validado | Cantidad en cero, quants revertidos en las dos, línea presente |
| Guard: operador | `AccessError` al editar un validado |
| Guard: manager con una sola compañía | `AccessError` |
| Guard: manager con ambas | Edita correctamente |
| Recepción parcial | Recibir 9 de 10 deja la entrega en 9 y no crea backorder |
| Lote nuevo | Se crea en la compañía destino con el mismo nombre |
| Picking sin contraparte | Comportamiento estándar de Odoo, sin guard y con backorder normal |

El último es el que protege contra el efecto colateral más probable de todo este trabajo: romperle el flujo a las transferencias que no son intercompany.
