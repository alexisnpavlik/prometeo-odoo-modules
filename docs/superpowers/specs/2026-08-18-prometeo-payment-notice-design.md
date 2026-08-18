# Diseño: Aviso de pago pendiente (`prometeo_payment_notice` + servicio `cobranzas`)

**Fecha:** 2026-08-18
**Estado:** Aprobado, pendiente de plan de implementación
**Repos involucrados:** `prometeo-odoo-modules` (rama `cobris`), `prometeo_local_server`

---

## 1. Problema

Los clientes de Prometeo pagan el servicio el día 5 de cada mes. Cuando un pago no se
registra, hoy no hay ningún mecanismo dentro del propio Odoo del cliente que lo recuerde.

Se busca un **recordatorio amistoso** visible dentro del Odoo del cliente cuando el pago
del período en curso no figura registrado, con el mismo tono y ubicación que el cartel de
"base de datos neutralizada" de Odoo. Nunca bloquea ni degrada funcionalidad.

## 2. Contexto y restricciones

- Los Odoo de los clientes corren en VPS accesibles solo por internet (ej. `72.61.53.216`).
- La base de datos de cobranzas vive en el server local `192.168.1.147`
  (repo `prometeo_local_server`), que ya publica servicios por `cloudflared`.
- **Alexis es el administrador de las instalaciones**; el cliente no tiene acceso admin.
  No hace falta protección anti-manipulación: alcanza con no exponer credenciales de DB.
- Los pagos se cargan a mano por SQL. No hay panel de administración en el alcance.
- El repo `prometeo-odoo-modules` es Odoo 18.0 y no tiene suite de tests.

## 3. Decisión de arquitectura: API HTTP intermedia

El Odoo del cliente **no** se conecta a Postgres. Consulta una API HTTP mínima que corre
junto a la base en el server local y se publica por el túnel de Cloudflare existente.

Alternativas descartadas:

- **Postgres expuesto directo (`psycopg2`)**: obliga a abrir el puerto 5432 a internet o
  instalar `cloudflared` en cada VPS cliente, y a mantener `pg_hba.conf` + firewall por
  cada alta. Además reparte credenciales de base en instalaciones ajenas.
- **JSON estático servido por nginx**: el más simple, pero pierde el estado por cliente y
  la trazabilidad de qué instancia consultó.

Consecuencia clave: **la lógica de negocio de fechas vive en el servidor**, no en el
módulo. Cambiar un plazo, otorgar una prórroga o reescribir el mensaje de un cliente es un
`UPDATE` en la base local, sin actualizar módulos en ningún VPS.

## 4. Lado servidor: `services/cobranzas/`

Sigue el patrón del repo: carpeta propia con su `docker-compose.yml`, `.env.example`,
`Dockerfile` y `README.md`, incluida desde el `docker-compose.yml` raíz y conectada a la
red `prometeo-net`. Deploy con `git pull` + `make deploy`, igual que el resto.

### 4.1 Esquema Postgres

Contenedor Postgres propio, **sin puertos publicados al host**: solo alcanzable desde
`prometeo-net`.

```sql
CREATE TABLE clientes (
    id              SERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL,
    instance_key    TEXT NOT NULL UNIQUE,
    token           TEXT NOT NULL,
    dia_vencimiento INT  NOT NULL DEFAULT 5,
    dias_gracia     INT  NOT NULL DEFAULT 5,
    mensaje_custom  TEXT,
    activo          BOOLEAN NOT NULL DEFAULT true,
    creado          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pagos (
    id          SERIAL PRIMARY KEY,
    cliente_id  INT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    periodo     DATE NOT NULL,          -- primer día del mes que se está pagando
    monto       NUMERIC(12,2),
    fecha_pago  DATE NOT NULL,
    medio       TEXT,
    nota        TEXT,
    creado      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cliente_id, periodo)
);

CREATE TABLE consultas (
    id         SERIAL PRIMARY KEY,
    cliente_id INT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip         TEXT
);
```

`periodo` se normaliza siempre al día 1 del mes. `consultas` funciona como heartbeat: si
una instancia deja de aparecer, se sabe que dejó de reportar.

Se provee un script SQL con una función helper para registrar el pago sin tipear el INSERT
completo, del estilo `SELECT registrar_pago('mega-erp', '2026-08-01', 50000, 'transferencia');`.

### 4.2 API

FastAPI, un solo endpoint funcional más un health check.

`GET /v1/status`
Headers: `X-Instance-Key`, `X-Token`.

Respuesta 200:

```json
{
  "al_dia": false,
  "mostrar_aviso": true,
  "periodo": "2026-08-01",
  "vencio_el": "2026-08-05",
  "dias_atraso": 13,
  "mensaje": "Hola! No nos figura registrado el pago de agosto. Si ya lo hiciste, avisanos."
}
```

Regla de decisión:

```
periodo      = primer día del mes actual
vencio_el    = periodo + (dia_vencimiento - 1) días
limite       = vencio_el + dias_gracia días
al_dia       = existe fila en pagos para (cliente, periodo)
mostrar_aviso = cliente.activo AND NOT al_dia AND hoy >= limite
```

Con los valores por defecto (vencimiento 5, gracia 5), el aviso empieza a mostrarse el
día 10 del mes: si para el día 10 el pago no figura registrado, aparece el cartel.

`mensaje` sale de `mensaje_custom` si está cargado; si no, de una plantilla por defecto con
el nombre del mes interpolado.

Errores: `401` si `instance_key` + `token` no coinciden o el cliente está inactivo.
`GET /health` devuelve `{"status": "ok"}` para el healthcheck del contenedor.

Cada request autenticado inserta una fila en `consultas` con la IP de origen.

Publicación: hostname propio en la config de `cloudflared`, apuntando al servicio dentro
de `prometeo-net`. La base nunca sale a internet.

## 5. Lado Odoo: módulo `prometeo_payment_notice`

Estructura estándar del repo: `__manifest__.py`, `models/`, `views/`, `data/`,
`static/src/`, `security/`, `static/description/icon.png`.

Depende de `base`, `web` y `point_of_sale`.

### 5.1 Configuración

Sección propia en Ajustes, todos los valores persistidos en `ir.config_parameter` vía
`res.config.settings`:

| Parámetro | Descripción |
|---|---|
| `prometeo_payment_notice.api_url` | URL base de la API |
| `prometeo_payment_notice.instance_key` | Identificador de esta instalación |
| `prometeo_payment_notice.token` | Token de la instalación |
| `prometeo_payment_notice.pos_mode` | `oculto` / `franja` / `popup` |
| `prometeo_payment_notice.state` | JSON cacheado con la última respuesta + timestamp (interno, no editable) |

Botón **"Probar conexión"**: ejecuta la consulta en el momento y devuelve el resultado en
un toast, para validar el alta de un cliente sin esperar al cron.

### 5.2 Consulta y cacheo

`ir.cron` diario que llama a la API con `requests` (timeout 10s, sin reintentos) y guarda
la respuesta completa más el timestamp de la consulta en el parámetro `state`.

Manejo de errores con `try/except Exception as e` y logging estructurado. **Ante cualquier
fallo (timeout, DNS, 5xx, JSON inválido) se conserva el último estado conocido y jamás se
genera un aviso nuevo.** El criterio es fail-safe: ante la duda, el cliente está al día.

Ninguna vista de Odoo hace llamadas de red: todas leen el parámetro cacheado.

### 5.3 Cartel en el backend

Override de `ir.http._get_session_info()` para inyectar en la sesión:

```python
{"prometeo_payment_notice": {"mostrar": bool, "mensaje": str}}
```

Es el mismo mecanismo con el que Odoo entrega `expiration_date` para el cartel de base
neutralizada, así que no agrega ningún RPC.

Del lado JS, un componente OWL insertado por herencia de la plantilla `web.WebClient`
(entre la barra de navegación y el contenido) que renderiza una franja cuando `mostrar` es
`true`. La ven **todos los usuarios** del backend. No es descartable, pero tampoco bloquea ninguna acción.

Estilo: fondo ámbar suave, texto oscuro, tono cordial.

### 5.4 Aviso en el POS

El mismo dict se carga dentro de los datos de la sesión del POS junto con el valor de
`pos_mode`. Según el modo configurado:

- `oculto`: no se monta nada.
- `franja`: barra fina permanente en la parte superior de la pantalla del POS.
- `popup`: diálogo amistoso una sola vez al abrir la sesión, cerrable con un botón.

Nunca interfiere con el cobro ni con el cierre de caja.

## 6. Flujo completo

1. Alexis da de alta al cliente: `INSERT` en `clientes` con su `instance_key` y `token`.
2. Configura esos dos valores más la `api_url` en los Ajustes del Odoo del cliente y
   verifica con "Probar conexión".
3. Cada día el cron de ese Odoo consulta `/v1/status` y cachea la respuesta.
4. Si el pago del mes no está cargado y pasó la fecha límite, la API devuelve
   `mostrar_aviso: true` y el cartel aparece en el backend (y en el POS si está activado).
5. Alexis registra el pago con la función SQL; al día siguiente el cron trae
   `mostrar_aviso: false` y el cartel desaparece.

## 7. Verificación

Sin suite de tests automatizados, en línea con el resto del repo.

1. Levantar `services/cobranzas` localmente y cargar un cliente de prueba sin pago del
   período en curso.
2. Comprobar a mano las respuestas de `/v1/status`: cliente al día, cliente en mora,
   cliente dentro del período de gracia, y credenciales inválidas.
3. Instalar el módulo en el contenedor local `odoo-odoo-1` con `-u` y verificar la franja
   en el backend.
4. Verificar las variantes `franja` y `popup` del POS, más el modo `oculto`.
5. Verificar el comportamiento fail-safe apagando el servicio de la API: el Odoo no debe
   mostrar avisos nuevos ni registrar errores que rompan el cron.

## 8. Fuera de alcance

- Panel web de administración de cobranzas (la carga es por SQL).
- Automatización del registro de pagos (n8n, MercadoPago, mail).
- Cualquier bloqueo o degradación de funcionalidad por falta de pago.
- Notificaciones por fuera de Odoo (mail, WhatsApp).
