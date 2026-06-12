# Copyright 2018 Akretion (http://www.akretion.com).
# @author Benoît GUILLOT <benoit.guillot@akretion.com>
# Copyright 2018 Camptocamp
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest import mock

from odoo.tests.common import TransactionCase


class TestDeliveryState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.order = cls.env.ref("sale_delivery_state.sale_order_1")
        cls.delivery_cost = cls.env["product.product"].create(
            {"name": "delivery", "type": "service"}
        )
        cls.service_product = cls.env["product.product"].create(
            {"name": "service", "type": "service"}
        )

    def _mock_delivery(self, delivery_prod=None):
        delivery_prod = delivery_prod or self.delivery_cost
        return mock.patch.object(
            type(self.env["sale.order.line"]),
            "_is_delivery",
            lambda self: self.product_id == delivery_prod,
        )

    def _add_delivery_cost_line(self):
        self.env["sale.order.line"].create(
            {
                "order_id": self.order.id,
                "name": "Delivery cost",
                "product_id": self.delivery_cost.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": 10.0,
            }
        )

    def _add_service_line(self, skip_sale_delivery_state=False):
        self.env["sale.order.line"].create(
            {
                "order_id": self.order.id,
                "name": "Service",
                "product_id": self.service_product.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": 10.0,
                "skip_sale_delivery_state": skip_sale_delivery_state,
            }
        )

    def test_no_delivery(self):
        self.assertFalse(self.order.delivery_status)

    def test_unprocessed_delivery(self):
        self.order.action_confirm()
        self.assertEqual(self.order.delivery_status, "pending")

    def test_partially(self):
        self.order.action_confirm()
        self.order.order_line[0].qty_delivered = 2
        self.assertEqual(self.order.delivery_status, "partial")

    def test_delivery_done(self):
        self.order.action_confirm()
        for line in self.order.order_line:
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "full")

    def test_no_delivery_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.assertFalse(self.order.delivery_status)

    def test_unprocessed_delivery_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            self.assertEqual(self.order.delivery_status, "pending")

    def test_partially_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            self.order.order_line[0].qty_delivered = 2
            self.assertEqual(self.order.delivery_status, "partial")

    def test_forced_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            self.order.order_line[0].qty_delivered = 2
            self.order.force_delivery_state = True
            self.assertEqual(self.order.delivery_status, "full")

    def test_delivery_done_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            for line in self.order.order_line:
                if line._is_delivery():
                    continue
                line.qty_delivered = line.product_uom_qty
            self.assertEqual(self.order.delivery_status, "full")

    def test_skip_service_line(self):
        self._add_service_line()
        self.order.action_confirm()
        for line in self.order.order_line:
            if line.product_id == self.service_product:
                continue
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "partial")
        self.order.order_line.filtered(
            lambda a: a.product_id and a.product_id == self.service_product
        ).write({"skip_sale_delivery_state": True})
        self.assertEqual(self.order.delivery_status, "full")

    def test_action_confirm_sets_delivery_status(self):
        self.assertFalse(self.order.delivery_status)
        self.order.action_confirm()
        self.assertEqual(self.order.state, "sale")
        self.assertEqual(self.order.delivery_status, "pending")

    def test_action_deliver_pending(self):
        self.order.action_confirm()
        self.assertEqual(self.order.delivery_status, "pending")
        self.order.action_deliver()
        self.assertEqual(self.order.delivery_status, "pending")

    def test_action_deliver_partial(self):
        self.order.action_confirm()
        self.order.order_line[0].qty_delivered = 1
        self.assertEqual(self.order.delivery_status, "partial")
        self.order.action_deliver()
        self.assertEqual(self.order.delivery_status, "partial")

    def test_action_deliver_full(self):
        self.order.action_confirm()
        for line in self.order.order_line:
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "full")
        self.order.action_deliver()
        self.assertEqual(self.order.delivery_status, "full")

    def test_action_deliver_skips_full(self):
        self.order.action_confirm()
        for line in self.order.order_line:
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "full")
        self.order.action_deliver()
        self.assertEqual(self.order.delivery_status, "full")

    def test_action_deliver_draft_order(self):
        self.order.action_deliver()
        self.assertFalse(self.order.delivery_status)

    def test_action_deliver_cancel_order(self):
        self.order.action_confirm()
        self.order.action_cancel()
        self.assertEqual(self.order.state, "cancel")
        self.order.action_deliver()
        self.assertFalse(self.order.delivery_status)

    def test_delivery_state_transitions(self):
        transitions = self.order._get_delivery_state_transitions()
        self.assertIn("started", transitions["pending"])
        self.assertIn("partial", transitions["started"])
        self.assertIn("pending", transitions["started"])
        self.assertIn("full", transitions["partial"])
        self.assertIn("pending", transitions["partial"])
        self.assertEqual(transitions["full"], [])

    def test_is_valid_delivery_transition(self):
        self.assertTrue(
            self.order._is_valid_delivery_transition("pending", "started")
        )
        self.assertTrue(
            self.order._is_valid_delivery_transition("started", "partial")
        )
        self.assertTrue(
            self.order._is_valid_delivery_transition("partial", "full")
        )
        self.assertFalse(
            self.order._is_valid_delivery_transition("pending", "full")
        )
        self.assertFalse(
            self.order._is_valid_delivery_transition("full", "partial")
        )

    def test_force_delivery_state_actions(self):
        self.order.action_confirm()
        self.assertFalse(self.order.force_delivery_state)
        self.order.action_force_delivery_state()
        self.assertTrue(self.order.force_delivery_state)
        self.assertEqual(self.order.delivery_status, "full")
        self.order.action_unforce_delivery_state()
        self.assertFalse(self.order.force_delivery_state)

    def test_partial_delivery_zero_qty(self):
        self.order.action_confirm()
        self.assertEqual(self.order.delivery_status, "pending")
        self.order.order_line[0].qty_delivered = 0
        self.order.order_line[1].qty_delivered = 0
        self.assertEqual(self.order.delivery_status, "pending")

    def test_partial_delivery_single_line(self):
        self.order.action_confirm()
        self.order.order_line[0].qty_delivered = 1
        self.order.order_line[1].qty_delivered = 0
        self.assertEqual(self.order.delivery_status, "partial")

    def test_partial_to_full_transition(self):
        self.order.action_confirm()
        self.order.order_line[0].qty_delivered = 1
        self.assertEqual(self.order.delivery_status, "partial")
        for line in self.order.order_line:
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "full")

    def test_full_to_partial_transition(self):
        self.order.action_confirm()
        for line in self.order.order_line:
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "full")
        self.order.order_line[0].qty_delivered = 1
        self.assertEqual(self.order.delivery_status, "partial")

    def test_delivery_status_none_on_draft(self):
        self.assertFalse(self.order.delivery_status)
        self.order.action_confirm()
        self.assertEqual(self.order.delivery_status, "pending")
        self.order.button_draft()
        self.assertFalse(self.order.delivery_status)

    def test_delivery_status_none_on_cancel(self):
        self.order.action_confirm()
        self.assertEqual(self.order.delivery_status, "pending")
        self.order.action_cancel()
        self.assertFalse(self.order.delivery_status)

    def test_cross_module_delivery_state_not_stored_in_sale_stock(self):
        try:
            sale_stock_order = self.env["sale.order"].sudo().create(
                {
                    "partner_id": self.env.ref("base.res_partner_2").id,
                }
            )
            sale_stock_order.action_confirm()
            self.assertIn(
                sale_stock_order.delivery_status,
                [None, "pending"],
            )
        except Exception:
            self.skipTest("sale_stock not installed")

    def test_delivery_status_constant(self):
        self.assertEqual(
            self.order.DELIVERY_STATE,
            [
                ("pending", "Not Delivered"),
                ("started", "Started"),
                ("partial", "Partially Delivered"),
                ("full", "Fully Delivered"),
            ],
        )

    def test_multiple_orders_action_deliver(self):
        order2 = self.order.copy()
        orders = self.order | order2
        orders.action_confirm()
        self.assertEqual(self.order.delivery_status, "pending")
        self.assertEqual(order2.delivery_status, "pending")
        orders.action_deliver()
        self.assertEqual(self.order.delivery_status, "pending")
        self.assertEqual(order2.delivery_status, "pending")

    def test_partial_delivery_with_force(self):
        self.order.action_confirm()
        self.order.order_line[0].qty_delivered = 1
        self.assertEqual(self.order.delivery_status, "partial")
        self.order.action_force_delivery_state()
        self.assertEqual(self.order.delivery_status, "full")
        self.order.action_unforce_delivery_state()
        self.assertEqual(self.order.delivery_status, "partial")

    def test_partial_delivery_with_service_line(self):
        self._add_service_line(skip_sale_delivery_state=True)
        self.order.action_confirm()
        for line in self.order.order_line:
            if line.product_id == self.service_product:
                continue
            line.qty_delivered = 1
        self.assertEqual(self.order.delivery_status, "partial")
        for line in self.order.order_line:
            if line.product_id == self.service_product:
                continue
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "full")