# Correcciones de QA de Venta en cuotas

**Objetivo:** resolver los cinco defectos funcionales del informe y verificar la auditoría ya corregida en `70f8618`.
**Referencia:** `/home/alexis/Documents/odoo-qa/2026-09-09-muebles-completa.md`.
**Arquitectura:** cambios acotados en las vistas, defaults del asistente, cálculos almacenados y dashboard. Mantener permisos y reglas de negocio existentes.
**Entorno:** Odoo 18; módulo `collections_from_vendors_installments`; validar primero en `qa_cvi_20260909_01a08779`.

1. [x] Reproducir guardado de supervisión con `Form`: contador visible 1, almacenado 0. Reproducir escritura de resultado y líneas juntos.
2. [x] Separar `_compute_counts` de `_compute_result`; corregir contadores previos al actualizar sin alterar el resultado manual ni el historial. Comprobar las dos regresiones y las 19 pruebas originales.
3. [x] Quitar `active_ids` de la expresión XML; usar `default_get` solo para `active_model == 'cvi.card'`. Verificar apertura vacía, selección y modelo ajeno. Exponer motivo de retiro antes de marcar, conservando su validación.
4. [x] Corregir rangos inclusivos con `N - 1`, usando una única fecha base. Acotar el scroll móvil al área disponible y evitar compresión del contenido; verificar 360, 390, 768 y 1440 px.
5. [x] Ejecutar suite completa, validar sintaxis/diff, actualizar versión y documentar evidencia. Aplicar el módulo corregido a `muebles` con respaldo previo y comprobar el servicio. La comprobación visual autenticada queda pendiente de acceso del usuario.

**Evidencia:** 382 pruebas, salida 0; muebles actualizado a 18.0.3.1.3; SUP/000001 reparada; contenedor reiniciado y healthy. Informe: `/home/alexis/Documents/odoo-qa/2026-09-09-correcciones-muebles.md`.
