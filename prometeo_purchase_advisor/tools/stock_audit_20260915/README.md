# Repetir la auditoría de lectura

Estos scripts documentan el corte histórico 2026-09-15. No ejecutar pruebas Odoo
con `--test-enable` en `prod`. Los scripts siguientes no crean ni corrigen movimientos.

Desde el host con Docker:

```sh
mkdir -p /tmp/advisor-stock-audit
python3 audit.py
python3 pos.py
python3 pos-pack.py
```

`audit.py`, `pos.py` y `pos-pack.py` usan consultas SELECT con `psql` dentro de
`odoo-postgres18-1`, usuario `odoo`, base `prod`; adaptar esos nombres si cambia
el entorno. Los JSON se guardan en `/tmp/advisor-stock-audit`.

`reconcile.py` y `backtest.py` se ejecutan como entrada de Odoo shell, con el
código de la versión 18.0.1.4.1 o posterior cargado. Ambos establecen la
transacción como READ ONLY y terminan con rollback. Ejemplo en este Docker:

```sh
docker exec -i odoo-odoo-1 odoo shell -c /etc/odoo/odoo.conf -d prod --no-http --workers=0 --max-cron-threads=0 < reconcile.py
docker exec -i odoo-odoo-1 odoo shell -c /etc/odoo/odoo.conf -d prod --no-http --workers=0 --max-cron-threads=0 < backtest.py
```

El backtest usa usuario2 con sudo para leer las compañías de la copia y su zona
horaria, almacenes2/5/6/9/12 y cortes fijos. Adaptar IDs/fechas antes de aplicarlo
a otra base. No cambia modelos ni permisos. La conciliación compara en la misma
zona horaria que el builder; el informe indica la utilizada en la ejecución.
