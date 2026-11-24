from odoo.addons.base.models.assetsbundle import ScssStylesheetAsset
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPosAssets(TransactionCase):
    """El SCSS del módulo compila dentro del bundle del POS (un error ahí rompe todo el CSS de la caja)."""

    def test_pos_scss_compiles(self):
        bundle = self.env["ir.qweb"]._get_asset_bundle("point_of_sale.assets_prod", css=True, js=False)
        assets = [asset for asset in bundle.stylesheets if isinstance(asset, ScssStylesheetAsset)]
        self.assertTrue(any("pos_promotions" in asset.url for asset in assets))
        source = "\n".join(asset.get_source() for asset in assets)
        assets[0].compile(source)
