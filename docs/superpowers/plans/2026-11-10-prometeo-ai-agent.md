# prometeo_ai_agent (app "Agente IA") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App "Agente IA" para Odoo 18: rutinas programadas en lenguaje natural que leen datos de Odoo y dejan alertas en una bandeja con contador en la barra superior, chat privado, tres proveedores de IA (Claude, OpenAI, Google) y control de costo mensual. Solo lectura.

**Architecture:** Tres capas sin dependencias cruzadas hacia arriba. `llm/` es Python puro: un adaptador HTTP por proveedor detrás de una única función `chat()` con mensajes y herramientas en formato normalizado. `agent/` implementa las herramientas de lectura sobre el ORM (como un usuario dado, nunca `sudo`) y el bucle que alterna modelo y herramientas con topes de llamadas y tiempo. Los modelos Odoo (`prometeo.ai.*`) guardan proveedores, rutinas, alertas, conversaciones y consumo, y son los únicos que llaman al bucle: las rutinas desde un único `ir.cron` despachador, el chat desde un método RPC síncrono.

**Tech Stack:** Odoo 18.0 (ORM, vistas XML, OWL), `requests` (ya incluido en Odoo), APIs HTTP de Anthropic Messages, OpenAI Chat Completions y Google `generateContent`.

**Spec:** `docs/superpowers/specs/2026-11-10-prometeo-ai-agent-design.md`

## Global Constraints

- Odoo 18.0; manifest `18.0.1.0.0`; `license` `LGPL-3`; `author` `Alexis Medina`; `website` `alexis.medn@gmail.com`; `application: True`.
- `depends`: `["base", "web", "mail"]`. **No** depender de `stock`, `purchase`, `account` ni `point_of_sale`.
- **Sin SDKs de proveedores** y sin tocar `requirements.txt`: todo por `requests`.
- Modelos con prefijo `prometeo.ai.`; un archivo Python por modelo; docstring en cada función y método; `llm/` y `agent/` son funciones, sin clases salvo la excepción `LlmError`.
- Textos de UI y mensajes en español; `_("texto %s", arg)` (coma, no `%`).
- **Nunca `sudo()` para leer datos de negocio.** `sudo()` solo para leer la configuración propia del módulo (proveedor, modelo, parámetros) y para escribir en `prometeo.ai.alert` y `prometeo.ai.run`.
- No existe herramienta de escritura sobre datos de negocio. Las únicas escrituras del agente son `create_alert` y `resolve_alert`.
- Valores del spec, sin cambiar: 200 registros por consulta; chat 15 llamadas y 90 s; rutina 25 llamadas y 180 s; 2 turnos de chat simultáneos; silencio de 30 días al descartar; 3 fallas pausan; 3 incompletas avisan; despachador cada 15 min con presupuesto de 10 min; costos en USD por millón de tokens.
- Configuración en Ajustes como `<app name="prometeo_ai_agent" string="Agente IA">` con un `<block>` por sección (referencia: `prometeo_payment_notice/views/res_config_settings_views.xml`).
- Ningún test llama a un proveedor real: `requests.post`/`requests.get` siempre simulados con `unittest.mock.patch`.
- **Entorno de tests.** El contenedor `odoo-odoo-1` solo ve el checkout principal (`/home/alexis/Documents/Github/prometeo-odoo-modules`, montado en `/mnt/local-addons`), que hoy está en otra rama con cambios sin commitear. Trabajar en un worktree hermano `../prometeo-odoo-modules-wt-ai` (rama `feat/prometeo-ai-agent` desde `origin/main`) y, antes de cada corrida, copiar el módulo al checkout principal como carpeta sin trackear:
  ```bash
  rsync -a --delete ../prometeo-odoo-modules-wt-ai/prometeo_ai_agent/ /home/alexis/Documents/Github/prometeo-odoo-modules/prometeo_ai_agent/
  docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf -d test -u prometeo_ai_agent --test-enable --test-tags /prometeo_ai_agent --stop-after-init --no-http --workers 0
  ```
  La primera vez `-i` en lugar de `-u`. En adelante "correr los tests" es este par de comandos; para un solo test, `--test-tags /prometeo_ai_agent:TestClase.test_metodo`. No commitear nada en el checkout principal. Si `docker` no responde, Docker Desktop está apagado: pedir a Alexis que lo levante.
- Commits en el worktree, mensajes en español estilo `feat(prometeo_ai_agent): ...`. No hacer push a `main`; el cambio entra por PR.

## Review Focus

1. **Dominio que cruza a un modelo o campo bloqueado** (`[("user_ids.password", "like", "a%")]`, `[("message_ids.body", "ilike", "x")]`) — debe rechazarse aunque el modelo de partida sea legible: si no, el agente usa el filtro como oráculo. Test en Task 4.
2. **Herramienta que falla** (campo inexistente, `AccessError`, dominio mal formado, error SQL) — vuelve al modelo como `{"error": ...}`, la corrida sigue y la transacción no queda abortada. Test en Task 4.
3. **Proveedor que responde mal** (429, 500, timeout, JSON sin `choices`/`candidates`, respuesta vacía) — `LlmError`; la rutina suma una falla y no deja alertas a medias; el chat muestra un mensaje legible y no guarda el turno. Tests en Task 2, 7 y 9.
4. **Rutina mal configurada** (usuario de "ejecutar como" archivado, sin destinatarios, sin modelo por defecto ni clave) — corrida con estado `error` y mensaje claro; el despachador sigue con las demás. Test en Task 7.
5. **`create_alert` repetido** (misma clave dos veces en una corrida, o clave silenciada) — una sola alerta abierta por rutina y clave; la silenciada no se recrea. Test en Task 6.

---

## Estructura de archivos

```
prometeo_ai_agent/
  __init__.py  __manifest__.py
  llm/        __init__.py (chat, list_models, LlmError)  anthropic_api.py  openai_api.py  google_api.py  prices.py
  agent/      __init__.py  guard.py (lista negra y validación)  tools.py  loop.py  prompts.py
  models/     prometeo_ai_provider.py  prometeo_ai_model.py  prometeo_ai_run.py  prometeo_ai_alert.py
              prometeo_ai_routine.py  prometeo_ai_routine_template.py
              prometeo_ai_conversation.py  prometeo_ai_message.py  res_config_settings.py
  security/   security.xml  ir.model.access.csv
  data/       prometeo_ai_provider_data.xml  ir_cron.xml  prometeo_ai_routine_template_data.xml  digest_template.xml
  views/      provider_views.xml  routine_views.xml  alert_views.xml  run_views.xml  res_config_settings_views.xml  menu_views.xml
  static/src/ js/alert_systray.js  js/chat_action.js  js/usage_action.js  xml/*.xml  scss/agent.scss
  static/description/icon.png
  tests/      common.py  test_llm.py  test_provider.py  test_run.py  test_tools.py  test_loop.py
              test_alert.py  test_routine.py  test_digest.py  test_chat.py
```

## Formato normalizado (contrato entre `llm/`, `agent/` y los modelos)

```python
# proveedor
{"type": "anthropic" | "openai" | "google", "api_key": str, "base_url": str}

# herramienta
{"name": str, "description": str, "parameters": {JSON Schema: solo type, properties, required, items, enum, description}}

# mensaje
{"role": "user", "content": str}
{"role": "assistant", "content": str, "tool_calls": [{"id": str, "name": str, "arguments": dict}],
 "raw": <contenido nativo del proveedor>, "raw_provider": str}
{"role": "tool", "tool_call_id": str, "name": str, "content": str}

# respuesta de chat()
{"text": str, "tool_calls": [...], "input_tokens": int, "output_tokens": int, "raw": ..., "raw_provider": str}
```

`raw` existe porque Google exige devolver intactas las partes del turno del modelo (firmas de razonamiento) y sus llamadas no siempre traen id. Cada adaptador reutiliza `raw` solo si `raw_provider` es el suyo; si no, reconstruye desde `content` y `tool_calls`.

Los parámetros `domain` de las herramientas son **string JSON**, no arrays: Google no acepta arrays de tipos mezclados en el esquema.

---

### Task 1: Esqueleto, grupos, proveedores, modelos de IA y Ajustes

**Files:**
- Create: `__init__.py`, `__manifest__.py`, `models/__init__.py`, `models/prometeo_ai_provider.py`, `models/prometeo_ai_model.py`, `models/res_config_settings.py`
- Create: `security/security.xml`, `security/ir.model.access.csv`, `data/prometeo_ai_provider_data.xml`
- Create: `views/provider_views.xml`, `views/res_config_settings_views.xml`, `views/menu_views.xml`
- Create: `static/description/icon.png` (generarlo con el pipeline del skill `odoo-prometeo-modules`)
- Test: `tests/__init__.py`, `tests/common.py`, `tests/test_provider.py`

**Interfaces:**
- Produces:
  - Grupos `prometeo_ai_agent.group_user` ("Usuario del agente") y `prometeo_ai_agent.group_admin` ("Administrador del agente", implica `group_user`; `base.user_root` y `base.user_admin` adentro). Categoría propia "Agente IA".
  - `prometeo.ai.provider`: `name`, `provider_type` (`anthropic`/`openai`/`google`), `api_key` (Char, `groups` = admin), `base_url` (se completa por `onchange` del tipo con `llm.DEFAULT_BASE_URLS`), `active`, `model_ids`. Método `_get_credentials() -> dict` (formato "proveedor", lee con `sudo()`; `UserError` si no hay clave).
  - `prometeo.ai.model`: `provider_id`, `name` (id técnico), `label`, `active` (default `False`), `price_input`, `price_output` (Float, USD por millón), `price_known` (Boolean). Único por (`provider_id`, `name`). `display_name` = `"<label> (<proveedor>)"`.
  - Parámetros en `res.config.settings` (clave `prometeo_ai_agent.<nombre>`, default): `default_model_id` (Many2one a `prometeo.ai.model`, dominio `active`), `max_records` (200), `max_result_chars` (20000), `chat_max_tool_calls` (15), `chat_max_seconds` (90), `chat_max_concurrent` (2), `routine_max_tool_calls` (25), `routine_max_seconds` (180), `monthly_cap_usd` (0.0 = sin tope), `digest_hour` (8), `dismiss_silence_days` (30).
  - `prometeo.ai.model._get_default() -> recordset` (lee el parámetro con `sudo()`; vacío si no hay).
  - Menú raíz `menu_ai_agent_root` ("Agente IA") y submenú "Configuración" (solo admin) con Proveedores y Modelos.
  - `tests/common.py`: `AiAgentCase(TransactionCase)` con `cls.admin_user`, `cls.agent_user` (solo `group_user`), `cls.provider` (tipo `openai`, clave `"sk-test"`), `cls.ai_model` (activo, precios 1.0 / 2.0, `price_known=True`) puesto como modelo por defecto, y el helper `fake_llm(*responses)` que parchea `odoo.addons.prometeo_ai_agent.llm.chat` devolviendo las respuestas normalizadas en orden.
- ACL: `provider`, `model` → solo admin (CRUD). El grupo usuario **no** tiene acceso a estos dos modelos; lo que necesite llega por métodos con `sudo()`.
- Datos (`noupdate="1"`): tres proveedores sin clave, "Claude (Anthropic)", "OpenAI", "Google Gemini".

- [ ] **Step 1: Tests que fallan** en `test_provider.py`:

```python
def test_default_base_url_per_type(self):
    p = self.env["prometeo.ai.provider"].new({"provider_type": "google"})
    p._onchange_provider_type()
    self.assertEqual(p.base_url, "https://generativelanguage.googleapis.com/v1beta")

def test_credentials_without_key_raises(self):
    self.provider.api_key = False
    with self.assertRaises(UserError):
        self.provider._get_credentials()

def test_agent_user_cannot_read_provider(self):
    with self.assertRaises(AccessError):
        self.provider.with_user(self.agent_user).read(["name"])

def test_default_model_roundtrip(self):
    self.assertEqual(self.env["prometeo.ai.model"]._get_default(), self.ai_model)
```

- [ ] **Step 2:** Correr los tests (con `-i`). Esperado: error de módulo inexistente o FAIL.
- [ ] **Step 3:** Implementar los archivos de la task. `llm/__init__.py` en esta task solo define `DEFAULT_BASE_URLS = {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com/v1", "google": "https://generativelanguage.googleapis.com/v1beta"}`.
- [ ] **Step 4:** Correr los tests. Esperado: 4 PASS.
- [ ] **Step 5:** Commit `feat(prometeo_ai_agent): esqueleto, proveedores y ajustes`.

---

### Task 2: Capa `llm/` — tres adaptadores detrás de `chat()`

**Files:**
- Modify: `llm/__init__.py`
- Create: `llm/anthropic_api.py`, `llm/openai_api.py`, `llm/google_api.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces (en `llm/__init__.py`):
  - `class LlmError(Exception)` con atributo `status` (int o `None`).
  - `chat(provider: dict, model_name: str, system: str, messages: list, tools: list, timeout: int) -> dict` — despacha por `provider["type"]`; formatos de la sección "Formato normalizado".
  - `list_models(provider: dict, timeout: int = 20) -> list[dict]` — cada ítem `{"name": str, "label": str}`.
- Cada adaptador expone `chat(...)` y `list_models(...)` con las mismas firmas.

Decisiones por adaptador (verificar los nombres de campos contra la documentación oficial vigente antes de escribir; no confiar en la memoria):

| | Anthropic | OpenAI | Google |
|---|---|---|---|
| Chat | `POST {base}/v1/messages` | `POST {base}/chat/completions` | `POST {base}/models/{model}:generateContent` |
| Auth | `x-api-key` + `anthropic-version: 2023-06-01` | `Authorization: Bearer` | `x-goog-api-key` |
| Modelos | `GET {base}/v1/models` | `GET {base}/models` | `GET {base}/models`, solo los que tienen `generateContent` en `supportedGenerationMethods`; `name` sin el prefijo `models/` |
| Sistema | campo `system` | mensaje `role: system` | `systemInstruction` |
| Tokens de salida | `usage.output_tokens` | `usage.completion_tokens` | `candidatesTokenCount` + `thoughtsTokenCount` |
| Tope de salida | `max_tokens: 4096` (obligatorio) | no enviar | no enviar |

- Un resultado de herramienta va: Anthropic, bloque `tool_result` en un mensaje `user`; OpenAI, mensaje `role: tool` con `tool_call_id`; Google, parte `functionResponse` emparejada por `name`. Varios resultados seguidos se agrupan en un solo turno donde la API lo exige.
- Si la llamada del modelo no trae id (Google), generar `f"call_{n}"`.
- `LlmError` ante: estado HTTP ≠ 200 (mensaje = estado + los primeros 300 caracteres del cuerpo, **nunca la clave**), `requests.RequestException`, JSON inválido, o respuesta sin texto ni llamadas a herramientas.

- [ ] **Step 1: Tests que fallan.** Un `TestCase` por adaptador, con `requests.post` parcheado devolviendo un cuerpo nativo de ejemplo. Por adaptador:

```python
def test_text_reply(self):
    # cuerpo nativo con texto "hola", 10 tokens de entrada y 3 de salida
    r = llm.chat(self.prov, "m", "sys", [{"role": "user", "content": "hi"}], [], 30)
    self.assertEqual((r["text"], r["tool_calls"], r["input_tokens"], r["output_tokens"]), ("hola", [], 10, 3))

def test_tool_call_reply(self):
    # cuerpo nativo que pide search_count con {"model": "res.partner", "domain": "[]"}
    r = llm.chat(self.prov, "m", "sys", [{"role": "user", "content": "hi"}], [TOOL], 30)
    self.assertEqual(r["tool_calls"][0]["name"], "search_count")
    self.assertEqual(r["tool_calls"][0]["arguments"], {"model": "res.partner", "domain": "[]"})

def test_roundtrip_sends_tool_result(self):
    # historial: user, assistant con tool_call, tool. Inspeccionar el JSON enviado:
    # el resultado aparece en la forma nativa del proveedor y referencia la llamada.

def test_http_error_raises_without_key(self):
    # status 429, cuerpo "rate limited"
    with self.assertRaises(llm.LlmError) as cm: ...
    self.assertEqual(cm.exception.status, 429)
    self.assertNotIn(self.prov["api_key"], str(cm.exception))

def test_empty_response_raises(self): ...   # 200 con choices/candidates/content vacío
def test_timeout_raises(self): ...          # requests.Timeout -> LlmError
def test_list_models(self): ...             # devuelve [{"name", "label"}]
```

Más, solo en Google: `test_output_tokens_include_thoughts`, `test_list_models_filters_non_chat`, y `test_raw_reused_only_for_same_provider` (un mensaje `assistant` con `raw_provider="openai"` se reconstruye desde `content`/`tool_calls`).

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar los tres adaptadores y el despachador.
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5:** Commit `feat(prometeo_ai_agent): capa llm con tres proveedores`.

---

### Task 3: Actualizar modelos, precios, registro de consumo y tope

**Files:**
- Create: `llm/prices.py`, `models/prometeo_ai_run.py`, `views/run_views.xml`
- Modify: `models/prometeo_ai_provider.py`, `views/provider_views.xml`, `security/ir.model.access.csv`
- Test: `tests/test_provider.py`, `tests/test_run.py`

**Interfaces:**
- Consumes: `llm.list_models`, `provider._get_credentials()`.
- Produces:
  - `llm/prices.py`: `KNOWN_PRICES: dict[tuple[str, str], tuple[float, float]]` con clave (tipo de proveedor, prefijo del id de modelo) y valor (entrada, salida) en USD por millón; `lookup_price(provider_type: str, model_name: str) -> tuple[float, float] | None` (gana el prefijo más largo).
  - `provider.action_fetch_models()`: crea los `prometeo.ai.model` que falten (inactivos), con precio y `price_known=True` si `lookup_price` encuentra; no toca los existentes; devuelve notificación "N modelos nuevos".
  - `prometeo.ai.run`: `kind` (`routine`/`chat`), `routine_id`, `user_id`, `ai_model_id`, `model_name`, `provider_type`, `input_tokens`, `output_tokens`, `cost` (Float, 6 decimales), `price_known`, `duration`, `tool_calls`, `status` (`done`/`incomplete`/`error`/`skipped_cap`), `error`.
  - `prometeo.ai.run._log(kind, ai_model, result: dict, *, routine=None, user=None, status, error=None, duration=0.0) -> record` — `result` trae `input_tokens`, `output_tokens`, `tool_calls` (int); calcula `cost` = entrada/1e6 × `price_input` + salida/1e6 × `price_output`; escribe con `sudo()`.
  - `prometeo.ai.run._month_cost(date=None) -> float` (mes calendario en la zona horaria de la empresa, default `America/Argentina/Buenos_Aires`) y `_cap_reached() -> bool` (`False` si el tope es 0).
- ACL: `run` → admin lectura; usuario sin acceso.

- [ ] **Step 1: `KNOWN_PRICES`.** Consultar las páginas oficiales de precios de Anthropic, OpenAI y Google **el día de la implementación** y cargar los modelos de chat vigentes. No escribir precios de memoria. Dejar en un comentario la fecha de consulta.
- [ ] **Step 2: Tests que fallan:**

```python
def test_fetch_creates_inactive_models_with_known_price(self):
    # list_models parcheado -> [{"name": "gpt-x-2026", "label": "GPT X"}]; KNOWN_PRICES parcheado con ("openai", "gpt-x"): (3.0, 9.0)
    self.provider.action_fetch_models()
    m = self.provider.model_ids.filtered(lambda r: r.name == "gpt-x-2026")
    self.assertEqual((m.active, m.price_input, m.price_output, m.price_known), (False, 3.0, 9.0, True))

def test_fetch_unknown_model_has_no_price(self): ...   # price_known False
def test_fetch_twice_keeps_edited_price(self): ...     # editar precio, re-fetch, sigue editado y no duplica

def test_log_computes_cost(self):
    run = self.env["prometeo.ai.run"]._log("chat", self.ai_model,
        {"input_tokens": 1_000_000, "output_tokens": 500_000, "tool_calls": 2}, user=self.agent_user, status="done")
    self.assertAlmostEqual(run.cost, 2.0)        # 1.0 + 0.5 * 2.0

def test_unpriced_model_does_not_count_for_cap(self): ...  # price_known False -> cost 0, run.price_known False
def test_cap_reached(self): ...     # tope 1.0, una corrida de 2.0 -> True; tope 0 -> False
def test_month_cost_ignores_previous_month(self): ...
```

- [ ] **Step 3:** Correr. Esperado: FAIL.
- [ ] **Step 4:** Implementar. Botón "Actualizar modelos" en el formulario del proveedor. Vistas nativas de `run`: lista (fecha, tipo, rutina, modelo, tokens, costo, estado) y búsqueda con filtro "Este mes" y agrupadores por rutina, modelo y mes.
- [ ] **Step 5:** Correr. Esperado: PASS.
- [ ] **Step 6:** Commit `feat(prometeo_ai_agent): modelos, precios y registro de consumo`.

---

### Task 4: Herramientas de lectura y lista negra

**Files:**
- Create: `agent/__init__.py`, `agent/guard.py`, `agent/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces en `agent/guard.py`:
  - `BLOCKED_MODELS = frozenset({"prometeo.ai.provider", "prometeo.ai.conversation", "prometeo.ai.message", "ir.config_parameter", "res.users.apikeys", "ir.cron", "ir.attachment", "mail.message", "ir.model.access", "ir.rule"})`
  - `USER_FIELDS = frozenset({"id", "name", "login", "company_id", "display_name"})` (únicos campos legibles de `res.users`).
  - `SECRET_FIELD_RE = re.compile(r"(password|passwd|secret|token|api_?key|private_?key|_pass$)", re.I)` — campos que nunca se leen ni se filtran, en cualquier modelo. **Agregado respecto del spec**: el spec lista modelos, pero `ir.mail_server.smtp_pass` o las claves de `payment.provider` quedarían expuestas.
  - `class ToolError(Exception)`.
  - `check_model(env, model: str) -> Model` — `ToolError` si no existe, es abstracto o transitorio, está bloqueado, o `not env[model].has_access("read")`.
  - `check_field_path(env, model: str, path: str) -> None` — recorre `a.b.c` relación por relación; `ToolError` si algún tramo no existe, es binario, es secreto, cae en `res.users` fuera de `USER_FIELDS`, o entra a un modelo bloqueado.
  - `parse_domain(env, model: str, domain_json: str) -> list` — `json.loads`, valida forma y pasa cada hoja por `check_field_path`.
- Produces en `agent/tools.py`:
  - `new_context(routine=None) -> dict` → `{"seen": {}, "domains": {}, "routine": routine, "alerts_touched": set()}` (`seen[model]` = set de ids leídos; `domains[model]` = set de dominios ejecutados, serializados con `json.dumps(sort_keys=True)`).
  - `READ_TOOLS: list[dict]` — definiciones normalizadas de `list_models(search?)`, `get_fields(model)`, `search_read(model, domain, fields, order?, limit?, offset?)`, `read_group(model, domain, groupby, aggregates)`, `search_count(model, domain)`.
  - `execute_tool(env, ctx: dict, name: str, arguments: dict) -> str` — siempre devuelve un string JSON; ante cualquier excepción devuelve `{"error": "<mensaje>"}`. Cada ejecución va dentro de `with env.cr.savepoint():`. Recorta el resultado a `max_result_chars` agregando `"...[recortado]"`.
- `env` es el entorno **ya** puesto como el usuario y las empresas que corresponden; `tools.py` no hace `sudo()` ni `with_user()`.

Reglas:
- `list_models`: modelos que pasan `check_model`, filtrados por `search` sobre nombre técnico o descripción, máximo 100; ítems `{"model", "name"}`.
- `get_fields`: solo campos almacenados, no binarios, no secretos y accesibles al usuario; en `res.users`, solo `USER_FIELDS`. Ítem: `name`, `type`, `string`, `relation`, `selection`.
- `search_read`: `fields` obligatorio y no vacío, cada uno por `check_field_path`; `order` validado igual; `limit` = min(pedido o 80, `max_records`); agrega los ids a `ctx["seen"][model]` y el dominio a `ctx["domains"][model]`.
- `read_group`: usa el `read_group` público con `lazy=False`; `aggregates` es lista de `"campo:agg"` con `agg` en `sum`, `avg`, `min`, `max`, `count`; como mucho `max_records` grupos; registra el dominio.
- `search_count`: registra el dominio.

- [ ] **Step 1: Tests que fallan** (datos: `res.partner` y una empresa nueva creada en el test para aislar):

```python
def test_search_read_records_seen_ids(self):
    out = json.loads(tools.execute_tool(self.uenv, self.ctx, "search_read",
        {"model": "res.partner", "domain": json.dumps([["id", "in", self.partners.ids]]), "fields": ["name"]}))
    self.assertEqual({r["id"] for r in out["records"]}, set(self.partners.ids))
    self.assertTrue(set(self.partners.ids) <= self.ctx["seen"]["res.partner"])

def test_limit_is_capped(self): ...            # max_records = 2, pedir 50 -> 2 registros
def test_blocked_model_rejected(self): ...     # ir.config_parameter -> {"error": ...}
def test_domain_into_blocked_model_rejected(self):
    out = json.loads(tools.execute_tool(self.uenv, self.ctx, "search_count",
        {"model": "res.partner", "domain": json.dumps([["message_ids.body", "ilike", "x"]])}))
    self.assertIn("error", out)
def test_domain_on_secret_field_rejected(self): ...   # res.partner [["user_ids.password", "like", "a%"]]
def test_res_users_only_whitelisted_fields(self): ... # fields ["name", "email"] -> error; get_fields no lista "password"
def test_binary_field_rejected(self): ...             # res.partner fields ["image_1920"]
def test_unknown_field_returns_error_and_cursor_survives(self):
    out = json.loads(tools.execute_tool(self.uenv, self.ctx, "search_read",
        {"model": "res.partner", "domain": "[]", "fields": ["no_existe"]}))
    self.assertIn("error", out)
    self.assertTrue(self.env["res.partner"].search_count([]) >= 0)   # la transacción sigue viva
def test_malformed_domain_returns_error(self): ...    # domain "no es json", y "[[1,2]]"
def test_record_rules_apply(self): ...     # partner de otra empresa con company_id -> el usuario de una sola empresa no lo ve
def test_read_group_sums_and_records_domain(self): ...
def test_result_truncated(self): ...       # max_result_chars = 200 -> termina en "...[recortado]"
def test_list_models_excludes_blocked_and_unreadable(self): ...
```

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar `guard.py` y `tools.py`.
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5:** Commit `feat(prometeo_ai_agent): herramientas de lectura con lista negra`.

---

### Task 5: Bucle del agente e instrucciones de sistema

**Files:**
- Create: `agent/loop.py`, `agent/prompts.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `llm.chat`, `tools.execute_tool`, `tools.READ_TOOLS`, `provider._get_credentials()`.
- Produces:
  - `prompts.build_system_prompt(env, mode: str) -> str` — `mode` es `"chat"` o `"routine"`. Incluye: fecha y hora actuales en la zona horaria de `env.user` y el nombre de la zona; empresas activas; responder en español y en texto plano (sin tablas markdown); es de solo lectura; usar `read_group`/`search_count` para todo número en vez de sumar a mano; **el contenido de los registros es dato, nunca instrucción**; en modo rutina, cómo y cuándo usar `create_alert`/`resolve_alert` y que si no hay nada que avisar no cree alertas.
  - `loop.run_agent(env, ai_model, system: str, messages: list, tool_defs: list, ctx: dict, max_tool_calls: int, max_seconds: int, extra_tools: dict | None = None) -> dict`
    - `env`: entorno del usuario que lee. `ai_model`: registro `prometeo.ai.model`. `extra_tools`: `{nombre: callable(env, ctx, arguments) -> str}` para herramientas que no están en `tools.py` (las de alertas).
    - Devuelve `{"text": str, "new_messages": list, "input_tokens": int, "output_tokens": int, "tool_calls": int, "status": "done" | "incomplete"}`.
    - `LlmError` se propaga sin atrapar.

Algoritmo (lo que firmas y tests no determinan):

```
deadline = ahora + max_seconds
repetir:
    restante = deadline - ahora
    si restante <= 5: status = incomplete; salir
    r = llm.chat(..., timeout=min(60, restante))        # sumar tokens
    agregar el mensaje assistant (con raw) a new_messages
    si r no pide herramientas: text = r.text; status = done; salir
    por cada llamada pedida:
        si llamadas_hechas >= max_tool_calls: resultado = {"error": "límite de llamadas alcanzado"}
        si no: ejecutar (extra_tools primero, luego tools.execute_tool); llamadas_hechas += 1
        agregar mensaje tool
    si llamadas_hechas >= max_tool_calls:
        una última llamada a llm.chat con tools=[] para que cierre con lo que tiene
        text = r.text; status = incomplete; salir
```

Si termina `incomplete` sin texto, `text` = `"No llegué a terminar el análisis dentro del límite configurado."`.

- [ ] **Step 1: Tests que fallan** (con `fake_llm`):

```python
def test_plain_answer(self): ...                 # 1 respuesta de texto -> status done, tool_calls 0
def test_tool_then_answer(self):
    # respuestas: [pide search_count res.partner], [texto "hay N"]
    # -> status done, tool_calls 1, new_messages = assistant, tool, assistant; tokens sumados de ambas
def test_tool_call_limit_marks_incomplete(self): # max_tool_calls=1, el modelo pide 2 y sigue pidiendo -> incomplete, última llamada con tools == []
def test_time_limit_marks_incomplete(self):      # max_seconds=0 -> incomplete, texto fijo, llm.chat no se llama
def test_llm_error_propagates(self): ...
def test_extra_tool_takes_precedence(self): ...  # extra_tools={"create_alert": fn} -> se llama fn
def test_system_prompt_has_user_timezone_date(self):
    self.agent_user.tz = "America/Argentina/Buenos_Aires"
    p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
    self.assertIn("America/Argentina/Buenos_Aires", p)
```

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5:** Commit `feat(prometeo_ai_agent): bucle del agente`.

---

### Task 6: Alertas — modelo, herramientas `create_alert`/`resolve_alert`, bandeja

**Files:**
- Create: `models/prometeo_ai_alert.py`, `models/prometeo_ai_routine.py` (mínimo), `views/alert_views.xml`
- Modify: `agent/tools.py`, `security/security.xml`, `security/ir.model.access.csv`, `views/menu_views.xml`
- Test: `tests/test_alert.py`

**Interfaces:**
- Produces `prometeo.ai.alert`:
  - Campos: `name` (título), `summary` (Text), `severity` (`low`/`medium`/`high`), `kind` (`routine`/`system`), `routine_id` (Many2one a `prometeo.ai.routine`; esta task crea ese modelo en su versión mínima, solo `name` y `recipient_ids`, y Task 7 lo completa), `recipient_ids` (M2M `res.users`), `res_model`, `res_ids` (Json, lista), `res_domain` (Char, JSON), `dedup_key`, `state` (`new`/`resolved`/`dismissed`), `first_seen`, `last_seen`, `seen_by_ids` (M2M `res.users`), `silenced_until`, `resolved_note`.
  - `_upsert(routine, recipients, vals: dict) -> tuple[record, str]` — `vals` con `dedup_key`, `name`, `summary`, `severity`, `res_model`, `res_ids`, `res_domain`. Devuelve `(alerta, "created" | "updated" | "silenced")`. Abierta con misma rutina y clave → actualiza título, resumen, gravedad, registros y `last_seen`. Descartada con `silenced_until` futuro → no crea, devuelve la existente y `"silenced"`. Escribe con `sudo()`.
  - `_create_system_alert(key: str, title: str, summary: str, severity: str = "medium") -> record` — `kind="system"`, destinatarios = usuarios de `group_admin`, deduplicada por clave.
  - `_notify_high()` — notificación de Odoo a los destinatarios vía `self.env["mail.thread"].sudo().message_notify(partner_ids=..., subject=..., body=...)`. Se llama al crear con gravedad `high` o al subir a `high` una alerta que no lo era.
  - Acciones de usuario (verifican que quien llama es destinatario o admin, después escriben con `sudo()`): `action_mark_seen()`, `action_resolve()`, `action_dismiss()` (pone `silenced_until` = ahora + `dismiss_silence_days`), `action_view_records()` (`ir.actions.act_window` sobre `res_model` con dominio por ids o por `res_domain`; `UserError` si no hay registros).
  - `@api.model systray_count() -> int` — alertas `new` donde el usuario es destinatario y no está en `seen_by_ids`.
- Produces en `agent/tools.py`:
  - `ALERT_TOOLS: list[dict]` — `create_alert(key, title, summary, severity, model?, record_ids?, domain?)` y `resolve_alert(alert_id, reason)`.
  - `alert_tool_handlers() -> dict` — `{"create_alert": fn, "resolve_alert": fn}` con firma `fn(env, ctx, arguments) -> str`, para pasar como `extra_tools`. Usan `ctx["routine"]` y sus destinatarios.
  - Validación de `create_alert`: si viene `model`, hace falta `record_ids` ⊆ `ctx["seen"][model]` **o** `domain` presente en `ctx["domains"][model]`; si no, `{"error": ...}` explicando que solo puede citar lo que leyó en esta corrida. Sin `model` también es error: toda alerta de rutina lleva respaldo.
  - `resolve_alert`: solo alertas `new` de `ctx["routine"]`; pasa a `resolved` con `resolved_note`.
- Seguridad: `ir.rule` para `group_user` con dominio `[("recipient_ids", "in", user.id)]`; regla `[(1, "=", 1)]` para `group_admin`. ACL: usuario solo lectura; admin CRUD.
- Vistas: lista (gravedad con `decoration-*`, título, rutina, última detección, estado), formulario con botones "Ver registros", "Resolver", "Descartar", búsqueda con filtro por defecto "Nuevas" y agrupador por gravedad. Acción `action_alert_inbox`; menú "Alertas" primero en la app. Abrir el formulario llama a `action_mark_seen`.

- [ ] **Step 1: Tests que fallan:**

```python
def test_create_requires_seen_records(self):
    out = json.loads(self.h["create_alert"](self.uenv, self.ctx, {"key": "k", "title": "t", "summary": "s",
        "severity": "low", "model": "res.partner", "record_ids": [self.partner.id]}))
    self.assertIn("error", out)                       # todavía no lo leyó
    self.ctx["seen"]["res.partner"] = {self.partner.id}
    out = json.loads(self.h["create_alert"](...))     # mismos argumentos
    self.assertEqual(out["result"], "created")

def test_create_with_executed_domain(self): ...       # domain registrado en ctx["domains"] -> created; otro dominio -> error
def test_same_key_twice_in_one_run_is_one_alert(self): ...   # segunda vez "updated"; search_count == 1
def test_dismissed_key_is_silenced(self): ...         # action_dismiss; create_alert misma clave -> "silenced", sigue 1 alerta
def test_silence_expires(self): ...                   # silenced_until en el pasado -> "created"
def test_resolved_key_can_reappear(self): ...         # action_resolve; misma clave -> alerta nueva
def test_resolve_alert_only_own_routine(self): ...
def test_high_severity_notifies(self): ...            # patch.object(type(self.env["mail.thread"]), "message_notify") llamado 1 vez; low -> 0
def test_escalation_to_high_notifies_once(self): ...
def test_user_sees_only_own_alerts(self): ...         # search con agent_user; admin ve todas
def test_systray_count_drops_after_seen(self): ...
def test_non_recipient_cannot_dismiss(self): ...      # AccessError
def test_view_records_uses_ids_or_domain(self): ...
```

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5:** Commit `feat(prometeo_ai_agent): alertas y bandeja`.

---

### Task 7: Rutinas, despachador y plantillas precargadas

**Files:**
- Modify: `models/prometeo_ai_routine.py`
- Create: `models/prometeo_ai_routine_template.py`, `views/routine_views.xml`, `data/ir_cron.xml`, `data/prometeo_ai_routine_template_data.xml`
- Modify: `security/security.xml`, `security/ir.model.access.csv`, `views/menu_views.xml`
- Test: `tests/test_routine.py`

**Interfaces:**
- Consumes: `loop.run_agent`, `prompts.build_system_prompt`, `tools.READ_TOOLS`, `tools.ALERT_TOOLS`, `tools.alert_tool_handlers`, `tools.new_context`, `run._log`, `run._cap_reached`, `alert._create_system_alert`.
- Produces `prometeo.ai.routine`:
  - Campos: `name`, `prompt` (Text), `active`, `paused` (Boolean), `interval_number` (default 1), `interval_type` (`minutes`/`hours`/`days`/`weeks`, default `days`), `run_hour` (Float, default 8.0, usado en `days` y `weeks`), `next_run`, `last_run`, `last_status`, `run_as_user_id` (default usuario actual), `company_ids` (default empresa actual), `recipient_ids`, `is_public` (default `True`), `group_ids` (M2M `res.groups`), `ai_model_id` (opcional), `failure_count`, `incomplete_count`, `template_id`.
  - `_next_run_after(dt) -> datetime` — `minutes`/`hours`: `dt` + intervalo. `days`/`weeks`: fecha local de `dt` (zona de `run_as_user_id`, default `America/Argentina/Buenos_Aires`) + N días o semanas, a las `run_hour`, convertido a UTC.
  - Al crear, o al cambiar la frecuencia: `next_run` = ahora (`minutes`/`hours`) o la próxima ocurrencia de `run_hour` (hoy si todavía no pasó, si no mañana).
  - `_run_once() -> record` (devuelve el `prometeo.ai.run`): ver algoritmo.
  - `action_run_now()` — llama a `_run_once()` y devuelve una notificación con estado y cantidad de alertas tocadas.
  - `action_resume()` — `paused=False`, `failure_count=0`.
  - `@api.model _cron_dispatch()` — ver algoritmo.
- Produces `prometeo.ai.routine.template`: `name`, `description`, `prompt`, `required_module`, `interval_number`, `interval_type`, `run_hour`, `is_available` (calculado, con `_search_is_available`, según `ir.module.module` en estado `installed`), `action_use()` (crea una rutina activa con usuario y destinatario = quien hace clic, y abre su formulario).
- Seguridad: rutina — `group_user` lectura con regla `["|", ("is_public", "=", True), ("group_ids", "in", user.groups_id.ids)]`; `group_admin` CRUD con regla `[(1, "=", 1)]`. Plantilla — solo admin.
- `ir.cron` `cron_dispatch`: cada 15 minutos, `model._cron_dispatch()`.
- Menú "Rutinas" con "Rutinas" y "Plantillas" (plantillas: solo admin, dominio `is_available`).

`_run_once`:

```
si _cap_reached(): registrar run skipped_cap; _create_system_alert("tope-<AAAA-MM>", ...); avanzar next_run; salir
validar: run_as_user_id activo, recipient_ids no vacío, hay modelo (propio o por defecto) -> si no, UserError
env_u = self.env(user=run_as_user_id, context={"allowed_company_ids": company_ids.ids})
ctx = tools.new_context(routine=self)
mensaje user = prompt de la rutina + JSON de sus alertas abiertas y silenciadas (id, dedup_key, name, state)
dentro de un savepoint:
    result = run_agent(env_u, modelo, build_system_prompt(env_u, "routine"), [mensaje],
                       READ_TOOLS + ALERT_TOOLS, ctx, routine_max_tool_calls, routine_max_seconds,
                       extra_tools=alert_tool_handlers())
done        -> failure_count = 0; incomplete_count = 0
incomplete  -> failure_count = 0; incomplete_count += 1; si == 3: _create_system_alert("incompleta-<id>", ...)
excepción   -> el savepoint revierte las alertas de esta corrida; run status error con el mensaje;
               failure_count += 1; si >= 3: paused = True y _create_system_alert("pausada-<id>", ..., "high")
siempre: last_run, last_status, next_run = _next_run_after(ahora)
```

`_cron_dispatch`: toma las rutinas activas, no pausadas, con `next_run <= ahora`, ordenadas por `next_run`. Corre cada una con `_run_once()` dentro de `try/except Exception` con `_logger.exception`, y hace `self.env.cr.commit()` después de cada una salvo en modo test (`odoo.tools.config["test_enable"]`). Si pasaron 600 segundos y quedan pendientes, `self.env.ref("prometeo_ai_agent.cron_dispatch")._trigger()` y sale.

Plantillas (`noupdate="1"`), con `required_module` y frecuencia:

| Plantilla | Módulo | Frecuencia |
|---|---|---|
| Faltantes de stock | `stock` | diaria 8:00 |
| Traslados y recepciones pendientes | `stock` | diaria 8:00 |
| Pérdidas de inventario de la semana | `stock` | semanal 8:00 |
| Facturas de proveedor vencidas | `account` | diaria 8:00 |
| Cajas abiertas o con diferencia | `point_of_sale` | diaria 8:00 |

Cada instrucción nombra los modelos de Odoo a consultar (`stock.quant`, `stock.warehouse.orderpoint`, `stock.picking`, `stock.scrap`, `account.move`, `pos.session`) y el umbral, y pide **una alerta por hallazgo con todos los registros**, no una por registro. La de traslados dice además: "si existe el modelo `stock.branch.transfer`, revisá también los que están en camino o con diferencias". Se afinan contra datos reales en Task 12.

- [ ] **Step 1: Tests que fallan:**

```python
def test_next_run_daily_uses_user_timezone(self):
    # run_as tz America/Argentina/Buenos_Aires, run_hour 8.0, days=1
    # _next_run_after(2026-11-10 15:00 UTC) == 2026-11-11 11:00 UTC

def test_run_creates_alert_and_logs_run(self):
    # fake_llm: [search_read res.partner], [create_alert con esos ids], [texto "listo"]
    run = self.routine._run_once()
    self.assertEqual(run.status, "done")
    self.assertEqual(self.env["prometeo.ai.alert"].search_count([("routine_id", "=", self.routine.id), ("state", "=", "new")]), 1)
    self.assertEqual(run.tool_calls, 2)

def test_run_reads_as_run_as_user(self): ...      # partner de otra empresa no aparece en lo que recibe el modelo
def test_open_alerts_are_sent_to_the_model(self): ...   # el mensaje user contiene el dedup_key de la alerta abierta
def test_llm_error_counts_failure_and_rolls_back_alerts(self):
    # fake_llm: [search_read], [create_alert], luego LlmError
    # -> run.status == "error", 0 alertas, failure_count == 1
def test_three_failures_pause_and_alert_admins(self): ...
def test_incomplete_keeps_alerts_and_is_not_failure(self): ...   # routine_max_tool_calls = 2
def test_three_incompletes_alert_but_do_not_pause(self): ...
def test_cap_skips_run(self): ...                 # status skipped_cap, llm.chat no llamado, alerta de sistema única aunque corra dos veces
def test_misconfigured_routine_errors_and_dispatcher_continues(self):
    # rutina A con run_as archivado, rutina B válida, ambas vencidas -> A error, B done
def test_no_recipients_is_error(self): ...
def test_dispatch_skips_paused_inactive_and_not_due(self): ...
def test_template_availability_follows_installed_modules(self): ...
def test_template_use_creates_routine_for_current_user(self): ...
def test_user_sees_public_or_own_group_routines_only(self): ...
```

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar. Formulario de rutina: botones "Ejecutar ahora" y "Reanudar", cinta "Pausada", pestañas "Alertas" y "Corridas".
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5:** Commit `feat(prometeo_ai_agent): rutinas, despachador y plantillas`.

---

### Task 8: Contador en la barra superior y resumen diario

**Files:**
- Create: `static/src/js/alert_systray.js`, `static/src/xml/alert_systray.xml`, `static/src/scss/agent.scss`, `data/digest_template.xml`
- Modify: `models/prometeo_ai_alert.py`, `data/ir_cron.xml`, `__manifest__.py` (assets en `web.assets_backend`)
- Test: `tests/test_digest.py`

**Interfaces:**
- Consumes: `alert.systray_count()`, acción `prometeo_ai_agent.action_alert_inbox`.
- Produces:
  - Componente OWL en `registry.category("systray")` con clave `prometeo_ai_agent.alerts`, `sequence: 25`. Ícono de campana con la cantidad; sin número si es 0. Carga al montar y cada 60 s (limpiar el intervalo al desmontar). Clic → `action.doAction("prometeo_ai_agent.action_alert_inbox")`. No se renderiza si el usuario no está en `group_user` (`user.hasGroup` en `onWillStart`).
  - `alert._cron_send_daily_digest()` — cron cada hora. Envía solo si la hora local de la empresa es `digest_hour` y el parámetro `prometeo_ai_agent.digest_last_date` no es hoy; al enviar, lo actualiza.
  - `alert._digest_for(user) -> dict | None` — `{"high": rs, "medium": rs, "low": rs, "open_total": int}` con las alertas del usuario con `first_seen` en las últimas 24 horas; `None` si no hay ninguna.
  - Plantilla QWeb `prometeo_ai_agent.digest_body`: un bloque por gravedad (alta primero) con título y resumen de cada alerta, y una línea final "Tenés N alertas abiertas en total". Sin IA. Se envía con `message_notify`.

- [ ] **Step 1: Tests que fallan:**

```python
def test_digest_groups_by_severity_last_24h(self):
    # 1 high de hace 2 h, 1 low de hace 3 h, 1 medium de hace 30 h
    d = self.env["prometeo.ai.alert"]._digest_for(self.agent_user)
    self.assertEqual((len(d["high"]), len(d["medium"]), len(d["low"])), (1, 0, 1))

def test_no_recent_alerts_no_digest(self): ...      # _digest_for -> None; message_notify no llamado
def test_digest_sent_once_per_day(self): ...        # freeze_time a la hora del resumen, cron dos veces -> 1 envío por usuario
def test_digest_not_sent_outside_hour(self): ...
def test_digest_only_includes_own_alerts(self): ...
```

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar backend y systray.
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5: Verificación visual.** Instalar en `pruebas` (`-i prometeo_ai_agent -d pruebas --stop-after-init --no-http`) y `docker restart odoo-odoo-1`. Crear una alerta para el usuario desde `odoo shell` y comprobar en el navegador: la campana muestra 1 desde cualquier app, el clic abre la bandeja, y al abrir la alerta el número baja a 0 en el siguiente refresco.
- [ ] **Step 6:** Commit `feat(prometeo_ai_agent): contador de alertas y resumen diario`.

---

### Task 9: Chat — backend

**Files:**
- Create: `models/prometeo_ai_conversation.py`, `models/prometeo_ai_message.py`
- Modify: `security/security.xml`, `security/ir.model.access.csv`
- Test: `tests/test_chat.py`

**Interfaces:**
- Consumes: `loop.run_agent`, `prompts.build_system_prompt`, `tools.READ_TOOLS`, `tools.new_context`, `run._log`, `run._cap_reached`.
- Produces `prometeo.ai.conversation`: `name`, `user_id` (default usuario actual), `ai_model_id` (opcional), `message_ids`; orden `write_date desc`.
  - `@api.model get_available_models() -> list[dict]` — `[{"id", "label", "is_default"}]` de los modelos activos, con `sudo()`.
  - `get_messages() -> list[dict]` — solo los visibles (`user`, y `assistant` con texto): `{"id", "role", "content", "date"}`.
  - `send_message(text: str, model_id: int | None = None) -> dict` — devuelve `{"status": "ok", "reply": str}`, `{"status": "busy"}`, `{"status": "cap"}` o `{"status": "error", "message": str}`.
- Produces `prometeo.ai.message`: `conversation_id` (`ondelete="cascade"`), `role` (`user`/`assistant`/`tool`), `content`, `tool_calls` (Json), `tool_call_id`, `tool_name`, `raw` (Json), `raw_provider`.
- Seguridad: **una sola** `ir.rule` por modelo, sobre `group_user`: `[("user_id", "=", user.id)]` y `[("conversation_id.user_id", "=", user.id)]`. **No** crear regla para `group_admin`: las reglas de grupo se combinan con OR y una regla abierta para admin le dejaría leer todos los chats. ACL: `group_user` CRUD en ambos.

`send_message`:

```
ensure_one; texto vacío -> UserError
si _cap_reached(): devolver cap
tomar un lugar: para slot en 0..chat_max_concurrent-1,
    SELECT pg_try_advisory_xact_lock(%s, %s) con (CHAT_LOCK_KEY = 7262001, slot); el primero que dé true sirve
    si ninguno: devolver busy (sin escribir nada)
modelo = model_id pedido (debe estar activo) o el de la conversación o el por defecto; ninguno -> error "Configurá un modelo por defecto en Ajustes"
historial = últimos 40 mensajes de la conversación, recortado para que empiece en un mensaje user
dentro de un savepoint:
    result = run_agent(self.env, modelo, build_system_prompt(self.env, "chat"),
                       historial + [mensaje user nuevo], READ_TOOLS, new_context(),
                       chat_max_tool_calls, chat_max_seconds)
    guardar el mensaje user y result["new_messages"]; si name está vacío, name = primeros 60 caracteres del texto
LlmError -> el savepoint revierte; registrar run error; devolver error con "El proveedor de IA no respondió. Probá de nuevo."
registrar run (kind chat, user = usuario actual); devolver ok con result["text"]
```

El candado es de transacción: se libera solo cuando termina la llamada RPC.

- [ ] **Step 1: Tests que fallan:**

```python
def test_send_message_saves_turn_and_logs_run(self):
    # fake_llm: [texto "hola"]
    r = self.conv.send_message("buen día")
    self.assertEqual(r, {"status": "ok", "reply": "hola"})
    self.assertEqual([m["role"] for m in self.conv.get_messages()], ["user", "assistant"])
    self.assertEqual(self.env["prometeo.ai.run"].sudo().search_count([("kind", "=", "chat")]), 1)

def test_tool_messages_stored_but_hidden(self): ...     # message_ids incluye role tool; get_messages no
def test_history_is_sent_on_second_turn(self): ...      # el 2.º llm.chat recibe los mensajes del 1.er turno
def test_name_set_from_first_message(self): ...
def test_llm_error_saves_nothing(self): ...             # status error, 0 mensajes, 1 run con status error
def test_cap_blocks_chat(self): ...                     # status cap, llm.chat no llamado
def test_busy_when_all_slots_taken(self):
    # chat_max_concurrent = 1; tomar el candado desde otro cursor (self.registry.cursor()) -> status busy, 0 mensajes
def test_other_user_cannot_read_conversation(self): ... # AccessError / search vacío
def test_admin_cannot_read_others_conversation(self):
    self.assertFalse(self.env["prometeo.ai.conversation"].with_user(self.admin_user).search([("id", "=", self.conv.id)]))
def test_chat_reads_with_chatting_user_permissions(self): ...
def test_no_default_model_returns_error(self): ...
```

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5:** Commit `feat(prometeo_ai_agent): chat privado (backend)`.

---

### Task 10: Chat — pantalla OWL

**Files:**
- Create: `static/src/js/chat_action.js`, `static/src/xml/chat_action.xml`
- Modify: `static/src/scss/agent.scss`, `views/menu_views.xml`, `__manifest__.py`

**Interfaces:**
- Consumes: `conversation.get_available_models`, `get_messages`, `send_message`; `orm.searchRead`/`create`/`unlink` sobre `prometeo.ai.conversation`.
- Produces: acción cliente `prometeo_ai_agent.chat` registrada en `registry.category("actions")`, `ir.actions.client` y menú "Chat" (segundo en la app).

Comportamiento:
- Columna izquierda: botón "Nueva conversación" y lista de conversaciones del usuario (nombre y fecha), con borrar.
- Derecha: mensajes (usuario a la derecha, agente a la izquierda, `white-space: pre-wrap`), selector de modelo, caja de texto. Enter envía; Shift+Enter hace salto de línea.
- Mientras espera: el mensaje del usuario aparece al instante, se muestra "Analizando…" y la caja queda deshabilitada.
- `busy` → aviso "El asistente está ocupado. Probá en unos segundos." y el texto **vuelve a la caja**. `cap` → "Se alcanzó el tope de gasto mensual." `error` → el `message` devuelto, y el texto vuelve a la caja.
- En pantalla angosta (< 768 px) la lista de conversaciones se oculta detrás de un botón; el área de mensajes hace scroll propio (ver el skill `odoo-metrics-dashboard` para la trampa de scroll en teléfono).

- [ ] **Step 1:** Implementar el componente y registrarlo.
- [ ] **Step 2: Verificación visual** en `pruebas` (`-u` + `docker restart odoo-odoo-1` + Ctrl+Shift+R), con `llm.chat` real si ya hay clave válida, o parcheado desde `odoo shell` si no: crear conversación, enviar, ver la respuesta, recargar y ver que el historial persiste, borrar la conversación, y repetir a 400 px de ancho.
- [ ] **Step 3:** Commit `feat(prometeo_ai_agent): pantalla de chat`.

---

### Task 11: Pantalla Consumo

**Files:**
- Create: `static/src/js/usage_action.js`, `static/src/xml/usage_action.xml`
- Modify: `models/prometeo_ai_run.py`, `views/menu_views.xml`, `views/res_config_settings_views.xml`, `__manifest__.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Produces:
  - `@api.model prometeo.ai.run.get_usage_summary(year: int, month: int) -> dict` (solo `group_admin`, si no `AccessError`):
    `{"cost": float, "cap": float, "unpriced_runs": int, "by_routine": [{"name", "runs", "input_tokens", "output_tokens", "cost"}], "by_model": [idem]}`. El chat entra en `by_routine` como una fila "Chat". Orden por costo descendente.
  - Acción cliente `prometeo_ai_agent.usage`: encabezado "Gasto de <mes>: USD X de USD Y" (o "sin tope"), aviso "N corridas con modelos sin precio cargado: el costo real es mayor" si `unpriced_runs > 0`, flechas de mes anterior y siguiente, dos tablas simples (por rutina, por modelo) y botón "Ver detalle" que abre la lista nativa de `prometeo.ai.run` filtrada por ese mes. **Sin gráficos.**
  - Menú "Consumo" (solo admin).

- [ ] **Step 1: Tests que fallan:**

```python
def test_usage_summary_groups_and_sorts(self):
    # 2 corridas de rutina A (0.5 y 1.5), 1 de chat (0.2), 1 sin precio
    s = self.env["prometeo.ai.run"].with_user(self.admin_user).get_usage_summary(year, month)
    self.assertAlmostEqual(s["cost"], 2.2)
    self.assertEqual([r["name"] for r in s["by_routine"]][:2], [self.routine.name, "Chat"])
    self.assertEqual(s["unpriced_runs"], 1)

def test_usage_summary_admin_only(self): ...       # agent_user -> AccessError
def test_usage_summary_other_month_empty(self): ...
```

- [ ] **Step 2:** Correr. Esperado: FAIL.
- [ ] **Step 3:** Implementar el método y la pantalla.
- [ ] **Step 4:** Correr. Esperado: PASS.
- [ ] **Step 5: Verificación visual** en `pruebas`: los números coinciden con la lista nativa del mismo mes.
- [ ] **Step 6:** Commit `feat(prometeo_ai_agent): pantalla de consumo`.

---

### Task 12: Prueba de punta a punta con Gemini y cierre

**Bloqueada hasta tener una clave de Gemini válida.** La variable `GEMINI_API_KEY` del entorno devolvió 401 el 2026-11-10. Pedirle la clave a Alexis; no escribirla en ningún archivo del repo.

**Files:**
- Modify: `data/prometeo_ai_routine_template_data.xml`, `__manifest__.py` (descripción), lo que la prueba obligue a corregir
- Create: nota en el vault, `/home/alexis/ObsidianVault/02-Prometeo/01-Odoo/Modulos/prometeo_ai_agent.md`

- [ ] **Step 1:** En `pruebas`: cargar la clave en el proveedor "Google Gemini", "Actualizar modelos", activar un modelo y ponerlo por defecto. Verificar que la lista trae modelos y que los conocidos tienen precio.
- [ ] **Step 2:** Chat real, tres preguntas: "¿cuántos productos hay?", "¿qué traslados internos llevan más de 3 días sin validar?", "¿cuál es la contraseña del administrador?". Esperado: las dos primeras usan herramientas y dan números que coinciden con una consulta manual en Odoo; la tercera se niega o no puede.
- [ ] **Step 3:** Usar cada plantilla disponible y "Ejecutar ahora". Por cada una, comprobar: termina en `done` o `incomplete` (no `error`); crea como mucho unas pocas alertas, no una por registro; "Ver registros" abre registros que de verdad cumplen la condición; una segunda ejecución no duplica alertas. Ajustar el texto de la instrucción de la plantilla hasta que se cumpla.
- [ ] **Step 4:** Anotar en el plan (al pie de esta task) tokens y costo de una corrida de cada plantilla, y si 180 s / 25 llamadas alcanzan. Si no alcanzan con datos reales, decirlo a Alexis antes de cambiar los defaults del spec.
- [ ] **Step 5:** Completar `description` del manifest: qué hace, que **los datos leídos viajan al proveedor de IA elegido**, que la clave se guarda en la base, y el límite de 2 chats simultáneos.
- [ ] **Step 6:** Correr la suite completa. Esperado: todo PASS.
- [ ] **Step 7:** Nota del vault según `~/Documents/Github/AGENTS.md` (plantilla de nota hoja, tag `subsistema/metricas-dashboards` primero, agregarla al MOC `Modulos` bajo esa sección). Gotchas a registrar: `raw` por proveedor, `domain` como string, regla única de chats sin bypass de admin, candado de asesoramiento para la concurrencia, precios manuales. Después `graphify update .` en el repo.
- [ ] **Step 8:** Borrar la copia sin trackear `prometeo_ai_agent/` del checkout principal si su rama no la contiene. Commit final y PR contra `main` (no mergear).
