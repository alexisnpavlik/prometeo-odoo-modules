{
    "name": "Agente IA",
    "version": "18.0.1.1.0",
    "category": "Productivity",
    "summary": "Agente de IA de solo lectura: rutinas, alertas y chat sobre los datos de Odoo",
    "description": """
        Agente de IA dentro de Odoo, de solo lectura, para dueños de negocio que no
        revisan cada módulo.

        - Rutinas: una instrucción en lenguaje natural más una frecuencia. Un cron
          cada 15 minutos corre las vencidas; el agente consulta los datos y, si
          encuentra algo, deja una alerta. Trae 5 plantillas (faltantes de stock,
          traslados pendientes, pérdidas de inventario, facturas de proveedor
          vencidas, cajas abiertas o con diferencia), visibles solo si el módulo
          que necesitan está instalado.
        - Alertas: bandeja propia, campana con contador en la barra superior,
          notificación inmediata para las de gravedad alta y resumen diario.
          Descartar silencia la alerta 30 días; resolver no.
        - Chat privado: ni el administrador ve las conversaciones de otros.
          Máximo 2 turnos simultáneos por base (configurable): cada turno ocupa
          un worker mientras espera al proveedor.
        - Proveedores: Claude (Anthropic), OpenAI (o compatibles, cambiando la URL
          base) y Google Gemini. "Actualizar modelos" trae los modelos nuevos sin
          actualizar el módulo; los precios no vienen de ninguna API y se cargan a
          mano (el módulo trae los conocidos al 2026-11-11).
        - Consumo: costo por corrida, pantalla mensual y tope de gasto.

        Importante:
        - Los datos que el agente lee viajan al proveedor de IA elegido.
        - La clave de API se guarda en la base, visible solo para el grupo
          Administrador del agente.
        - El agente lee con los permisos del usuario (chat) o del usuario
          "Ejecutar como" (rutinas), nunca como superusuario, y tiene una lista
          negra fija de modelos y de campos con nombre de secreto.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail", "bus"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/prometeo_ai_provider_data.xml",
        "data/digest_template.xml",
        "data/ir_cron.xml",
        "data/prometeo_ai_routine_template_data.xml",
        "views/provider_views.xml",
        "views/run_views.xml",
        "views/alert_views.xml",
        "views/routine_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "prometeo_ai_agent/static/src/scss/agent.scss",
            "prometeo_ai_agent/static/src/js/alert_systray.js",
            "prometeo_ai_agent/static/src/xml/alert_systray.xml",
            "prometeo_ai_agent/static/src/js/chat_action.js",
            "prometeo_ai_agent/static/src/xml/chat_action.xml",
            "prometeo_ai_agent/static/src/js/usage_action.js",
            "prometeo_ai_agent/static/src/xml/usage_action.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
