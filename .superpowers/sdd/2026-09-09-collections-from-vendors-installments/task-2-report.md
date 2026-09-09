# Task 2 — Mantener actualizada la antigüedad de mora

## Resultado

El cron diario ahora vuelve a seleccionar las cuotas vencidas que siguen
abiertas, además de las pendientes y parciales que ya vencieron. Tras recalcular
el estado de esas cuotas, fuerza el cálculo almacenado de `days_overdue` y
`amount_overdue` únicamente en las tarjetas afectadas.

La selección se limita a tarjetas `sold`, `routed` y `active`; por lo tanto no
recorre cuotas `paid` ni tarjetas `draft`, `done`, `recovered` o `cancel`.
No se modificaron roles, reglas multiempresa, contrato JSON, índices ni
dependencias.

## Prueba agregada

`TestCviRecovery.test_cron_refreshes_days_overdue_for_open_overdue_installments`
crea la tarjeta vencida del fixture, conserva su antigüedad actual, avanza la
fecha efectiva un día con `odoo.tests.common.freeze_time` y ejecuta el cron. La
aserción lee el campo almacenado tras invalidar su caché y exige exactamente un
día más. `freeze_time` es la utilidad de pruebas incluida en Odoo; no se agregó
ninguna librería externa.

La mutación que esta prueba detecta es retirar `overdue` del dominio del cron o
dejar de recalcular `_compute_overdue_info()`: en ambos casos la tarjeta guarda
la antigüedad del día anterior.

## RED

Comando ejecutado:

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable \
  --test-tags /collections_from_vendors_installments:TestCviRecovery.test_cron_refreshes_days_overdue_for_open_overdue_installments \
  --workers 0 --http-port 8079 --stop-after-init --no-http
```

Evidencia relevante de la implementación anterior:

```text
Cron de cuotas vencidas: 0 cuotas revisadas
FAIL: TestCviRecovery.test_cron_refreshes_days_overdue_for_open_overdue_installments
AssertionError: 2403 != 2404
1 failed, 0 error(s) of 1 tests when loading database 'calidad'
```

Esto demuestra que las cuotas que ya tenían estado `overdue` quedaban fuera del
cron y que la antigüedad almacenada no avanzaba.

## GREEN

Se ejecutó el mismo test tras el cambio:

```text
Cron de cuotas vencidas: 3 cuotas revisadas
0 failed, 0 error(s) of 1 tests when loading database 'calidad'
```

Luego se ejecutaron las suites de alcance:

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable \
  --test-tags /collections_from_vendors_installments:TestCviAgenda,/collections_from_vendors_installments:TestCviInstallmentSchedule,/collections_from_vendors_installments:TestCviRecovery \
  --workers 0 --http-port 8079 --stop-after-init --no-http
```

Resultado:

```text
collections_from_vendors_installments: 50 tests 16.18s 7345 queries
0 failed, 0 error(s) of 44 tests when loading database 'calidad'
```

`TestCviInstallmentSchedule` cubre la tolerancia de mora; las suites de agenda
y recuperación cubren cuotas pagadas, comisión y exclusión de tarjetas
recuperadas de la cobranza. Todas permanecieron verdes.

## Verificaciones adicionales

```bash
git diff --check
python3 -m compileall -q collections_from_vendors_installments
```

Ambos comandos finalizaron sin salida ni errores.

## Archivos modificados

- `collections_from_vendors_installments/models/cvi_installment.py`
- `collections_from_vendors_installments/tests/test_recovery.py`
- `.superpowers/sdd/2026-09-09-collections-from-vendors-installments/task-2-report.md`

## Autorrevisión

- El dominio conserva el criterio de vencimiento `date_due < today`, incorpora
  sólo estados impagos (`pending`, `partial`, `overdue`) y limita la tarjeta a
  los tres estados abiertos de cobranza.
- Se conservan tolerancia, cobros parciales y comisiones: el estado sigue siendo
  calculado por `_compute_state()` y no cambió su lógica; el cron sólo actualiza
  registros que esa lógica ya puede evaluar.
- El resumen se recalcula para `candidates.mapped("card_id")`, sin una búsqueda
  adicional ni recorrido de tarjetas cerradas o cuotas pagadas.
- No fue necesario modificar `cvi_card.py`: `_compute_overdue_info()` ya expresa
  correctamente el resumen; faltaba invocarlo cuando el tiempo cambia.

## Preocupaciones

Las corridas contra la base compartida `calidad` muestran advertencias
preexistentes de etiquetas de campos duplicadas y GC de archivos de filestore
ausentes. No produjeron fallos de prueba ni provienen de los archivos cambiados.
