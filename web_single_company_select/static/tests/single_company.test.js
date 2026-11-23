import { beforeEach, describe, expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    getService,
    makeMockEnv,
    makeServerError,
    models,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";

import { animationFrame } from "@odoo/hoot-mock";
import { cookie } from "@web/core/browser/cookie";
import { user } from "@web/core/user";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";
import { WebClient } from "@web/webclient/webclient";
import { isBounce, pickSingleCompanyId } from "@web_single_company_select/js/single_company";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");

class Partner extends models.Model {
    name = fields.Char();
    _records = [{ id: 1, name: "Cliente de otra empresa" }];
    _views = { form: `<form><field name="name"/></form>` };
}

defineModels([Partner]);

const openCompanyMenu = () => contains(".dropdown-toggle").click();

const stepOnCookieChange = () =>
    patchWithCleanup(cookie, {
        set(key, value) {
            if (key === "cids") {
                expect.step(value);
            }
            return super.set(key, value);
        },
    });

beforeEach(() => {
    /**
     *   Hermit (3)
     *   Herman's (2)
     *   Heroes TM (1)
     *      Hercules (4)
     *      Hulk (5)
     */
    serverState.companies = [
        { id: 3, name: "Hermit", sequence: 1, parent_id: false, child_ids: [] },
        { id: 2, name: "Herman's", sequence: 2, parent_id: false, child_ids: [] },
        { id: 1, name: "Heroes TM", sequence: 3, parent_id: false, child_ids: [4, 5] },
        { id: 4, name: "Hercules", sequence: 4, parent_id: 1, child_ids: [] },
        { id: 5, name: "Hulk", sequence: 5, parent_id: 1, child_ids: [] },
    ];
});

test("pickSingleCompanyId: gana la primera empresa nueva", () => {
    // selector: la elegida va adelante
    expect(pickSingleCompanyId([2, 3], [3])).toBe(2);
    // formulario: la empresa del registro se agrega al final
    expect(pickSingleCompanyId([3, 2], [3])).toBe(2);
    // sin empresas nuevas: la primera pedida
    expect(pickSingleCompanyId([3], [3])).toBe(3);
    // pedido vacío: la actual
    expect(pickSingleCompanyId([], [3])).toBe(3);
});

test("con varias empresas en la cookie arranca solo con la primera", async () => {
    cookie.set("cids", "3-2-1");
    stepOnCookieChange();
    await makeMockEnv();
    const company = getService("company");
    expect(company.activeCompanyIds).toEqual([3]);
    expect(company.currentCompany.id).toBe(3);
    expect(cookie.get("cids")).toBe("3");
    expect(user.context.allowed_company_ids).toEqual([3]);
    expect.verifySteps(["3-2-1", "3"]);
});

test("setCompanies con varias empresas deja una sola (cambio desde formulario)", async () => {
    stepOnCookieChange();
    await makeMockEnv();
    expect.verifySteps(["3"]);
    const company = getService("company");
    // así lo pide form_controller ante un AccessError con suggested_company
    const ids = company.activeCompanyIds;
    ids.push(2);
    await company.setCompanies(ids, true);
    expect.verifySteps(["2"]);
    expect(user.context.allowed_company_ids).toEqual([2]);
});

test("setCompanies no suma las sucursales de la empresa elegida", async () => {
    stepOnCookieChange();
    await makeMockEnv();
    expect.verifySteps(["3"]);
    await getService("company").setCompanies([1], true);
    expect.verifySteps(["1"]);
});

test("el menú muestra opciones (radio) y no tiene 'Seleccionar todas'", async () => {
    await mountWithCleanup(SwitchCompanyMenu);
    await openCompanyMenu();
    expect("[data-company-id]").toHaveCount(5);
    expect("[data-company-id] [role=menuitemcheckbox]").toHaveCount(0);
    expect("[data-company-id] [role=menuitemradio]").toHaveCount(5);
    expect("[data-company-id] .fa-dot-circle-o").toHaveCount(1);
    expect("[data-company-id] .fa-circle-o").toHaveCount(4);
    expect("[data-company-id] .fa-check-square, [data-company-id] .fa-square-o").toHaveCount(0);
    expect(".dropdown-menu [aria-label='Select all']").toHaveCount(0);
});

test("tocar el casillero de otra empresa entra solo a esa", async () => {
    stepOnCookieChange();
    await mountWithCleanup(SwitchCompanyMenu);
    expect.verifySteps(["3"]);
    await openCompanyMenu();
    await contains("[data-company-id='2'] [role=menuitemradio]").click();
    expect.verifySteps(["2"]);
    expect(".o_switch_company_menu_buttons").toHaveCount(0);
});

test("entrar a una empresa con sucursales no activa las sucursales", async () => {
    stepOnCookieChange();
    await mountWithCleanup(SwitchCompanyMenu);
    expect.verifySteps(["3"]);
    await openCompanyMenu();
    await contains("[data-company-id='1'] .log_into").click();
    expect.verifySteps(["1"]);
});

test("tocar la empresa actual no cambia nada", async () => {
    stepOnCookieChange();
    await mountWithCleanup(SwitchCompanyMenu);
    expect.verifySteps(["3"]);
    await openCompanyMenu();
    await contains("[data-company-id='3'] [role=menuitemradio]").click();
    expect.verifySteps([]);
    expect(getService("company").activeCompanyIds).toEqual([3]);
});

test("abrir un registro de otra empresa cambia a esa empresa, no la suma", async () => {
    // Odoo responde AccessError + suggested_company cuando el registro es de
    // una empresa no activa; el formulario pide sumarla a las activas.
    onRpc("web_read", () => {
        throw makeServerError({
            type: "AccessError",
            context: { suggested_company: { id: 2, display_name: "Herman's" } },
        });
    });
    stepOnCookieChange();
    await mountWithCleanup(WebClient);
    expect.verifySteps(["3"]);
    // no se espera doAction: el formulario nunca termina de cargar porque
    // el cambio de empresa recarga la página
    getService("action").doAction({
        type: "ir.actions.act_window",
        res_model: "partner",
        res_id: 1,
        views: [[false, "form"]],
    });
    await animationFrame();
    await animationFrame();
    expect.verifySteps(["2"]);
    expect(user.context.allowed_company_ids).toEqual([2]);
});

test("isBounce: volver enseguida a la empresa de la que se salió", () => {
    const last = { from: 2, to: 3, ts: 1000 };
    expect(isBounce(last, 3, 2, 2000)).toBe(true);
    expect(isBounce(last, 3, 5, 2000)).toBe(false); // otra empresa
    expect(isBounce(last, 3, 2, 1000 + 61000)).toBe(false); // pasó el minuto
    expect(isBounce(null, 3, 2, 2000)).toBe(false);
});

test("rebote (Ajustes con empleados de dos empresas): deja las dos, sin bucle", async () => {
    // 1ra carga en Hermit (3): el formulario pide Herman's (2) -> cambia a 2
    stepOnCookieChange();
    await makeMockEnv();
    expect.verifySteps(["3"]);
    let company = getService("company");
    await company.setCompanies([...company.activeCompanyIds, 2], true);
    expect.verifySteps(["2"]);
    const saved = browser.sessionStorage.getItem("web_single_company_select.last_auto_switch");
    expect(JSON.parse(saved)).toMatchObject({ from: 3, to: 2 });
});

test("rebote: estando en 2 y pidiendo volver a 3, activa las dos", async () => {
    browser.sessionStorage.setItem(
        "web_single_company_select.last_auto_switch",
        JSON.stringify({ from: 3, to: 2, ts: Date.now() })
    );
    cookie.set("cids", "2");
    stepOnCookieChange();
    await makeMockEnv();
    expect.verifySteps(["2"]);
    const company = getService("company");
    await company.setCompanies([...company.activeCompanyIds, 3], true);
    expect.verifySteps(["2-3"]);
    expect(
        JSON.parse(browser.sessionStorage.getItem("web_single_company_select.multi_ids"))
    ).toEqual([2, 3]);
});

test("rebote: al recargar con las dos permitidas no las colapsa", async () => {
    browser.sessionStorage.setItem("web_single_company_select.multi_ids", JSON.stringify([2, 3]));
    cookie.set("cids", "2-3");
    await makeMockEnv();
    expect(getService("company").activeCompanyIds).toEqual([2, 3]);
});

test("elegir una empresa en el selector sale del modo varias empresas", async () => {
    browser.sessionStorage.setItem("web_single_company_select.multi_ids", JSON.stringify([2, 3]));
    cookie.set("cids", "2-3");
    stepOnCookieChange();
    await mountWithCleanup(SwitchCompanyMenu);
    expect.verifySteps(["2-3"]);
    await openCompanyMenu();
    await contains("[data-company-id='3'] [role=menuitemradio]").click();
    expect.verifySteps(["3"]);
    expect(browser.sessionStorage.getItem("web_single_company_select.multi_ids")).toBe(null);
});

test("cookie con varias empresas sin permiso guardado: colapsa a una", async () => {
    browser.sessionStorage.setItem("web_single_company_select.multi_ids", JSON.stringify([2, 5]));
    cookie.set("cids", "2-3");
    await makeMockEnv();
    expect(getService("company").activeCompanyIds).toEqual([2]);
});
