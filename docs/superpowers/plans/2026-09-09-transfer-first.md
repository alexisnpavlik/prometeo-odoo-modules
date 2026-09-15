# Transferencias antes de compras

**Objetivo:** recomendar y preparar traslados de excedentes antes de comprar al proveedor.

**Diseño:** conservar estimadores y filtros existentes. Distinguir destinos a abastecer de posibles orígenes; reservar en cada origen su cobertura, plazo y seguridad. Distribuir únicamente excedente físico libre, sin financiarlo con entradas futuras. Guardar propuestas con origen/destino/cantidad y calcular compra residual. El usuario prepara movimientos desde un botón con sus permisos de Inventario; nunca se validan entregas automáticamente. Las propuestas pendientes bloquean la generación de órdenes; tras preparar movimientos se exige recalcular. La operación intercompañía utiliza una salida y recepción explícitas por tránsito compartido, encadenadas; no delega la elección de destino a un partner ambiguo.

**Validación:** escenarios de excedente, reserva del origen, entradas futuras, misma/intercompañía, permisos, duplicados, solo traslados y compra residual. Suite Odoo base/EWMA, revisión independiente y prueba reversible de instalación en prod.

- [x] Implementar asignación conservadora y propuestas persistidas, incluyendo seguridad de orígenes actuales e históricos.
- [x] Implementar preparación de movimientos, bloqueo de compras con propuestas pendientes y recálculo obligatorio.
- [x] Exponer selección de orígenes, detalle de traslados y compra residual; documentar.
- [x] Validar escenarios y suite, revisar y desplegar con respaldo.

**Resultado:** suite base/EWMA de 150 pruebas aprobada; otras 16 pruebas de traslados aprobadas tras corregir el redondeo de la necesidad antes de asignar existencias. Producción actualizada a 18.0.1.3.0 con respaldo; simulación sin guardar movimientos ni compras y controles de integridad sin cambios.
