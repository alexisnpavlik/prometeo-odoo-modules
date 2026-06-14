# 🚀 Prometeo Odoo Modules (v18.0)

[![Odoo Version](https://img.shields.io/badge/Odoo-18.0-875A7B.svg)](https://www.odoo.com)
[![License: AGPL--3](https://img.shields.io/badge/License-AGPL--3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0-standalone.html)
[![License: LGPL--3](https://img.shields.io/badge/License-LGPL--3-lightgrey.svg)](https://www.gnu.org/licenses/lgpl-3.0-standalone.html)

Colección optimizada de módulos y adaptaciones de **Odoo v18.0** para entornos de producción. Este repositorio centraliza soluciones esenciales de **Localización Argentina (AFIP)**, mejoras avanzadas de **usabilidad y experiencia de usuario (UX)**, optimizaciones clave para el **Punto de Venta (POS)**, y herramientas de administración **Multi-Compañía**.

---

## 📋 Índice

- [🚀 Características Principales](#-características-principales)
- [📂 Catálogo de Módulos](#-catálogo-de-módulos)
  - [1. Localización Argentina & AFIP](#1-localización-argentina--afip)
  - [2. Punto de Venta (POS)](#2-punto-de-venta-pos)
  - [3. Contabilidad & Finanzas](#3-contabilidad--finanzas)
  - [4. Inventario, Compras & Ventas](#4-inventario-compras--ventas)
  - [5. Interfaz de Usuario & Base (Web)](#5-interfaz-de-usuario--base-web)
- [🛠️ Requisitos e Instalación](#️-requisitos-e-instalación)
  - [Dependencias de Python](#dependencias-de-python)
  - [Configuración en Odoo (`odoo.conf`)](#configuración-en-odoo-odooconf)
- [👥 Créditos y Agradecimientos](#-créditos-y-agradecimientos)
- [📄 Licencia](#-licencia)

---

## 🚀 Características Principales

*   🇦🇷 **Localización Argentina Completa**: Integración nativa con los servicios web de AFIP (Facturación Electrónica, Consulta de Padrón, etc.) mediante la librería `pyafipws` portada para Odoo 18.
*   🛒 **Punto de Venta (POS) Profesional**: Botones de descuento ágiles, control de perfiles de solo lectura, venta estructurada de packs, y parametrizaciones por defecto para evitar errores operativos en caja.
*   🏢 **Gestión Multi-Compañía Segura**: Herramientas visuales y de control del framework (como selectores de compañía seguros y colores dinámicos) que evitan registros accidentales en empresas incorrectas.
*   📊 **KPIs y Métricas**: Tableros analíticos e indicadores integrados para Inventario y POS, listos para la toma de decisiones.
*   💳 **Usabilidad Financiera (LATAM)**: Gestión refinada de transferencias internas, cobros complejos y administración de cheques de terceros.

---

## 📂 Catálogo de Módulos

### 1. Localización Argentina & AFIP

Módulos diseñados para cumplir con las normativas impositivas y de facturación de la República Argentina.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **WS AFIP Base** | [`l10n_ar_afipws`](./l10n_ar_afipws) | Conexión, administración de certificados digitales y pasarela base con AFIP. |
| **Facturación Electrónica** | [`l10n_ar_afipws_fe`](./l10n_ar_afipws_fe) | Emisión, validación y obtención de CAE para comprobantes electrónicos. |
| **POS Factura Electrónica** | [`l10n_ar_pos_afipws_fe`](./l10n_ar_pos_afipws_fe) | Emisión automática de comprobantes con CAE directamente desde la interfaz del POS. |
| **Cheques LATAM UX** | [`l10n_latam_check_ux`](./l10n_latam_check_ux) | Gestión extendida y optimizada de la cartera de cheques (propios y de terceros). |
| **UX Argentina** | [`l10n_ar_ux`](./l10n_ar_ux) | Adaptaciones visuales y de flujo requeridas para la contabilidad argentina. |
| **Adicionales AR** | `l10n_ar_*` | Módulos complementarios para compras, impuestos (`l10n_ar_tax`), bancos y reportes específicos. |

### 2. Punto de Venta (POS)

Extensiones para mejorar la velocidad de atención, la seguridad y el control del Punto de Venta.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **POS Global Discount** | [`pos_global_discount_button`](./pos_global_discount_button) | Agrega un botón configurable para aplicar descuentos a todo el pedido de forma ágil. |
| **POS Invoice Default Off** | [`pos_invoice_default_off`](./pos_invoice_default_off) | Desmarca por defecto la opción de solicitar factura al cobrar, acelerando el flujo de tickets. |
| **POS Management Metrics** | [`pos_management_metrics`](./pos_management_metrics) | Dashboard y reportes con indicadores clave sobre ventas y arqueos de caja. |
| **POS Product Pack** | [`pos_product_pack`](./pos_product_pack) | Habilita la venta de productos compuestos (combos/packs) de forma integrada. |
| **POS Readonly User** | [`pos_user_readonly`](./pos_user_readonly) | Permite restringir el POS a un modo de solo visualización para ciertos perfiles de cajero. |
| **POS Print Last Session** | [`pos_print_last_session`](./pos_print_last_session) | Permite imprimir el reporte de cierre de caja correspondiente a la sesión anterior. |
| **POS Special Approval** | [`pos_special_approval_omax`](./pos_special_approval_omax) | Requiere la autorización de un supervisor para aplicar acciones críticas (devoluciones, descuentos). |

### 3. Contabilidad & Finanzas

Flujos contables simplificados y adaptaciones de usabilidad para el equipo de administración.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Transferencias Internas** | [`account_internal_transfer`](./account_internal_transfer) | Facilita el traspaso y conciliación de fondos entre bancos y cajas de la misma empresa. |
| **Talonarios de Recibos** | [`account_payment_pro_receiptbook`](./account_payment_pro_receiptbook) | Control y numeración de cobros/pagos mediante el uso de talonarios de recibos físicos. |
| **Pagos Avanzados** | [`account_payment_pro`](./account_payment_pro) | Interfaz unificada y extendida para el procesamiento de cobros y pagos contables. |
| **UX Contabilidad** | [`account_ux`](./account_ux) | Pequeños ajustes de usabilidad para acelerar la carga de facturas y la conciliación. |

### 4. Inventario, Compras & Ventas

Operaciones automatizadas y visibilidad logística integrada en tiempo real.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Actualización de Costos** | [`purchase_auto_update_cost`](./purchase_auto_update_cost) | Actualiza el costo de adquisición del producto de forma automática al recibir la compra. |
| **Remitos de Entrega** | [`stock_picking_delivery_note`](./stock_picking_delivery_note) | Generación e impresión de remitos oficiales y notas de entrega personalizadas. |
| **Intercompany Sales/Stock** | `purchase_sale_*_inter_company` | Genera de forma automática órdenes espejo y transferencias de stock entre empresas vinculadas. |
| **Métricas de Inventario** | [`inventory_dashboard_metrics`](./inventory_dashboard_metrics) | KPIs de rotación, stock mínimo, valorización y estado general del inventario. |

### 5. Interfaz de Usuario & Base (Web)

Ajustes a nivel de framework para mitigar errores operativos en configuraciones multi-compañía.

| Módulo | Directorio | Descripción |
| :--- | :--- | :--- |
| **Web Company Color** | [`web_company_color`](./web_company_color) | Cambia el color de la interfaz de Odoo dinámicamente según la compañía activa, brindando una señal visual clara. |
| **Web Single Company** | [`web_single_company`](./web_single_company) | Fuerza la navegación y selección a una única empresa activa por sesión de usuario. |

---

## 🛠️ Requisitos e Instalación

### Dependencias de Python

Para interactuar con la AFIP, es obligatorio instalar las dependencias de criptografía y comunicación SOAP. Instálalas ejecutando:

```bash
pip install -r requirements.txt
```

> [!IMPORTANT]
> El archivo [`requirements.txt`](./requirements.txt) incluye un enlace directo a la bifurcación optimizada de `pyafipws` para Odoo 18. Asegúrate de compilar y tener las librerías del sistema de criptografía instaladas en tu SO (por ejemplo, `libssl-dev` y `swig` en distribuciones Debian/Ubuntu) para que `M2Crypto` compile correctamente.

### Configuración en Odoo (`odoo.conf`)

Descarga o clona este repositorio en tu servidor y agrega su ruta al parámetro `addons_path` de tu archivo `odoo.conf`:

```ini
[options]
addons_path = /ruta/a/odoo/addons, /ruta/a/prometeo-odoo-modules
```

Posteriormente, reinicia tu servicio de Odoo, activa el **Modo Desarrollador**, ve a la sección de **Aplicaciones**, presiona **Actualizar lista de aplicaciones** e instala los módulos que requieras.

---

## 👥 Créditos y Agradecimientos

Este repositorio recopila, adapta y optimiza contribuciones excepcionales de la comunidad global y regional de Odoo. Agradecemos especialmente a:

*   **[Asociación Civil Adhoc (ADHOC SA)](https://www.adhoc.com.ar/)**: Líderes en el ecosistema de localización argentina y creadores de la base de muchos de estos módulos.
*   **[Odoo Community Association (OCA)](https://odoo-community.org/)**: Por mantener estándares de desarrollo de alta calidad y componentes base robustos.
*   **Moldeo Interactive**: Por los esfuerzos iniciales y continuos en el desarrollo de la facturación electrónica en Argentina.

---

## 📄 Licencia

Este repositorio es una colección de módulos bajo licencias libres y de código abierto. La mayoría están licenciados bajo la **GNU Affero General Public License (AGPL-3)** o la **GNU Lesser General Public License (LGPL-3)**. 

Para obtener más detalles sobre la licencia de un módulo específico, por favor consulta su respectivo archivo `__manifest__.py`.

---
*Desarrollado y adaptado para Odoo 18 por [Alexis Medina](mailto:alexisnpavlik@gmail.com).*