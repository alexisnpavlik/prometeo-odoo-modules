# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Apaga el filtro nativo por Categorías de PdV: este módulo lo reemplaza y quedaría invisible."""
    configs = env["pos.config"].with_context(active_test=False).search([("limit_categories", "=", True)])
    if not configs:
        return
    _logger.info(
        "pos_category_filter: se apagó limit_categories en %s. Configurar su filtro por categoría de producto.",
        ", ".join(configs.mapped("name")),
    )
    configs.with_context(bypass_categories_forbidden_change=True).write({"limit_categories": False})
