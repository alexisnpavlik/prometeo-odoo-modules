/** @odoo-module **/

/**
 * Pure, side-effect-free helpers for the installment surcharge/discount math.
 *
 * Kept free of any POS/Odoo imports on purpose so the logic can be unit-tested
 * with plain Node. The `/** @odoo-module *\/` pragma above is just a comment for
 * the Odoo bundler and is ignored by Node's ESM loader.
 */

/**
 * Combined multiplier applied to the net order total.
 *
 *   final_total = net_total * coefficient * (1 - bank_discount / 100)
 *
 * The surcharge (coefficient) inflates the total; the bank discount (reintegro)
 * is a percentage applied on top of the already-surcharged amount, matching the
 * server-side calculation in account.card.installment.map_installment_values.
 *
 * @param {number} coefficient surcharge coefficient (e.g. 1.06 for +6%)
 * @param {number} [bankDiscountPercent=0] reintegro percentage (e.g. 5 for 5%)
 * @returns {number} multiplier to apply to each line's unit price
 */
export function surchargeMultiplier(coefficient, bankDiscountPercent = 0) {
    const coef = Number(coefficient);
    const disc = Number(bankDiscountPercent);
    if (!isFinite(coef) || coef <= 0) {
        return 1;
    }
    const safeDisc = isFinite(disc) ? disc : 0;
    return coef * (1 - safeDisc / 100);
}

/**
 * New unit price for a line once the multiplier is applied.
 *
 * Scaling the unit price (instead of recomputing from the catalog price)
 * preserves the line's own discount and quantity, and keeps zero-priced lines
 * at zero — no division, so no NaN/Infinity is possible.
 *
 * @param {number} originalUnitPrice unit price before any surcharge
 * @param {number} multiplier value from {@link surchargeMultiplier}
 * @returns {number}
 */
export function surchargedUnitPrice(originalUnitPrice, multiplier) {
    const price = Number(originalUnitPrice);
    const m = Number(multiplier);
    if (!isFinite(price) || !isFinite(m)) {
        return 0;
    }
    return price * m;
}

/**
 * Computes all fee, discount, final amount, and installment details for an installment plan.
 * Replicates the logic of map_installment_values from account.card.installment backend model.
 *
 * @param {object} installment the installment plan data from POS cache
 * @param {number} amountTotal net total of the order
 * @returns {object} calculated values rounded to 2 decimal places
 */
export function calculateInstallmentValues(installment, amountTotal) {
    const surchargeCoefficient = Number(installment.surcharge_coefficient || 1.0);
    const divisor = Number(installment.divisor || 1);
    const bankDiscount = Number(installment.bank_discount || 0);

    const roundTo = (num, decimals = 2) => {
        const factor = Math.pow(10, decimals);
        return Math.round((num + Number.EPSILON) * factor) / factor;
    };

    const coefficient = roundTo(surchargeCoefficient, 5);
    const amountTotalR = roundTo(amountTotal, 2);
    const amount = roundTo(amountTotalR * coefficient, 2);
    const discount = roundTo((amount * bankDiscount) / 100, 2);
    const finalAmount = roundTo(amount - discount, 2);
    const installmentAmount = divisor > 0 ? roundTo(finalAmount / divisor, 2) : 0;

    return {
        id: installment.id,
        name: installment.name,
        installment: installment.installment,
        coefficient: coefficient,
        bank_discount: bankDiscount,
        divisor: divisor,
        base_amount: amountTotalR,
        amount: amount,
        fee: roundTo(amount - amountTotalR, 2),
        discount: discount,
        final_amount: finalAmount,
        installment_amount: installmentAmount,
    };
}

