from . import models
from . import controllers

def pre_init_check(cr):
    from odoo.service import common
    from odoo.exceptions import ValidationError
    version_info = common.exp_version()
    server_version = version_info.get('server_version', '')
    if not server_version.startswith('18.'):
        raise ValidationError(
            'This module supports Odoo 18.x series. Your Odoo version is {}.'.format(server_version)
        )
    return True
