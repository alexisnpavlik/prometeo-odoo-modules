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

## Monitoreo del Lado Servidor (Python)

El módulo también inicializa el SDK de Sentry para Python de forma global al arrancar el servidor Odoo.

### Decisiones de Arquitectura (Estabilidad del Sistema)
Se evaluó la posibilidad de realizar monkey patches de bajo nivel en métodos core de Odoo como `odoo.http.Root.dispatch` o `BaseModel._call_kw`. **Estas opciones fueron descartadas deliberadamente** debido a que operan en la ruta crítica (hot path) de ejecución de todas las transacciones de las 12 sucursales. Un fallo en dicha lógica podría tumbar el sistema Odoo entero.

En su lugar, se implementan dos capas de bajo riesgo y alta estabilidad:
1. **`before_send` con extracción de módulo de origen**: Analiza el traceback del error utilizando `traceback.extract_tb()` para determinar dinámicamente cuál fue el módulo/addon de origen mediante expresiones regulares.
   - Agrega la etiqueta `odoo_module` con el nombre del módulo.
   - Agrega la etiqueta `is_custom_module` (`true`/`false`) para saber si el error ocurrió en un módulo propio (ej: `pos_pricelist_unit_price`, `pos_sales_readonly`, etc.) o en el core/ingadhoc.
   - Agrega la etiqueta `db_name` a partir de la información de base de datos a nivel de hilo en ejecución (`threading.current_thread().dbname`).
2. **`LoggingIntegration` de Sentry**: Utiliza la integración de logging oficial de Sentry (`sentry_sdk.integrations.logging.LoggingIntegration`).
   - Envía automáticamente a Sentry los logs de nivel `ERROR` como eventos individuales.
   - Agrega logs de nivel `INFO` o superior como *breadcrumbs* contextuales.
   - El tag `logger` se genera automáticamente con la ruta completa del módulo que emitió el log.

Todo el código de inicialización y procesamiento de Sentry se encuentra protegido en bloques `try/except` para garantizar que un problema con Sentry (ej: falta de conectividad o DSN inválido) nunca afecte la funcionalidad principal de Odoo.
