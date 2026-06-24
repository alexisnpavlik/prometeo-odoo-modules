from . import models


def post_init_hook(env):
    """Asigna el producto Recargo a las pos.config existentes sin uno."""
    product = env.ref(
        "pos_global_surcharge_button.product_product_surcharge",
        raise_if_not_found=False,
    )
    if not product:
        return
    configs = env["pos.config"].search([("surcharge_product_id", "=", False)])
    if configs:
        configs.write({"surcharge_product_id": product.id})
