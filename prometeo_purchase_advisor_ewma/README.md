# Recomendador de compra - Suavizado exponencial (EWMA)

Agrega el método de estimación **EWMA** al módulo `prometeo_purchase_advisor`.

## Qué aporta

El método del módulo base promedia varias ventanas (14, 30 y 90 días) y trata
por igual a todos los días dentro de cada una. El EWMA le baja el peso a cada
día a medida que envejece, de forma continua: reacciona más rápido a un cambio
de ritmo de venta, y a cambio es más nervioso ante el ruido.

`alpha` controla esa reacción. Más alto, más peso al pasado reciente:

| alpha | Comportamiento |
|---|---|
| 0.05 | Muy amortiguado, casi un promedio largo |
| 0.30 | Equilibrado (valor por defecto) |
| 0.50 | Sigue de cerca las últimas semanas |

Cuando el producto tiene menos de 7 días utilizables el suavizado no llega a
estabilizarse, así que **degrada** al promedio ponderado del módulo base, deja
`method_used = weighted_ma` y explica por qué en las advertencias de la línea.

## Por qué existe este módulo

Es la prueba de que la arquitectura del recomendador se puede extender. Agrega
un método de estimación **sin modificar una sola línea del módulo base**:

- extiende el `Selection` de métodos con `super()`;
- define `_estimate_ewma`, que el despacho por nombre del core encuentra solo;
- reutiliza los helpers del core (recorte de outliers, desvío, confianza) sin
  duplicarlos;
- agrega su propia vista para mostrar `alpha`.

El core no menciona `ewma` en ningún lado. Si en algún momento hace falta
tocarlo para sumar un método, la arquitectura falló y hay que arreglarla antes
de seguir agregando métodos.

## Uso

*Compras → Recomendador de compra → Configuración → Modelos de demanda*: crear un modelo con método
**Suavizado exponencial (EWMA)** y ajustar `alpha`. Se asigna a los productos
por la misma cascada que cualquier otro modelo (producto → categoría → reglas →
default de la compañía).
