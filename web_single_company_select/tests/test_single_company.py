from odoo.tests import HttpCase, tagged

TEST_SUITE = "@web_single_company_select"


@tagged("post_install", "-at_install")
class TestSingleCompanySelect(HttpCase):
    """Corre los tests JS (HOOT) del módulo dentro de un navegador real."""

    def _hoot_suite_hash(self, name):
        """Hash del filtro de HOOT, igual al de web/tests/test_js.py."""
        value = 0
        for char in name:
            value = ((value << 5) - value + ord(char)) & 0xFFFFFFFF
        return f"{value:08x}"

    def test_patch_in_backend_bundle(self):
        """El parche del selector entra en el bundle del backend."""
        files = self.env["ir.qweb"]._get_asset_content("web.assets_backend")[0]
        urls = [asset["url"] for asset in files]
        self.assertIn("/web_single_company_select/static/src/js/single_company.js", urls)
        self.assertIn("/web_single_company_select/static/src/xml/switch_company_menu.xml", urls)

    def test_hoot_suite(self):
        """Tests de navegador: una sola empresa activa en todos los caminos."""
        suite_id = self._hoot_suite_hash(TEST_SUITE)
        self.browser_js(
            f"/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&id={suite_id}",
            "",
            "",
            login="admin",
            timeout=180,
            success_signal="[HOOT] Test suite succeeded",
            error_checker=lambda message: "[HOOT]" not in message,
        )
