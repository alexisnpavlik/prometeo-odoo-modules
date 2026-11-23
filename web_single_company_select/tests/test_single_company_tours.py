from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestSingleCompanyTours(HttpCase):
    """Tours en navegador real con distintos usuarios y datos multiempresa."""

    @classmethod
    def setUpClass(cls):
        """Dos empresas, contactos cruzados y tres usuarios con accesos distintos."""
        super().setUpClass()
        Company = cls.env["res.company"]
        cls.company_a = Company.create({"name": "SCS Empresa A"})
        cls.company_b = Company.create({"name": "SCS Empresa B"})
        Partner = cls.env["res.partner"]
        cls.partner_only_b = Partner.create({"name": "SCS Solo B", "company_id": cls.company_b.id})
        both = [cls.company_a.id, cls.company_b.id]
        cls.user_ab = new_test_user(
            cls.env, login="scs_user_ab", groups="base.group_user,base.group_partner_manager",
            company_id=cls.company_a.id, company_ids=[(6, 0, both)],
        )
        cls.user_a = new_test_user(
            cls.env, login="scs_user_a", groups="base.group_user,base.group_partner_manager",
            company_id=cls.company_a.id, company_ids=[(6, 0, [cls.company_a.id])],
        )
        cls.user_admin_ab = new_test_user(
            cls.env, login="scs_admin_ab", groups="base.group_system,base.group_partner_manager",
            company_id=cls.company_a.id, company_ids=[(6, 0, both)],
        )

    def _partner_url(self, partner):
        """URL del formulario del contacto."""
        return f"/odoo/action-base.action_partner_form/{partner.id}"

    def test_user_ab_record_other_company(self):
        """Usuario común con A y B abre un contacto de B estando en A: entra a B sola."""
        self.start_tour(self._partner_url(self.partner_only_b), "scs_record_other_company", login="scs_user_ab")

    def test_admin_record_other_company(self):
        """Administrador con A y B: mismo caso que el usuario común."""
        self.start_tour(self._partner_url(self.partner_only_b), "scs_record_other_company", login="scs_admin_ab")

    def test_user_ab_switcher(self):
        """Usuario común usa el selector: queda una sola empresa."""
        self.start_tour("/odoo", "scs_switcher_single", login="scs_user_ab")

    def test_admin_switcher(self):
        """Administrador usa el selector: queda una sola empresa."""
        self.start_tour("/odoo", "scs_switcher_single", login="scs_admin_ab")


@tagged("post_install", "-at_install")
class TestSingleCompanySettingsTours(HttpCase):
    """Ajustes como en prod: cada caja tiene empleados de la otra empresa."""

    @classmethod
    def setUpClass(cls):
        """Dos empresas con caja propia y empleados cruzados (necesita pos_hr)."""
        super().setUpClass()
        if "pos_hr" not in cls.env.registry._init_modules:
            cls.skip_settings = True
            return
        cls.skip_settings = False
        Company = cls.env["res.company"]
        cls.company_a = Company.create({"name": "SCS Ajustes A"})
        cls.company_b = Company.create({"name": "SCS Ajustes B"})
        Employee = cls.env["hr.employee"]
        emp_a = Employee.create({"name": "SCS Empleado A", "company_id": cls.company_a.id})
        emp_b = Employee.create({"name": "SCS Empleado B", "company_id": cls.company_b.id})
        PosConfig = cls.env["pos.config"]
        for company in (cls.company_a, cls.company_b):
            PosConfig.with_company(company).create({"name": f"Caja {company.name}", "payment_method_ids": [(6, 0, [])]})
        # como en prod: cada caja lista empleados de las dos empresas
        configs = PosConfig.search([("company_id", "in", (cls.company_a + cls.company_b).ids)])
        cls.env.cr.execute(
            "INSERT INTO pos_hr_basic_employee_hr_employee (pos_config_id, hr_employee_id) "
            "SELECT c, e FROM unnest(%s) c, unnest(%s) e ON CONFLICT DO NOTHING",
            (configs.ids, [emp_a.id, emp_b.id]),
        )
        cls.env.invalidate_all()
        both = [cls.company_a.id, cls.company_b.id]
        new_test_user(
            cls.env, login="scs_settings_admin", groups="base.group_system,point_of_sale.group_pos_manager",
            company_id=cls.company_a.id, company_ids=[(6, 0, both)],
        )
        new_test_user(
            cls.env, login="scs_settings_admin_a", groups="base.group_system,point_of_sale.group_pos_manager",
            company_id=cls.company_a.id, company_ids=[(6, 0, [cls.company_a.id])],
        )

    def setUp(self):
        """Saltea si la base no tiene pos_hr."""
        super().setUp()
        if self.skip_settings:
            self.skipTest("pos_hr no instalado")

    def test_settings_admin_two_companies(self):
        """Admin con A y B entra a Ajustes: carga sin bucle de recargas."""
        self.start_tour("/odoo/settings", "scs_settings_no_loop", login="scs_settings_admin")

    def test_settings_admin_only_a(self):
        """Admin solo con A: no puede ver al empleado de B; error de acceso, sin bucle."""
        self.start_tour("/odoo/settings", "scs_settings_error_no_loop", login="scs_settings_admin_a")
