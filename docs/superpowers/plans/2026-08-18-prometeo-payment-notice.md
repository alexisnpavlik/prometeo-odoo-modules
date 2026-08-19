# Aviso de pago pendiente — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el Odoo de un cliente muestre un cartel amistoso cuando el pago mensual del servicio no figura registrado en la base de cobranzas del server local.

**Architecture:** Un servicio nuevo (`services/cobranzas/`) en el server local `192.168.1.147` corre un Postgres privado y una API FastAPI que decide, según el día del mes y los pagos cargados, si corresponde avisar. La API se publica por el túnel de Cloudflare existente. Un módulo Odoo 18 (`prometeo_payment_notice`) la consulta con un cron diario, cachea la respuesta en `ir.config_parameter` y pinta una franja en el cliente web y, opcionalmente, en el POS.

**Tech Stack:** Docker Compose, Postgres 15, Python 3.11 + FastAPI + psycopg2, cloudflared, Odoo 18.0 (Python + OWL/QWeb).

**Spec:** `docs/superpowers/specs/2026-08-18-prometeo-payment-notice-design.md`

## Global Constraints

- Dos repos: Tareas 1–2 en `/home/alexis/Documents/Github/prometeo_local_server` (rama `master`); Tareas 3–6 en `/home/alexis/Documents/Github/prometeo-odoo-modules` (rama `cobris`). Cada tarea commitea en su propio repo.
- Odoo 18.0. Versión del módulo `18.0.1.0.0`. `author` = `Alexis Medina`, `website` = `alexis.medn@gmail.com`, `license` = `LGPL-3`.
- snake_case en todo. Docstring en toda función/método. Errores con `try/except Exception as e` + logging estructurado (`_logger`), nunca `print` dentro del módulo Odoo.
- Textos de UI en español rioplatense, tono cordial. Nada bloquea ni degrada funcionalidad.
- **Fail-safe:** ante cualquier error de red, timeout, 4xx/5xx o JSON inválido, el módulo conserva el último estado conocido y **nunca genera un aviso nuevo**.
- El Postgres de cobranzas **no publica puertos al host**. La API publica `8096`. `cloudflared` corre en el host y apunta a `http://localhost:8096`.
- Hostname público: `cobranzas.prometeolab.com.ar`.
- Valores por defecto del negocio: `dia_vencimiento = 5`, `dias_gracia = 5` → el aviso arranca el día 10.
- Sin suite de tests automatizados (igual que el resto de los repos): cada tarea se verifica con comandos concretos y salida esperada.

---

### Task 1: Servicio `cobranzas` — base de datos

**Files:**
- Create: `services/cobranzas/docker-compose.yml`
- Create: `services/cobranzas/.env.example`
- Create: `services/cobranzas/sql/01_schema.sql`
- Create: `services/cobranzas/sql/02_funciones.sql`
- Modify: `docker-compose.yml` (bloque `include`)
- Modify: `Makefile` (target `check-env` y nuevo `logs-cobranzas`)

**Interfaces:**
- Produces: base `cobranzas` con las tablas `clientes`, `pagos`, `consultas` y la función `registrar_pago(text, date, numeric, text)`. Contenedor `cobranzas-db` en la red `prometeo-net`, alcanzable por hostname `cobranzas-db:5432`.

- [ ] **Step 1: Crear el esquema SQL**

Crear `services/cobranzas/sql/01_schema.sql`:

```sql
-- Esquema de la base de cobranzas de Prometeo.
-- Se ejecuta una sola vez, al inicializar el volumen del contenedor.

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
    periodo     DATE NOT NULL,
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

CREATE INDEX idx_consultas_cliente_ts ON consultas (cliente_id, ts DESC);
```

- [ ] **Step 2: Crear las funciones helper**

Crear `services/cobranzas/sql/02_funciones.sql`:

```sql
-- Helpers para operar la base a mano, sin tipear INSERTs completos.

-- Da de alta un cliente y devuelve el token generado.
CREATE OR REPLACE FUNCTION alta_cliente(p_nombre TEXT, p_instance_key TEXT)
RETURNS TEXT AS $func$
DECLARE
    v_token TEXT;
BEGIN
    v_token := encode(gen_random_bytes(24), 'hex');
    INSERT INTO clientes (nombre, instance_key, token)
    VALUES (p_nombre, p_instance_key, v_token);
    RETURN v_token;
END;
$func$ LANGUAGE plpgsql;

-- Registra el pago de un período. El período se normaliza al día 1 del mes.
CREATE OR REPLACE FUNCTION registrar_pago(
    p_instance_key TEXT,
    p_periodo      DATE,
    p_monto        NUMERIC DEFAULT NULL,
    p_medio        TEXT    DEFAULT NULL
) RETURNS INT AS $func$
DECLARE
    v_cliente_id INT;
    v_pago_id    INT;
BEGIN
    SELECT id INTO v_cliente_id FROM clientes WHERE instance_key = p_instance_key;
    IF v_cliente_id IS NULL THEN
        RAISE EXCEPTION 'No existe cliente con instance_key %', p_instance_key;
    END IF;

    INSERT INTO pagos (cliente_id, periodo, monto, fecha_pago, medio)
    VALUES (v_cliente_id, date_trunc('month', p_periodo)::date, p_monto, CURRENT_DATE, p_medio)
    ON CONFLICT (cliente_id, periodo) DO UPDATE
        SET monto = EXCLUDED.monto,
            fecha_pago = EXCLUDED.fecha_pago,
            medio = EXCLUDED.medio
    RETURNING id INTO v_pago_id;

    RETURN v_pago_id;
END;
$func$ LANGUAGE plpgsql;

-- Estado rápido de todos los clientes para el mes en curso.
CREATE OR REPLACE VIEW estado_actual AS
SELECT c.nombre,
       c.instance_key,
       c.activo,
       (p.id IS NOT NULL) AS pago_registrado,
       p.fecha_pago,
       p.monto,
       (SELECT max(ts) FROM consultas q WHERE q.cliente_id = c.id) AS ultima_consulta
FROM clientes c
LEFT JOIN pagos p
       ON p.cliente_id = c.id
      AND p.periodo = date_trunc('month', CURRENT_DATE)::date
ORDER BY c.nombre;
```

`gen_random_bytes` viene de `pgcrypto`. Agregar al principio de `01_schema.sql`, antes de los `CREATE TABLE`:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

- [ ] **Step 3: Crear el compose del servicio**

Crear `services/cobranzas/docker-compose.yml` (por ahora solo la DB; la API se agrega en la Tarea 2):

```yaml
services:
  cobranzas-db:
    image: postgres:15-alpine
    container_name: cobranzas-db
    env_file:
      - .env
    environment:
      POSTGRES_USER: ${COBRANZAS_DB_USER:-cobranzas}
      POSTGRES_PASSWORD: ${COBRANZAS_DB_PASSWORD}
      POSTGRES_DB: ${COBRANZAS_DB_NAME:-cobranzas}
    volumes:
      - "${COBRANZAS_DB_HOST_DIR:-/home/alexis/prometeo_local_server/data/cobranzas/db}:/var/lib/postgresql/data"
      - "./sql:/docker-entrypoint-initdb.d:ro"
    mem_limit: 256m
    restart: unless-stopped
    networks:
      - prometeo-net
    healthcheck:
      test: [ "CMD-SHELL", "pg_isready -U ${COBRANZAS_DB_USER:-cobranzas}" ]
      interval: 10s
      timeout: 5s
      retries: 5
```

Los scripts de `/docker-entrypoint-initdb.d` corren **solo** cuando el volumen está vacío. Para reiniciar el esquema hay que borrar el directorio de datos.

- [ ] **Step 4: Crear el `.env.example`**

Crear `services/cobranzas/.env.example`:

```bash
COBRANZAS_DB_USER=cobranzas
COBRANZAS_DB_PASSWORD=changeme
COBRANZAS_DB_NAME=cobranzas
COBRANZAS_DB_HOST_DIR=/home/alexis/prometeo_local_server/data/cobranzas/db
```

- [ ] **Step 5: Enganchar el servicio al stack**

En `docker-compose.yml` (raíz), agregar la línea al bloque `include`, después de `services/gastos-dashboard/docker-compose.yml`:

```yaml
  - services/cobranzas/docker-compose.yml
```

En `Makefile`, dentro del target `check-env`, agregar `cobranzas` a la lista del `for`:

```makefile
	@for s in vikunja gastos-dashboard n8n cobranzas; do \
```

Y agregar un target nuevo después de `logs-n8n`, más su nombre en la línea `.PHONY`:

```makefile
logs-cobranzas: ## Sigue los logs del servicio de cobranzas y su base de datos
	docker compose logs -f --tail=100 cobranzas-api cobranzas-db
```

- [ ] **Step 6: Levantar y verificar el esquema**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
cp services/cobranzas/.env.example services/cobranzas/.env
docker compose config >/dev/null && echo "compose OK"
docker compose up -d cobranzas-db
sleep 8
docker exec cobranzas-db psql -U cobranzas -d cobranzas -c '\dt'
```

Esperado: `compose OK` y una tabla con `clientes`, `consultas`, `pagos`.

- [ ] **Step 7: Verificar las funciones helper**

```bash
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "SELECT alta_cliente('Cliente de prueba', 'demo-test');"
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "SELECT registrar_pago('demo-test', CURRENT_DATE, 50000, 'transferencia');"
docker exec cobranzas-db psql -U cobranzas -d cobranzas -c "SELECT * FROM estado_actual;"
```

Esperado: `alta_cliente` devuelve un token hexadecimal de 48 caracteres, `registrar_pago` devuelve un id, y `estado_actual` muestra `pago_registrado = t` para `demo-test`.

- [ ] **Step 8: Commit**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
git add services/cobranzas docker-compose.yml Makefile
git commit -m "feat(cobranzas): base de datos de cobranzas con esquema y helpers SQL"
```

---

### Task 2: API de estado de pago + publicación

**Files:**
- Create: `services/cobranzas/api/logic.py`
- Create: `services/cobranzas/api/main.py`
- Create: `services/cobranzas/api/requirements.txt`
- Create: `services/cobranzas/Dockerfile`
- Create: `services/cobranzas/README.md`
- Modify: `services/cobranzas/docker-compose.yml` (agregar `cobranzas-api`)
- Modify: `services/cobranzas/.env.example` (variables de la API)
- Modify: `services/cloudflared/config.template.yml` (hostname público)

**Interfaces:**
- Consumes: tablas `clientes`, `pagos`, `consultas` de la Tarea 1.
- Produces: `GET /health` → `{"status": "ok"}`. `GET /v1/status` con headers `X-Instance-Key` y `X-Token` → JSON con las claves `al_dia` (bool), `mostrar_aviso` (bool), `periodo` (str `YYYY-MM-DD`), `vencio_el` (str `YYYY-MM-DD`), `dias_atraso` (int), `mensaje` (str). Es el contrato exacto que consume el módulo Odoo en la Tarea 3.

- [ ] **Step 1: Escribir la lógica de decisión**

Crear `services/cobranzas/api/logic.py`:

```python
"""Decide si corresponde mostrar el aviso de pago para un cliente."""

from datetime import date, timedelta

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

MENSAJE_DEFAULT = (
    "Hola! No nos figura registrado el pago de {mes}. "
    "Si ya lo hiciste, avisanos y lo damos de baja del sistema. ¡Gracias!"
)


def periodo_de(hoy):
    """Devuelve el primer día del mes de la fecha dada."""
    return hoy.replace(day=1)


def calcular_estado(cliente, tiene_pago, hoy=None):
    """Arma la respuesta de estado para un cliente.

    cliente: dict con nombre, dia_vencimiento, dias_gracia, mensaje_custom, activo.
    tiene_pago: True si existe un pago cargado para el período en curso.
    hoy: fecha de referencia; por defecto la del sistema.
    """
    hoy = hoy or date.today()
    periodo = periodo_de(hoy)
    vencio_el = periodo + timedelta(days=cliente["dia_vencimiento"] - 1)
    limite = vencio_el + timedelta(days=cliente["dias_gracia"])

    al_dia = bool(tiene_pago)
    mostrar_aviso = bool(cliente["activo"]) and not al_dia and hoy >= limite
    dias_atraso = 0 if al_dia else max((hoy - vencio_el).days, 0)

    mensaje = cliente.get("mensaje_custom") or MENSAJE_DEFAULT.format(
        mes=MESES[periodo.month - 1]
    )

    return {
        "al_dia": al_dia,
        "mostrar_aviso": mostrar_aviso,
        "periodo": periodo.isoformat(),
        "vencio_el": vencio_el.isoformat(),
        "dias_atraso": dias_atraso,
        "mensaje": mensaje,
    }
```

- [ ] **Step 2: Escribir la API**

Crear `services/cobranzas/api/main.py`:

```python
"""API de estado de pago para las instalaciones de Odoo de Prometeo."""

import logging
import os

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Header, HTTPException, Request

from logic import calcular_estado

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("cobranzas")

app = FastAPI(title="Cobranzas Prometeo", docs_url=None, redoc_url=None)


def conectar():
    """Abre una conexión a la base de cobranzas."""
    return psycopg2.connect(
        host=os.getenv("COBRANZAS_DB_HOST", "cobranzas-db"),
        port=int(os.getenv("COBRANZAS_DB_PORT", "5432")),
        user=os.getenv("COBRANZAS_DB_USER", "cobranzas"),
        password=os.getenv("COBRANZAS_DB_PASSWORD", ""),
        dbname=os.getenv("COBRANZAS_DB_NAME", "cobranzas"),
        connect_timeout=5,
    )


def ip_de(request):
    """Devuelve la IP de origen, respetando la cabecera de Cloudflare."""
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else ""
    )


@app.get("/health")
def health():
    """Health check del contenedor."""
    return {"status": "ok"}


@app.get("/v1/status")
def status(
    request: Request,
    x_instance_key: str = Header(default=""),
    x_token: str = Header(default=""),
):
    """Devuelve el estado de pago del período en curso para una instalación."""
    if not x_instance_key or not x_token:
        raise HTTPException(status_code=401, detail="Credenciales faltantes")

    conn = None
    try:
        conn = conectar()
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, nombre, dia_vencimiento, dias_gracia,
                           mensaje_custom, activo
                      FROM clientes
                     WHERE instance_key = %s AND token = %s
                    """,
                    (x_instance_key, x_token),
                )
                cliente = cur.fetchone()
                if not cliente:
                    _logger.warning("Credenciales invalidas para %s", x_instance_key)
                    raise HTTPException(status_code=401, detail="Credenciales inválidas")

                cur.execute(
                    """
                    SELECT id FROM pagos
                     WHERE cliente_id = %s
                       AND periodo = date_trunc('month', CURRENT_DATE)::date
                    """,
                    (cliente["id"],),
                )
                tiene_pago = cur.fetchone() is not None

                cur.execute(
                    "INSERT INTO consultas (cliente_id, ip) VALUES (%s, %s)",
                    (cliente["id"], ip_de(request)),
                )
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("Fallo la consulta de estado: %s", e)
        raise HTTPException(status_code=503, detail="Base no disponible")
    finally:
        if conn is not None:
            conn.close()

    return calcular_estado(dict(cliente), tiene_pago)
```

`with conn` commitea la transacción al salir del bloque sin excepción, así que el `INSERT` en `consultas` queda persistido — pero **no** cierra la conexión: de ahí el `finally` con `conn.close()`, sin el cual cada request dejaría una conexión abierta.

- [ ] **Step 3: Escribir requirements y Dockerfile**

Crear `services/cobranzas/api/requirements.txt`:

```
fastapi==0.115.6
uvicorn==0.34.0
psycopg2-binary==2.9.10
```

Crear `services/cobranzas/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ .

EXPOSE 8096
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8096"]
```

- [ ] **Step 4: Agregar el servicio de API al compose**

En `services/cobranzas/docker-compose.yml`, agregar debajo de `cobranzas-db`:

```yaml
  cobranzas-api:
    build: .
    image: cobranzas-api:local
    container_name: cobranzas-api
    env_file:
      - .env
    depends_on:
      cobranzas-db:
        condition: service_healthy
    ports:
      - "8096:8096"
    environment:
      COBRANZAS_DB_HOST: cobranzas-db
    mem_limit: 256m
    restart: unless-stopped
    networks:
      - prometeo-net
    healthcheck:
      test: [ "CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8096/health')\"" ]
      interval: 30s
      timeout: 5s
      retries: 3
```

En `services/cobranzas/.env.example`, agregar al final:

```bash
COBRANZAS_DB_HOST=cobranzas-db
COBRANZAS_DB_PORT=5432
```

- [ ] **Step 5: Levantar la API y verificar el health check**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
cp services/cobranzas/.env.example services/cobranzas/.env  # si no existe todavía
docker compose up -d --build cobranzas-api
sleep 10
curl -s http://localhost:8096/health
```

Esperado: `{"status":"ok"}`.

- [ ] **Step 6: Verificar los cuatro casos de negocio**

Con el cliente `demo-test` creado en la Tarea 1 (que ya tiene el pago del mes registrado):

```bash
TOKEN=$(docker exec cobranzas-db psql -U cobranzas -d cobranzas -tA \
  -c "SELECT token FROM clientes WHERE instance_key='demo-test';")

# 1) Cliente al día
curl -s -H "X-Instance-Key: demo-test" -H "X-Token: $TOKEN" \
  http://localhost:8096/v1/status

# 2) Cliente en mora (borrar el pago del mes)
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "DELETE FROM pagos WHERE cliente_id=(SELECT id FROM clientes WHERE instance_key='demo-test');"
curl -s -H "X-Instance-Key: demo-test" -H "X-Token: $TOKEN" \
  http://localhost:8096/v1/status

# 3) Dentro del período de gracia (gracia enorme => nunca avisa)
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "UPDATE clientes SET dias_gracia=90 WHERE instance_key='demo-test';"
curl -s -H "X-Instance-Key: demo-test" -H "X-Token: $TOKEN" \
  http://localhost:8096/v1/status
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "UPDATE clientes SET dias_gracia=5 WHERE instance_key='demo-test';"

# 4) Credenciales inválidas
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-Instance-Key: demo-test" -H "X-Token: nope" \
  http://localhost:8096/v1/status
```

Esperado: (1) `"al_dia":true,"mostrar_aviso":false`; (2) `"al_dia":false` y `mostrar_aviso` en `true` si hoy es 10 o posterior; (3) `"mostrar_aviso":false`; (4) `401`.

- [ ] **Step 7: Verificar el registro de consultas**

```bash
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "SELECT count(*), max(ts) FROM consultas;"
```

Esperado: `count` mayor a 0 y `max(ts)` de hace segundos — una fila por cada consulta autenticada de los pasos anteriores.

- [ ] **Step 8: Publicar por cloudflared**

En `services/cloudflared/config.template.yml`, agregar dentro del bloque del dominio nuevo, antes del catch-all:

```yaml
  - hostname: cobranzas.prometeolab.com.ar
    service: http://localhost:8096
```

El túnel corre en el host, no en Docker: por eso apunta a `localhost:8096`, el puerto que publica `cobranzas-api`. Requiere crear el CNAME en Cloudflare y reinstalar la config con `services/cloudflared/setup-tunnel.sh`.

- [ ] **Step 9: Escribir el README del servicio**

Crear `services/cobranzas/README.md` con las secciones: qué hace, cómo levantarlo, **alta de un cliente nuevo** (`SELECT alta_cliente('Nombre', 'clave-instancia');` → anotar el token, cargarlo en el Odoo del cliente), **registrar un pago** (`SELECT registrar_pago('clave-instancia', CURRENT_DATE, 50000, 'transferencia');`), **ver el estado de todos** (`SELECT * FROM estado_actual;`), dar de baja temporal (`UPDATE clientes SET activo=false ...`), otorgar prórroga (`UPDATE clientes SET dias_gracia=... ...`) y el contrato de `/v1/status`.

- [ ] **Step 10: Commit**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
git add services/cobranzas services/cloudflared/config.template.yml
git commit -m "feat(cobranzas): API de estado de pago publicada por el tunel"
```

---

### Task 3: Módulo Odoo — configuración, consulta y cacheo

**Files:**
- Create: `prometeo_payment_notice/__init__.py`
- Create: `prometeo_payment_notice/__manifest__.py`
- Create: `prometeo_payment_notice/models/__init__.py`
- Create: `prometeo_payment_notice/models/prometeo_payment_notice.py`
- Create: `prometeo_payment_notice/models/res_config_settings.py`
- Create: `prometeo_payment_notice/views/res_config_settings_views.xml`
- Create: `prometeo_payment_notice/data/ir_cron.xml`

**Interfaces:**
- Consumes: contrato `GET /v1/status` de la Tarea 2.
- Produces: modelo abstracto `prometeo.payment.notice` con `fetch_status()` (consulta y cachea, devuelve dict crudo o `{}`), `get_notice()` (devuelve `{"mostrar": bool, "mensaje": str}` desde la caché) y `cron_check()`. Parámetros de sistema `prometeo_payment_notice.api_url`, `.instance_key`, `.token`, `.pos_mode`, `.state`. Las Tareas 4 y 5 consumen `get_notice()` y `.pos_mode`.

- [ ] **Step 1: Crear el esqueleto del módulo**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
mkdir -p prometeo_payment_notice/{models,views,data,static/description}
printf 'from . import models\n' > prometeo_payment_notice/__init__.py
printf 'from . import prometeo_payment_notice\nfrom . import res_config_settings\n' > prometeo_payment_notice/models/__init__.py
```

- [ ] **Step 2: Escribir el manifest**

Crear `prometeo_payment_notice/__manifest__.py`:

```python
# -*- coding: utf-8 -*-
{
    "name": "Prometeo - Aviso de pago del servicio",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Muestra un aviso amistoso cuando el pago mensual del servicio no figura registrado",
    "description": """
Consulta una vez por día la API de cobranzas de Prometeo y, si el pago del mes
en curso no figura registrado pasada la fecha límite, muestra una franja
amistosa en la parte superior del cliente web y, opcionalmente, en el POS.

La respuesta se cachea en un parámetro del sistema: ninguna pantalla hace
llamadas de red. Si el servidor no responde se conserva el último estado
conocido y nunca se genera un aviso nuevo.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "web", "point_of_sale"],
    "data": [
        "data/ir_cron.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
```

Los assets se agregan en las Tareas 4 y 5.

- [ ] **Step 3: Escribir el modelo**

Crear `prometeo_payment_notice/models/prometeo_payment_notice.py`:

```python
# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PARAM_URL = "prometeo_payment_notice.api_url"
PARAM_KEY = "prometeo_payment_notice.instance_key"
PARAM_TOKEN = "prometeo_payment_notice.token"
PARAM_POS_MODE = "prometeo_payment_notice.pos_mode"
PARAM_STATE = "prometeo_payment_notice.state"

TIMEOUT = 10
SIN_AVISO = {"mostrar": False, "mensaje": ""}


class PrometeoPaymentNotice(models.AbstractModel):
    _name = "prometeo.payment.notice"
    _description = "Aviso de pago del servicio"

    @api.model
    def _get_param(self, key, default=""):
        """Lee un parámetro del sistema con sudo y default seguro."""
        return self.env["ir.config_parameter"].sudo().get_param(key, default) or default

    @api.model
    def fetch_status(self):
        """Consulta la API de cobranzas y cachea la respuesta.

        Devuelve el dict crudo de la API, o {} si no está configurado o la
        consulta falla. Ante error se conserva el último estado cacheado.
        """
        url = self._get_param(PARAM_URL)
        instance_key = self._get_param(PARAM_KEY)
        token = self._get_param(PARAM_TOKEN)
        if not (url and instance_key and token):
            _logger.info("Aviso de pago: módulo sin configurar, no se consulta")
            return {}

        try:
            response = requests.get(
                "%s/v1/status" % url.rstrip("/"),
                headers={"X-Instance-Key": instance_key, "X-Token": token},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            _logger.warning("Aviso de pago: falló la consulta de estado (%s)", e)
            return {}

        data["consultado_el"] = fields.Datetime.to_string(fields.Datetime.now())
        self.env["ir.config_parameter"].sudo().set_param(PARAM_STATE, json.dumps(data))
        _logger.info("Aviso de pago: estado actualizado (aviso=%s)", data.get("mostrar_aviso"))
        return data

    @api.model
    def get_notice(self):
        """Devuelve el aviso a mostrar según el último estado cacheado.

        Fail-safe: si no hay caché o está corrupta, no se muestra nada.
        """
        raw = self._get_param(PARAM_STATE)
        if not raw:
            return dict(SIN_AVISO)
        try:
            data = json.loads(raw)
        except ValueError:
            _logger.warning("Aviso de pago: estado cacheado ilegible, se ignora")
            return dict(SIN_AVISO)
        return {
            "mostrar": bool(data.get("mostrar_aviso")),
            "mensaje": data.get("mensaje") or "",
        }

    @api.model
    def get_pos_mode(self):
        """Modo de visualización en el POS: oculto, franja o popup."""
        return self._get_param(PARAM_POS_MODE, "oculto")

    @api.model
    def cron_check(self):
        """Punto de entrada del cron diario."""
        self.fetch_status()
```

- [ ] **Step 4: Escribir el cron**

Crear `prometeo_payment_notice/data/ir_cron.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="ir_cron_prometeo_payment_notice" model="ir.cron">
        <field name="name">Prometeo: verificar estado de pago del servicio</field>
        <field name="model_id" ref="model_prometeo_payment_notice"/>
        <field name="state">code</field>
        <field name="code">model.cron_check()</field>
        <field name="interval_number">1</field>
        <field name="interval_type">days</field>
        <field name="active" eval="True"/>
    </record>
</odoo>
```

- [ ] **Step 5: Escribir la configuración**

Crear `prometeo_payment_notice/models/res_config_settings.py`:

```python
# -*- coding: utf-8 -*-
from odoo import _, fields, models

from .prometeo_payment_notice import (
    PARAM_KEY,
    PARAM_POS_MODE,
    PARAM_TOKEN,
    PARAM_URL,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    prometeo_notice_api_url = fields.Char(
        string="URL de la API de cobranzas",
        config_parameter=PARAM_URL,
        help="Base de la API, sin barra final. Ej: https://cobranzas.prometeolab.com.ar",
    )
    prometeo_notice_instance_key = fields.Char(
        string="Clave de instalación",
        config_parameter=PARAM_KEY,
        help="Identificador de esta instalación en la base de cobranzas.",
    )
    prometeo_notice_token = fields.Char(
        string="Token",
        config_parameter=PARAM_TOKEN,
        help="Token entregado al dar de alta esta instalación.",
    )
    prometeo_notice_pos_mode = fields.Selection(
        selection=[
            ("oculto", "No mostrar en el POS"),
            ("franja", "Franja fija arriba"),
            ("popup", "Aviso al abrir la sesión"),
        ],
        string="Aviso en el POS",
        default="oculto",
        config_parameter=PARAM_POS_MODE,
        help="Dónde mostrar el aviso dentro del Punto de Venta.",
    )

    def action_test_payment_notice(self):
        """Guarda la configuración y consulta la API mostrando el resultado."""
        self.ensure_one()
        self.execute()
        data = self.env["prometeo.payment.notice"].fetch_status()
        if not data:
            mensaje = _("No se pudo consultar la API. Revisá la URL, la clave y el token.")
            tipo = "warning"
        elif data.get("mostrar_aviso"):
            mensaje = _("Conexión OK. Hay un aviso activo: %s", data.get("mensaje", ""))
            tipo = "warning"
        else:
            mensaje = _("Conexión OK. El pago del período figura registrado.")
            tipo = "success"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Aviso de pago"),
                "message": mensaje,
                "type": tipo,
                "sticky": False,
            },
        }
```

- [ ] **Step 6: Escribir la vista de configuración**

Crear `prometeo_payment_notice/views/res_config_settings_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="res_config_settings_view_form_inherit_prometeo_payment_notice" model="ir.ui.view">
        <field name="name">res.config.settings.form.inherit.prometeo.payment.notice</field>
        <field name="model">res.config.settings</field>
        <field name="inherit_id" ref="base.res_config_settings_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//form" position="inside">
                <app data-string="Aviso de pago" string="Aviso de pago" name="prometeo_payment_notice">
                    <block title="Conexión con cobranzas" name="prometeo_notice_connection">
                        <setting string="URL de la API" help="Base de la API de cobranzas, sin barra final.">
                            <field name="prometeo_notice_api_url" placeholder="https://cobranzas.prometeolab.com.ar"/>
                        </setting>
                        <setting string="Clave de instalación" help="Identificador de esta instalación.">
                            <field name="prometeo_notice_instance_key"/>
                        </setting>
                        <setting string="Token" help="Token entregado al dar de alta esta instalación.">
                            <field name="prometeo_notice_token" password="True"/>
                        </setting>
                        <setting string="Probar conexión" help="Consulta la API en el momento y muestra el resultado.">
                            <button name="action_test_payment_notice" type="object" string="Probar conexión" class="btn-secondary"/>
                        </setting>
                    </block>
                    <block title="Punto de Venta" name="prometeo_notice_pos">
                        <setting string="Aviso en el POS" help="Dónde mostrar el aviso dentro del Punto de Venta.">
                            <field name="prometeo_notice_pos_mode"/>
                        </setting>
                    </block>
                </app>
            </xpath>
        </field>
    </record>
</odoo>
```

- [ ] **Step 7: Validar sintaxis**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
python3 -c "import ast; ast.parse(open('prometeo_payment_notice/__manifest__.py').read()); print('manifest OK')"
python3 -c "import xml.dom.minidom as m; m.parse('prometeo_payment_notice/data/ir_cron.xml'); m.parse('prometeo_payment_notice/views/res_config_settings_views.xml'); print('XML OK')"
```

Esperado: `manifest OK` y `XML OK`.

El bloque `<app>` de Ajustes muestra el icono del módulo: hasta la Tarea 6 se va a ver sin logo, lo cual es esperable y no rompe nada.

- [ ] **Step 8: Instalar en el contenedor local**

El módulo tiene que estar visible en `/mnt/local-addons`. Confirmar el nombre de la base antes de correr (`prod` o `calidad`):

```bash
docker exec odoo-odoo-1 odoo -i prometeo_payment_notice -d calidad --stop-after-init --no-http
```

Esperado: termina sin traceback y con `Modules loaded.` en el log.

- [ ] **Step 9: Configurar y probar la conexión**

En el navegador: Ajustes → Aviso de pago. Cargar la URL de la API (si el Odoo local no llega al `.147`, usar la IP directa `http://192.168.1.147:8096`), la clave `demo-test` y su token. Apretar **Probar conexión**.

Esperado: una notificación verde ("El pago del período figura registrado") o naranja con el mensaje de aviso, según si el pago del mes está cargado en la base. Una nueva fila en `consultas`:

```bash
docker exec cobranzas-db psql -U cobranzas -d cobranzas -c "SELECT ts, ip FROM consultas ORDER BY ts DESC LIMIT 1;"
```

- [ ] **Step 10: Verificar el comportamiento fail-safe**

```bash
docker stop cobranzas-api
```

Volver a apretar **Probar conexión**.

Esperado: notificación naranja de "No se pudo consultar la API", **sin traceback en el log de Odoo**, y el parámetro `prometeo_payment_notice.state` conserva el valor anterior (Ajustes → Técnico → Parámetros del sistema). Después: `docker start cobranzas-api`.

- [ ] **Step 11: Commit**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
git add prometeo_payment_notice
git commit -m "feat(payment-notice): modelo, configuracion y cron de consulta de estado"
```

---

### Task 4: Cartel en el cliente web

**Files:**
- Create: `prometeo_payment_notice/models/ir_http.py`
- Create: `prometeo_payment_notice/static/src/js/payment_notice_banner.js`
- Create: `prometeo_payment_notice/static/src/xml/payment_notice_banner.xml`
- Create: `prometeo_payment_notice/static/src/css/payment_notice_banner.css`
- Modify: `prometeo_payment_notice/models/__init__.py`
- Modify: `prometeo_payment_notice/__manifest__.py` (bloque `assets`)

**Interfaces:**
- Consumes: `prometeo.payment.notice.get_notice()` de la Tarea 3.
- Produces: clave `prometeo_payment_notice` en `session_info` con forma `{"mostrar": bool, "mensaje": str}`, leída desde JS con `session.prometeo_payment_notice`.

- [ ] **Step 1: Inyectar el aviso en la sesión**

Crear `prometeo_payment_notice/models/ir_http.py`:

```python
# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """Agrega el aviso de pago cacheado a la información de sesión.

        Es el mismo mecanismo con el que Odoo entrega la fecha de expiración
        de la base: el cliente web lo lee sin ningún RPC extra.
        """
        result = super().session_info()
        try:
            result["prometeo_payment_notice"] = self.env["prometeo.payment.notice"].get_notice()
        except Exception as e:
            _logger.warning("Aviso de pago: no se pudo agregar a la sesión (%s)", e)
            result["prometeo_payment_notice"] = {"mostrar": False, "mensaje": ""}
        return result
```

Agregar la línea a `prometeo_payment_notice/models/__init__.py`:

```python
from . import ir_http
```

- [ ] **Step 2: Escribir el componente OWL**

Crear `prometeo_payment_notice/static/src/js/payment_notice_banner.js`:

```javascript
/** @odoo-module **/

import { Component } from "@odoo/owl";
import { session } from "@web/session";
import { WebClient } from "@web/webclient/webclient";

export class PaymentNoticeBanner extends Component {
    static template = "prometeo_payment_notice.Banner";
    static props = {};

    setup() {
        this.notice = session.prometeo_payment_notice || { mostrar: false, mensaje: "" };
    }
}

WebClient.components = { ...WebClient.components, PaymentNoticeBanner };
```

- [ ] **Step 3: Escribir la plantilla QWeb**

Crear `prometeo_payment_notice/static/src/xml/payment_notice_banner.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

    <t t-name="prometeo_payment_notice.Banner">
        <div t-if="notice.mostrar" class="o_prometeo_payment_notice">
            <i class="fa fa-info-circle me-2"/>
            <span t-esc="notice.mensaje"/>
        </div>
    </t>

    <t t-name="prometeo_payment_notice.WebClientBanner" t-inherit="web.WebClient" t-inherit-mode="extension">
        <xpath expr="//ActionContainer" position="before">
            <PaymentNoticeBanner/>
        </xpath>
    </t>

</templates>
```

El banner se inserta entre la barra de navegación y el contenido: queda pegado al header, como el cartel de base neutralizada.

Nota sobre el spec: éste hereda la plantilla `web.WebClient` en lugar de registrar el componente en `main_components`. `MainComponentsContainer` renderiza fuera del flujo del documento (es para diálogos y notificaciones flotantes), así que una franja registrada ahí quedaría superpuesta al contenido en vez de empujarlo. La herencia de plantilla lo deja en el flujo, que es el comportamiento buscado.

- [ ] **Step 4: Escribir el estilo**

Crear `prometeo_payment_notice/static/src/css/payment_notice_banner.css`:

```css
.o_prometeo_payment_notice {
    background-color: #fff3cd;
    color: #664d03;
    border-bottom: 1px solid #ffe69c;
    padding: 6px 12px;
    font-size: 13px;
    text-align: center;
    flex: 0 0 auto;
}
```

- [ ] **Step 5: Declarar los assets**

En `prometeo_payment_notice/__manifest__.py`, agregar después de la clave `data`:

```python
    "assets": {
        "web.assets_backend": [
            "prometeo_payment_notice/static/src/css/payment_notice_banner.css",
            "prometeo_payment_notice/static/src/js/payment_notice_banner.js",
            "prometeo_payment_notice/static/src/xml/payment_notice_banner.xml",
        ],
    },
```

- [ ] **Step 6: Actualizar el módulo**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
docker exec odoo-odoo-1 odoo -u prometeo_payment_notice -d calidad --stop-after-init --no-http
```

Esperado: sin traceback.

- [ ] **Step 7: Verificar el cartel con aviso activo**

Forzar el estado de mora en la base de cobranzas y refrescar la caché:

```bash
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "DELETE FROM pagos WHERE cliente_id=(SELECT id FROM clientes WHERE instance_key='demo-test');"
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "UPDATE clientes SET dia_vencimiento=1, dias_gracia=0 WHERE instance_key='demo-test';"
```

En Odoo: Ajustes → Aviso de pago → **Probar conexión**, y recargar el navegador (F5, para que se regenere `session_info`).

Esperado: franja ámbar con el mensaje, arriba de todo, debajo de la barra de navegación, visible en cualquier pantalla del backend.

- [ ] **Step 8: Verificar que desaparece al registrar el pago**

```bash
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "SELECT registrar_pago('demo-test', CURRENT_DATE, 50000, 'transferencia');"
```

**Probar conexión** otra vez y recargar el navegador.

Esperado: la franja desaparece. Restaurar los valores de prueba:

```bash
docker exec cobranzas-db psql -U cobranzas -d cobranzas \
  -c "UPDATE clientes SET dia_vencimiento=5, dias_gracia=5 WHERE instance_key='demo-test';"
```

- [ ] **Step 9: Commit**

```bash
git add prometeo_payment_notice
git commit -m "feat(payment-notice): franja de aviso en el cliente web"
```

---

### Task 5: Aviso en el POS

**Files:**
- Create: `prometeo_payment_notice/models/pos_session.py`
- Create: `prometeo_payment_notice/static/src/js/pos_payment_notice.js`
- Create: `prometeo_payment_notice/static/src/xml/pos_payment_notice.xml`
- Modify: `prometeo_payment_notice/models/__init__.py`
- Modify: `prometeo_payment_notice/__manifest__.py` (bundle `point_of_sale._assets_pos`)

**Interfaces:**
- Consumes: `get_notice()` y `get_pos_mode()` de la Tarea 3.
- Produces: claves `prometeo_notice_show` (bool), `prometeo_notice_message` (str) y `prometeo_notice_mode` (str) en el registro de `pos.session`, leídas en JS como `this.pos.session.prometeo_notice_show`.

- [ ] **Step 1: Inyectar el aviso en los datos de la sesión POS**

Crear `prometeo_payment_notice/models/pos_session.py`:

```python
# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _load_pos_data(self, data):
        """Agrega el aviso de pago a los datos de la sesión del POS.

        Se inyectan claves sueltas en el registro de pos.session, igual que
        hace el core con _has_cash_move_perm: llegan al frontend sin tocar
        _load_pos_data_fields de pos.config.
        """
        result = super()._load_pos_data(data)
        notice = self.env["prometeo.payment.notice"].get_notice()
        mode = self.env["prometeo.payment.notice"].get_pos_mode()
        result["data"][0]["prometeo_notice_show"] = bool(notice["mostrar"]) and mode != "oculto"
        result["data"][0]["prometeo_notice_message"] = notice["mensaje"]
        result["data"][0]["prometeo_notice_mode"] = mode
        return result
```

Agregar la línea a `prometeo_payment_notice/models/__init__.py`:

```python
from . import pos_session
```

- [ ] **Step 2: Escribir el JS del POS**

Crear `prometeo_payment_notice/static/src/js/pos_payment_notice.js`:

```javascript
/** @odoo-module **/

import { Component } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Chrome } from "@point_of_sale/app/pos_app";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";

export class PosPaymentNoticeBanner extends Component {
    static template = "prometeo_payment_notice.PosBanner";
    static props = {};

    setup() {
        this.pos = usePos();
    }

    get visible() {
        const session = this.pos.session || {};
        return session.prometeo_notice_show && session.prometeo_notice_mode === "franja";
    }

    get message() {
        return (this.pos.session || {}).prometeo_notice_message || "";
    }
}

Chrome.components = { ...Chrome.components, PosPaymentNoticeBanner };

patch(PosStore.prototype, {
    /**
     * Muestra el aviso de pago una sola vez al abrir la sesión, cuando el
     * modo configurado es "popup".
     */
    async afterProcessServerData() {
        const result = await super.afterProcessServerData(...arguments);
        const session = this.session || {};
        if (session.prometeo_notice_show && session.prometeo_notice_mode === "popup") {
            this.dialog.add(AlertDialog, {
                title: _t("Aviso de pago"),
                body: session.prometeo_notice_message,
                confirmLabel: _t("Entendido"),
            });
        }
        return result;
    },
});
```

- [ ] **Step 3: Escribir la plantilla del POS**

Crear `prometeo_payment_notice/static/src/xml/pos_payment_notice.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

    <t t-name="prometeo_payment_notice.PosBanner">
        <div t-if="visible" class="o_prometeo_payment_notice">
            <i class="fa fa-info-circle me-2"/>
            <span t-esc="message"/>
        </div>
    </t>

    <t t-name="prometeo_payment_notice.PosChrome" t-inherit="point_of_sale.Chrome" t-inherit-mode="extension">
        <xpath expr="//Navbar" position="after">
            <PosPaymentNoticeBanner/>
        </xpath>
    </t>

</templates>
```

Reusa la clase CSS `o_prometeo_payment_notice`, que hay que sumar también al bundle del POS.

- [ ] **Step 4: Declarar los assets del POS**

En `prometeo_payment_notice/__manifest__.py`, dentro de `assets`, agregar el bundle:

```python
        "point_of_sale._assets_pos": [
            "prometeo_payment_notice/static/src/css/payment_notice_banner.css",
            "prometeo_payment_notice/static/src/js/pos_payment_notice.js",
            "prometeo_payment_notice/static/src/xml/pos_payment_notice.xml",
        ],
```

- [ ] **Step 5: Actualizar el módulo**

```bash
docker exec odoo-odoo-1 odoo -u prometeo_payment_notice -d calidad --stop-after-init --no-http
```

Esperado: sin traceback.

- [ ] **Step 6: Verificar el modo franja**

Dejar el estado en mora (como en la Tarea 4, Step 7), poner **Aviso en el POS = Franja fija arriba** en Ajustes, apretar **Probar conexión**, y abrir el POS.

Esperado: franja ámbar bajo la barra del POS, presente en pantalla de productos y de pago, sin desplazar ni tapar botones.

- [ ] **Step 7: Verificar el modo popup**

Cambiar a **Aviso al abrir la sesión**, cerrar el POS, volver a abrirlo.

Esperado: un diálogo con el mensaje y el botón "Entendido"; al cerrarlo no vuelve a aparecer durante esa sesión, y no queda ninguna franja.

- [ ] **Step 8: Verificar el modo oculto**

Cambiar a **No mostrar en el POS**, cerrar y reabrir el POS.

Esperado: ni franja ni popup en el POS, pero la franja del backend sigue visible.

- [ ] **Step 9: Verificar que no interfiere con el cobro**

Con el modo franja activo, hacer una venta completa: agregar producto, cobrar en efectivo, validar y cerrar la caja.

Esperado: el flujo completo funciona sin errores en la consola del navegador.

- [ ] **Step 10: Commit**

```bash
git add prometeo_payment_notice
git commit -m "feat(payment-notice): aviso configurable en el POS (franja y popup)"
```

---

### Task 6: Icono, documentación y catálogo

**Files:**
- Create: `prometeo_payment_notice/static/description/icon.png`
- Create: `prometeo_payment_notice/README.md`
- Modify: `README.md` (catálogo de módulos del repo)

**Interfaces:**
- Consumes: el módulo terminado de las Tareas 3–5.
- Produces: nada que otra tarea consuma.

- [ ] **Step 1: Generar el SVG del icono**

Copiar la plantilla Cyber-Glassmorphic del skill a un archivo temporal y cambiar el glifo por `$`:

```bash
cp /home/alexis/.claude/skills/odoo-prometeo-modules/assets/cyber-glass-icon.svg /tmp/payment_notice_icon.svg
```

Editar el `<text>` de la plantilla para que el glifo sea `$`, manteniendo los acentos cian `#22e6ff` y magenta `#ff3df0`.

- [ ] **Step 2: Renderizar el PNG**

```bash
cd /home/alexis/Documents/Github/prometeo-odoo-modules
google-chrome-stable --headless --disable-gpu --no-sandbox \
  --default-background-color=00000000 --window-size=512,512 \
  --screenshot="prometeo_payment_notice/static/description/icon.png" \
  "file:///tmp/payment_notice_icon.svg"
```

No usar ImageMagick: su renderer descarta el `<text>` y los gradientes radiales.

- [ ] **Step 3: Verificar el PNG**

```bash
file prometeo_payment_notice/static/description/icon.png
```

Esperado: `PNG image data, 512 x 512`. Abrirlo y confirmar que el glifo `$` y el resplandor están presentes.

- [ ] **Step 4: Escribir el README del módulo**

Crear `prometeo_payment_notice/README.md` con: qué hace, cómo se configura (URL, clave, token, modo POS), cómo se verifica con "Probar conexión", el comportamiento fail-safe, dónde vive la contraparte (`services/cobranzas/` en el repo `prometeo_local_server`) y cómo dar de alta una instalación nueva.

- [ ] **Step 5: Agregar el módulo al catálogo del repo**

En `README.md` (raíz del repo), agregar la fila de `prometeo_payment_notice` en la sección de **Métricas, Dashboards & Monitoreo** (es donde vive `prometeo_sentry_monitoring`), y actualizar el conteo de módulos del índice y del título de la sección del catálogo.

- [ ] **Step 6: Commit**

```bash
git add prometeo_payment_notice README.md
git commit -m "docs(payment-notice): icono, README del modulo y entrada en el catalogo"
```

---

## Verificación final

Con las seis tareas completas, correr de punta a punta:

1. `docker compose up -d` en `prometeo_local_server`: `cobranzas-db` y `cobranzas-api` levantan sanos (`docker compose ps` los muestra `healthy`).
2. `curl -s https://cobranzas.prometeolab.com.ar/health` desde afuera de la LAN devuelve `{"status":"ok"}` (requiere el CNAME creado y el túnel reinstalado).
3. En el Odoo de prueba: borrar el pago del mes, forzar `dia_vencimiento=1, dias_gracia=0`, correr el cron a mano (Ajustes → Técnico → Acciones planificadas → "Prometeo: verificar estado de pago del servicio" → Ejecutar manualmente), recargar → aparece la franja.
4. Registrar el pago con `registrar_pago`, ejecutar el cron a mano, recargar → la franja desaparece.
5. `docker stop cobranzas-api`, ejecutar el cron a mano → el log de Odoo muestra el warning, no hay traceback y el estado cacheado no cambia.
6. Dejar los datos de prueba consistentes: `dia_vencimiento=5`, `dias_gracia=5` y el pago del mes registrado para `demo-test`.
