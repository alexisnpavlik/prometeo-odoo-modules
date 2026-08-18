# prometeo_payment_notice

Módulo de Odoo 18 que muestra un aviso amistoso dentro de Odoo cuando el pago
mensual del servicio de Prometeo no figura registrado. Nunca bloquea ni
degrada ninguna funcionalidad: es solo un aviso visual.

## Configuración

**Ajustes → Aviso de pago.**

- **URL de la API de cobranzas**: base de la API, sin barra final (ej.
  `https://cobranzas.prometeolab.com.ar`).
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

## Fail-safe

Ante cualquier error de red, timeout, respuesta 4xx/5xx, JSON inválido o
estado cacheado corrupto, se conserva el último estado conocido y nunca se
genera un aviso nuevo. Ante la duda, el cliente está al día.

## Contraparte

El servicio vive en `services/cobranzas/` del repo `prometeo_local_server`
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
