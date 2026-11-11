# prometeo_ai_agent — App "Agente IA" (alertas proactivas, rutinas y chat)

Fecha: 2026-11-10
Estado: pendiente de aprobación

Las decisiones marcadas **(decisión del diseño)** las tomó quien escribió este
documento, no Alexis. El resto salió de la conversación.

## Problema

Cuando Alexis conecta una IA a los datos de Odoo encuentra patrones que nadie
estaba mirando: pérdidas de stock, traslados que quedaron pendientes, faltantes.
Pero eso depende de que él se siente a preguntar. Los dueños de negocio no entran
a cada módulo ni revisan cada reporte, así que la información existe y nadie la ve.

## Objetivo

Una app propia, **Agente IA**, en el menú principal de Odoo 18, que:

- corre **rutinas** programadas: una instrucción en lenguaje natural más una
  frecuencia, al estilo de las rutinas de Claude. En cada corrida el agente
  consulta los datos de Odoo por su cuenta y, si encuentra algo, deja una alerta;
- muestra las alertas en una **bandeja** dentro de Odoo, con un **contador en la
  barra superior** visible desde cualquier pantalla, y un **resumen diario**;
- ofrece un **chat** privado dentro de Odoo para preguntarle cosas en el momento;
- funciona con **Claude, OpenAI y Google**, con modelo elegible, y toma los
  modelos nuevos sin actualizar el módulo;
- muestra el **costo mensual** y respeta un tope de gasto.

Versión 1 es **solo lectura**: avisos e información. El agente no modifica datos
de negocio.

## No-objetivos (versión 1)

- Avisos por WhatsApp. Queda para una etapa posterior (gateway OpenWA).
- Acciones del agente sobre Odoo (crear actividades, borradores de compra o de
  traslado). Queda para una etapa posterior, siempre con aprobación humana.
- Crear rutinas desde el chat.
- Respuesta del chat en streaming.
- Gráficos en la pantalla de consumo: Alexis prefiere tablas simples.
- SQL libre para el agente.

## Anti-objetivos (fallaría aunque "funcione")

1. **Ruido.** Decenas de alertas por día y el dueño deja de mirarlas. La misma
   alerta no se repite mientras siga abierta.
2. **Datos inventados.** Una alerta que cita registros que no existen.
3. **Costo descontrolado.** Una rutina frecuente con un modelo caro sin que nadie
   se entere.
4. **Ver lo que no corresponde.** El agente leyendo como administrador y mostrando
   datos de otra empresa o de un modelo restringido.
5. **Odoo lento.** Una consulta pesada del agente en horario de venta.
6. **Que el agente escriba** en datos de negocio, por cualquier camino.

## Restricciones

- Odoo 18, repo `prometeo-odoo-modules`, convenciones del skill
  `odoo-prometeo-modules`.
- La configuración va como **app propia en la barra lateral de Ajustes**, con un
  `<block>` por sección.
- El módulo se instala en bases con conjuntos de módulos distintos (mega-erp,
  las 6 bases de prometeo.com.ar). No puede depender de `stock`, `purchase` ni
  `point_of_sale`.
- **Sin SDKs de proveedores.** Las llamadas van por HTTP con `requests`, que Odoo
  ya trae. No se agrega nada a `requirements.txt` **(decisión del diseño)**: cada
  dependencia nueva hay que instalarla en todos los servidores.

## Diseño

### Nombres

- Módulo: `prometeo_ai_agent`. Depende de `base`, `web`, `mail`.
- Modelos con prefijo `prometeo.ai.` **(decisión del diseño)**: Odoo 19 Enterprise
  trae un módulo `ai` con modelo `ai.agent`, y se evita el choque a futuro.

### Proveedores y modelos

`prometeo.ai.provider`: nombre, tipo (`anthropic`, `openai`, `google`), clave de
API, URL base (con el valor oficial por defecto).

- La URL base es editable **(decisión del diseño)**: un proveedor tipo `openai`
  con otra URL sirve para cualquier servicio compatible con la API de OpenAI
  (NVIDIA, Ollama, etc.) sin escribir código.
- La clave se guarda en la base en texto plano, legible solo por el grupo
  Administrador del agente. El agente nunca puede leer este modelo (ver lista
  negra más abajo).

`prometeo.ai.model`: proveedor, identificador técnico, nombre, activo, precio por
millón de tokens de entrada y de salida.

- Botón **Actualizar modelos** en el proveedor: llama al endpoint de listado de
  cada API (`GET /v1/models` en Anthropic y OpenAI, `GET /v1beta/models` en
  Google filtrando los que soportan `generateContent`) y crea los que faltan.
  Así un modelo nuevo aparece sin tocar el módulo.
- Los modelos traídos entran **inactivos**; el administrador activa los que
  quiere ofrecer. El listado de OpenAI incluye modelos que no son de chat.
- **Los precios no vienen de ninguna API.** El módulo trae precios cargados para
  los modelos conocidos a la fecha y el administrador los edita. Un modelo sin
  precio se puede usar, pero su costo figura como "sin precio" y no como cero.

Hay un **modelo por defecto** global y cada rutina puede elegir otro
**(decisión del diseño)**. El chat usa el modelo por defecto, con un selector
entre los modelos activos.

### Capa común de proveedores

Un módulo Python por proveedor (`modules/`-style, funciones, sin clases salvo
necesidad) detrás de una interfaz única:

- entrada: instrucción de sistema, lista de mensajes, definición de herramientas;
- salida: texto, llamadas a herramientas pedidas, tokens de entrada y de salida.

Cada adaptador traduce el formato de herramientas de su API (Messages de
Anthropic, Chat Completions de OpenAI, `generateContent` de Google). El bucle del
agente no sabe qué proveedor hay detrás. Sumar un cuarto proveedor es agregar un
archivo y una opción al campo tipo.

### Herramientas del agente (solo lectura)

| Herramienta | Qué hace |
|---|---|
| `list_models` | Modelos de Odoo a los que el usuario tiene acceso de lectura, con su descripción |
| `get_fields` | Campos de un modelo: nombre, tipo, etiqueta, relación |
| `search_read` | Registros por dominio, con campos, orden y límite |
| `read_group` | Agregados (suma, conteo, promedio) agrupados por campos |
| `search_count` | Cantidad de registros de un dominio |
| `create_alert` | Solo en rutinas: deja una alerta |
| `resolve_alert` | Solo en rutinas: cierra una alerta abierta de esa rutina |

Reglas de las herramientas de lectura:

- Se ejecutan con el ORM como el usuario que corresponde (`with_user`), **nunca
  con `sudo()`**. Los permisos de modelo y las `ir.rule` de Odoo aplican tal cual.
- Empresas permitidas: en rutinas, las elegidas en la rutina; en el chat, las que
  el usuario tiene activas.
- **Lista negra fija** de modelos que el agente no lee aunque el usuario pueda:
  `prometeo.ai.provider`, `prometeo.ai.conversation` y sus mensajes,
  `ir.config_parameter`, `res.users.apikeys`, `ir.cron`, `ir.attachment`,
  `mail.message`, `ir.model.access`, `ir.rule`. En `res.users` solo nombre, login
  y empresa. Los campos binarios nunca se devuelven.
- Límites configurables en Ajustes: máximo de registros por consulta (200 por
  defecto) y recorte del resultado de cada herramienta por tamaño. Por separado
  para chat y rutinas **(decisión del diseño)**: el chat tiene 15 llamadas a
  herramientas y 90 segundos por turno; una rutina, 25 llamadas y 180 segundos.
- Ninguna herramienta ejecuta métodos arbitrarios del ORM. No existe herramienta
  de escritura sobre datos de negocio.

Las únicas escrituras del agente son sobre sus propias alertas.

La instrucción de sistema incluye fecha y hora en la **zona horaria del
usuario**, empresa, e indicación de responder en español. La zona horaria importa:
los filtros "de hoy" calculados en UTC devuelven cero filas a la noche.

### Rutinas

`prometeo.ai.routine`:

- nombre, instrucción (texto libre), activa;
- frecuencia: cada N minutos/horas/días/semanas, con hora del día, y próxima
  ejecución calculada;
- **ejecutar como** (usuario; por defecto quien la creó) **(decisión del diseño)**;
- empresas;
- **destinatarios** de las alertas (usuarios), definidos en la misma rutina;
- **visibilidad**: pública (la ve todo usuario del agente) o restringida a uno o
  más grupos de Odoo;
- modelo de IA (opcional; si no, el modelo por defecto).

Un **único `ir.cron`** cada 15 minutos despacha las rutinas vencidas
**(decisión del diseño)**, en lugar de un cron por rutina. Cada rutina corre en su
propia transacción: una falla no arrastra a las demás. Tres fallas seguidas pausan
la rutina y avisan a los administradores del agente.

Botón **Ejecutar ahora** en la rutina, para probarla sin esperar al cron.

En cada corrida el agente recibe la instrucción de la rutina y la lista de sus
**alertas abiertas y silenciadas**, para no repetirlas y para cerrar las que ya
no aplican.

**Corrida que choca con un límite** (tiempo o llamadas) **(decisión del
diseño)**: queda registrada como *incompleta*, no como falla. Las alertas que ya
creó se conservan. No cuenta para la regla de tres fallas; solo cuentan los
errores (proveedor caído, clave inválida, excepción). Una rutina con tres
corridas incompletas seguidas genera una alerta de sistema para que el
administrador ajuste la instrucción o el límite, pero no se pausa.

**Carga sobre el cron.** Los servidores tienen 1 o 2 hilos de cron
(`max_cron_threads` en `odoo_mega` y `odoo_multicompany`), y una rutina pasa casi
todo su tiempo esperando al proveedor. El despachador procesa rutinas vencidas
hasta un presupuesto de 10 minutos por pasada y, si quedan, se vuelve a disparar,
para no retener el hilo de cron frente a los demás trabajos programados.

**Rutinas precargadas.** Vienen como plantillas inactivas que se activan con un
clic y se pueden editar. Cada plantilla declara qué módulo de Odoo necesita y solo
se ofrece si está instalado:

1. Faltantes de stock (`stock`).
2. Traslados y recepciones pendientes hace más de N días (`stock`; incluye
   `stock_branch_transfer` si está).
3. Pérdidas de inventario: ajustes negativos y desechos de la última semana
   (`stock`).
4. Facturas de proveedor vencidas sin pagar (`account`).
5. Sesiones de caja abiertas hace más de 24 horas o con diferencia de cierre
   (`point_of_sale`).

El texto exacto de cada instrucción queda a cargo de quien construye, probado
contra datos reales.

**Consecuencia a tener presente:** los destinatarios ven lo que ve el usuario de
"ejecutar como". Si ese usuario accede a más que un destinatario, la alerta le
muestra información que por permisos propios no vería. Por eso solo los
administradores del agente crean y editan rutinas.

### Alertas

`prometeo.ai.alert`: título, resumen, gravedad (baja, media, alta), rutina,
destinatarios, modelo y registros de Odoo que la respaldan, clave de
deduplicación, estado (nueva, resuelta, descartada), primera y última detección,
y quién la vio.

- **Respaldo obligatorio en registros reales.** `create_alert` solo acepta
  registros que el agente efectivamente leyó en esa corrida; si cita un id que
  ninguna herramienta devolvió, la herramienta lo rechaza. El botón **Ver
  registros** abre esos registros en Odoo.
- Los números dentro del texto del resumen no se pueden verificar uno por uno.
  Se mitiga dándole `read_group` para que agregue Odoo y no el modelo. Es un
  límite conocido, no resuelto.
- **Respaldo de hallazgos agregados.** `read_group` y `search_count` no devuelven
  ids, así que una alerta se respalda de una de dos formas: lista de ids leídos,
  o **modelo más dominio**, donde el dominio tiene que ser uno que el agente
  ejecutó en esa corrida. "Ver registros" abre la lista de ids o el dominio.
- **Granularidad (decisión del diseño):** un hallazgo es una alerta, no una por
  registro. Treinta productos en falta son una alerta "30 productos en falta" con
  sus registros, no treinta alertas. El agente puede separar un caso individual
  cuando por gravedad lo amerite. Es lo que mantiene chica la bandeja.
- **Deduplicación:** una alerta abierta con la misma rutina y clave no se vuelve a
  crear; se actualizan su última detección, su resumen y sus registros. La clave
  es un identificador corto y estable que propone el agente por hallazgo (por
  ejemplo `faltantes-stock`), o modelo más registro cuando separa un caso
  individual.
- **Descartar silencia (decisión del diseño).** Descartar una alerta silencia su
  clave por 30 días (configurable): mientras tanto la rutina no la vuelve a
  crear. **Resolver** no silencia: si el problema reaparece en una corrida
  posterior, es una alerta nueva.
- **Alertas de sistema.** Tope de gasto alcanzado, rutina pausada por fallas y
  rutina con corridas incompletas son también `prometeo.ai.alert`, de tipo
  sistema, sin rutina ni registros obligatorios, dirigidas a los administradores
  del agente.
- "Vista" es por usuario; "resuelta" y "descartada" valen para todos.
- Cada usuario ve solo las alertas donde es destinatario. El administrador del
  agente ve todas.

**Contador en la barra superior:** ícono en el systray con la cantidad de alertas
nuevas no vistas del usuario; al hacer clic abre la bandeja.

**Aviso inmediato:** las alertas de gravedad alta generan además una notificación
de Odoo al destinatario. Las demás solo suman al contador.

**Resumen diario:** un cron a una hora configurable arma, para cada destinatario
con alertas en las últimas 24 horas, un resumen agrupado por gravedad y lo envía
como notificación de Odoo. Se arma con una plantilla fija, **sin IA**
**(decisión del diseño)**: no cuesta tokens ni puede inventar nada. Si el usuario
tiene sus notificaciones de Odoo configuradas por correo, le llega por correo.

### Chat

Acción cliente OWL: lista de conversaciones a la izquierda, mensajes a la derecha.

- `prometeo.ai.conversation` y sus mensajes son **privados**: una `ir.rule` deja
  ver solo las propias, también al administrador del agente. Quien tenga acceso
  directo a la base de datos o sea superusuario técnico las puede leer igual; eso
  no se puede impedir desde un módulo.
- Usa las mismas herramientas de lectura que las rutinas, con los permisos del
  usuario que chatea. No tiene `create_alert`.
- La respuesta llega completa, sin streaming, en una llamada síncrona. Los
  servidores corren con `workers = 6` y `limit_time_real = 1200`, así que el tope
  de 90 segundos por turno entra con margen.
- **Máximo de turnos de chat simultáneos (decisión del diseño):** 2 en toda la
  base, configurable. Un turno ocupa un worker HTTP mientras espera al proveedor,
  y esos 6 workers son los mismos que atienden el POS. Si ya hay 2 en curso, el
  chat responde que está ocupado y que se reintente. Si esto molesta en el uso
  real, el paso siguiente es pasar el chat a asíncrono (turno encolado y respuesta
  por bus); no se hace en la versión 1.

### Consumo

`prometeo.ai.run`: una fila por corrida de rutina o turno de chat, con proveedor,
modelo, tokens de entrada y salida, costo, duración, llamadas a herramientas,
estado y error. Del chat se registra el consumo, no el contenido.

Pantalla **Consumo** (solo administradores): gasto del mes en curso contra el
tope, y tabla por rutina y por modelo con corridas, tokens y costo. Historial mes
a mes. Vistas nativas de Odoo (lista agrupada y pivot) salvo que no alcancen.

**Tope mensual** configurable en Ajustes. Al alcanzarlo, las rutinas dejan de
correr (la corrida queda registrada como omitida por tope), el chat responde que
se alcanzó el límite, y los administradores reciben una alerta. El tope solo
cuenta modelos con precio cargado; la pantalla avisa si hubo consumo sin precio.

### Permisos

Dos grupos **(decisión del diseño)**:

- **Usuario del agente:** ve sus alertas, usa el chat, ve las rutinas visibles
  para él.
- **Administrador del agente:** crea y edita rutinas, configura proveedores,
  modelos y límites, ve consumo y todas las alertas.

### Menú

Agente IA → Alertas · Chat · Rutinas · Consumo · Configuración (proveedores y
modelos). Ajustes → Agente IA con bloques: Modelo por defecto, Límites, Tope de
gasto, Resumen diario.

## Riesgos aceptados

- **Los datos salen de Odoo.** Lo que el agente lee viaja al proveedor de IA
  elegido. Es inherente a la idea; se documenta en la descripción del módulo.
- **Instrucciones escondidas en los datos.** Un texto dentro de un registro
  (nombre de producto, nota) podría intentar dirigir al agente. Como no hay
  herramientas de escritura, el daño máximo es una alerta falsa. Este riesgo crece
  el día que se sumen acciones y hay que revisarlo ahí.

## Etapas posteriores (fuera de este diseño)

1. Canal WhatsApp para alertas y resumen diario.
2. Acciones con aprobación: el agente propone (actividad asignada, borrador de
   orden de compra, borrador de traslado) y una persona aprueba con un botón desde
   la alerta. Nunca valida, confirma ni borra solo. El modelo de alerta debería
   poder alojar una acción propuesta sin rediseño.
3. Crear rutinas desde el chat.

## A cargo de quien construye

- Estructura interna de archivos y nombres de campos.
- Texto de las instrucciones de sistema y de las rutinas precargadas.
- Formato exacto de los mensajes de herramientas por proveedor.
- Diseño visual del chat y de la bandeja, siguiendo los módulos OWL existentes.
- Tests: el repo los usa; las llamadas a proveedores van simuladas.

## Pendiente de Alexis

- Con qué proveedor y clave de API se prueba de punta a punta, y si los datos de
  la base `prod` local pueden salir a ese proveedor durante el desarrollo. Sin
  eso, los adaptadores y las rutinas precargadas se verifican solo con respuestas
  simuladas y la prueba contra datos reales queda como tarea manual.
