# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.exceptions import UserError
from odoo.tests.common import Form, HttpCase, tagged

from odoo.addons.sale.tests.common import TestSaleCommonBase


@tagged("post_install", "-at_install")
class TestSaleWorkflowForm(TestSaleCommonBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.product2 = cls.env.ref("product.product_delivery_02")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product2, cls.stock_location, 100
        )
        cls.sale_team = cls.env["crm.team"].create(
            {
                "name": "Test Manual Delivery Team",
                "manual_delivery": True,
            }
        )
        cls.sale_team_standard = cls.env["crm.team"].create(
            {
                "name": "Test Standard Delivery Team",
                "manual_delivery": False,
            }
        )

    def test_01_form_onchange_team_manual_delivery(self):
        sale_order_form = Form(self.env["sale.order"])
        sale_order_form.partner_id = self.partner
        self.assertFalse(sale_order_form.manual_delivery)
        sale_order_form.team_id = self.sale_team
        self.assertTrue(
            sale_order_form.manual_delivery,
            "Form onchange: team_id with manual_delivery=True should set "
            "manual_delivery to True on the sale order",
        )
        order = sale_order_form.save()
        self.assertTrue(order.manual_delivery)
        self.assertEqual(order.team_id, self.sale_team)

    def test_02_form_onchange_team_standard_delivery(self):
        sale_order_form = Form(self.env["sale.order"])
        sale_order_form.partner_id = self.partner
        sale_order_form.team_id = self.sale_team_standard
        self.assertFalse(
            sale_order_form.manual_delivery,
            "Form onchange: team_id with manual_delivery=False should keep "
            "manual_delivery as False",
        )
        order = sale_order_form.save()
        self.assertFalse(order.manual_delivery)
        self.assertEqual(order.team_id, self.sale_team_standard)

    def test_03_form_create_order_with_multiple_lines(self):
        sale_order_form = Form(self.env["sale.order"])
        sale_order_form.partner_id = self.partner
        sale_order_form.team_id = self.sale_team
        with sale_order_form.order_line.new() as line:
            line.product_id = self.product
            line.product_uom_qty = 5.0
        with sale_order_form.order_line.new() as line:
            line.product_id = self.product2
            line.product_uom_qty = 3.0
        order = sale_order_form.save()
        self.assertEqual(len(order.order_line), 2)
        self.assertTrue(order.manual_delivery)
        total_qty = sum(line.product_uom_qty for line in order.order_line)
        self.assertEqual(total_qty, 8.0)

    def test_04_form_onchange_product_triggers_compute(self):
        sale_order_form = Form(self.env["sale.order"])
        sale_order_form.partner_id = self.partner
        with sale_order_form.order_line.new() as line:
            line.product_id = self.product
            line.product_uom_qty = 10.0
        order = sale_order_form.save()
        order_line = order.order_line[0]
        self.assertEqual(order_line.product_uom_qty, 10.0)
        self.assertEqual(order_line.product_id, self.product)
        self.assertEqual(
            order_line.product_uom,
            self.product.uom_id,
            "Form onchange: product_uom should be set to the product's default UoM",
        )

    def test_05_form_onchange_manual_delivery_field_consistency(self):
        sale_order_form = Form(self.env["sale.order"])
        sale_order_form.partner_id = self.partner
        sale_order_form.team_id = self.sale_team
        self.assertTrue(sale_order_form.manual_delivery)
        order = sale_order_form.save()
        self.assertEqual(
            order.state,
            "draft",
            "Newly created order via Form should be in draft state",
        )
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(order.team_id, self.sale_team)
        self.assertTrue(order.manual_delivery)


@tagged("post_install", "-at_install")
class TestSaleWorkflowIntegration(TestSaleCommonBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.product2 = cls.env.ref("product.product_delivery_02")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product2, cls.stock_location, 100
        )

    def _manual_delivery_wizard(self, records, vals=None):
        if not vals:
            vals = {}
        return (
            self.env["manual.delivery"]
            .with_context(
                active_model=records._name,
                active_ids=records.ids,
            )
            .create(vals)
        )

    def test_01_standard_delivery_stock_picking_creation(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 5.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    )
                ],
                "manual_delivery": False,
            }
        )
        self.assertEqual(order.state, "draft")
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertTrue(
            order.picking_ids,
            "Standard delivery: stock.picking must be created on confirmation",
        )
        picking = order.picking_ids[0]
        self.assertEqual(picking.state, "confirmed")
        self.assertEqual(
            picking.picking_type_id.code,
            "outgoing",
            "Picking type should be outgoing/delivery order",
        )
        self.assertEqual(
            len(picking.move_ids),
            1,
            "Picking should have exactly one stock move for one order line",
        )
        move = picking.move_ids[0]
        self.assertEqual(move.product_id, self.product)
        self.assertEqual(move.product_uom_qty, 5.0)

    def test_02_delivery_validation_updates_qty_delivered(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 10.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    )
                ],
                "manual_delivery": False,
            }
        )
        order.action_confirm()
        picking = order.picking_ids
        self.assertTrue(picking, "Picking must be created after confirmation")
        picking.action_assign()
        self.assertEqual(picking.state, "assigned")
        picking.move_line_ids.write({"quantity": 10.0})
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        order_line = order.order_line[0]
        self.assertEqual(
            order_line.qty_delivered,
            10.0,
            "qty_delivered must be updated to 10.0 after full delivery validation",
        )

    def test_03_manual_delivery_creates_picking_via_wizard(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 5.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    )
                ],
                "manual_delivery": True,
            }
        )
        order.action_confirm()
        self.assertFalse(
            order.picking_ids,
            "Manual delivery: no picking should be created on confirmation",
        )
        wizard = self._manual_delivery_wizard(order)
        self.assertTrue(wizard.line_ids, "Wizard should have lines to deliver")
        wizard.confirm()
        self.assertTrue(
            order.picking_ids,
            "Manual delivery: picking must be created after wizard confirmation",
        )
        picking = order.picking_ids[0]
        self.assertEqual(picking.state, "confirmed")
        self.assertEqual(
            picking.move_ids.product_uom_qty,
            5.0,
            "Picking move quantity should match the wizard line quantity",
        )

    def test_04_manual_delivery_validation_updates_qty_delivered(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 8.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    )
                ],
                "manual_delivery": True,
            }
        )
        order.action_confirm()
        wizard = self._manual_delivery_wizard(order)
        wizard.line_ids.write({"quantity": 8.0})
        wizard.confirm()
        picking = order.picking_ids
        self.assertTrue(picking, "Picking must be created via wizard")
        picking.action_assign()
        picking.move_line_ids.write({"quantity": 8.0})
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        order_line = order.order_line[0]
        self.assertEqual(
            order_line.qty_delivered,
            8.0,
            "qty_delivered must be updated to 8.0 after manual delivery "
            "validation",
        )

    def test_05_partial_delivery_two_lines_one_shipped(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 10.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": self.product2.name,
                            "product_id": self.product2.id,
                            "product_uom_qty": 10.0,
                            "product_uom": self.product2.uom_id.id,
                            "price_unit": self.product2.list_price,
                        },
                    ),
                ],
                "manual_delivery": True,
            }
        )
        order.action_confirm()
        self.assertFalse(order.picking_ids)
        wizard = self._manual_delivery_wizard(order.order_line[0])
        wizard.line_ids.write({"quantity": 10.0})
        wizard.confirm()
        picking = order.picking_ids
        self.assertEqual(len(picking), 1, "Only one picking should be created")
        self.assertEqual(
            len(picking.move_ids),
            1,
            "Picking should contain only one move for the first line",
        )
        picking.action_assign()
        picking.move_line_ids.write({"quantity": 10.0})
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        line1 = order.order_line[0]
        line2 = order.order_line[1]
        self.assertEqual(
            line1.qty_delivered,
            10.0,
            "First line qty_delivered should be 10.0 after full delivery",
        )
        self.assertEqual(
            line2.qty_delivered,
            0.0,
            "Second line qty_delivered should remain 0.0 (not yet delivered)",
        )
        self.assertGreater(
            line2.qty_to_procure,
            0.0,
            "Second line should still have pending qty_to_procure",
        )
        self.assertTrue(
            order.has_pending_delivery,
            "Order should still have pending delivery for the second line",
        )

    def test_06_partial_delivery_qty_delivered_edge_computation(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 10.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": self.product2.name,
                            "product_id": self.product2.id,
                            "product_uom_qty": 10.0,
                            "product_uom": self.product2.uom_id.id,
                            "price_unit": self.product2.list_price,
                        },
                    ),
                ],
                "manual_delivery": True,
            }
        )
        order.action_confirm()
        wizard = self._manual_delivery_wizard(order.order_line[0])
        wizard.line_ids.write({"quantity": 5.0})
        wizard.confirm()
        picking = order.picking_ids
        picking.action_assign()
        picking.move_line_ids.write({"quantity": 5.0})
        picking.button_validate()
        line1 = order.order_line[0]
        line2 = order.order_line[1]
        self.assertEqual(
            line1.qty_delivered,
            5.0,
            "First line qty_delivered should be 5.0 after partial delivery",
        )
        self.assertEqual(
            line2.qty_delivered,
            0.0,
            "Second line qty_delivered should remain 0.0",
        )
        self.assertEqual(
            line1.qty_to_procure,
            5.0,
            "First line should have 5.0 remaining to procure",
        )
        self.assertEqual(
            line2.qty_to_procure,
            10.0,
            "Second line should have 10.0 remaining to procure",
        )
        total_delivered = sum(line.qty_delivered for line in order.order_line)
        self.assertEqual(
            total_delivered,
            5.0,
            "Total qty_delivered across all lines should be 5.0",
        )
        self.assertTrue(order.has_pending_delivery)
        wizard2 = self._manual_delivery_wizard(order.order_line[0])
        wizard2.line_ids.write({"quantity": 5.0})
        wizard2.confirm()
        wizard3 = self._manual_delivery_wizard(order.order_line[1])
        wizard3.line_ids.write({"quantity": 10.0})
        wizard3.confirm()
        all_pickings = order.picking_ids
        for pick in all_pickings:
            if pick.state != "done":
                pick.action_assign()
                pick.move_line_ids.write({"quantity": pick.move_ids.product_uom_qty})
                pick.button_validate()
        self.assertEqual(
            line1.qty_delivered,
            10.0,
            "First line should be fully delivered: 10.0",
        )
        self.assertEqual(
            line2.qty_delivered,
            10.0,
            "Second line should be fully delivered: 10.0",
        )
        self.assertFalse(
            order.has_pending_delivery,
            "Order should have no pending delivery after full delivery",
        )

    def test_07_manual_delivery_constraint_on_confirmed_order(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 1.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    )
                ],
                "manual_delivery": True,
            }
        )
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        with self.assertRaises(UserError):
            order.write({"manual_delivery": False})

    def test_08_manual_delivery_respects_qty_to_procure(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 5.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    )
                ],
                "manual_delivery": True,
            }
        )
        order.action_confirm()
        wizard = self._manual_delivery_wizard(order)
        wizard.line_ids.write({"quantity": 2.0})
        wizard.confirm()
        wizard2 = self._manual_delivery_wizard(order)
        self.assertEqual(wizard2.line_ids.quantity, 3.0)
        wizard2.line_ids.write({"quantity": 3.0})
        wizard2.confirm()
        self.assertFalse(order.has_pending_delivery)
        wizard3 = self._manual_delivery_wizard(order)
        self.assertFalse(
            wizard3.line_ids,
            "No lines should remain in the wizard after full delivery",
        )


@tagged("post_install", "-at_install")
class TestSaleWorkflowController(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product,
            cls.env.ref("stock.stock_location_stock"),
            100,
        )
        cls.order = (
            cls.env["sale.order"]
            .with_context(tracking_disable=True)
            .create(
                {
                    "partner_id": cls.partner.id,
                    "partner_invoice_id": cls.partner.id,
                    "partner_shipping_id": cls.partner.id,
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "name": cls.product.name,
                                "product_id": cls.product.id,
                                "product_uom_qty": 5.0,
                                "product_uom": cls.product.uom_id.id,
                                "price_unit": cls.product.list_price,
                            },
                        )
                    ],
                    "manual_delivery": True,
                }
            )
        )
        cls.order.action_confirm()
        cls.order_url = "/sale_manual_delivery/order/%d" % cls.order.id
        cls.lines_url = "/sale_manual_delivery/order/%d/lines" % cls.order.id

    def test_01_unauthenticated_user_returns_403(self):
        response = self.url_open(self.order_url, timeout=30)
        self.assertEqual(
            response.status_code,
            403,
            "Unauthenticated request to order endpoint must return 403",
        )

    def test_02_authenticated_user_returns_200(self):
        self.authenticate("admin", "admin")
        response = self.url_open(self.order_url, timeout=30)
        self.assertEqual(
            response.status_code,
            200,
            "Authenticated request to order endpoint must return 200",
        )
        data = response.json()
        self.assertEqual(data["id"], self.order.id)
        self.assertEqual(data["state"], self.order.state)
        self.assertTrue(data["manual_delivery"])

    def test_03_authenticated_user_gets_order_lines(self):
        self.authenticate("admin", "admin")
        response = self.url_open(self.lines_url, timeout=30)
        self.assertEqual(
            response.status_code,
            200,
            "Authenticated request to lines endpoint must return 200",
        )
        data = response.json()
        self.assertIn("lines", data)
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["product_uom_qty"], 5.0)
        self.assertEqual(data["lines"][0]["product_id"], self.product.id)

    def test_04_unauthenticated_lines_returns_403(self):
        response = self.url_open(self.lines_url, timeout=30)
        self.assertEqual(
            response.status_code,
            403,
            "Unauthenticated request to lines endpoint must return 403",
        )

    def test_05_nonexistent_order(self):
        self.authenticate("admin", "admin")
        response = self.url_open(
            "/sale_manual_delivery/order/999999", timeout=30
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["error"], "Not found")

    def test_06_demo_user_can_access(self):
        self.authenticate("demo", "demo")
        response = self.url_open(self.order_url, timeout=30)
        self.assertEqual(
            response.status_code,
            200,
            "Demo user should be able to access the order endpoint",
        )


@tagged("post_install", "-at_install")
class TestSaleWorkflowI18n(TestSaleCommonBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product,
            cls.env.ref("stock.stock_location_stock"),
            100,
        )
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "partner_invoice_id": cls.partner.id,
                "partner_shipping_id": cls.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": cls.product.name,
                            "product_id": cls.product.id,
                            "product_uom_qty": 5.0,
                            "product_uom": cls.product.uom_id.id,
                            "price_unit": cls.product.list_price,
                        },
                    )
                ],
                "manual_delivery": True,
            }
        )

    def test_01_italian_translation_state_display(self):
        order_it = self.order.with_context(lang="it_IT")
        state_selection = dict(
            self.env["sale.order"].fields_get(["state"])["state"]["selection"]
        )
        self.assertIn(
            order_it.state,
            state_selection,
            "Order state should be one of the valid selection values",
        )
        self.assertEqual(
            order_it.state,
            "draft",
            "Newly created order should be in draft state",
        )

    def test_02_italian_translation_manual_delivery_label(self):
        order_it = self.order.with_context(lang="it_IT")
        field_info = self.env["sale.order"].with_context(
            lang="it_IT"
        ).fields_get(["manual_delivery"])
        self.assertIn("manual_delivery", field_info)
        manual_delivery_label = field_info["manual_delivery"]["string"]
        self.assertEqual(
            manual_delivery_label,
            "Consegna manuale",
            "Manual Delivery field label should be translated to Italian: "
            "'Consegna manuale'",
        )

    def test_03_italian_translation_has_pending_delivery_label(self):
        field_info = self.env["sale.order"].with_context(
            lang="it_IT"
        ).fields_get(["has_pending_delivery"])
        pending_label = field_info["has_pending_delivery"]["string"]
        self.assertEqual(
            pending_label,
            "Consegna in attesa?",
            "Delivery pending label should be translated to Italian: "
            "'Consegna in attesa?'",
        )

    def test_04_italian_translation_sales_order_model_name(self):
        model_name_it = (
            self.env["ir.model"]
            .with_context(lang="it_IT")
            .search([("model", "=", "sale.order")])
            .name
        )
        self.assertEqual(
            model_name_it,
            "Ordine di vendita",
            "Sales Order model name should be translated to Italian: "
            "'Ordine di vendita'",
        )

    def test_05_italian_translation_qty_procured_label(self):
        field_info = self.env["sale.order.line"].with_context(
            lang="it_IT"
        ).fields_get(["qty_procured"])
        qty_procured_label = field_info["qty_procured"]["string"]
        self.assertEqual(
            qty_procured_label,
            "Quantità approvvigionata",
            "Quantity Procured label should be translated to Italian: "
            "'Quantità approvvigionata'",
        )

    def test_06_italian_translation_qty_to_procure_label(self):
        field_info = self.env["sale.order.line"].with_context(
            lang="it_IT"
        ).fields_get(["qty_to_procure"])
        qty_to_procure_label = field_info["qty_to_procure"]["string"]
        self.assertEqual(
            qty_to_procure_label,
            "Quantità da approvvigionare",
            "Quantity to Procure label should be translated to Italian: "
            "'Quantità da approvvigionare'",
        )

    def test_07_english_fallback_translation(self):
        field_info_en = self.env["sale.order"].with_context(
            lang="en_US"
        ).fields_get(["manual_delivery"])
        manual_delivery_label_en = field_info_en["manual_delivery"]["string"]
        self.assertEqual(
            manual_delivery_label_en,
            "Manual Delivery",
            "Manual Delivery field label should be in English with en_US context",
        )

    def test_08_italian_error_message_translation(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": 1.0,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": self.product.list_price,
                        },
                    )
                ],
                "manual_delivery": True,
            }
        )
        order.action_confirm()
        with self.assertRaises(UserError) as ctx:
            order.with_context(lang="it_IT").write({"manual_delivery": False})
        error_msg = str(ctx.exception)
        self.assertIn(
            "solo in un preventivo",
            error_msg,
            "Italian error message should contain the translated text",
        )
        self.assertIn(
            "non un ordine",
            error_msg,
            "Italian error message should contain the translated text",
        )