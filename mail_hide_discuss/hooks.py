# -*- coding: utf-8 -*-


def uninstall_hook(env):
    """Restaura el menú Conversaciones al desinstalar el módulo."""
    menu = env.ref("mail.menu_root_discuss", raise_if_not_found=False)
    if menu:
        menu.active = True
