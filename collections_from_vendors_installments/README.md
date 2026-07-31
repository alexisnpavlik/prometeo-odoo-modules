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
   la primera vez.
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

## Fuera de alcance de esta versión

Etapa 2 (rendición de caja, supervisión, morosidad, retiro del mueble, clientes
problemáticos) y etapa 3 (geolocalización de la venta, fotos de DNI y vivienda,
tablero de indicadores) no están implementadas. Cuando se implementen, la
decisión tomada es que el sistema **advierte pero no bloquea** ante falta de GPS,
falta de foto o cliente con antecedentes.

## Tests

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments \
  --stop-after-init --no-http
```
