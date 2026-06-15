/**
 * Pruebas del helper puro de cálculo de cuotas (recargo + reintegro).
 *
 * No requiere Odoo: el helper no importa nada del framework, así que se corre
 * con Node directamente:
 *
 *     node card_installment/static/tests/installment_math.test.mjs
 *
 * Sale con código 0 si todo pasa, 1 si falla algún caso.
 */
import {
    surchargeMultiplier,
    surchargedUnitPrice,
} from "../src/js/installment_math.js";

let passed = 0;
let failed = 0;
const EPS = 0.005;

function approx(actual, expected, msg) {
    if (Math.abs(actual - expected) <= EPS) {
        passed++;
    } else {
        failed++;
        console.error(`FAIL: ${msg}\n   esperado ${expected}, obtenido ${actual}`);
    }
}
function eq(actual, expected, msg) {
    if (actual === expected) {
        passed++;
    } else {
        failed++;
        console.error(`FAIL: ${msg}\n   esperado ${expected}, obtenido ${actual}`);
    }
}

// --- Modelo mínimo de orden para validar el reparto proporcional ---
// Cada línea: {unitPrice, qty, discount(%)}
function lineSubtotal(line) {
    return line.unitPrice * line.qty * (1 - (line.discount || 0) / 100);
}
function orderTotal(lines) {
    return lines.reduce((s, l) => s + lineSubtotal(l), 0);
}
// Igual que confirm(): escala el precio unitario por el multiplicador.
function applyMultiplier(lines, m) {
    return lines.map((l) => ({ ...l, unitPrice: surchargedUnitPrice(l.unitPrice, m) }));
}

// ============================ surchargeMultiplier ============================
approx(surchargeMultiplier(1.06, 0), 1.06, "coef 1.06 sin descuento");
approx(surchargeMultiplier(1.0, 0), 1.0, "coef 1.0 sin descuento");
approx(surchargeMultiplier(1.06, 5), 1.06 * 0.95, "coef 1.06 con 5% reintegro");
approx(surchargeMultiplier(1.422, 10), 1.422 * 0.9, "coef 1.422 con 10% reintegro");
approx(surchargeMultiplier(1.0625, 0), 1.0625, "coef 1.0625 conserva 4 decimales");
approx(surchargeMultiplier(1.205, 0), 1.205, "coef 1.205 (demo) no se trunca");
// guardas defensivas
eq(surchargeMultiplier(0, 0), 1, "coef 0 -> 1 (guarda)");
eq(surchargeMultiplier(NaN, 5), 1, "coef NaN -> 1 (guarda)");
eq(surchargeMultiplier(-1, 0), 1, "coef negativo -> 1 (guarda)");
approx(surchargeMultiplier(1.06, NaN), 1.06, "descuento NaN -> 0%");
approx(surchargeMultiplier("1.06", "5"), 1.06 * 0.95, "acepta strings numéricos");

// ============================ surchargedUnitPrice ============================
approx(surchargedUnitPrice(100, 1.06), 106, "precio 100 x 1.06");
eq(surchargedUnitPrice(0, 1.06), 0, "precio 0 se queda en 0 (sin NaN)");
eq(surchargedUnitPrice(100, NaN), 0, "multiplicador NaN -> 0 (guarda)");
eq(isFinite(surchargedUnitPrice(0, surchargeMultiplier(1.06, 0))), true, "línea precio 0 -> finito");

// ============================ Reparto en la orden ============================

// 1 línea, qty 1, recargo 6%
{
    const lines = [{ unitPrice: 1000, qty: 1, discount: 0 }];
    const after = applyMultiplier(lines, surchargeMultiplier(1.06, 0));
    approx(orderTotal(after), 1060, "1 línea: 1000 -> 1060");
}

// Multi-línea, distintos precios: total neto * m y proporciones intactas
{
    const lines = [
        { unitPrice: 1000, qty: 1, discount: 0 },
        { unitPrice: 500, qty: 1, discount: 0 },
        { unitPrice: 250, qty: 1, discount: 0 },
    ];
    const net = orderTotal(lines);
    const m = surchargeMultiplier(1.11, 0);
    const after = applyMultiplier(lines, m);
    approx(orderTotal(after), net * m, "multi-línea: total neto * m");
    approx(lineSubtotal(after[0]) / lineSubtotal(after[1]), 2, "multi-línea: proporción 1000/500 intacta");
}

// qty > 1
{
    const lines = [{ unitPrice: 200, qty: 3, discount: 0 }];
    const net = orderTotal(lines);
    const m = surchargeMultiplier(1.06, 0);
    const after = applyMultiplier(lines, m);
    approx(orderTotal(after), net * m, "qty>1: total neto * m");
    approx(after[0].unitPrice, 212, "qty>1: unitario 200 -> 212");
}

// Línea con descuento de línea: el recargo aplica sobre el neto y conserva el %
{
    const lines = [{ unitPrice: 1000, qty: 1, discount: 20 }];
    const net = orderTotal(lines);
    const after = applyMultiplier(lines, surchargeMultiplier(1.06, 0));
    approx(net, 800, "descuento línea: neto 800");
    approx(orderTotal(after), 848, "descuento línea: recargo sobre neto -> 848");
    eq(after[0].discount, 20, "descuento de línea preservado");
}

// Línea de precio 0 (producto gratis) no rompe
{
    const lines = [
        { unitPrice: 1000, qty: 1, discount: 0 },
        { unitPrice: 0, qty: 2, discount: 0 },
    ];
    const after = applyMultiplier(lines, surchargeMultiplier(1.06, 0));
    eq(after.every((l) => isFinite(l.unitPrice)), true, "precio 0: todo finito (sin NaN)");
    approx(orderTotal(after), 1060, "precio 0: total 1060");
    eq(after[1].unitPrice, 0, "precio 0: línea gratis sigue en 0");
}

// Recargo + reintegro combinados
{
    const lines = [{ unitPrice: 1000, qty: 1, discount: 0 }];
    const after = applyMultiplier(lines, surchargeMultiplier(1.1, 5));
    approx(orderTotal(after), 1045, "recargo+reintegro: 1000 -> 1045");
}

// Reintegro > recargo: total final menor al neto
{
    const lines = [{ unitPrice: 1000, qty: 1, discount: 0 }];
    const after = applyMultiplier(lines, surchargeMultiplier(1.0, 10));
    approx(orderTotal(after), 900, "reintegro sin recargo: 1000 -> 900");
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
