# Task 1 — Aislamiento multiempresa y entradas del dashboard

## Alcance entregado

- Se agregó `_cvi_parse_company(env, company)` y `_cvi_company_ids()` para validar
  la empresa solicitada contra `env.companies` y reutilizar el conjunto resultante.
- KPIs, gráficos, mapa, tabla y CSV conservan sus contratos; las consultas SQL y el
  dominio ORM reciben el mismo scope de empresas. En particular, los cobros por
  cobrador y `vendor_stock` ya respetan la empresa seleccionada.
- La tabla y el CSV rechazan modelos distintos de `cards` e `installments`. La tabla
  también rechaza página o tamaño de página no numéricos, menores a uno o mayores a
  200, mediante `UserError` traducible.
- Se caracterizó la búsqueda por nombre y DNI de `cvi.customer`. Pasó con el dominio
  existente `("customer_id", "ilike", search)` gracias a
  `_rec_names_search = ["name", "dni"]`; no se modificó ese dominio.

## TDD

### RED

Comando focalizado (con módulo actualizado):

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviDashboardController \
  --workers 0 --http-port 8079 --stop-after-init --no-http
```

Salida relevante antes del cambio de producción:

```text
AttributeError: 'CviDashboardController' object has no attribute '_cvi_parse_company'
AttributeError: 'CviDashboardController' object has no attribute '_cvi_parse_pagination'
FAIL: ...test_invalid_records_model_is_a_functional_error
AssertionError: UserError not raised
FAIL: ...test_selected_company_filters_collected_by_collector
AssertionError: 8000.0 != 7000.0
FAIL: ...test_selected_company_filters_vendor_stock
... ['Vendedores/Vendedor Test', 'Vendedores Empresa Dos/Vendedor Empresa Dos']
... != ['Vendedores Empresa Dos/Vendedor Empresa Dos']
ERROR ... 3 failed, 5 error(s) of 27 tests
```

Durante la autorrevisión se agregó `company=0` al test de entrada inválida y se
repitió el RED:

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable \
  --test-tags /collections_from_vendors_installments:TestCviDashboardController.test_invalid_company_is_a_functional_error \
  --workers 0 --http-port 8079 --stop-after-init --no-http
```

Salida relevante:

```text
FAIL: Subtest ...test_invalid_company_is_a_functional_error (company=0)
AssertionError: UserError not raised
ERROR ... 1 failed, 0 error(s) of 1 tests
```

### GREEN

Comando final:

```bash
docker exec odoo-odoo-1 odoo -d calidad -u collections_from_vendors_installments \
  --test-enable --test-tags /collections_from_vendors_installments:TestCviDashboardController \
  --workers 0 --http-port 8079 --stop-after-init --no-http
```

Salida relevante:

```text
collections_from_vendors_installments: 29 tests 13.58s 6716 queries
0 failed, 0 error(s) of 27 tests when loading database 'calidad'
```

También se ejecutó:

```bash
git diff --check
python3 -m compileall -q collections_from_vendors_installments
```

Ambos terminaron sin salida ni error.

## Archivos modificados

- `collections_from_vendors_installments/controllers/dashboard_controller.py`
- `collections_from_vendors_installments/tests/test_dashboard_controller.py`
- `.superpowers/sdd/2026-09-09-collections-from-vendors-installments/task-1-report.md`

## Autorrevisión

- Verifiqué que los filtros de empresa cubren las rutas de métricas mediante
  `_cvi_where`, pagos de KPI, pagos por cobrador, rendiciones y stock de vendedores.
- Verifiqué que mapa reutiliza `_cvi_where`, y que tabla y CSV comparten
  `_cvi_records_domain` validado.
- No se modificaron roles, reglas de registro ni estructura JSON; no hay índices,
  migraciones ni dependencias nuevas.
- Los tests nuevos usan datos reales de dos empresas habilitadas y mutan los valores
  que antes producían cada fuga, además de validar nombre/DNI y entradas inválidas.

## Preocupaciones

- La corrida de Odoo muestra advertencias preexistentes de etiquetas duplicadas y,
  al invocar helpers directamente desde `TransactionCase`, avisos de que no hay idioma
  de traducción detectado. Las excepciones usan `_()` y la suite final no tuvo fallos.
- La última corrida registró avisos de GC de filestore por archivos ausentes en la DB
  compartida `calidad`; no corresponden a estos archivos ni afectaron el resultado.
