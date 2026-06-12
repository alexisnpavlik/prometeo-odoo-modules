import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

const getRecordId = (val) => {
    if (!val) return null;
    if (typeof val === "object") {
        return val.id !== undefined ? val.id : val[0];
    }
    return val;
};

patch(PosStore.prototype, {
    async addLineToOrder(vals, order, opts = {}, configure = true) {
        let product = vals.product_id;
        if (typeof product === "number") {
            product = this.data.models["product.product"].get(product);
        }

        if (product && product.pack_ok && !opts.from_pack) {
            // Find component lines of the pack
            const packLines = this.data.models["product.pack.line"]
                .getAll()
                .filter((line) => {
                    const parentId = getRecordId(line.parent_product_id);
                    return parentId === product.id;
                });

            if (product.pack_type === "detailed") {
                const compPriceType = product.pack_component_price; // 'detailed', 'totalized', 'ignored'

                // Calculate parent price if component prices are totalized in it
                let parentPrice = product.lst_price;
                if (compPriceType === "totalized") {
                    let sumComp = 0;
                    for (const line of packLines) {
                        const compProductId = getRecordId(line.product_id);
                        const compProduct = this.data.models[
                            "product.product"
                        ].get(compProductId);
                        if (compProduct) {
                            sumComp += compProduct.lst_price * line.quantity;
                        }
                    }
                    parentPrice += sumComp;
                }

                // Create the parent line
                const parentVals = Object.assign({}, vals, {
                    price_unit: parentPrice,
                });
                const parentLine = await super.addLineToOrder(
                    parentVals,
                    order,
                    Object.assign({}, opts, { from_pack: true }),
                    configure
                );

                // Create lines for components
                for (const line of packLines) {
                    const compProductId = getRecordId(line.product_id);
                    const compProduct = this.data.models[
                        "product.product"
                    ].get(compProductId);
                    if (compProduct) {
                        let compPrice = 0;
                        if (compPriceType === "detailed") {
                            compPrice = compProduct.lst_price;
                        }
                        const compVals = {
                            product_id: compProduct,
                            qty: (vals.qty || 1) * line.quantity,
                            price_unit: compPrice,
                        };
                        await super.addLineToOrder(
                            compVals,
                            order,
                            Object.assign({}, opts, { from_pack: true }),
                            configure
                        );
                    }
                }
                return parentLine;
            }
        }
        return await super.addLineToOrder(vals, order, opts, configure);
    },
});
