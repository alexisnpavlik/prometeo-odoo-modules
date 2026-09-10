# Cobranza a vendedores y cuotas

Venta domiciliaria financiada para una fábrica de muebles: el vendedor retira
mercadería, la vende en cuotas en el domicilio del cliente, cobra la primera
cuota como comisión y enruta la tarjeta a un cobrador que gestiona el resto.

## Circuito

1. **Ingreso de producción** — Inventario nativo de Odoo. Un albarán de entrada
   o un ajuste suma cantidad por modelo en `WH/Stock`. Los muebles no se
   identifican por unidad: los productos no llevan lote ni serie.
2. **Entrega al vendedor** — Venta en cuotas > Depósito > *Entregar / recibir
   mercadería*, con dirección "Entrega al vendedor". Genera un albarán interno
   de `WH/Stock` a `Vendedores/<nombre>`. La ubicación del vendedor se crea sola
   la primera vez. Con el ajuste *Permitir entregar sin stock* (activo por
   defecto) la entrega no se traba por falta de existencias: el faltante queda
   como stock negativo en `WH/Stock` y se regulariza al cerrar la producción. La
   devolución del vendedor a fábrica se sigue chequeando siempre.
3. **Venta** — Venta en cuotas > Vendedor > *Mis ventas*. Se carga el cliente,
   el modelo de mueble y uno de los planes de cuotas de ese mueble. El plan fija
   cantidad de cuotas, importe de cuota y frecuencia; el precio total sale de
   cuotas × importe. El vendedor no puede cambiarlos: solo un administrador
   vende con valores distintos al plan. Al confirmar:
   - se descuenta el mueble del stock del vendedor hacia Clientes,
   - se genera el calendario de cuotas,
   - se registra el cobro de la primera cuota a nombre del vendedor.
4. **Enrutamiento** — El cobrador se puede elegir al cargar la venta, o después
   desde *Sin cobrador* seleccionando varias tarjetas y usando la acción
   *Enviar al cobrador*. La tarjeta queda "Enrutada".
5. **Aceptación** — Venta en cuotas > Cobrador > *Pendientes de aceptar*. Recién
   al aceptar el cobrador se hace responsable y la tarjeta entra en su cartera.
   También puede rechazarla indicando un motivo: vuelve al vendedor.
6. **Cobranza** — *Agenda de cobro* lista las cuotas de la cartera que vencen hoy
   o quedaron atrasadas, con dirección, teléfono, saldo de la tarjeta y un botón
   que abre la ubicación en el mapa. Los cobros se registran desde *Cobros* o
   desde la tarjeta.
7. **Cierre** — Cuando el residual llega a cero, la tarjeta pasa sola a
   Finalizada y sale de la cartera activa.

## Planes de cuotas

Cada modelo de mueble lleva sus propios planes, en la ficha del producto,
pestaña *Planes de cuotas*. Un plan es: nombre, cantidad de cuotas, importe de
cuota y modalidad (mensual o semanal). El precio total se calcula solo:
cantidad × importe.

| Plan | Cuotas | Importe | Total |
|---|---|---|---|
| 6 cuotas | 6 | 22.000 | 132.000 |
| 12 cuotas | 12 | 13.500 | 162.000 |
| 20 semanas | 20 | 7.000 | 140.000 |

El importe de cada cuota ya incluye el interés, por eso el total no es una
división del precio de contado. **El precio de lista del producto no se usa para
nada**: cada plan es una opción cerrada que se carga a mano. No hay coeficientes
ni tasas que mantener.

Los planes mensuales y semanales conviven en la misma tabla; elegir el plan es lo
que define la modalidad de cobro. Un plan archivado deja de ofrecerse en ventas
nuevas, pero las tarjetas ya vendidas con él no se tocan.

Definir planes requiere ser administrador; vendedores y cobradores solo los leen.

## Imputación de cobros

Un cobro se imputa automáticamente sobre las cuotas impagas de la tarjeta,
ordenadas por vencimiento (FIFO). Soporta pago parcial y pago de varias cuotas
de una vez. Un cobro que supere el saldo de la tarjeta se rechaza.

La cuota de comisión del vendedor está separada: un cobro normal nunca la toca,
y el cobrador no la ve como pendiente.

## Calendario de cuotas

- La cuota 1 vence el día de la venta (la cobra el vendedor).
- **Mensual**: la cuota 2 vence el día de cobro elegido, del mes siguiente al de
  la venta. Si el mes no llega a ese día (31 en febrero), vence el último día.
- **Semanal**: la cuota 2 vence en la próxima ocurrencia del día de la semana
  elegido, siempre posterior a la venta.
- Todas las cuotas valen el importe que fija el plan.

Una cuota puntual se puede correr de fecha a pedido del cliente sin tocar el
resto del calendario; queda registrado en el historial de la tarjeta.

## Roles

| Grupo | Ve | Puede |
|---|---|---|
| Vendedor | Sus propias ventas | Cargar y confirmar ventas, enrutar tarjetas |
| Cobrador | Las tarjetas donde figura como cobrador | Aceptar, rechazar, registrar cobros |
| Administrador de cobranzas | Todo | Configurar, transferir carteras, anular cobros |

Un cobro registrado no se puede borrar: solo anular, y queda el registro.
Precio, cantidad de cuotas, importe y mercadería quedan congelados al confirmar
la venta.

## Configuración

Ajustes > Venta en cuotas:
- **Cuotas por defecto** (12) — se propone al cargar una venta nueva.
- **Frecuencias permitidas** — mensual, semanal o ambas.
- **Días de tolerancia de mora** — atraso tolerado antes de marcar una cuota
  como vencida. Un cron diario recalcula las vencidas.

## Operación, seguimiento y tablero

Esta versión también incluye:

- **Rendiciones de caja** por cobrador: reúnen los cobros pendientes, calculan
  diferencias y dejan la revisión del administrador asentada.
- **Supervisión**: asignación temporal de cobradores, visitas con tarjetas
  revisadas y observaciones trazables.
- **Mora y recuperaciones**: el cron diario actualiza cuotas vencidas y la
  antigüedad de la deuda; se pueden marcar tarjetas para retiro y registrar el
  reingreso del mueble recuperado. Al registrar el retiro, las cuotas que
  quedaban sin cobrar pasan a **Cancelada** y la tarjeta queda con saldo cero: la
  deuda se da por perdida junto con el mueble y no se devuelve dinero. Lo que el
  cliente alcanzó a pagar queda en *Cobrado al retirar*, así que la pérdida es el
  total menos ese importe. El mueble entra a la ubicación `Recuperados`, que no es
  stock vendible, y se ve en Depósito > *Muebles retirados*.
- **Clientes y antecedentes**: historial, sugerencia y marca manual de cliente
  problemático con motivo pedido al marcar; la marca puede levantarse si
  corresponde. La ficha guarda frente y dorso del DNI, con filtro para encontrar
  a quién le falta, y las notas se registran en el historial del cliente.
- **Evidencia de venta**: ubicación GPS opcional, enlace de mapa con respaldo
  por dirección y foto opcional de la vivienda.
- **Tablero de indicadores** para administradores de cobranzas: KPIs, gráficos,
  mora por antigüedad, rendiciones con diferencia, stock en vendedores, mapa,
  listados y exportación CSV.

GPS, fotos y antecedentes son avisos operativos: **no bloquean** la venta. Si no
hay GPS, la agenda usa la dirección del cliente como respaldo.

### Validaciones del tablero

El tablero solo permite elegir empresas a las que el usuario tiene acceso. Sus
listados aceptan únicamente las pestañas publicadas (ventas o cuotas); la página
debe ser un entero mayor o igual a 1 y la cantidad por página un entero entre 1
y 200. Los valores inválidos se rechazan con un error funcional, sin corregir la
consulta silenciosamente.

### Concurrencia de cobros

Para desarrollo, una prueba con dos cursores PostgreSQL reales verifica la
garantía bajo el aislamiento `REPEATABLE READ` de Odoo: dos cobros concurrentes
no pueden imputar más que el saldo de una misma cuota. Uno se confirma y el otro
recibe un conflicto de serialización; al reintentar, ve el saldo actualizado y
se rechaza si excede la deuda. No se agregó un bloqueo de aplicación adicional.

## Tests

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --workers=0 --http-port=8068
```
