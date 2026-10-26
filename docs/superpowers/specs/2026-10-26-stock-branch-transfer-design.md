# stock_branch_transfer — App "Traslados" entre sucursales

Fecha: 2026-10-26
Estado: pendiente de aprobación

## Problema

Hoy la mercadería entre sucursales se mueve con el módulo OCA `stock_intercompany`:
se valida una salida hacia tránsito y se genera sola una recepción en la empresa
destino (origen "Partners/Vendors"). En `prod` hay ~557 envíos así, y **125
recepciones quedaron sin validar** (de mayo a octubre) porque nadie en la sucursal
destino se entera de que le llegó algo. Mientras tanto, esa mercadería vive en una
ubicación de tránsito virtual que no pertenece a ninguna sucursal.

Además, una vez validado un envío no se puede corregir ni anular.

## Objetivo

Una app propia, **Traslados**, en el menú principal, donde:

- cualquier usuario de una sucursal arma un envío a otra sucursal interna;
- la sucursal destino lo ve con un **contador en el ícono de la app** y lo recibe;
- el stock sale del origen al enviar y entra al destino al recibir;
- si llega distinto, se recibe "con diferencias" y queda pendiente hasta que un
  manager lo cierre;
- un manager puede **editar o eliminar** un traslado en cualquier estado, y el
  stock de ambas sucursales se corrige solo.

## No-objetivos

- Migrar las 125 recepciones pendientes del flujo viejo (se hace más adelante).
- Desinstalar `stock_intercompany`: **conviven** por ahora.
- Facturación o contabilidad intercompany (`account_invoice_inter_company` no está instalado).
- Lotes, números de serie, paquetes, multi-almacén por sucursal (en `prod` ningún
  producto usa tracking y cada empresa tiene un solo almacén).
- Aviso en el POS.

## Anti-objetivos (fallaría aunque "funcione")

- Que un traslado del módulo nuevo dispare también la recepción automática de
  `stock_intercompany` → recepciones duplicadas y stock doble en destino.
- Que editar/eliminar deje stock inconsistente entre origen, tránsito y destino.
- Que para usar la app haya que darle a un cajero el grupo de Inventario completo
  (rompe lo que protege `pos_user_readonly`).

## Contexto en `prod` (local)

| Dato | Valor |
|---|---|
| Empresas | 15 (`res.company`), incluye "My Company" (id 1) y "test" (id 7) |
| Almacenes por empresa | 1 |
| Productos con tracking | 0 |
| Usuarios con acceso a >1 empresa | 14 |
| Usuarios `pos_user_readonly` (cajeros) | 26 |
| Usuarios `stock.group_stock_user` / `group_stock_manager` | 17 / 6 |

## Roles (decidido con Alexis)

| Rol | Crea envíos | Recibe | Edita / elimina validados |
|---|---|---|---|
| **Usuario de sucursal** (cajero o encargado — en la práctica son lo mismo) | Sí, desde sus sucursales | Sí, solo lo que llega a sus sucursales | No |
| **Manager** | Sí | Sí | Sí, en cualquier estado |

"Sus sucursales" = las empresas a las que el usuario tiene acceso en Odoo
(`company_ids`). Un cajero no puede recibir en una sucursal a la que no tiene acceso.

Dos grupos propios del módulo: **Traslados / Usuario** y **Traslados / Manager**
(Manager implica Usuario). *Llamada mía:* no se reutilizan los grupos de
Inventario, para no abrirle Inventario a los cajeros. Las operaciones de stock que
el usuario no tiene permiso de hacer corren con `sudo()` acotado (patrón de
`pos_user_readonly/models/pos_session.py`).

## Flujo y estados

```
Borrador → En camino → Recibido
                    ↘ Con diferencias → (manager edita) → Cerrado
```

*Llamada mía:* un traslado "Recibido" sin diferencias se considera cerrado; no
hace falta un paso extra. También existe el estado **Anulado** (ver Eliminar).

1. **Borrador** — el usuario elige sucursal destino y carga líneas (producto +
   cantidad). Se edita libremente; el creador puede borrarlo.
2. **Enviar** → **En camino** — sale el stock del origen hacia tránsito.
3. En destino, dos botones:
   - **Recibido** — entra todo lo enviado. → **Recibido**.
   - **Recibido con diferencias** — abre un asistente donde se carga la cantidad
     real por línea (pueden ser menos, más, o productos no enviados) y una nota.
     Lo que llegó **entra al stock del destino en el momento**; el faltante queda
     en tránsito. → **Con diferencias**, y la sucursal de origen lo ve en su contador.
4. **Con diferencias** queda pendiente en ambos lados hasta que un manager lo
   edita con las cantidades finales y lo valida → **Cerrado**.

**Faltante (decidido por Alexis):** lo enviado que no llegó **vuelve al stock del
origen** cuando el manager cierra el traslado (tránsito → origen).

**Sobrante (decidido por Alexis):** si llega más de lo enviado, o un producto que
no estaba en el envío, el excedente **se descuenta del stock del origen**.
*Llamada mía sobre el momento:* se descuenta al recibir con diferencias (origen →
destino en ese mismo acto), así tránsito nunca queda negativo; si el manager luego
corrige la cantidad, se ajusta como cualquier otra edición.

## Edición y eliminación por manager

- **En camino (no recibido):** el manager cambia líneas/cantidades/destino; el
  stock en tránsito se ajusta (sale más del origen o vuelve al origen).
- **Recibido / Con diferencias / Cerrado:** el manager cambia cantidades enviadas
  y/o recibidas; el sistema genera los movimientos de corrección necesarios en
  origen, tránsito y destino para que el stock final refleje lo editado.
- **Eliminar:** *llamada mía* — un borrador se borra de verdad; un traslado con
  stock movido no puede borrarse físicamente (Odoo no deja borrar movimientos
  hechos), así que "Eliminar" **revierte todo el stock** a como estaba antes del
  envío y deja el traslado en estado **Anulado** (oculto por defecto, con chatter
  para auditoría).
- Nunca se modifican movimientos ya hechos: toda corrección es un movimiento nuevo
  enlazado al traslado (trazabilidad).

## Pantallas

- **App "Traslados"** en el menú principal, con ícono propio (estilo Cyber-Glassmorphic).
- **Menú "Enviados"** — traslados cuyo origen es una de mis sucursales.
- **Menú "Por recibir"** — traslados cuyo destino es una de mis sucursales.
- **Formulario** — como un pedido de compra: cabecera (origen, destino, fechas,
  usuario, estado), tabla de líneas con producto buscable por **nombre o código de
  barras** (igual que en Compras), columnas "Enviado" y "Recibido", nota de
  diferencias, botones según estado y rol, chatter.
- **Destino:** selector que lista solo empresas internas (`res.company`), excluyendo
  la de origen y las marcadas como "no es sucursal". *Llamada mía:* ese check vive
  en Ajustes, en una sección propia de Traslados, y por defecto marca "My Company"
  (id 1) y "test" (id 7).
- **Origen:** la empresa activa del usuario (selector de empresas de Odoo).

## Contador en el ícono

Número sobre el ícono de la app en el menú principal = traslados **En camino**
hacia mis sucursales + traslados **Con diferencias** donde participa alguna de mis
sucursales. Si es 0, no se muestra.

## Restricciones técnicas

- Odoo 18.0, repo `prometeo-odoo-modules`, convenciones del skill `odoo-prometeo-modules`.
- **Convivencia con `stock_intercompany`:** su `stock.picking._action_done` crea una
  recepción en la otra empresa cuando el destino de la salida es una ubicación de
  uso `customer` o `transit` y el partner es una empresa propia. Los pickings del
  módulo nuevo no deben disparar eso.
- Multi-empresa: los pickings de salida viven en la empresa origen y los de entrada
  en la destino; los record rules por empresa del stock nativo tienen que respetarse.

## Decisiones tomadas tras la revisión (llamadas mías)

- **Valuación:** todas las categorías son `manual_periodic` (default en `ir_default`),
  no hay asientos por movimiento → no hay trabajo contable.
- **Stock insuficiente en origen:** se permite enviar igual (en `prod` hay ~19.700
  quants internos negativos; bloquear rompería la operación). El formulario muestra
  un aviso no bloqueante en las líneas sin stock suficiente.
- **Productos de una sola empresa:** hay 269 productos con `company_id` propio
  (`product_company_restriction`). Las líneas solo aceptan productos sin empresa
  o compartidos con la empresa destino.
- **Alcance del Manager:** ve y actúa sobre todos los traslados de todas las
  sucursales; su contador cuenta lo de sus sucursales (`company_ids`), igual que
  el usuario.
- **Asignación de grupos:** Traslados / Usuario se implica desde `base.group_user`
  (todo usuario interno puede enviar, como pidió Alexis). Traslados / Manager se
  asigna a mano.

## Pendiente para el builder

- Mecanismo concreto de stock (pickings por empresa + ubicación de tránsito
  propia vs. la "Inter-company transit" nativa) y cómo evitar el disparador de
  `stock_intercompany` (contexto, campo en el picking, depender del módulo, etc.).
- Cómo se implementan las correcciones de un traslado ya recibido (pickings de
  ajuste/devolución).
- Implementación del contador en el ícono (patch OWL del menú de apps + refresco).
- Secuencia del nombre (ej. `TRS/00001`), record rules, vistas, ícono.
