# 🚀 Prometeo Odoo Modules (v18.0)

[![Odoo Version](https://img.shields.io/badge/Odoo-18.0-875A7B.svg)](https://www.odoo.com)
[![License: AGPL--3](https://img.shields.io/badge/License-AGPL--3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0-standalone.html)
[![License: LGPL--3](https://img.shields.io/badge/License-LGPL--3-lightgrey.svg)](https://www.gnu.org/licenses/lgpl-3.0-standalone.html)

Colección optimizada y auditada de módulos y adaptaciones de **Odoo v18.0** para entornos de producción. Este repositorio centraliza soluciones esenciales de **Localización Argentina (AFIP)**, mejoras avanzadas de **usabilidad y experiencia de usuario (UX)**, optimizaciones clave para el **Punto de Venta (POS)**, flujos de **Cuentas Corrientes & Finanzas**, y herramientas de administración **Multi-Compañía**.

---

## 📋 Índice

- [🚀 Características Principales](#-características-principales)
- [📂 Catálogo Completo de Módulos (55 Módulos)](#-catálogo-completo-de-módulos-55-módulos)
  - [1. Localización Argentina & AFIP](#1-localización-argentina--afip)
  - [2. Punto de Venta (POS)](#2-punto-de-venta-pos)
  - [3. Contabilidad & Finanzas](#3-contabilidad--finanzas)
  - [4. Inventario, Compras & Ventas](#4-inventario-compras--ventas)
  - [5. Productos & Catálogo](#5-productos--catálogo)
  - [6. Métricas, Dashboards & Monitoreo](#6-métricas-dashboards--monitoreo)
  - [7. Interfaz de Usuario & Base (Web)](#7-interfaz-de-usuario--base-web)
- [🏗️ Estándares de Desarrollo & Arquitectura](#️-estándares-de-desarrollo--arquitectura)
- [🧠 Documentación & Vault de Obsidian](#-documentación--vault-de-obsidian)
- [🛠️ Requisitos e Instalación](#️-requisitos-e-instalación)
  - [Dependencias de Python](#dependencias-de-python)
  - [Configuración en Odoo (`odoo.conf`)](#configuración-en-odoo-odooconf)
- [👥 Créditos y Agradecimientos](#-créditos-y-agradecimientos)
- [📄 Licencia](#-licencia)

---

## 🚀 Características Principales

* 🇦🇷 **Localización Argentina Completa**: Integración nativa con los servicios web de AFIP (Facturación Electrónica, Consulta de Padrón, Libro IVA Digital, Retenciones/Percepciones) mediante la librería `pyafipws` portada para Odoo 18.
* 🛒 **Punto de Venta (POS) Profesional**: Botones de descuento y recargo ágiles, control de perfiles de solo lectura, venta estructurada de packs, cuotas con tarjeta, log de auditoría de eliminaciones y parametrizaciones por defecto para evitar errores operativos en caja.
* 💳 **Cuentas Corrientes & Finanzas**: Módulo exclusivo de gestión informal de cuentas corrientes (retiros de mercancía con abonos parciales, límites de crédito y estados de cuenta imprimibles), además de transferencias internas entre diarios y cheques LATAM.
* 🏢 **Gestión Multi-Compañía Segura**: Herramientas de aislamiento visual y lógico (selectores de compañía seguros, colores dinámicos por empresa y generación automática de órdenes/facturas/remitos espejo inter-compañía).
* 📊 **KPIs y Métricas OWL**: Tableros analíticos en tiempo real con Chart.js para Inventario, POS, Facturación, Asesores de Venta y Listas de Precios.
* 🔍 **Trazabilidad y Monitoreo**: Historial de cambios en productos en el chatter, registro de motivos de borrado en POS y captura automática de excepciones frontend en Sentry.

---

## 📂 Catálogo Completo de Módulos (55 Módulos)

### 1. Localización Argentina & AFIP

Módulos diseñados para cumplir con las normativas impositivas, bancarias y de facturación de la República Argentina.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **WS AFIP Base** | [`l10n_ar_afipws`](./l10n_ar_afipws) | Conexión, administración de certificados digitales y pasarela base con AFIP. |
| **Facturación Electrónica** | [`l10n_ar_afipws_fe`](./l10n_ar_afipws_fe) | Emisión, validación y obtención de CAE para comprobantes electrónicos. |
| **POS Factura Electrónica** | [`l10n_ar_pos_afipws_fe`](./l10n_ar_pos_afipws_fe) | Emisión automática de comprobantes con CAE directamente desde la interfaz del POS. |
| **Bancos Argentinos** | [`l10n_ar_bank`](./l10n_ar_bank) | Listado preconfigurado y validación de bancos argentinos (CBU/Alias). |
| **Compras Argentina** | [`l10n_ar_purchase`](./l10n_ar_purchase) | Adaptación impositiva y de documentos LATAM para órdenes de compra y facturación de proveedores. |
| **Compras & Stock AR** | [`l10n_ar_purchase_stock`](./l10n_ar_purchase_stock) | Integración entre la valoración de remitos impositivos y la recepción de mercadería. |
| **Reportes Impositivos** | [`l10n_ar_reports`](./l10n_ar_reports) | Generación e impresión de reportes fiscales (Libro IVA Digital Compras/Ventas). |
| **Impuestos Base AR** | [`l10n_ar_tax`](./l10n_ar_tax) | Configuración de impuestos nacionales y provinciales (IVA, Percepciones/Retenciones IIBB). |
| **Fórmulas Python de Impuestos** | [`l10n_ar_tax_python`](./l10n_ar_tax_python) | Permite la aplicación de fórmulas dinámicas en Python dentro de las posiciones fiscales. |
| **Ratio de Impuestos** | [`l10n_ar_tax_ratio`](./l10n_ar_tax_ratio) | Proporcionalidad impositiva en comprobantes mixtos y notas de crédito. |
| **Compatibilidad Fiscal** | [`l10n_ar_tax_backward_compatibility`](./l10n_ar_tax_backward_compatibility) | Mantiene compatibilidad de esquemas impositivos en migraciones de versión. |
| **Cheques LATAM UX** | [`l10n_latam_check_ux`](./l10n_latam_check_ux) | Gestión extendida y optimizada de la cartera de cheques (propios y de terceros). |
| **UX Argentina** | [`l10n_ar_ux`](./l10n_ar_ux) | Adaptaciones visuales y de flujo requeridas para la contabilidad argentina. |

### 2. Punto de Venta (POS)

Extensiones para mejorar la velocidad de atención, la seguridad y el control del Punto de Venta en Odoo 18.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Card installment** | [`card_installment`](./card_installment) | Gestión de coeficientes de cuotas y recargos con tarjetas en los métodos de pago del POS. |
| **POS Close Draft Invoices** | [`pos_close_with_draft_invoices`](./pos_close_with_draft_invoices) | Permite cerrar la sesión de POS aunque queden facturas en borrador vinculadas a las órdenes. |
| **POS Deletion Reason Log** | [`pos_deletion_reason_log`](./pos_deletion_reason_log) | Audit trail: solicita motivo y registra anulaciones de orden/línea, bajas de cantidad o descuentos; incluye dashboard interactivo y export a Excel. |
| **POS Global Discount** | [`pos_global_discount_button`](./pos_global_discount_button) | Agrega un botón configurable para aplicar descuentos a todo el pedido de forma ágil. |
| **POS Global Surcharge** | [`pos_global_surcharge_button`](./pos_global_surcharge_button) | Agrega un botón 'Recargo' tipo toggle en el POS para aplicar/quitar un porcentaje de recargo global. |
| **POS Invoice Default Off** | [`pos_invoice_default_off`](./pos_invoice_default_off) | Desmarca por defecto la opción de solicitar factura al cobrar, acelerando el flujo de tickets. |
| **POS Pricelist Enforce** | [`pos_pricelist_enforce`](./pos_pricelist_enforce) | Corrige el comportamiento del POS que deja líneas a precio público en lugar de forzar la lista fija asignada. |
| **POS Print Last Session** | [`pos_print_last_session`](./pos_print_last_session) | Permite imprimir el reporte de cierre de caja correspondiente a la sesión anterior. |
| **POS Product Pack** | [`pos_product_pack`](./pos_product_pack) | Habilita la venta de productos compuestos (combos/packs) de forma integrada en el catálogo del POS. |
| **POS Sales Advisors** | [`pos_sales_advisor`](./pos_sales_advisor) | Trackeo de asesores de venta: selección en pantalla de pago, registro en la orden y dashboard OWL de métricas. |
| **POS Special Approval** | [`pos_special_approval_omax`](./pos_special_approval_omax) | Requiere la autorización con clave/pin de un supervisor para aplicar acciones críticas. |
| **POS Readonly User** | [`pos_user_readonly`](./pos_user_readonly) | Restringe el POS a un modo de solo lectura para perfiles de cajero específicos. |
| **POS Stock Readonly** | [`pos_user_stock_readonly`](./pos_user_stock_readonly) | Grupo de seguridad para cajeros sin permisos de edición de catálogo/stock, pero con visualización de stock real. |

### 3. Contabilidad & Finanzas

Flujos contables simplificados, cuentas corrientes informales y administración financiera.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Cuentas Corrientes - Retiros** | [`cuenta_corriente_retiros`](./cuenta_corriente_retiros) | Gestión informal de cuentas corrientes: retiros de mercadería con abonos parciales (sin asiento contable pesado), límite de crédito y estado de cuenta imprimible. |
| **Transferencias Internas** | [`account_internal_transfer`](./account_internal_transfer) | Facilita el traspaso y conciliación automática de fondos entre bancos y cajas de la misma empresa. |
| **Talonarios de Recibos** | [`account_payment_pro_receiptbook`](./account_payment_pro_receiptbook) | Control y numeración de cobros/pagos mediante el uso de talonarios de recibos físicos. |
| **Pagos Avanzados** | [`account_payment_pro`](./account_payment_pro) | Interfaz unificada y extendida para el procesamiento de cobros y pagos contables complejos. |
| **UX Contabilidad** | [`account_ux`](./account_ux) | Pequeños ajustes de usabilidad para acelerar la carga de facturas y la conciliación. |
| **Facturas Inter-Compañía** | [`account_invoice_inter_company`](./account_invoice_inter_company) | Genera automáticamente la factura espejo (compra/venta) en la empresa contraparte del grupo. |

### 4. Inventario, Compras & Ventas

Operaciones automatizadas, remitos e integración logística inter-compañía.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Actualización de Costos** | [`purchase_auto_update_cost`](./purchase_auto_update_cost) | Actualiza el costo de adquisición del producto de forma automática al recibir la compra. |
| **Hide Create Receipt** | [`stock_hide_create_receipt`](./stock_hide_create_receipt) | Oculta los botones de creación manual de nuevas recepciones en el flujo de almacén. |
| **Purchase/Sale Intercompany** | [`purchase_sale_inter_company`](./purchase_sale_inter_company) | Genera automáticamente una Sale Order (SO) en la empresa proveedora al confirmar una Purchase Order (PO). |
| **Purchase/Sale Stock Intercompany** | [`purchase_sale_stock_inter_company`](./purchase_sale_stock_inter_company) | Extiende la integración PO/SO propagando la entrega/recepción de stock sincronizada entre compañías. |
| **Stock Intercompany** | [`stock_intercompany`](./stock_intercompany) | Vincula la entrega de una empresa con la recepción automática en la empresa destino. |
| **Remitos de Entrega** | [`stock_picking_delivery_note`](./stock_picking_delivery_note) | Generación e impresión de remitos oficiales y notas de entrega personalizadas. |
| **Stock Picking Auto Qty** | [`stock_picking_auto_qty`](./stock_picking_auto_qty) | Auto-completa la cantidad hecha con la cantidad demandada en albaranes de salida. |
| **Conteo por Código de Barras** | [`stock_count_barcode`](./stock_count_barcode) | Sesiones de inventario rápido escaneando códigos de barra desde dispositivos móviles o lectores láser. |

### 5. Productos & Catálogo

Gestión del catálogo, control de cambios y restricciones multi-compañía sobre productos.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Product Default Settings** | [`product_default_settings`](./product_default_settings) | Valores por defecto y configuraciones automáticas para nuevos productos en el catálogo. |
| **Product Image Zoom** | [`product_image_zoom`](./product_image_zoom) | Amplía la imagen del producto al hacer clic en su ficha en el backend web. |
| **Product Pack** | [`product_pack`](./product_pack) | Define productos compuestos (packs/combos) con sus componentes y reglas de precio en backend. |
| **Product Change History** | [`product_change_history`](./product_change_history) | Postea en el chatter **todos** los campos editados del producto, garantizando auditabilidad. |
| **Product Company Restriction** | [`product_company_restriction`](./product_company_restriction) | Grupo que limita la creación/edición/borrado de productos a los de la propia empresa del usuario. |
| **Barcodes Generator** | [`barcodes_generator_abstract`](./barcodes_generator_abstract) · [`barcodes_generator_product`](./barcodes_generator_product) | Generación automática de códigos de barras (EAN13) para plantillas y variantes de producto. |

### 6. Métricas, Dashboards & Monitoreo

Tableros OWL con Chart.js sobre datos en vivo, más monitoreo de errores en producción.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Métricas de Inventario** | [`inventory_dashboard_metrics`](./inventory_dashboard_metrics) | KPIs de rotación, stock crítico, valorización por sucursal y dead stock. |
| **Métricas de POS** | [`pos_management_metrics`](./pos_management_metrics) | Dashboard e indicadores clave sobre ventas y arqueos de caja con exportación a Excel. |
| **Métricas de Facturación** | [`account_management_metrics`](./account_management_metrics) | Comprobantes por tipo (A/B/C, NC), facturación por sucursal/diario y cobros por medio de pago. |
| **Métricas de Listas de Precios** | [`pricelist_management_metrics`](./pricelist_management_metrics) | Comparativa de precio base vs. precio vigente por lista/sucursal, filtrable por categoría. |
| **Cambios de Precio (Góndola)** | [`product_price_change_metrics`](./product_price_change_metrics) | Lista de trabajo por sucursal con los productos que cambiaron de precio para reetiquetar en góndola. |
| **Sentry Monitoring** | [`prometeo_sentry_monitoring`](./prometeo_sentry_monitoring) | Captura excepciones de frontend (backend web y POS) y las envía a Sentry (`SENTRY_DSN`). |

### 7. Interfaz de Usuario & Base (Web)

Ajustes de framework para usabilidad y seguridad multi-empresa.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Web Company Color** | [`web_company_color`](./web_company_color) | Cambia el color de la barra superior de Odoo dinámicamente según la compañía activa. |
| **Multi Company Base** | [`base_multi_company`](./base_multi_company) | Base técnica (OCA) para agregar soporte multi-compañía a modelos personalizados. |

---

## 🏗️ Estándares de Desarrollo & Arquitectura

Todos los módulos en este repositorio siguen estrictamente las mejores prácticas para **Odoo v18.0**:

1. **Aislamiento Multi-Compañía Lógico y Visual**:
   - En backend, la seguridad multi-empresa se garantiza mediante `check_company=True` en relaciones y reglas de registro `ir.rule` basadas en `[('company_id', 'in', company_ids)]`.
   - En frontend web, `web_company_color` aplica el color corporativo oficial en el navbar superior para prevenir cargas accidentales en empresas no deseadas.
2. **Desarrollo en POS (OWL Framework)**:
   - Patcheo de componentes nativos (`ControlButtons`, `PosOrderline`, `PaymentScreen`) extendiendo la clase vía patch de OWL sin sobrescribir código base para mantener compatibilidad con actualizaciones de Odoo 18.
3. **Optimización de Consultas SQL en Dashboards**:
   - Los módulos de métricas utilizan SQL directo optimizado con CTEs e inyección de `company_ids` vía `request.env.companies.ids` para asegurar respuestas en milisegundos sin sobrecargar el ORM.

---

## 🧠 Documentación & Vault de Obsidian

La arquitectura detallada de cada módulo, sus dependencias cruzadas y gotchas de desarrollo se encuentran documentados y vinculados en el **Vault de Obsidian de Prometeo**:

- 📂 **Ubicación en Vault**: `02-Prometeo/01-Odoo/Modulos/`
- 🗺️ **MOC Principal de Módulos**: `[[Modulos]]`
- 🎨 **Visualización en Grafo**: El archivo `.obsidian/graph.json` contiene la configuración de colores oficial por subsistema (POS, AFIP, Contabilidad, Métricas, Inventario, Productos, UI-Base).

---

## 🛠️ Requisitos e Instalación

### Dependencias de Python

Para interactuar con los servicios de AFIP y funcionalidades avanzadas, instala las dependencias de Python:

```bash
pip install -r requirements.txt
```

> [!IMPORTANT]
> El archivo [`requirements.txt`](./requirements.txt) incluye la versión optimizada de `pyafipws` para Odoo 18. Asegúrate de compilar y tener las librerías del sistema instaladas (`libssl-dev` y `swig` en distribuciones Debian/Ubuntu) para la correcta compilación de `M2Crypto`.

### Configuración en Odoo (`odoo.conf`)

Agrega la ruta de este repositorio a tu archivo de configuración `odoo.conf`:

```ini
[options]
addons_path = /ruta/a/odoo/addons, /ruta/a/prometeo-odoo-modules
```

Luego, reinicia el servicio de Odoo, activa el **Modo Desarrollador**, ve a **Aplicaciones** > **Actualizar lista de aplicaciones** e instala los módulos que requieras.

---

## 👥 Créditos y Agradecimientos

Este repositorio recopila, adapta y optimiza contribuciones de la comunidad de Odoo:

* **[Asociación Civil Adhoc (ADHOC SA)](https://www.adhoc.com.ar/)**: Creadores de la base de localización argentina y componentes financieros clave.
* **[Odoo Community Association (OCA)](https://odoo-community.org/)**: Por mantener estándares de desarrollo de código abierto de alta calidad.
* **Moldeo Interactive**: Por los desarrollos iniciales de facturación electrónica en Argentina.

---

## 📄 Licencia

Colección bajo licencias libres **GNU AGPL-3** y **GNU LGPL-3**. Revisa el archivo `__manifest__.py` de cada módulo para conocer su licencia específica.

---
*Desarrollado y adaptado para Odoo 18 por [Alexis Medina](mailto:alexisnpavlik@gmail.com).*