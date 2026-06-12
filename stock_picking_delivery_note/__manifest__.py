{
    "name": "Stock Picking - Notas en Vales de Entrega",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Muestra las notas internas de la operación en el reporte impreso de Vales de Entrega",
    "description": """
Este módulo extiende el reporte impreso de Vales de Entrega (stock.report_deliveryslip) 
para incluir las Notas / Observaciones internas (note) definidas en la operación de inventario (stock.picking).
Las notas se imprimen de forma elegante justo antes de la sección de firma.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["stock"],
    "data": [
        "report/report_deliveryslip_templates.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
