# UI de administración de cobranzas — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Administrar clientes, pagos y comprobantes del servicio de cobranzas desde una interfaz web con login, servida por el mismo contenedor y el mismo hostname que la API.

**Architecture:** Se extiende la app FastAPI existente. `/v1/status` y `/health` quedan como están —los consumen los Odoo de los clientes— y todo lo demás pasa a vivir detrás de una sesión por cookie. El código se separa por responsabilidad: `db.py` las consultas, `status.py` la API de máquina, `auth.py` la sesión, `ui.py` las pantallas, `main.py` solo arma la app.

**Tech Stack:** FastAPI, Jinja2, psycopg2, Postgres 15, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-18-cobranzas-ui-design.md`

## Global Constraints

- Repo: `/home/alexis/Documents/Github/prometeo_local_server`, rama `master`, commits directos.
- Servicio: `services/cobranzas/`. El código de la app vive en `services/cobranzas/api/`, que el Dockerfile copia entero a `/app`.
- **`/v1/status` y `/health` no cambian de contrato ni quedan detrás del login.** Su respuesta tiene exactamente estas claves: `al_dia` (bool), `mostrar_aviso` (bool), `periodo` (str `YYYY-MM-DD`), `vencio_el` (str), `dias_atraso` (int), `meses_adeudados` (int), `mensaje` (str). `401` con credenciales inválidas o faltantes, `503` si la base no responde.
- Un solo usuario. Credenciales en `.env` **en texto plano** (repo privado, convención ya establecida), comparadas con `secrets.compare_digest`.
- Cookie de sesión: `httponly`, `secure`, `samesite=lax`, vencimiento **12 horas**.
- Comprobantes: se guardan en Postgres. Tipos permitidos `image/*` y `application/pdf`; tamaño máximo **5 MB**. Se valida **antes** de escribir y un archivo rechazado no registra el pago a medias.
- snake_case en todo. Docstring en toda función. Textos de UI en español rioplatense. `_logger`, nunca `print`.
- Los scripts de `sql/` solo corren con el volumen vacío: todo cambio de esquema va también como migración idempotente en `services/cobranzas/migrations/`.
- Sin suite de tests: cada tarea se verifica con comandos concretos y salida esperada.
- El entorno de desarrollo local tiene `cobranzas-db` y `cobranzas-api` corriendo, con un cliente de prueba `demo-test`. `docker` corre sin `sudo`.

---

### Task 1: Separar el código en módulos, sin cambiar comportamiento

**Files:**
- Create: `services/cobranzas/api/db.py`
- Create: `services/cobranzas/api/status.py`
- Modify: `services/cobranzas/api/main.py` (queda solo con el armado de la app)

**Interfaces:**
- Consumes: `logic.calcular_estado(cliente, tiene_pago, hoy, meses_adeudados)` y `logic.periodo_de(hoy)`, ya existentes y sin cambios.
- Produces: `db.conectar()` → conexión psycopg2; `db.ip_de(request)` → str; `db.cursor_dict(conn)` → cursor con `RealDictCursor`; `status.router` → `APIRouter` con `/health` y `/v1/status`. Las tareas siguientes usan `db.conectar()` y `db.cursor_dict()` para todas sus consultas.

- [ ] **Step 1: Crear `db.py` con la conexión y los helpers**

```python
"""Acceso a la base de cobranzas."""

import logging
import os

import psycopg2
import psycopg2.extras

_logger = logging.getLogger("cobranzas")


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


def cursor_dict(conn):
    """Devuelve un cursor que entrega las filas como diccionarios."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def ip_de(request):
    """Devuelve la IP de origen, respetando la cabecera de Cloudflare."""
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else ""
    )
```

- [ ] **Step 2: Crear `status.py` con la API de máquina**

Es el mismo código que hoy vive en `main.py`, movido tal cual salvo por usar los helpers de `db.py`. No cambiar ni una consulta ni un mensaje.

```python
"""API de estado de pago para las instalaciones de Odoo de Prometeo."""

import logging
from datetime import date

from fastapi import APIRouter, Header, HTTPException, Request

from db import conectar, cursor_dict, ip_de
from logic import calcular_estado, periodo_de

_logger = logging.getLogger("cobranzas")

router = APIRouter()


@router.get("/health")
def health():
    """Health check del contenedor."""
    return {"status": "ok"}


@router.get("/v1/status")
def status(
    request: Request,
    x_instance_key: str = Header(default=""),
    x_token: str = Header(default=""),
):
    """Devuelve el estado de pago del período en curso para una instalación."""
    if not x_instance_key or not x_token:
        raise HTTPException(status_code=401, detail="Credenciales faltantes")

    hoy = date.today()
    periodo = periodo_de(hoy)

    conn = None
    try:
        conn = conectar()
        with conn:
            with cursor_dict(conn) as cur:
                cur.execute(
                    """
                    SELECT id, nombre, dia_vencimiento, dias_gracia,
                           mensaje_custom, activo,
                           COALESCE(cobra_desde, date_trunc('month', creado)::date)
                               AS cobra_desde
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
                       AND periodo = %s
                    """,
                    (cliente["id"], periodo),
                )
                tiene_pago = cur.fetchone() is not None

                # Meses sin pago desde que el cliente empezó a facturar, para
                # distinguir una deuda de un mes de una acumulada.
                cur.execute(
                    """
                    SELECT count(*) AS meses
                      FROM generate_series(%s::date, %s::date, '1 month') AS m(periodo)
                     WHERE NOT EXISTS (
                           SELECT 1 FROM pagos p
                            WHERE p.cliente_id = %s
                              AND p.periodo = m.periodo::date
                           )
                    """,
                    (cliente["cobra_desde"], periodo, cliente["id"]),
                )
                meses_adeudados = cur.fetchone()["meses"]

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

    return calcular_estado(dict(cliente), tiene_pago, hoy, meses_adeudados)
```

- [ ] **Step 3: Reescribir `main.py`**

```python
"""Servicio de cobranzas de Prometeo: API de estado y UI de administración."""

import logging

from fastapi import FastAPI

import status

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Cobranzas Prometeo", docs_url=None, redoc_url=None)
app.include_router(status.router)
```

- [ ] **Step 4: Levantar y verificar que el contrato no cambió**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker compose up -d --build cobranzas-api
sleep 8
curl -s http://localhost:8096/health
TOKEN=$(docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas -tA \
  -c "SELECT token FROM clientes WHERE instance_key='demo-test';")
curl -s -H "X-Instance-Key: demo-test" -H "X-Token: $TOKEN" http://localhost:8096/v1/status
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Instance-Key: demo-test" -H "X-Token: nope" \
  http://localhost:8096/v1/status
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8096/v1/status
```

Esperado: `{"status":"ok"}`; un JSON con las siete claves del contrato; `401` con token inválido; `401` sin cabeceras.

- [ ] **Step 5: Commit**

```bash
git add services/cobranzas/api
git commit -m "refactor(cobranzas): separar db y status de main"
```

---

### Task 2: Login y sesión

**Files:**
- Create: `services/cobranzas/api/auth.py`
- Create: `services/cobranzas/api/templates/base.html`
- Create: `services/cobranzas/api/templates/login.html`
- Create: `services/cobranzas/api/static/estilo.css`
- Modify: `services/cobranzas/api/main.py`
- Modify: `services/cobranzas/api/requirements.txt`
- Modify: `services/cobranzas/.env` y `services/cobranzas/.env.example`

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces: `auth.router` (`GET/POST /login`, `POST /logout`); `auth.requerir_sesion(request)`, dependencia que redirige a `/login` si no hay sesión; `auth.plantillas`, instancia de `Jinja2Templates` que reusan las tareas siguientes. La plantilla `base.html` define los bloques `titulo` y `contenido` que heredan todas las demás pantallas.

- [ ] **Step 1: Agregar las dependencias**

En `services/cobranzas/api/requirements.txt`, dejar el archivo así:

```
fastapi==0.115.6
uvicorn==0.34.0
psycopg2-binary==2.9.10
jinja2==3.1.5
python-multipart==0.0.20
itsdangerous==2.2.0
```

- [ ] **Step 2: Agregar las variables de entorno**

Al final de `services/cobranzas/.env`:

```bash
COBRANZAS_UI_USER=alexis
COBRANZAS_UI_PASSWORD=cambiar-esto
COBRANZAS_SESSION_SECRET=cambiar-esto-por-algo-aleatorio
```

Al final de `services/cobranzas/.env.example`, las mismas tres vacías:

```bash
COBRANZAS_UI_USER=
COBRANZAS_UI_PASSWORD=
COBRANZAS_SESSION_SECRET=
```

- [ ] **Step 3: Escribir `auth.py`**

```python
"""Sesión y control de acceso de la UI de administración."""

import logging
import os
import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

_logger = logging.getLogger("cobranzas")

plantillas = Jinja2Templates(directory="templates")

router = APIRouter()


def credenciales_validas(usuario, password):
    """Compara las credenciales recibidas con las configuradas.

    Usa compare_digest para que el tiempo de respuesta no delate cuántos
    caracteres coincidieron.
    """
    usuario_ok = secrets.compare_digest(usuario, os.getenv("COBRANZAS_UI_USER", ""))
    password_ok = secrets.compare_digest(password, os.getenv("COBRANZAS_UI_PASSWORD", ""))
    return usuario_ok and password_ok


def requerir_sesion(request: Request):
    """Dependencia de guardia: corta con una redirección si no hay sesión.

    Se aplica al router entero de la UI, no ruta por ruta, para que una
    pantalla nueva quede protegida por construcción.
    """
    if not request.session.get("usuario"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


@router.get("/login")
def login_form(request: Request):
    """Muestra el formulario de acceso."""
    return plantillas.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, usuario: str = Form(...), password: str = Form(...)):
    """Valida las credenciales y abre la sesión."""
    if not credenciales_validas(usuario, password):
        _logger.warning("Intento de acceso fallido para el usuario %s", usuario)
        return plantillas.TemplateResponse(
            request, "login.html", {"error": "Usuario o contraseña incorrectos"}, status_code=401
        )
    request.session["usuario"] = usuario
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    """Cierra la sesión."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
```

- [ ] **Step 4: Escribir la plantilla base**

`services/cobranzas/api/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>{% block titulo %}Cobranzas{% endblock %}</title>
    <link rel="stylesheet" href="/static/estilo.css"/>
</head>
<body>
    <header class="barra">
        <a class="marca" href="/">Cobranzas Prometeo</a>
        {% if request.session.get("usuario") %}
        <form method="post" action="/logout">
            <button class="secundario" type="submit">Salir</button>
        </form>
        {% endif %}
    </header>
    <main>
        {% block contenido %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 5: Escribir la plantilla de login**

`services/cobranzas/api/templates/login.html`:

```html
{% extends "base.html" %}
{% block titulo %}Acceso — Cobranzas{% endblock %}
{% block contenido %}
<form class="tarjeta angosta" method="post" action="/login">
    <h1>Acceso</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <label>Usuario
        <input name="usuario" autocomplete="username" autofocus required/>
    </label>
    <label>Contraseña
        <input name="password" type="password" autocomplete="current-password" required/>
    </label>
    <button type="submit">Entrar</button>
</form>
{% endblock %}
```

- [ ] **Step 6: Escribir la hoja de estilos**

`services/cobranzas/api/static/estilo.css`:

```css
:root {
    --fondo: #f6f7f9;
    --texto: #1f2933;
    --borde: #d9dee5;
    --acento: #2f6f4e;
    --alerta-fondo: #fff3cd;
    --alerta-texto: #664d03;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    background: var(--fondo);
    color: var(--texto);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}

.barra {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    background: #fff;
    border-bottom: 1px solid var(--borde);
}

.marca { font-weight: 600; text-decoration: none; color: var(--texto); }

main { max-width: 1000px; margin: 24px auto; padding: 0 16px; }

.tarjeta {
    background: #fff;
    border: 1px solid var(--borde);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 20px;
}

.angosta { max-width: 360px; margin: 60px auto; }

h1 { font-size: 20px; margin-top: 0; }

label { display: block; margin-bottom: 14px; font-size: 13px; color: #52606d; }

input, select, textarea {
    display: block;
    width: 100%;
    margin-top: 4px;
    padding: 8px 10px;
    border: 1px solid var(--borde);
    border-radius: 6px;
    font: inherit;
    color: var(--texto);
    background: #fff;
}

button {
    padding: 8px 16px;
    border: 0;
    border-radius: 6px;
    background: var(--acento);
    color: #fff;
    font: inherit;
    cursor: pointer;
}

button.secundario { background: #52606d; }

table { width: 100%; border-collapse: collapse; }

th, td { padding: 10px 8px; text-align: left; border-bottom: 1px solid var(--borde); }

th { font-size: 12px; text-transform: uppercase; color: #52606d; }

.error {
    background: #fde8e8;
    color: #8a1c1c;
    padding: 8px 10px;
    border-radius: 6px;
}

.ok { background: #e6f4ea; color: #1e4620; padding: 8px 10px; border-radius: 6px; }

.deuda { background: var(--alerta-fondo); color: var(--alerta-texto); padding: 2px 8px; border-radius: 999px; }

.acciones a { margin-right: 10px; color: var(--acento); }
```

- [ ] **Step 7: Montar la sesión y los estáticos en `main.py`**

```python
"""Servicio de cobranzas de Prometeo: API de estado y UI de administración."""

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import auth
import status

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Cobranzas Prometeo", docs_url=None, redoc_url=None)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("COBRANZAS_SESSION_SECRET", ""),
    max_age=12 * 60 * 60,
    https_only=True,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(status.router)
app.include_router(auth.router)
```

- [ ] **Step 8: Verificar el login**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker compose up -d --build cobranzas-api
sleep 8
curl -s -o /dev/null -w "login GET: %{http_code}\n" http://localhost:8096/login
curl -s -o /dev/null -w "password mala: %{http_code}\n" \
  -d "usuario=alexis&password=incorrecta" http://localhost:8096/login
curl -s -o /dev/null -w "password buena: %{http_code}\n" -c /tmp/cookies.txt \
  -d "usuario=alexis&password=cambiar-esto" http://localhost:8096/login
grep -c cobranzas /tmp/cookies.txt || true
curl -s -o /dev/null -w "status sigue publico: %{http_code}\n" http://localhost:8096/health
```

Esperado: `200` en el GET; `401` con la contraseña mala; `303` con la buena y una cookie de sesión guardada en `/tmp/cookies.txt`; `200` en `/health`, que no depende de la sesión.

`https_only=True` hace que la cookie solo viaje por HTTPS. En las pruebas locales por `http://localhost` el navegador no la guardaría, pero `curl -c` sí la registra, así que la verificación es válida; la prueba real por HTTPS llega en la Tarea 6.

- [ ] **Step 9: Commit**

```bash
git add services/cobranzas
git commit -m "feat(cobranzas): login y sesion de la UI de administracion"
```

---

### Task 3: Panel de clientes

**Files:**
- Create: `services/cobranzas/api/ui.py`
- Create: `services/cobranzas/api/templates/panel.html`
- Modify: `services/cobranzas/api/db.py` (agregar `listar_clientes`)
- Modify: `services/cobranzas/api/main.py` (montar el router de UI)

**Interfaces:**
- Consumes: `db.conectar()`, `db.cursor_dict()`, `auth.requerir_sesion`, `auth.plantillas`, `base.html`.
- Produces: `db.listar_clientes()` → lista de dicts con `nombre`, `instance_key`, `activo`, `monto_cuota`, `pago_registrado`, `fecha_pago`, `monto`, `meses_adeudados`, `ultima_consulta`; `ui.router`, un `APIRouter` con la guardia de sesión aplicada al router entero. Las Tareas 4 y 5 agregan sus rutas a ese mismo router.

- [ ] **Step 1: Agregar la consulta a `db.py`**

Al final del archivo:

```python
def listar_clientes():
    """Devuelve el estado actual de todos los clientes, ordenado por nombre."""
    conn = None
    try:
        conn = conectar()
        with conn:
            with cursor_dict(conn) as cur:
                cur.execute("SELECT * FROM estado_actual")
                return [dict(fila) for fila in cur.fetchall()]
    finally:
        if conn is not None:
            conn.close()
```

La vista `estado_actual` ya ordena por nombre y ya expone las nueve columnas.

- [ ] **Step 2: Escribir `ui.py`**

```python
"""Pantallas de administración de cobranzas."""

import logging

from fastapi import APIRouter, Depends, Request

from auth import plantillas, requerir_sesion
from db import listar_clientes

_logger = logging.getLogger("cobranzas")

router = APIRouter(dependencies=[Depends(requerir_sesion)])


@router.get("/")
def panel(request: Request):
    """Muestra el estado de todos los clientes."""
    return plantillas.TemplateResponse(
        request, "panel.html", {"clientes": listar_clientes()}
    )
```

- [ ] **Step 3: Escribir la plantilla del panel**

`services/cobranzas/api/templates/panel.html`:

```html
{% extends "base.html" %}
{% block titulo %}Clientes — Cobranzas{% endblock %}
{% block contenido %}
<div class="tarjeta">
    <h1>Clientes</h1>
    <p class="acciones">
        <a href="/clientes/nuevo">Nuevo cliente</a>
        <a href="/pagos/nuevo">Registrar pago</a>
    </p>
    <table>
        <tr>
            <th>Cliente</th>
            <th>Estado</th>
            <th>Cuota</th>
            <th>Último pago</th>
            <th>Última consulta</th>
            <th></th>
        </tr>
        {% for c in clientes %}
        <tr>
            <td>
                {{ c.nombre }}<br/>
                <small>{{ c.instance_key }}</small>
                {% if not c.activo %}<br/><small>inactivo</small>{% endif %}
            </td>
            <td>
                {% if c.pago_registrado %}
                    Al día
                {% elif c.meses_adeudados > 1 %}
                    <span class="deuda">Debe {{ c.meses_adeudados }} meses</span>
                {% else %}
                    <span class="deuda">Debe el mes</span>
                {% endif %}
            </td>
            <td>{{ "%.2f"|format(c.monto_cuota) if c.monto_cuota else "—" }}</td>
            <td>{{ c.fecha_pago or "—" }}</td>
            <td>{{ c.ultima_consulta.strftime("%d/%m/%Y %H:%M") if c.ultima_consulta else "nunca" }}</td>
            <td class="acciones">
                <a href="/pagos/nuevo?cliente={{ c.instance_key }}">Pago</a>
                <a href="/clientes/{{ c.instance_key }}">Editar</a>
            </td>
        </tr>
        {% else %}
        <tr><td colspan="6">Todavía no hay clientes cargados.</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
```

La columna "Última consulta" es la que delata una instalación que dejó de reportar.

- [ ] **Step 4: Montar el router en `main.py`**

Agregar `import ui` junto a los otros imports y, después de `app.include_router(auth.router)`:

```python
app.include_router(ui.router)
```

- [ ] **Step 5: Verificar el panel y la guardia**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker compose up -d --build cobranzas-api
sleep 8
curl -s -o /dev/null -w "sin sesion: %{http_code}\n" http://localhost:8096/
curl -s -o /dev/null -w "redirige a: %{redirect_url}\n" http://localhost:8096/
curl -s -c /tmp/cookies.txt -o /dev/null \
  -d "usuario=alexis&password=cambiar-esto" http://localhost:8096/login
curl -s -b /tmp/cookies.txt http://localhost:8096/ | grep -c "demo-test"
```

Esperado: `303` sin sesión, redirigiendo a `/login`; con sesión, el HTML del panel contiene `demo-test`, o sea que la tabla se renderizó con datos reales.

- [ ] **Step 6: Commit**

```bash
git add services/cobranzas/api
git commit -m "feat(cobranzas): panel de clientes"
```

---

### Task 4: Alta y edición de clientes

**Files:**
- Create: `services/cobranzas/api/templates/cliente_nuevo.html`
- Create: `services/cobranzas/api/templates/cliente_editar.html`
- Modify: `services/cobranzas/api/db.py` (agregar `crear_cliente`, `traer_cliente`, `actualizar_cliente`)
- Modify: `services/cobranzas/api/ui.py` (agregar las cuatro rutas)

**Interfaces:**
- Consumes: `db.conectar()`, `db.cursor_dict()`, `ui.router`, `auth.plantillas`.
- Produces: `db.crear_cliente(nombre, instance_key, monto_cuota)` → str con el token generado; `db.traer_cliente(instance_key)` → dict o `None`; `db.actualizar_cliente(instance_key, campos)` → `None`, donde `campos` es un dict con las claves `monto_cuota`, `dia_vencimiento`, `dias_gracia`, `cobra_desde`, `mensaje_custom`, `activo`.

- [ ] **Step 1: Agregar las consultas a `db.py`**

Al final del archivo:

```python
def crear_cliente(nombre, instance_key, monto_cuota):
    """Da de alta un cliente y devuelve el token generado."""
    conn = None
    try:
        conn = conectar()
        with conn:
            with cursor_dict(conn) as cur:
                cur.execute(
                    "SELECT alta_cliente(%s, %s, %s) AS token",
                    (nombre, instance_key, monto_cuota),
                )
                return cur.fetchone()["token"]
    finally:
        if conn is not None:
            conn.close()


def traer_cliente(instance_key):
    """Devuelve un cliente por su clave de instancia, o None si no existe."""
    conn = None
    try:
        conn = conectar()
        with conn:
            with cursor_dict(conn) as cur:
                cur.execute(
                    "SELECT * FROM clientes WHERE instance_key = %s", (instance_key,)
                )
                fila = cur.fetchone()
                return dict(fila) if fila else None
    finally:
        if conn is not None:
            conn.close()


def actualizar_cliente(instance_key, campos):
    """Actualiza los datos editables de un cliente."""
    conn = None
    try:
        conn = conectar()
        with conn:
            with cursor_dict(conn) as cur:
                cur.execute(
                    """
                    UPDATE clientes
                       SET nombre = %(nombre)s,
                           monto_cuota = %(monto_cuota)s,
                           dia_vencimiento = %(dia_vencimiento)s,
                           dias_gracia = %(dias_gracia)s,
                           cobra_desde = %(cobra_desde)s,
                           mensaje_custom = %(mensaje_custom)s,
                           activo = %(activo)s
                     WHERE instance_key = %(instance_key)s
                    """,
                    dict(campos, instance_key=instance_key),
                )
    finally:
        if conn is not None:
            conn.close()
```

- [ ] **Step 2: Agregar las rutas de alta a `ui.py`**

Ampliar los imports:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from db import (
    actualizar_cliente,
    crear_cliente,
    listar_clientes,
    traer_cliente,
)
```

Y agregar:

```python
@router.get("/clientes/nuevo")
def cliente_nuevo_form(request: Request):
    """Muestra el formulario de alta de cliente."""
    return plantillas.TemplateResponse(
        request, "cliente_nuevo.html", {"error": None, "token": None, "datos": {}}
    )


@router.post("/clientes/nuevo")
def cliente_nuevo(
    request: Request,
    nombre: str = Form(...),
    instance_key: str = Form(...),
    monto_cuota: str = Form(""),
):
    """Da de alta el cliente y muestra el token generado."""
    datos = {"nombre": nombre, "instance_key": instance_key, "monto_cuota": monto_cuota}
    try:
        cuota = float(monto_cuota) if monto_cuota.strip() else None
    except ValueError:
        return plantillas.TemplateResponse(
            request,
            "cliente_nuevo.html",
            {"error": "La cuota tiene que ser un número.", "token": None, "datos": datos},
            status_code=400,
        )

    if traer_cliente(instance_key):
        return plantillas.TemplateResponse(
            request,
            "cliente_nuevo.html",
            {
                "error": "Ya existe un cliente con esa clave de instancia.",
                "token": None,
                "datos": datos,
            },
            status_code=400,
        )

    try:
        token = crear_cliente(nombre, instance_key, cuota)
    except Exception as e:
        _logger.error("No se pudo dar de alta el cliente %s: %s", instance_key, e)
        return plantillas.TemplateResponse(
            request,
            "cliente_nuevo.html",
            {"error": "No se pudo dar de alta el cliente.", "token": None, "datos": datos},
            status_code=500,
        )

    return plantillas.TemplateResponse(
        request,
        "cliente_nuevo.html",
        {"error": None, "token": token, "datos": datos},
    )
```

- [ ] **Step 3: Agregar las rutas de edición a `ui.py`**

```python
@router.get("/clientes/{instance_key}")
def cliente_editar_form(request: Request, instance_key: str):
    """Muestra el formulario de edición de un cliente."""
    cliente = traer_cliente(instance_key)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente inexistente")
    return plantillas.TemplateResponse(
        request, "cliente_editar.html", {"cliente": cliente, "guardado": False, "error": None}
    )


@router.post("/clientes/{instance_key}")
def cliente_editar(
    request: Request,
    instance_key: str,
    nombre: str = Form(...),
    monto_cuota: str = Form(""),
    dia_vencimiento: int = Form(...),
    dias_gracia: int = Form(...),
    cobra_desde: str = Form(""),
    mensaje_custom: str = Form(""),
    activo: str = Form(""),
):
    """Guarda los cambios de un cliente."""
    cliente = traer_cliente(instance_key)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente inexistente")

    try:
        campos = {
            "nombre": nombre,
            "monto_cuota": float(monto_cuota) if monto_cuota.strip() else None,
            "dia_vencimiento": dia_vencimiento,
            "dias_gracia": dias_gracia,
            "cobra_desde": cobra_desde or None,
            "mensaje_custom": mensaje_custom or None,
            "activo": bool(activo),
        }
    except ValueError:
        return plantillas.TemplateResponse(
            request,
            "cliente_editar.html",
            {"cliente": cliente, "guardado": False, "error": "La cuota tiene que ser un número."},
            status_code=400,
        )

    actualizar_cliente(instance_key, campos)
    return plantillas.TemplateResponse(
        request,
        "cliente_editar.html",
        {"cliente": traer_cliente(instance_key), "guardado": True, "error": None},
    )
```

- [ ] **Step 4: Escribir la plantilla de alta**

`services/cobranzas/api/templates/cliente_nuevo.html`:

```html
{% extends "base.html" %}
{% block titulo %}Nuevo cliente — Cobranzas{% endblock %}
{% block contenido %}
<div class="tarjeta angosta">
    <h1>Nuevo cliente</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    {% if token %}
        <p class="ok">Cliente creado. Cargá estos datos en su Odoo:</p>
        <p><small>Clave de instancia</small><br/><code>{{ datos.instance_key }}</code></p>
        <p><small>Token</small><br/><code>{{ token }}</code></p>
        <p class="acciones"><a href="/">Volver al panel</a></p>
    {% else %}
        <form method="post" action="/clientes/nuevo">
            <label>Nombre
                <input name="nombre" value="{{ datos.nombre or '' }}" required/>
            </label>
            <label>Clave de instancia
                <input name="instance_key" value="{{ datos.instance_key or '' }}" required/>
            </label>
            <label>Cuota mensual
                <input name="monto_cuota" value="{{ datos.monto_cuota or '' }}" inputmode="decimal"/>
            </label>
            <button type="submit">Crear</button>
        </form>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Escribir la plantilla de edición**

`services/cobranzas/api/templates/cliente_editar.html`:

```html
{% extends "base.html" %}
{% block titulo %}{{ cliente.nombre }} — Cobranzas{% endblock %}
{% block contenido %}
<div class="tarjeta angosta">
    <h1>{{ cliente.nombre }}</h1>
    {% if guardado %}<p class="ok">Cambios guardados.</p>{% endif %}
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p>
        <small>Clave de instancia</small><br/><code>{{ cliente.instance_key }}</code><br/>
        <small>Token</small><br/><code>{{ cliente.token }}</code>
    </p>
    <form method="post" action="/clientes/{{ cliente.instance_key }}">
        <label>Nombre
            <input name="nombre" value="{{ cliente.nombre }}" required/>
        </label>
        <label>Cuota mensual
            <input name="monto_cuota" value="{{ cliente.monto_cuota or '' }}" inputmode="decimal"/>
        </label>
        <label>Día de vencimiento
            <input name="dia_vencimiento" type="number" min="1" max="28"
                   value="{{ cliente.dia_vencimiento }}" required/>
        </label>
        <label>Días de gracia
            <input name="dias_gracia" type="number" min="0" max="60"
                   value="{{ cliente.dias_gracia }}" required/>
        </label>
        <label>Cobra desde
            <input name="cobra_desde" type="date" value="{{ cliente.cobra_desde or '' }}"/>
        </label>
        <label>Mensaje personalizado
            <textarea name="mensaje_custom" rows="3">{{ cliente.mensaje_custom or '' }}</textarea>
        </label>
        <label>
            <input name="activo" type="checkbox" value="1" {% if cliente.activo %}checked{% endif %}/>
            Activo
        </label>
        <button type="submit">Guardar</button>
    </form>
    <p class="acciones"><a href="/">Volver al panel</a></p>
</div>
{% endblock %}
```

El campo "Cobra desde" es el que evita que un cliente con historia previa al sistema aparezca debiendo todos los meses desde su alta.

- [ ] **Step 6: Verificar alta y edición**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker compose up -d --build cobranzas-api
sleep 8
curl -s -c /tmp/cookies.txt -o /dev/null \
  -d "usuario=alexis&password=cambiar-esto" http://localhost:8096/login
echo "--- alta ---"
curl -s -b /tmp/cookies.txt -d "nombre=Cliente UI&instance_key=cliente-ui&monto_cuota=45000" \
  http://localhost:8096/clientes/nuevo | grep -A1 "Token"
echo "--- clave duplicada ---"
curl -s -b /tmp/cookies.txt -o /dev/null -w "%{http_code}\n" \
  -d "nombre=Otro&instance_key=cliente-ui&monto_cuota=1" http://localhost:8096/clientes/nuevo
echo "--- edicion ---"
curl -s -b /tmp/cookies.txt -o /dev/null \
  -d "nombre=Cliente UI&monto_cuota=52000&dia_vencimiento=5&dias_gracia=5&cobra_desde=&mensaje_custom=&activo=1" \
  http://localhost:8096/clientes/cliente-ui
docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas \
  -c "SELECT nombre, monto_cuota, activo FROM clientes WHERE instance_key='cliente-ui';"
```

Esperado: el alta devuelve un token de 48 caracteres hexadecimales; la clave duplicada da `400`; después de la edición la base muestra `monto_cuota = 52000.00` y `activo = t`.

- [ ] **Step 7: Commit**

```bash
git add services/cobranzas/api
git commit -m "feat(cobranzas): alta y edicion de clientes"
```

---

### Task 5: Registrar pago con comprobante

**Files:**
- Create: `services/cobranzas/migrations/2026-08-18-comprobantes.sql`
- Create: `services/cobranzas/api/templates/pago_nuevo.html`
- Modify: `services/cobranzas/sql/01_schema.sql`
- Modify: `services/cobranzas/api/db.py` (agregar `registrar_pago`, `traer_comprobante`)
- Modify: `services/cobranzas/api/ui.py` (agregar las rutas de pago y de descarga)

**Interfaces:**
- Consumes: `db.conectar()`, `db.cursor_dict()`, `db.listar_clientes()`, `db.traer_cliente()`, `ui.router`, `auth.plantillas`.
- Produces: `db.registrar_pago(instance_key, periodo, monto, medio, nota, comprobante)` → `None`, donde `comprobante` es `None` o una tupla `(nombre, tipo, datos_bytes)`; `db.traer_comprobante(pago_id)` → dict con `comprobante_nombre`, `comprobante_tipo`, `comprobante_datos`, o `None`.

- [ ] **Step 1: Escribir la migración**

`services/cobranzas/migrations/2026-08-18-comprobantes.sql`:

```sql
-- Guarda el comprobante del pago dentro de la propia fila de pagos.
--
-- pagos ya tiene un registro único por (cliente_id, periodo), así que no hace
-- falta una tabla aparte.
--
-- Aplicar en bases ya inicializadas:
--   docker exec -i cobranzas-db psql -U cobranzas -d cobranzas \
--     < services/cobranzas/migrations/2026-08-18-comprobantes.sql
--
-- Es idempotente.

ALTER TABLE pagos ADD COLUMN IF NOT EXISTS comprobante_nombre TEXT;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS comprobante_tipo   TEXT;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS comprobante_datos  BYTEA;
```

- [ ] **Step 2: Actualizar el esquema base**

En `services/cobranzas/sql/01_schema.sql`, dentro de `CREATE TABLE pagos`, después de la línea de `nota`:

```sql
    comprobante_nombre TEXT,
    comprobante_tipo   TEXT,
    comprobante_datos  BYTEA,
```

- [ ] **Step 3: Aplicar la migración**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker exec -i cobranzas-db psql -U cobranzas -d cobranzas \
  < services/cobranzas/migrations/2026-08-18-comprobantes.sql
docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas -c "\d pagos" | grep comprobante
```

Esperado: las tres columnas listadas.

- [ ] **Step 4: Agregar las consultas a `db.py`**

Al final del archivo:

```python
def registrar_pago(instance_key, periodo, monto, medio, nota, comprobante):
    """Registra el pago de un período, con su comprobante opcional.

    comprobante es None, o una tupla (nombre, tipo, datos en bytes).
    Reusa la función registrar_pago de la base, que normaliza el período al
    día 1 del mes y hace upsert sobre (cliente_id, periodo).
    """
    conn = None
    try:
        conn = conectar()
        with conn:
            with cursor_dict(conn) as cur:
                cur.execute(
                    "SELECT registrar_pago(%s, %s, %s, %s) AS id",
                    (instance_key, periodo, monto, medio),
                )
                pago_id = cur.fetchone()["id"]

                nombre, tipo, datos = comprobante if comprobante else (None, None, None)
                cur.execute(
                    """
                    UPDATE pagos
                       SET nota = %s,
                           comprobante_nombre = COALESCE(%s, comprobante_nombre),
                           comprobante_tipo   = COALESCE(%s, comprobante_tipo),
                           comprobante_datos  = COALESCE(%s, comprobante_datos)
                     WHERE id = %s
                    """,
                    (nota, nombre, tipo, psycopg2.Binary(datos) if datos else None, pago_id),
                )
    finally:
        if conn is not None:
            conn.close()


def traer_comprobante(pago_id):
    """Devuelve el comprobante de un pago, o None si no tiene."""
    conn = None
    try:
        conn = conectar()
        with conn:
            with cursor_dict(conn) as cur:
                cur.execute(
                    """
                    SELECT comprobante_nombre, comprobante_tipo, comprobante_datos
                      FROM pagos
                     WHERE id = %s AND comprobante_datos IS NOT NULL
                    """,
                    (pago_id,),
                )
                fila = cur.fetchone()
                return dict(fila) if fila else None
    finally:
        if conn is not None:
            conn.close()
```

`COALESCE` deja que un pago ya cargado conserve su comprobante si se vuelve a registrar sin adjuntar uno nuevo.

- [ ] **Step 5: Agregar las rutas de pago a `ui.py`**

Ampliar los imports:

```python
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from db import (
    actualizar_cliente,
    crear_cliente,
    listar_clientes,
    registrar_pago,
    traer_cliente,
    traer_comprobante,
)

PREFIJO_IMAGEN = "image/"
TIPO_PDF = "application/pdf"
TAMANO_MAXIMO = 5 * 1024 * 1024
```

Y agregar las rutas:

```python
def validar_comprobante(archivo, contenido):
    """Devuelve un mensaje de error si el comprobante no es aceptable."""
    if len(contenido) > TAMANO_MAXIMO:
        return "El comprobante supera los 5 MB."
    tipo = archivo.content_type or ""
    if not tipo.startswith(PREFIJO_IMAGEN) and tipo != TIPO_PDF:
        return "El comprobante tiene que ser una imagen o un PDF."
    return None


@router.get("/pagos/nuevo")
def pago_nuevo_form(request: Request, cliente: str = ""):
    """Muestra el formulario para registrar un pago."""
    clientes = listar_clientes()
    elegido = traer_cliente(cliente) if cliente else None
    return plantillas.TemplateResponse(
        request,
        "pago_nuevo.html",
        {
            "clientes": clientes,
            "elegido": cliente,
            "monto_sugerido": elegido["monto_cuota"] if elegido else "",
            "periodo_actual": date.today().replace(day=1).isoformat(),
            "error": None,
        },
    )


@router.post("/pagos/nuevo")
async def pago_nuevo(
    request: Request,
    instance_key: str = Form(...),
    periodo: str = Form(...),
    monto: str = Form(""),
    medio: str = Form(""),
    nota: str = Form(""),
    comprobante: UploadFile = File(None),
):
    """Registra el pago y guarda el comprobante si vino uno."""
    def volver(error, codigo):
        """Rearma el formulario con el error a la vista."""
        return plantillas.TemplateResponse(
            request,
            "pago_nuevo.html",
            {
                "clientes": listar_clientes(),
                "elegido": instance_key,
                "monto_sugerido": monto,
                "periodo_actual": periodo,
                "error": error,
            },
            status_code=codigo,
        )

    if not traer_cliente(instance_key):
        return volver("Ese cliente no existe.", 400)

    try:
        importe = float(monto) if monto.strip() else None
    except ValueError:
        return volver("El monto tiene que ser un número.", 400)

    adjunto = None
    if comprobante is not None and comprobante.filename:
        contenido = await comprobante.read()
        error = validar_comprobante(comprobante, contenido)
        if error:
            return volver(error, 400)
        adjunto = (comprobante.filename, comprobante.content_type, contenido)

    try:
        registrar_pago(instance_key, periodo, importe, medio or None, nota or None, adjunto)
    except Exception as e:
        _logger.error("No se pudo registrar el pago de %s: %s", instance_key, e)
        return volver("No se pudo registrar el pago.", 500)

    return RedirectResponse("/", status_code=303)


@router.get("/comprobantes/{pago_id}")
def comprobante_descarga(pago_id: int):
    """Devuelve el comprobante de un pago para descargarlo."""
    comprobante = traer_comprobante(pago_id)
    if not comprobante:
        raise HTTPException(status_code=404, detail="Sin comprobante")
    return Response(
        content=bytes(comprobante["comprobante_datos"]),
        media_type=comprobante["comprobante_tipo"] or "application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="%s"' % comprobante["comprobante_nombre"]
        },
    )
```

La validación corre **antes** de tocar la base: un archivo rechazado no deja el pago registrado a medias.

- [ ] **Step 6: Importar psycopg2 en `db.py`**

`db.py` ya importa `psycopg2`, así que `psycopg2.Binary` está disponible sin cambios adicionales. Verificarlo con:

```bash
grep -n "^import psycopg2" services/cobranzas/api/db.py
```

Esperado: la línea existe.

- [ ] **Step 7: Escribir la plantilla del pago**

`services/cobranzas/api/templates/pago_nuevo.html`:

```html
{% extends "base.html" %}
{% block titulo %}Registrar pago — Cobranzas{% endblock %}
{% block contenido %}
<div class="tarjeta angosta">
    <h1>Registrar pago</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <form method="post" action="/pagos/nuevo" enctype="multipart/form-data">
        <label>Cliente
            <select name="instance_key" required>
                <option value="">Elegí un cliente</option>
                {% for c in clientes %}
                <option value="{{ c.instance_key }}" {% if c.instance_key == elegido %}selected{% endif %}>
                    {{ c.nombre }}
                </option>
                {% endfor %}
            </select>
        </label>
        <label>Período
            <input name="periodo" type="date" value="{{ periodo_actual }}" required/>
        </label>
        <label>Monto
            <input name="monto" value="{{ monto_sugerido or '' }}" inputmode="decimal"/>
        </label>
        <label>Medio
            <input name="medio" placeholder="transferencia, efectivo…"/>
        </label>
        <label>Nota
            <textarea name="nota" rows="2"></textarea>
        </label>
        <label>Comprobante (opcional)
            <input name="comprobante" type="file" accept="image/*,application/pdf"/>
        </label>
        <button type="submit">Registrar</button>
    </form>
    <p class="acciones"><a href="/">Volver al panel</a></p>
</div>
{% endblock %}
```

El período viene con el mes en curso y el monto con la cuota del cliente cuando se llega desde el botón del panel.

- [ ] **Step 8: Verificar el registro y la descarga**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker compose up -d --build cobranzas-api
sleep 8
curl -s -c /tmp/cookies.txt -o /dev/null \
  -d "usuario=alexis&password=cambiar-esto" http://localhost:8096/login

echo "hola comprobante" > /tmp/comprobante.txt
printf '%%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>' > /tmp/comprobante.pdf

echo "--- tipo no permitido ---"
curl -s -b /tmp/cookies.txt -o /dev/null -w "%{http_code}\n" \
  -F "instance_key=cliente-ui" -F "periodo=2026-08-01" -F "monto=45000" \
  -F "comprobante=@/tmp/comprobante.txt;type=text/plain" http://localhost:8096/pagos/nuevo

echo "--- pago con PDF ---"
curl -s -b /tmp/cookies.txt -o /dev/null -w "%{http_code}\n" \
  -F "instance_key=cliente-ui" -F "periodo=2026-08-01" -F "monto=45000" -F "medio=transferencia" \
  -F "comprobante=@/tmp/comprobante.pdf;type=application/pdf" http://localhost:8096/pagos/nuevo

PAGO=$(docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas -tA \
  -c "SELECT id FROM pagos WHERE cliente_id=(SELECT id FROM clientes WHERE instance_key='cliente-ui');")
echo "--- descarga ---"
curl -s -b /tmp/cookies.txt "http://localhost:8096/comprobantes/$PAGO" -o /tmp/bajado.pdf
diff /tmp/comprobante.pdf /tmp/bajado.pdf && echo "el archivo bajó idéntico"
```

Esperado: `400` con el `.txt`; `303` con el PDF; el `diff` sin diferencias.

- [ ] **Step 9: Verificar que el archivo rechazado no dejó pago a medias**

```bash
docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas \
  -c "SELECT count(*) FROM pagos WHERE cliente_id=(SELECT id FROM clientes WHERE instance_key='cliente-ui');"
```

Esperado: `1`, el del PDF. El intento rechazado no creó ninguna fila.

- [ ] **Step 10: Commit**

```bash
git add services/cobranzas
git commit -m "feat(cobranzas): registrar pagos con comprobante opcional"
```

---

### Task 6: Enlace al comprobante, documentación y prueba de punta a punta

**Files:**
- Modify: `services/cobranzas/api/db.py` (`listar_clientes` devuelve también el id del pago)
- Modify: `services/cobranzas/api/templates/panel.html` (enlace al comprobante)
- Modify: `services/cobranzas/sql/02_funciones.sql` (la vista expone el id del pago)
- Create: `services/cobranzas/migrations/2026-08-18-vista-pago-id.sql`
- Modify: `services/cobranzas/README.md`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: nada que otra tarea consuma.

- [ ] **Step 1: Exponer el id del pago en la vista**

En `services/cobranzas/sql/02_funciones.sql`, dentro del `SELECT` de `estado_actual`, agregar la columna justo después de `c.monto_cuota`:

```sql
       p.id AS pago_id,
```

El Step 2 trae la definición completa de la vista ya con esa columna: los dos archivos tienen que terminar iguales.

- [ ] **Step 2: Escribir la migración de la vista**

`services/cobranzas/migrations/2026-08-18-vista-pago-id.sql`:

```sql
-- Agrega el id del pago del mes a la vista estado_actual, para poder enlazar
-- el comprobante desde el panel.
--
-- Aplicar en bases ya inicializadas:
--   docker exec -i cobranzas-db psql -U cobranzas -d cobranzas \
--     < services/cobranzas/migrations/2026-08-18-vista-pago-id.sql
--
-- Reaplicar sql/02_funciones.sql tiene exactamente el mismo efecto.

DROP VIEW IF EXISTS estado_actual;
CREATE VIEW estado_actual AS
SELECT c.nombre,
       c.instance_key,
       c.activo,
       c.monto_cuota,
       p.id AS pago_id,
       (p.id IS NOT NULL) AS pago_registrado,
       p.fecha_pago,
       p.monto,
       (SELECT count(*)
          FROM generate_series(
                   COALESCE(c.cobra_desde, date_trunc('month', c.creado)::date),
                   date_trunc('month', CURRENT_DATE)::date,
                   '1 month') AS m(periodo)
         WHERE NOT EXISTS (SELECT 1 FROM pagos pp
                            WHERE pp.cliente_id = c.id
                              AND pp.periodo = m.periodo::date)
       ) AS meses_adeudados,
       (SELECT max(ts) FROM consultas q WHERE q.cliente_id = c.id) AS ultima_consulta
FROM clientes c
LEFT JOIN pagos p
       ON p.cliente_id = c.id
      AND p.periodo = date_trunc('month', CURRENT_DATE)::date
ORDER BY c.nombre;
```

En `sql/02_funciones.sql` el bloque de la vista tiene que quedar idéntico a éste, para que una instalación nueva y una migrada terminen con la misma definición.

- [ ] **Step 3: Aplicar y verificar**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker exec -i cobranzas-db psql -U cobranzas -d cobranzas \
  < services/cobranzas/migrations/2026-08-18-vista-pago-id.sql
docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas -c "SELECT nombre, pago_id FROM estado_actual;"
```

Esperado: la columna `pago_id` con valor para el cliente que tiene pago del mes.

- [ ] **Step 4: Enlazar el comprobante en el panel**

En `services/cobranzas/api/templates/panel.html`, reemplazar la celda del último pago por:

```html
            <td>
                {{ c.fecha_pago or "—" }}
                {% if c.pago_id %}
                <br/><a href="/comprobantes/{{ c.pago_id }}">Comprobante</a>
                {% endif %}
            </td>
```

El enlace aparece siempre que haya pago; si ese pago no tiene comprobante cargado, la descarga devuelve `404`, que es el comportamiento correcto y no rompe la pantalla.

- [ ] **Step 5: Documentar la UI en el README**

En `services/cobranzas/README.md`, agregar una sección al principio, después de la descripción del servicio, que explique: que la UI vive en `https://registropagos.prometeolab.com.ar/` detrás de un login; que el usuario y la contraseña salen de `COBRANZAS_UI_USER` y `COBRANZAS_UI_PASSWORD` del `.env`, y el secreto de la cookie de `COBRANZAS_SESSION_SECRET`; qué hace cada pantalla; y que el SQL a mano sigue siendo válido para lo que la UI no cubre. Aclarar además que los comprobantes se guardan en la base, aceptan imágenes y PDF, y tienen un máximo de 5 MB.

- [ ] **Step 6: Prueba de punta a punta**

```bash
cd /home/alexis/Documents/Github/prometeo_local_server
docker compose up -d --build cobranzas-api
sleep 8
echo "--- sin sesion, todo redirige ---"
for r in / /clientes/nuevo /pagos/nuevo; do
  curl -s -o /dev/null -w "$r: %{http_code}\n" "http://localhost:8096$r"
done
echo "--- la API de maquina sigue publica ---"
curl -s -o /dev/null -w "/health: %{http_code}\n" http://localhost:8096/health
TOKEN=$(docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas -tA \
  -c "SELECT token FROM clientes WHERE instance_key='demo-test';")
curl -s -H "X-Instance-Key: demo-test" -H "X-Token: $TOKEN" http://localhost:8096/v1/status
```

Esperado: `303` en las tres rutas de UI; `200` en `/health`; el JSON de `/v1/status` con sus siete claves, igual que antes de toda esta tarea.

- [ ] **Step 7: Limpiar el cliente de prueba**

```bash
docker exec -e PGPASSWORD=$(grep COBRANZAS_DB_PASSWORD services/cobranzas/.env | cut -d= -f2-) \
  cobranzas-db psql -U cobranzas -d cobranzas \
  -c "DELETE FROM clientes WHERE instance_key='cliente-ui';"
```

El borrado en cascada se lleva sus pagos y comprobantes.

- [ ] **Step 8: Commit**

```bash
git add services/cobranzas
git commit -m "feat(cobranzas): enlace al comprobante en el panel y documentacion de la UI"
```

---

## Verificación final

Con las seis tareas completas:

1. `docker compose up -d --build cobranzas-api` levanta sano y `/health` responde `ok`.
2. Sin sesión, toda ruta de UI da `303` hacia `/login`; con credenciales incorrectas el login da `401`.
3. Con sesión: el panel lista los clientes con su estado, se da de alta un cliente y aparece su token, se edita su cuota, se registra un pago con comprobante y el archivo baja íntegro.
4. Un archivo de tipo no permitido y uno de más de 5 MB se rechazan sin registrar el pago.
5. `/v1/status` devuelve las siete claves del contrato para los cuatro casos de siempre: al día, en mora, dentro del período de gracia y credenciales inválidas.
6. Queda pendiente para Alexis, que es quien tiene `sudo` en el `.147`: desplegar con `git pull` y probar el login por HTTPS en `https://registropagos.prometeolab.com.ar/`, donde la cookie `secure` sí viaja.
