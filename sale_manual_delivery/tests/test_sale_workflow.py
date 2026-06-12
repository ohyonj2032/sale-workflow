# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import json

from odoo import Command
from odoo.tests import Form, tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestSaleWorkflowFormOnchange(TransactionCase):
    """Scenario 1: Form testing with onchange linkage for multi-line sale orders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product_a = cls.env.ref("product.product_delivery_01")
        cls.product_b = cls.env.ref("product.product_delivery_02")
        cls.product_c = cls.env.ref("product.product_order_01")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        for product in [cls.product_a, cls.product_b, cls.product_c]:
            cls.env["stock.quant"]._update_available_quantity(
                product, cls.stock_location, 500
            )

    def test_01_form_multi_line_onchange_product(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True

        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 10.0

        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_b
            line_form.product_uom_qty = 5.0

        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_c
            line_form.product_uom_qty = 3.0

        order = order_form.save()

        self.assertEqual(len(order.order_line), 3)

        line_a = order.order_line.filtered(
            lambda l: l.product_id == self.product_a
        )
        line_b = order.order_line.filtered(
            lambda l: l.product_id == self.product_b
        )
        line_c = order.order_line.filtered(
            lambda l: l.product_id == self.product_c
        )

        self.assertTrue(line_a)
        self.assertTrue(line_b)
        self.assertTrue(line_c)
        self.assertEqual(line_a.product_uom_qty, 10.0)
        self.assertEqual(line_b.product_uom_qty, 5.0)
        self.assertEqual(line_c.product_uom_qty, 3.0)

        self.assertTrue(line_a.name)
        self.assertTrue(line_b.name)
        self.assertTrue(line_c.name)

        self.assertEqual(line_a.price_unit, self.product_a.list_price)
        self.assertEqual(line_b.price_unit, self.product_b.list_price)
        self.assertEqual(line_c.price_unit, self.product_c.list_price)

    def test_02_form_onchange_partner_propagation(self):
        partner_custom = self.env["res.partner"].create(
            {
                "name": "Test Partner Custom",
                "property_product_pricelist": self.env.ref(
                    "product.list0"
                ).id,
            }
        )

        order_form = Form(self.env["sale.order"])
        order_form.partner_id = partner_custom
        order_form.manual_delivery = True

        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 2.0

        order = order_form.save()

        self.assertEqual(order.partner_id, partner_custom)
        self.assertEqual(order.partner_invoice_id, partner_custom)
        self.assertEqual(order.partner_shipping_id, partner_custom)

    def test_03_form_edit_existing_order(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 5.0
        order = order_form.save()

        with Form(order) as edit_form:
            with edit_form.order_line.edit(0) as edit_line:
                edit_line.product_uom_qty = 20.0
            with edit_form.order_line.new() as new_line:
                new_line.product_id = self.product_b
                new_line.product_uom_qty = 7.0

        self.assertEqual(order.order_line[0].product_uom_qty, 20.0)
        self.assertEqual(len(order.order_line), 2)

    def test_04_form_onchange_triggers_price_computation(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Test Pricelist with discount",
                "discount_policy": "without_discount",
                "item_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "base": "list_price",
                            "percent_price": 20,
                        }
                    )
                ],
            }
        )

        partner_with_pricelist = self.env["res.partner"].create(
            {
                "name": "Partner with special pricelist",
                "property_product_pricelist": pricelist.id,
            }
        )

        order_form = Form(self.env["sale.order"])
        order_form.partner_id = partner_with_pricelist
        order_form.pricelist_id = pricelist
        order_form.manual_delivery = True

        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 1.0

        order = order_form.save()
        line = order.order_line[0]

        expected_price = self.product_a.list_price * 0.8
        self.assertAlmostEqual(line.price_unit, expected_price, places=2)


@tagged("post_install", "-at_install")
class TestSaleWorkflowCrossModuleIntegration(TransactionCase):
    """Scenario 2: Cross-module integration testing with sale_stock."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
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

    def test_01_action_deliver_creates_stock_picking(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 10.0
        order = order_form.save()

        self.assertFalse(order.picking_ids)

        order.action_confirm()

        self.assertFalse(
            order.picking_ids,
            "No picking should be created for manual delivery orders on confirmation",
        )

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        self.assertTrue(wizard.line_ids)
        wizard.confirm()

        self.assertTrue(
            order.picking_ids,
            "Picking must be created after manual delivery wizard confirm",
        )

        picking = order.picking_ids
        self.assertEqual(picking.state, "assigned", "Picking should be in assigned state")

        picking.move_line_ids.write({"quantity": 10.0})
        picking.button_validate()

        sol = order.order_line
        self.assertEqual(
            sol.qty_delivered,
            10.0,
            "qty_delivered must be updated after picking validation",
        )

    def test_02_partial_delivery_updates_qty_delivered(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 10.0
        order = order_form.save()

        order.action_confirm()

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        wizard.line_ids.write({"quantity": 4.0})
        wizard.confirm()

        picking = order.picking_ids
        picking.action_assign()
        picking.move_line_ids.write({"quantity": 4.0})
        picking.button_validate()

        sol = order.order_line
        self.assertEqual(
            sol.qty_delivered,
            4.0,
            "qty_delivered should reflect partial delivery",
        )
        self.assertEqual(
            sol.qty_to_deliver,
            6.0,
            "Remaining qty_to_deliver should be 6.0",
        )

    def test_03_stock_picking_state_correlation(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 5.0
        order = order_form.save()

        order.action_confirm()

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        wizard.confirm()

        picking = order.picking_ids
        self.assertEqual(len(picking), 1)
        self.assertEqual(picking.sale_id, order)
        self.assertEqual(picking.partner_id, order.partner_shipping_id)

        for move in picking.move_ids:
            self.assertEqual(move.sale_line_id, order.order_line)

    def test_04_multi_line_partial_delivery_stock_moves(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 10.0
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product2
            line_form.product_uom_qty = 8.0
        order = order_form.save()

        order.action_confirm()

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )

        line_a_wizard = wizard.line_ids.filtered(
            lambda l: l.product_id == self.product
        )
        line_b_wizard = wizard.line_ids.filtered(
            lambda l: l.product_id == self.product2
        )

        line_a_wizard.write({"quantity": 5.0})
        line_b_wizard.write({"quantity": 3.0})
        wizard.confirm()

        picking = order.picking_ids
        self.assertEqual(len(picking), 1)

        picking.action_assign()
        for ml in picking.move_line_ids:
            ml.quantity = ml.reserved_uom_qty
        picking.button_validate()

        line_a = order.order_line.filtered(
            lambda l: l.product_id == self.product
        )
        line_b = order.order_line.filtered(
            lambda l: l.product_id == self.product2
        )

        self.assertEqual(line_a.qty_delivered, 5.0)
        self.assertEqual(line_b.qty_delivered, 3.0)

        self.assertEqual(line_a.qty_to_deliver, 5.0)
        self.assertEqual(line_b.qty_to_deliver, 5.0)


@tagged("post_install", "-at_install")
class TestSaleWorkflowControllerAuth(HttpCase):
    """Scenario 3: Controller API authentication tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )

        cls.authenticated_user = new_test_user(
            cls.env,
            login="sale_api_user",
            groups="sales_team.group_sale_salesman",
        )

        cls.portal_user = new_test_user(
            cls.env,
            login="portal_user",
            groups="base.group_portal",
        )

        order_form = Form(cls.env["sale.order"])
        order_form.partner_id = cls.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = cls.product
            line_form.product_uom_qty = 5.0
        cls.order = order_form.save()
        cls.order.action_confirm()

    def test_01_unauthenticated_request_returns_403(self):
        response = self.url_open(
            f"/api/sale/order/{self.order.id}",
            headers={"Content-Type": "application/json"},
        )
        self.assertIn(response.status_code, [401, 403])

    def test_02_authenticated_user_can_access_order(self):
        self.authenticate("sale_api_user", "sale_api_user")
        response = self.url_open(
            f"/api/sale/order/{self.order.id}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode())
        self.assertEqual(data["id"], self.order.id)
        self.assertEqual(data["name"], self.order.name)
        self.assertEqual(data["state"], self.order.state)

    def test_03_portal_user_restricted_access(self):
        self.authenticate("portal_user", "portal_user")
        response = self.url_open(
            f"/api/sale/order/{self.order.id}",
            headers={"Content-Type": "application/json"},
        )
        self.assertIn(response.status_code, [200, 403])

        if response.status_code == 200:
            data = json.loads(response.content.decode())
            self.assertIn("error", data)

    def test_04_nonexistent_order_returns_404(self):
        self.authenticate("sale_api_user", "sale_api_user")
        response = self.url_open(
            "/api/sale/order/999999",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 404)

    def test_05_action_deliver_via_json_rpc(self):
        self.authenticate("sale_api_user", "sale_api_user")
        response = self.url_open(
            "/api/sale/order/%d/deliver" % self.order.id,
            data=json.dumps({"params": {}}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode())
        self.assertTrue(data.get("success"))
        self.assertGreater(data.get("picking_count", 0), 0)


@tagged("post_install", "-at_install")
class TestSaleWorkflowPartialDeliveryEdgeCases(TransactionCase):
    """Scenario 4: Partial delivery edge cases with multi-line orders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product_a = cls.env.ref("product.product_delivery_01")
        cls.product_b = cls.env.ref("product.product_delivery_02")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product_a, cls.stock_location, 100
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product_b, cls.stock_location, 100
        )

    def test_01_one_line_delivered_other_not(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 10.0
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_b
            line_form.product_uom_qty = 8.0
        order = order_form.save()

        order.action_confirm()
        self.assertEqual(order.state, "sale")

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )

        line_a_wizard = wizard.line_ids.filtered(
            lambda l: l.product_id == self.product_a
        )
        line_b_wizard = wizard.line_ids.filtered(
            lambda l: l.product_id == self.product_b
        )

        line_a_wizard.write({"quantity": 10.0})
        line_b_wizard.write({"quantity": 0.0})
        wizard.confirm()

        picking = order.picking_ids
        self.assertEqual(len(picking), 1)

        picking.action_assign()

        moves_for_a = picking.move_ids.filtered(
            lambda m: m.product_id == self.product_a
        )
        moves_for_b = picking.move_ids.filtered(
            lambda m: m.product_id == self.product_b
        )

        self.assertTrue(moves_for_a)
        self.assertFalse(moves_for_b, "No move should exist for product_b")

        for ml in picking.move_line_ids:
            ml.quantity = ml.reserved_uom_qty
        picking.button_validate()

        line_a = order.order_line.filtered(
            lambda l: l.product_id == self.product_a
        )
        line_b = order.order_line.filtered(
            lambda l: l.product_id == self.product_b
        )

        self.assertEqual(line_a.qty_delivered, 10.0)
        self.assertEqual(line_b.qty_delivered, 0.0)

        self.assertEqual(line_a.qty_to_deliver, 0.0)
        self.assertEqual(line_b.qty_to_deliver, 8.0)

        self.assertTrue(order.has_pending_delivery)

    def test_02_partial_delivery_float_precision(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 3.333
        order = order_form.save()

        order.action_confirm()

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        wizard.line_ids.write({"quantity": 1.111})
        wizard.confirm()

        picking = order.picking_ids
        picking.action_assign()
        for ml in picking.move_line_ids:
            ml.quantity = ml.reserved_uom_qty
        picking.button_validate()

        sol = order.order_line
        self.assertAlmostEqual(sol.qty_delivered, 1.111, places=3)
        self.assertAlmostEqual(sol.qty_to_deliver, 2.222, places=3)

    def test_03_delivery_completion_state_transition(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 5.0
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_b
            line_form.product_uom_qty = 5.0
        order = order_form.save()

        order.action_confirm()
        self.assertEqual(order.state, "sale")

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        wizard.line_ids.write({"quantity": 5.0})
        wizard.confirm()

        picking = order.picking_ids
        picking.action_assign()
        for ml in picking.move_line_ids:
            ml.quantity = ml.reserved_uom_qty
        picking.button_validate()

        line_a = order.order_line.filtered(
            lambda l: l.product_id == self.product_a
        )
        line_b = order.order_line.filtered(
            lambda l: l.product_id == self.product_b
        )

        self.assertEqual(line_a.qty_delivered, 5.0)
        self.assertEqual(line_b.qty_delivered, 5.0)

        self.assertFalse(order.has_pending_delivery)

    def test_04_qty_delivered_spike_after_overdelivery_attempt(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product_a
            line_form.product_uom_qty = 10.0
        order = order_form.save()

        order.action_confirm()

        wizard = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        wizard.line_ids.write({"quantity": 10.0})
        wizard.confirm()

        picking = order.picking_ids
        picking.action_assign()
        for ml in picking.move_line_ids:
            ml.quantity = ml.reserved_uom_qty
        picking.button_validate()

        sol = order.order_line
        self.assertEqual(sol.qty_delivered, 10.0)
        self.assertEqual(sol.qty_to_deliver, 0.0)

        wizard2 = (
            self.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        self.assertFalse(
            wizard2.line_ids,
            "No lines should be available after full delivery",
        )


@tagged("post_install", "-at_install")
class TestSaleWorkflowMultiLanguage(TransactionCase):
    """Scenario 5: Multi-language context assertions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )

    def test_01_italian_language_state_translation(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 5.0
        order = order_form.save()

        order.action_confirm()

        order_it = order.with_context(lang="it_IT")

        state_field = order_it._fields["state"]
        selection = state_field._description_selection(order_it.env)

        state_dict = dict(selection)
        self.assertIn("sale", state_dict)

        italian_state = state_dict.get("sale")
        self.assertTrue(italian_state)
        self.assertNotEqual(
            italian_state,
            "Sales Order",
            "Italian translation should differ from English source",
        )

    def test_02_italian_draft_state_translation(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 3.0
        order = order_form.save()

        order_it = order.with_context(lang="it_IT")
        state_field = order_it._fields["state"]
        selection = state_field._description_selection(order_it.env)
        state_dict = dict(selection)

        italian_draft = state_dict.get("draft")
        self.assertTrue(italian_draft)
        self.assertNotEqual(
            italian_draft,
            "Quotation",
            "Italian draft translation should differ from English source",
        )

    def test_03_english_default_language(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 2.0
        order = order_form.save()

        order.action_confirm()

        order_en = order.with_context(lang="en_US")
        state_field = order_en._fields["state"]
        selection = state_field._description_selection(order_en.env)
        state_dict = dict(selection)

        self.assertEqual(state_dict.get("sale"), "Sales Order")
        self.assertEqual(state_dict.get("draft"), "Quotation")

    def test_04_manual_delivery_field_translation_it(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 1.0
        order = order_form.save()

        order_it = order.with_context(lang="it_IT")

        manual_delivery_field = order_it._fields["manual_delivery"]
        self.assertTrue(manual_delivery_field)

        has_pending_field = order_it._fields["has_pending_delivery"]
        self.assertTrue(has_pending_field)

        self.assertTrue(order_it.manual_delivery)

    def test_05_multi_language_field_labels(self):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        order_form.manual_delivery = True
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            line_form.product_uom_qty = 4.0
        order = order_form.save()

        order_it = order.with_context(lang="it_IT")
        order_en = order.with_context(lang="en_US")

        state_field_it = order_it._fields["state"]
        state_field_en = order_en._fields["state"]

        selection_it = state_field_it._description_selection(order_it.env)
        selection_en = state_field_en._description_selection(order_en.env)

        dict_it = dict(selection_it)
        dict_en = dict(selection_en)

        for state_key in ["draft", "sent", "sale", "done", "cancel"]:
            if state_key in dict_it and state_key in dict_en:
                self.assertNotEqual(
                    dict_it[state_key],
                    dict_en[state_key],
                    f"Italian and English translations for '{state_key}' should differ",
                )
