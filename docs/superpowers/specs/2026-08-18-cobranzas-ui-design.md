# Diseño: UI de administración de cobranzas

**Fecha:** 2026-08-18
**Estado:** Aprobado, pendiente de plan de implementación
**Repo involucrado:** `prometeo_local_server` (rama `master`), servicio `services/cobranzas/`
**Antecedente:** `2026-08-18-prometeo-payment-notice-design.md`

---

## 1. Problema

El servicio de cobranzas ya decide y publica el estado de pago de cada cliente, pero
operarlo es por SQL: dar de alta un cliente, registrar un pago o cambiar una cuota exige
entrar al servidor y tipear consultas. Falta además guardar los comprobantes de pago, que
hoy no tienen dónde vivir.

Se busca una interfaz web, en el mismo dominio que la API, para administrar clientes y
pagos sin tocar la base a mano, con carga opcional de comprobantes.

## 2. Contexto y restricciones

- El servicio corre en el server local `192.168.1.147` y se publica por Cloudflare Tunnel
  en `https://registropagos.prometeolab.com.ar`.
- La API `GET /v1/status` la consumen los Odoo de los clientes: **no puede quedar detrás
  del login** ni cambiar su contrato.
- La UI queda expuesta a internet y **escribe** datos, así que necesita autenticación
  propia. El precedente del repo (`gastos-dashboard`) no tiene ninguna, pero es de solo
  lectura; acá no alcanza.
- Un solo usuario: Alexis. No hay tabla de usuarios ni recuperación de contraseña.
- El `.env` de este repo **está versionado a propósito**, así que ningún secreto puede ir
  en texto plano.
- Estructura de código del repo: `config`/`modules` por responsabilidad, un archivo por
  concern, `snake_case`, docstring en cada función.
- Sin suite de tests automatizados: la verificación es manual y documentada.

## 3. Decisión de arquitectura: extender el servicio existente

La UI se agrega a la app FastAPI que ya sirve la API, en el mismo contenedor y bajo el
mismo hostname. `/` y sus rutas son la interfaz humana con sesión; `/v1/status` sigue
siendo la interfaz de máquina con token.

Alternativas descartadas:

- **Servicio Flask aparte**, al estilo `gastos-dashboard`: separa UI de API, pero duplica
  Dockerfile, conexión a la base y ciclo de deploy, y obliga a routing por path en el
  túnel para servir todo bajo el mismo hostname.
- **Hostname aparte**: otro CNAME y otra pieza que mantener, y contradice el requisito
  explícito de usar el mismo dominio.

El costo de la decisión —un servicio que hace dos cosas— se paga separando el código por
responsabilidad, no dejando todo en `main.py`.

## 4. Datos

### 4.1 Comprobantes

`pagos` ya tiene un registro único por cliente y período (`UNIQUE (cliente_id, periodo)`),
así que el comprobante va en esa misma fila y no necesita tabla propia:

```sql
ALTER TABLE pagos
    ADD COLUMN IF NOT EXISTS comprobante_nombre TEXT,
    ADD COLUMN IF NOT EXISTS comprobante_tipo   TEXT,
    ADD COLUMN IF NOT EXISTS comprobante_datos  BYTEA;
```

Se guarda dentro de Postgres por decisión explícita. Para que la base no se convierta en
un depósito, el servidor valida **antes de escribir**:

- Tipo permitido: `image/*` o `application/pdf`. Cualquier otro se rechaza.
- Tamaño máximo: **5 MB**. Más grande se rechaza.

En ambos casos el formulario vuelve con el error explicado y el pago **no** se registra a
medias. Con un comprobante por cliente por mes, el crecimiento es despreciable.

La migración va en `services/cobranzas/migrations/`, idempotente, igual que las anteriores:
los scripts de `sql/` solo corren con el volumen vacío. El esquema base
(`sql/01_schema.sql`) se actualiza en paralelo para instalaciones nuevas.

### 4.2 Credenciales

Sin tabla de usuarios. Tres variables de entorno nuevas en `.env` y `.env.example`:

| Variable | Contenido |
|---|---|
| `COBRANZAS_UI_USER` | Nombre de usuario |
| `COBRANZAS_UI_PASSWORD_HASH` | Hash `scrypt` de la contraseña |
| `COBRANZAS_SESSION_SECRET` | Cadena aleatoria que firma la cookie de sesión |

La contraseña nunca se guarda en texto plano, porque el `.env` se versiona. El hash se
genera con un helper del propio servicio (`python -m hash_password`), que usa
`hashlib.scrypt` de la biblioteca estándar — sin dependencias de criptografía nuevas. La
verificación compara con `secrets.compare_digest`.

`.env.example` deja las tres vacías, para que olvidarse de configurarlas sea ruidoso.

## 5. Sesión y separación de accesos

La sesión es una cookie firmada por `SessionMiddleware` de Starlette, con `httponly`,
`secure`, `samesite=lax` y vencimiento a las **12 horas**. `POST /logout` la borra.

La guardia es una **dependencia de FastAPI aplicada al router entero** de la UI, no un
chequeo repetido en cada ruta: una ruta nueva queda protegida por construcción y no por
memoria del programador. Sin sesión, cualquier ruta de UI redirige a `/login`.

`/v1/status` y `/health` quedan fuera de ese router y no cambian: siguen autenticando por
`X-Instance-Key` + `X-Token` y por nada más.

## 6. Pantallas

| Ruta | Qué hace |
|---|---|
| `GET/POST /login` | Formulario de acceso |
| `GET /` | Panel de clientes |
| `GET/POST /clientes/nuevo` | Alta; al guardar muestra el token generado |
| `GET/POST /clientes/<instance_key>` | Edición del cliente |
| `GET/POST /pagos/nuevo` | Registrar pago con comprobante opcional |
| `GET /comprobantes/<pago_id>` | Descarga del comprobante |
| `POST /logout` | Cierra sesión |

**Panel.** Pantalla principal, una fila por cliente con: nombre, estado (al día, o
"debe N meses" resaltado), cuota, último pago y **última consulta de su Odoo**. Esa última
columna es la señal de que una instalación dejó de reportar. Cada fila tiene acceso a
registrar pago y a editar. Sale de la vista `estado_actual`, que ya expone todas esas
columnas.

**Alta.** Nombre, clave de instancia y cuota mensual. Al guardar muestra el token
generado, que es el dato que hay que cargar en el Odoo del cliente.

**Edición.** Cuota, día de vencimiento, días de gracia, `cobra_desde`, mensaje
personalizado y activo. También muestra el token, para cuando hay que reconfigurar el
Odoo de un cliente ya dado de alta.

**Registrar pago.** Cliente, período, monto, medio, nota y comprobante opcional. El
período viene prellenado con el mes en curso y el monto con la cuota del cliente, de modo
que el caso normal sea abrir, elegir cliente y confirmar. Reusa la función
`registrar_pago` que ya existe.

Todo renderizado en el servidor con Jinja. Sin framework de frontend ni build step: una
hoja de estilos propia y nada más.

## 7. Estructura de archivos

```
services/cobranzas/api/
  main.py            arma la app, middleware y monta los routers
  status.py          /v1/status y /health (se mudan desde main.py)
  ui.py              rutas de pantalla
  auth.py            sesión, login y la dependencia de guardia
  db.py              conexión y consultas
  logic.py           decisión del aviso (sin cambios)
  hash_password.py   helper para generar el hash de la contraseña
  templates/         login, panel, alta, edición, pago
  static/estilo.css
```

Mover `/v1/status` a `status.py` toca código que hoy funciona, pero sin eso `main.py`
queda siendo la app, la API y media UI a la vez. La lógica se mueve sin cambios.

Dependencias nuevas: `jinja2` (plantillas), `python-multipart` (recibir archivos),
`itsdangerous` (firma de la cookie).

## 8. Verificación

Sin tests automatizados, en línea con el resto del repo.

1. Sin sesión: toda ruta de UI redirige a `/login`; `/v1/status` y `/health` responden
   igual que siempre.
2. Login con contraseña incorrecta: rechaza sin crear sesión.
3. Con sesión: alta de un cliente de prueba, verificando que el token aparece y que el
   cliente queda en la base.
4. Registrar un pago con comprobante real (una imagen y un PDF), y volver a descargarlo
   comprobando que el archivo baja íntegro.
5. Rechazo de un archivo de tipo no permitido y de uno de más de 5 MB, verificando que el
   pago no se registró a medias.
6. Edición de un cliente: cambiar la cuota y confirmar el cambio en la base.
7. Los cuatro casos de contrato de `/v1/status` (al día, en mora, en gracia, credenciales
   inválidas), para probar que el refactor no lo rompió.

## 9. Fuera de alcance

- Múltiples usuarios, roles o recuperación de contraseña.
- Edición o borrado de pagos ya registrados.
- Reportes, gráficos o exportación.
- Notificaciones al cliente desde la UI.
- Cualquier cambio al módulo Odoo o al contrato de `/v1/status`.
