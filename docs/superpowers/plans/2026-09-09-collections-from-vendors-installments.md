# Collections From Vendors Installments Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corregir fallos demostrables de aislamiento multiempresa y actualización de mora, validar entradas del dashboard y evaluar con una prueba real el riesgo de cobros concurrentes.

**Architecture:** Mantener modelos y endpoints actuales. Los filtros de empresa se validan una sola vez y se aplican a todas las consultas. Los importes y estados almacenados se refrescan dentro de la transacción que los consume. La concurrencia solo se cambia si un test con dos cursores reproduce una sobreimputación.

**Tech Stack:** Odoo 18, Python, PostgreSQL, ORM Odoo y TransactionCase.

**Spec:** `collections_from_vendors_installments/README.md`.

## Global Constraints

- Trabajar en `analysis/collections-from-vendors-installments`, creada desde `main`.
- Sin dependencias externas ni cambios destructivos.
- Mantener roles, contrato JSON y reglas multiempresa.
- Aplicar TDD: fallo esperado, cambio mínimo y prueba verde.
- No agregar índices sin evidencia de `EXPLAIN` sobre una base representativa.

---

### Task 1: Aislamiento multiempresa y entradas del dashboard

**Files:**
- Modify: `collections_from_vendors_installments/controllers/dashboard_controller.py`
- Test: `collections_from_vendors_installments/tests/test_dashboard_controller.py`

**Interfaces:**
- Consumes: `company`, `page`, `per_page`, `model`, fechas y búsqueda de los endpoints actuales.
- Produces: `_cvi_parse_company(env, company)` y filtros consistentes para métricas, gráficos, mapa, tabla y CSV.

- [ ] Agregar tests con dos empresas habilitadas que demuestren que `portfolio_by_collector.collected` y `vendor_stock` respetan la empresa seleccionada.
- [ ] Agregar tests para empresa, paginación y modelo inválidos; deben generar un error funcional traducible, no `ValueError` ni seleccionar silenciosamente tarjetas.
- [ ] Probar la búsqueda actual por nombre y DNI de `cvi.customer`; cambiar el dominio únicamente si el test demuestra que falla.
- [ ] Ejecutar los tests y registrar RED.
- [ ] Implementar `_cvi_parse_company()` y helpers mínimos para reutilizar el filtro validado.
- [ ] Aplicar la empresa seleccionada a los cobros por cobrador y al stock de vendedores.
- [ ] Ejecutar GREEN y la suite del controlador.
- [ ] Commit: `fix(cvi): enforce dashboard company filters`.

### Task 2: Mantener actualizada la antigüedad de mora

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_installment.py`
- Modify: `collections_from_vendors_installments/models/cvi_card.py` solo si el recálculo del resumen lo requiere
- Test: `collections_from_vendors_installments/tests/test_recovery.py`

**Interfaces:**
- Consumes: `_cron_update_overdue()` y `_compute_overdue_info()`.
- Produces: `state`, `days_overdue` y `amount_overdue` actualizados cada ejecución diaria.

- [ ] Agregar un test que simule una cuota ya vencida, avance la fecha efectiva y ejecute el cron.
- [ ] Verificar RED: `days_overdue` debe quedar desactualizado con la implementación actual.
- [ ] Ampliar el cron para recalcular también cuotas vencidas abiertas y los resúmenes de sus tarjetas, sin recorrer cuotas pagadas o tarjetas cerradas.
- [ ] Verificar que la tolerancia, las cuotas parciales y la comisión mantienen su comportamiento.
- [ ] Ejecutar GREEN y `test_agenda.py`, `test_installment_schedule.py`, `test_recovery.py`.
- [ ] Commit: `fix(cvi): refresh overdue age in daily cron`.

### Task 3: Probar y, si corresponde, serializar cobros concurrentes

**Files:**
- Modify: `collections_from_vendors_installments/models/cvi_payment.py` solo si se reproduce la carrera
- Test: `collections_from_vendors_installments/tests/test_payment.py` o un nuevo `tests/test_payment_concurrency.py`

**Interfaces:**
- Consumes: `CviPayment.action_post()` y `_cvi_allocate()`.
- Produces: prueba con dos cursores; si falla, bloqueo con `SELECT ... FOR UPDATE` antes de leer residuales.

- [ ] Construir dos transacciones independientes sobre la misma tarjeta y sincronizarlas para que ambas intenten cobrar el mismo residual.
- [ ] Si PostgreSQL/Odoo ya serializa correctamente, conservar solo el test y documentar la evidencia; no agregar bloqueo redundante.
- [ ] Si se reproduce sobreimputación, bloquear la fila de `cvi_card`, invalidar las cuotas y volver a leer residuales antes de asignar.
- [ ] Verificar que un cobro concurrente espera o se rechaza y que la suma imputada nunca supera la deuda.
- [ ] Ejecutar `test_payment.py`, `test_payment_wizard.py` y `test_settlement.py`.
- [ ] Commit: `fix(cvi): serialize concurrent payment allocation` o `test(cvi): cover concurrent payment allocation`.

### Task 4: Documentación y verificación integral

**Files:**
- Modify: `collections_from_vendors_installments/README.md`
- Review: todo el módulo y los commits anteriores

- [ ] Actualizar “Fuera de alcance” porque rendiciones, supervisión, morosidad, recuperaciones, clientes problemáticos, GPS, fotos y dashboard ya existen.
- [ ] Documentar validaciones visibles nuevas del dashboard y la garantía de concurrencia si hubo cambio funcional.
- [ ] Ejecutar la suite completa del módulo en la base disponible.
- [ ] Ejecutar `python3 -m compileall -q collections_from_vendors_installments`, parseo XML/CSV y `git diff --check`.
- [ ] Revisar que no haya migración ni índices sin medición.
- [ ] Commit: `docs(cvi): align README with implemented scope`.

