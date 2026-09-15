# -*- coding: utf-8 -*-
"""Pasa la ciudad del cliente de texto libre a la lista de ciudades por provincia.

Hasta 18.0.3.5.0 la ciudad era un Char: la misma localidad entraba escrita de varias
formas y no había forma de filtrar por provincia. Ahora es cvi.city, colgada de las
provincias que ya trae Odoo.

Las ciudades se crean con el texto que había, SIN provincia: adivinarla sería
inventar un dato. Quedan listadas en el log para que administración les cargue la
provincia desde Configuración → Ciudades.

Odoo borra la columna del texto libre al terminar la actualización, así que lo que no
quede apuntado acá se pierde: por eso se crea una ciudad por cada valor distinto,
incluso los escritos raro.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Crea una ciudad por texto distinto y apunta a los clientes que lo tenían."""
    if not version:
        return
    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'cvi_customer' AND column_name = 'city'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        SELECT DISTINCT btrim(city) FROM cvi_customer
         WHERE btrim(coalesce(city, '')) <> ''
         ORDER BY 1
    """)
    names = [row[0] for row in cr.fetchall()]
    if not names:
        return
    created = []
    for name in names:
        cr.execute("SELECT id FROM cvi_city WHERE lower(name) = lower(%s) LIMIT 1", (name,))
        row = cr.fetchone()
        if row:
            city_id = row[0]
        else:
            cr.execute("""
                INSERT INTO cvi_city (name, active, create_uid, write_uid,
                                      create_date, write_date)
                     VALUES (%s, TRUE, 1, 1, now(), now())
                  RETURNING id
            """, (name,))
            city_id = cr.fetchone()[0]
            created.append(name)
        cr.execute("""
            UPDATE cvi_customer SET city_id = %s
             WHERE btrim(city) = %s AND city_id IS NULL
        """, (city_id, name))
    # La provincia del cliente es un related almacenado: se sincroniza con la de su
    # ciudad, que hoy está vacía y se completa sola cuando se la cargue.
    cr.execute("""
        UPDATE cvi_customer cu
           SET state_id = c.state_id
          FROM cvi_city c
         WHERE c.id = cu.city_id AND cu.state_id IS DISTINCT FROM c.state_id
    """)
    # Lo mismo con el texto que la agenda tiene copiado en cada cuota.
    cr.execute("""
        UPDATE cvi_installment i
           SET city = c.name
          FROM cvi_customer cu
          LEFT JOIN cvi_city c ON c.id = cu.city_id
         WHERE i.customer_id = cu.id AND i.city IS DISTINCT FROM c.name
    """)
    if created:
        _logger.warning(
            "Ciudades creadas desde el texto libre, SIN provincia (cargarla en "
            "Configuración → Ciudades): %s", ", ".join(created),
        )
