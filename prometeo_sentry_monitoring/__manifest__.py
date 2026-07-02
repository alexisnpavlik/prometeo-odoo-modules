# -*- coding: utf-8 -*-
{
    'name': 'Prometeo Sentry Monitoring',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Error Tracking Frontend/POS with Sentry JS SDK',
    'description': """
        Módulo para capturar errores del lado frontend (web backend y Punto de Venta) 
        y enviarlos a Sentry.
        
        Configuración:
        - El DSN se lee de la variable de entorno SENTRY_DSN o del parámetro del sistema 
          `prometeo_sentry_monitoring.sentry_dsn`.
    """,
    'author': 'Prometeo',
    'website': 'https://www.prometeo.com.ar/',
    'license': 'AGPL-3',
    'depends': [
        'point_of_sale',
        'web',
    ],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'prometeo_sentry_monitoring/static/src/js/error_tracking_poc.js',
            'prometeo_sentry_monitoring/static/src/js/sentry_backend_init.js',
        ],
        'point_of_sale._assets_pos': [
            'prometeo_sentry_monitoring/static/src/js/error_tracking_poc.js',
            'prometeo_sentry_monitoring/static/src/js/sentry_pos_init.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
}
