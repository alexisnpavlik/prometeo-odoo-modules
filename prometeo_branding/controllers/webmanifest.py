from odoo import http

from odoo.addons.web.controllers.webmanifest import WebManifest

from ..branding import APP_ICON_PATH, BRAND_NAME, BRAND_THEME_COLOR, IMG_PATH


class PrometeoWebManifest(WebManifest):

    def _get_webmanifest(self):
        """Manifest de la app instalable con nombre, colores e íconos de Prometeo."""
        manifest = super()._get_webmanifest()
        if manifest.get("name") == "Odoo":
            manifest["name"] = BRAND_NAME
        manifest["background_color"] = "#FFFFFF"
        manifest["theme_color"] = BRAND_THEME_COLOR
        manifest["icons"] = [{
            "src": f"/{IMG_PATH}/icon-{size}.png",
            "sizes": f"{size}x{size}",
            "type": "image/png",
        } for size in (192, 512)]
        return manifest

    def _icon_path(self):
        """Ícono de la página offline y de los accesos a apps sin ícono propio."""
        return APP_ICON_PATH

    @http.route()
    def scoped_app(self, app_id, path="", app_name=""):
        """Página de instalación de una app (ej. el POS) con el ícono iOS de Prometeo."""
        response = super().scoped_app(app_id, path=path, app_name=app_name)
        response.qcontext["apple_touch_icon"] = f"/{IMG_PATH}/icon-ios.png"
        return response
