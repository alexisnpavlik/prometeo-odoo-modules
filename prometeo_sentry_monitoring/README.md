# prometeo_sentry_monitoring

Módulo de Odoo 18 para el monitoreo de errores del lado frontend (Backend Web y Punto de Venta / POS) utilizando Sentry JS SDK.

## Configuración del Sentry DSN

El DSN de Sentry puede configurarse de tres formas jerárquicas (la de mayor prioridad sobreescribe las siguientes):

1. **Variable de Entorno (`SENTRY_DSN`)**:
   Se define en el entorno del contenedor o VPS donde corre Odoo:
   ```bash
   export SENTRY_DSN="tu_sentry_dsn_aqui"
   ```
   Luego de cambiar esta variable, reinicia el servidor/contenedor de Odoo para aplicar los cambios sin tocar código.

2. **Parámetro del Sistema (`ir.config_parameter`)**:
   Si la variable de entorno no está establecida, el módulo buscará el valor guardado en el parámetro de sistema:
   `prometeo_sentry_monitoring.sentry_dsn`.
   Puedes crearlo/editarlo desde el backend de Odoo (Ajustes -> Técnico -> Parámetros del sistema).

3. **DSN por Defecto (Fallback)**:
   Si no se define la variable de entorno ni el parámetro de sistema, se utilizará el DSN provisto por defecto:
   `https://5e7994545829f0e490b60b785ac8d645@o4511665781276672.ingest.us.sentry.io/4511665789272064`.

## Estructura del Módulo

- **Fase 1 (POC)**: `static/src/js/error_tracking_poc.js` captura errores no controlados y promesas rechazadas a través de las APIs nativas del navegador, registrándolos en consola con los prefijos `[POS ERROR]` y `[POS UNHANDLED PROMISE]`.
- **Fase 2 (Sentry SDK)**: Carga e inicializa el Sentry Browser SDK vendorizado (`static/lib/sentry/bundle.min.js`) usando `sentry_pos_init.js` para POS y `sentry_backend_init.js` para el backend web, inyectando las etiquetas dinámicas `module_source`, `db_name` y `pos_config_id`.
