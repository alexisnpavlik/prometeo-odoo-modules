# pos_promotions — burbujas de promociones disponibles — diseño

## Intención

Cuando el cajero carga un artículo que forma parte de una promoción que todavía no está
completa en la orden, el POS se lo recuerda con una burbuja flotante (p. ej. 1 Vaso cargado,
promo 2 Vasos a $1.500 → "Sumá 1 Vaso más, ahorra $300"). El objetivo es que el cajero le
ofrezca la promo al cliente en el momento y se vendan más packs.

## Objetivos

- Mostrar, en la pantalla de productos, las promos arrancadas pero incompletas de la orden actual.
- Que desaparezcan solas cuando ya no aplican (promo completada, línea borrada, otra orden).
- Funciona igual para promos de un producto (2 Vasos) y de varios (Fernet + Coca-Cola).

## No objetivos

- La burbuja **solo informa**: tocarla no agrega nada a la orden (decisión de Alexis).
- No se muestra en la pantalla del cliente ni en el ticket.
- Sin cambios de modelos ni de datos en el servidor.

## Anti-objetivos

- Que tape o frene el trabajo del cajero (nada de popups modales).
- Que muestre una promo que ya no aplica.

## Approaches considerados

- **A. Componente OWL propio que se recalcula con la orden** (elegida). Siempre refleja el estado
  actual, se descarta por orden. ~3 h.
- **B. Avisos del servicio de notificaciones de Odoo**: ~1 h, pero se apilan, quedan mostrando
  promos ya completadas y comparten lugar con los errores del POS.
- Popup modal: descartado, frena al cajero en cada artículo.

## Diseño (decidido con Alexis, mockups v3 + sin foto)

- **Ubicación:** esquina superior derecha del área de productos de `ProductScreen`.
- **Círculos flotantes** (54 px, naranja `#e8590c`, animación suave de subir/bajar), uno por promo,
  con el ahorro en una pastilla verde debajo. Máximo 3, primero los que más ahorran.
- **Foto del círculo:** imagen del primer producto que falta (la que ya tiene en Odoo), círculo blanco
  con borde naranja. Sin imagen → iniciales del producto (2 letras, p. ej. "CO", "VA") sobre naranja.
- **Burbuja abierta** debajo de los círculos: "PROMO DISPONIBLE" / "Sumá 1 Coca-Cola" /
  "Fernet + Coca-Cola a $9.000" / "Ahorra $1.200", con ✕. Se abre sola la de la promo tocada por
  el último producto agregado; tocar otro círculo abre ese.
- **✕** descarta esa promo para esa orden (estado en memoria de la orden, no se guarda).
- **Cuándo aparece una promo:** la orden tiene al menos una unidad de un componente que quedó
  **fuera** de los packs ya aplicados, y le falta algo para completar otro pack. Ej.: 2 Vasos con
  la promo aplicada → nada; 3 Vasos → "Sumá 1 Vaso más".
- **Qué promos:** las mismas que puede aplicar `applyPromotionPacks()`: sucursal de la caja,
  vigentes hoy, mismas líneas candidatas.
- **Ahorro y precio:** con el precio de la lista de la orden y `_getPromotionPackPrice()`, igual
  que la promo en sí. Solo se muestran las que ahorran (precio del pack < precio normal).

## Para el builder

- Reutilizar la lógica de `promotion_packs.js` (filtro de sucursal/vigencia, unidades sobrantes
  después de aplicar packs) en un método nuevo de `PosOrder`, p. ej. `getPromotionHints()`.
- Precio de los productos que faltan (no están en la orden): `product.get_price(pricelist, qty)`.
- Detectar si el producto tiene imagen con lo que carga el POS de Odoo 18 (verificar el campo).
- Tests: unitarios del cálculo de hints (QUnit/HOOT) si el repo ya los corre para este módulo;
  prueba manual en la base `pruebas`.
