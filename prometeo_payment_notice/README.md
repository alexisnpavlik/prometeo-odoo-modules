# prometeo_payment_notice

Módulo de Odoo 18 que muestra un aviso amistoso dentro de Odoo cuando el pago
mensual del servicio de Prometeo no figura registrado. Pasados los días que
indique el servidor de cobranzas, además puede hacer esperar al cajero antes
de abrir y de cerrar la caja del POS. Nunca impide vender ni cobrar.

## Configuración

**Ajustes → Aviso de pago.**

- **URL de la API de cobranzas**: base de la API, sin barra final (ej.
  `https://registropagos.prometeolab.com.ar`).
- **Clave de instalación**: identificador de esta instalación en la base de
  cobranzas.
- **Token**: token entregado al dar de alta la instalación.
- **Aviso en el POS**: modo de aviso dentro del Punto de Venta.
  - `No mostrar en el POS`
  - `Franja fija arriba`
  - `Aviso al abrir la sesión`

El botón **Probar conexión** guarda la configuración, consulta la API en el
momento y devuelve el resultado en una notificación (éxito, aviso activo o
error de conexión).

## Cómo funciona

Un cron diario (**Prometeo: verificar estado de pago del servicio**) consulta
`GET /v1/status` en la API de cobranzas, enviando los headers `X-Instance-Key`
y `X-Token`, y guarda la respuesta en el parámetro de sistema
`prometeo_payment_notice.state`.

Ninguna pantalla hace llamadas de red: la franja del backend lee el aviso
desde `session_info` y el POS lo recibe en los datos de la sesión.

## Bloqueo de caja

Cuando el servidor devuelve `bloqueo_caja`, el POS muestra un diálogo sin
salida —sin Escape y sin X— con una cuenta regresiva, y el botón para
continuar aparece recién al terminarla:

- **Al abrir la caja**, cada vez que se intenta. Si el cajero descarta el
  control de apertura y vuelve a entrar, espera de nuevo. Una vez abierta la
  caja no vuelve a salir: el disparador es `shouldShowOpeningControl`, o sea
  que la sesión siga en `opening_control`.
- **Al cerrar la caja**, cada vez que se pide el cierre.

Se configura por cliente en el panel de cobranzas, no acá: *trabar la caja*
(apagado por defecto), *días de atraso* (15) y *segundos de espera* (180). Un
cliente en mora no puede apagárselo desde sus propios Ajustes; el modo del
aviso del POS no lo afecta.

El bloqueo nunca cae en medio de una venta ni de un cobro: solo en la apertura
y en el cierre.

## Fail-safe

Ante cualquier error de red, timeout, respuesta 4xx/5xx, JSON inválido o
estado cacheado corrupto, se conserva el último estado conocido y nunca se
genera un aviso nuevo. Ante la duda, el cliente está al día.

El bloqueo de caja tiene un fail-safe más estricto que el aviso: si la última
consulta exitosa tiene 7 días o más, se apaga solo. Una caída larga del
servidor de cobranzas deja el aviso viejo en pantalla, pero nunca deja a un
cliente esperando para abrir la caja.

## Contraparte

El servicio vive en `services/prometeo_cobranzas/` del repo `prometeo_local_server`
(Postgres privado + API FastAPI publicada por el túnel de Cloudflare). Su
README tiene el detalle operativo (esquema, endpoints, despliegue).

## Alta de una instalación nueva

1. Dar de alta el cliente en la base de cobranzas:
   ```sql
   SELECT alta_cliente('Nombre del cliente', 'clave-instancia');
   ```
   Esto devuelve el token de la instalación.
2. Cargar la URL de la API, la clave de instalación y el token en
   **Ajustes → Aviso de pago** del Odoo del cliente.
3. Verificar con el botón **Probar conexión**.
