import base64
import json
import logging
import re

from odoo.tools import file_open

from .branding import BOT_AVATAR_PATH, BRAND_BOT_NAME, BRAND_NAME, BRAND_URL

_logger = logging.getLogger(__name__)

# Enlaces a odoo.com (con o sin utm) dentro del HTML de las plantillas.
_ODOO_URL_RE = re.compile(r"https?://www\.odoo\.com[^\"'\s<>\\]*")
# Dominio de ejemplo que se muestra cuando la base no tiene website_url.
_ODOO_SAMPLE_DOMAIN_RE = re.compile(r"\b(?:yourcompany|suempresa|tuempresa)\.odoo\.com\b")
# La palabra suelta; deja intactos OdooBot y las rutas /odoo/ en minúscula.
_ODOO_WORD_RE = re.compile(r"\bOdoo\b")


def _debrand_text(text):
    """Reemplaza enlaces, dominio de ejemplo y nombre de Odoo en un texto."""
    text = _ODOO_URL_RE.sub(BRAND_URL, text)
    text = _ODOO_SAMPLE_DOMAIN_RE.sub("prometeo.com.ar", text)
    return _ODOO_WORD_RE.sub(BRAND_NAME, text)


def _debrand_mail_templates(env):
    """Quita la marca Odoo del asunto y cuerpo de las plantillas de email, en todos los idiomas."""
    cr = env.cr
    cr.execute("""
        SELECT id, subject, body_html
          FROM mail_template
         WHERE subject::text ~ 'Odoo|odoo\\.com'
            OR body_html::text ~ 'Odoo|odoo\\.com'
    """)
    for template_id, subject, body_html in cr.fetchall():
        new_subject = {lang: _debrand_text(value or "") for lang, value in (subject or {}).items()}
        new_body = {lang: _debrand_text(value or "") for lang, value in (body_html or {}).items()}
        cr.execute(
            "UPDATE mail_template SET subject = %s::jsonb, body_html = %s::jsonb WHERE id = %s",
            (json.dumps(new_subject), json.dumps(new_body), template_id),
        )
        _logger.info("prometeo_branding: plantilla de email %s sin marca Odoo", template_id)
    env["mail.template"].invalidate_model(["subject", "body_html"])


def _rename_odoobot(env):
    """Renombra el partner de OdooBot y le pone el ícono de Prometeo."""
    partner = env.ref("base.partner_root", raise_if_not_found=False)
    if not partner:
        return
    with file_open(BOT_AVATAR_PATH, "rb") as avatar:
        partner.write({
            "name": BRAND_BOT_NAME,
            "image_1920": base64.b64encode(avatar.read()),
        })


def _set_web_app_name(env):
    """Nombre de la app instalable, salvo que ya tenga uno personalizado."""
    params = env["ir.config_parameter"].sudo()
    if params.get_param("web.web_app_name", "Odoo") == "Odoo":
        params.set_param("web.web_app_name", BRAND_NAME)


def post_init_hook(env):
    """Aplica los cambios de marca que viven en datos y no en vistas."""
    _debrand_mail_templates(env)
    _rename_odoobot(env)
    _set_web_app_name(env)
