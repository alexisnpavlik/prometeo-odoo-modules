# Repetir la evaluación

Herramientas de diagnóstico fuera del runtime del addon. Python estándar para comparaciones; Odoo 18 con core y EWMA corregidos para exportación/verificación. No instalar dependencias nuevas en producción.

1. Preparar una **copia de la base**, con cron/correo deshabilitados, y un directorio de addons con el código que se desea evaluar. No usar el servidor activo para instalar la revisión.
2. Ejecutar `export_cases.py` por entrada estándar de `odoo shell`, con `ADVISOR_EXPORT=/tmp/advisor-backtest-month.jsonl.gz`. Poner `--addons-path=...` **antes de `shell`** para que se carguen los addons correctos.
3. Ejecutar `verify_odoo.py` de igual manera; `ADVISOR_CASES` apunta al archivo exportado y `ADVISOR_VERIFIED` al archivo de salida. Verifica todos los casos contra el motor actualizado y falla si cambian las tasas del baseline.
4. Copiar el archivo verificado al entorno de análisis y ejecutar `python3 compare.py casos.jsonl.gz comparacion.json` y `python3 retail_report.py casos.jsonl.gz retail.json`.

Forma del comando Odoo (ajustar rutas y DB a la copia):

```sh
odoo --addons-path=/ruta/addons-revision,/ruta/odoo/addons shell \
  -c /ruta/review.conf -d advisor_copia --no-http --max-cron-threads=0 \
  < export_cases.py
```

Ambos scripts Odoo ponen la transacción en solo lectura y terminan con rollback. Los parámetros concretos del ensayo están en el exportador: almacén 1 excluido y central 3 separado en `retail_report.py`; adaptar estos IDs para otra base. La exclusión de contactos internos usa las empresas de esa base. El usuario de diagnóstico debe tener acceso a todas las empresas evaluadas.

`actual_engine` identifica el ponderado **anterior al guard** (no necesariamente la versión actualmente desplegada); `guarded_odoo` proviene de ejecutar el código corregido. `weighted_calendar_p95` siempre usa días calendario. Los EWMA/SBA/TSB de `compare.py` son candidatos offline; no equivalen a la extensión EWMA configurada para descontar quiebres. Los inicializados con todo el entrenamiento y EWMA calendario p95 de `retail_report.py` son análisis exploratorios adicionales.

El exportador conserva explícitamente vacío `unreliable_stock_ids` al estimar el baseline, para poder reproducir el error antiguo. `verify_odoo.py` vuelve a construir cada ventana con el builder real y exporta el resultado corregido. `train_stock_valid` y `train_clamped` son diagnósticos, **no sustitutos del guard efectivo**.

Las métricas `fully_observable`/`daily_balance_available` solo indican saldos diarios compatibles con disponibilidad; no prueban ausencia de faltantes intradía. `short_units`/`excess_units` son desvíos contra ventas, no quiebres/excedentes de inventario medidos. El stock se reconstruye desde el presente: el ensayo no es un replay histórico con instantáneas archivadas.

Los archivos de casos incluyen IDs y ventas diarias reales: mantenerlos fuera del repositorio. El JSON agregado no contiene nombres ni ventas por producto.
