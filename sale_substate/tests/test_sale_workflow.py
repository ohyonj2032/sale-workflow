# Copyright 2019 Akretion Mourad EL HADJ MIMOUNE
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestSaleWorkflowDeliveryState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.SaleOrder = cls.env["sale.order"]
        cls.SaleOrderLine = cls.env["sale.order.line"]
        cls.partner = cls.env["res.partner"].create({"name": "Test Partner"})
        cls.product_storable = cls.env["product.product"].create(
            {
                "name": "Test Storable Product",
                "type": "product",
            }
        )
        cls.product_service = cls.env["product.product"].create(
            {
                "name": "Test Service Product",
                "type": "service",
            }
        )

    def _create_sale_order(self, product, qty=10.0, price=100.0):
        order = self.SaleOrder.create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom": product.uom_id.id,
                            "name": product.name,
                            "price_unit": price,
                        },
                    )
                ],
            }
        )
        return order

    def test_delivery_state_draft_service(self):
        order = self._create_sale_order(self.product_service, qty=5.0)
        self.assertEqual(order.state, "draft")
        self.assertEqual(order.delivery_state, "no")

    def test_delivery_state_draft_storable(self):
        order = self._create_sale_order(self.product_storable, qty=5.0)
        self.assertEqual(order.state, "draft")
        self.assertEqual(order.delivery_state, "no")

    def test_delivery_state_after_confirm_storable(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertEqual(order.delivery_state, "pending")

    def test_delivery_state_after_confirm_service(self):
        order = self._create_sale_order(self.product_service, qty=5.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertEqual(order.delivery_state, "no")

    def test_partial_delivery_state(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        order.action_confirm()
        self.assertEqual(order.delivery_state, "pending")

        pickings = order.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
        self.assertTrue(pickings, "Expected at least one picking after confirmation")

        for picking in pickings:
            for move in picking.move_ids:
                move.quantity_done = move.product_uom_qty / 2.0
            picking.button_validate()

        order.invalidate_cache(fnames=["delivery_state"], ids=order.ids)
        self.assertEqual(order.delivery_state, "partial")

    def test_full_delivery_state(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        order.action_confirm()
        self.assertEqual(order.delivery_state, "pending")

        pickings = order.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
        self.assertTrue(pickings)

        for picking in pickings:
            for move in picking.move_ids:
                move.quantity_done = move.product_uom_qty
            picking.button_validate()

        order.invalidate_cache(fnames=["delivery_state"], ids=order.ids)
        self.assertEqual(order.delivery_state, "delivered")

    def test_action_deliver_changes_state(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        order.action_confirm()
        self.assertEqual(order.delivery_state, "pending")

        order.action_deliver()
        order.invalidate_cache(fnames=["delivery_state"], ids=order.ids)
        self.assertIn(order.delivery_state, ("delivered", "partial"))

    def test_action_partial_deliver_changes_state(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        order.action_confirm()
        self.assertEqual(order.delivery_state, "pending")

        order.action_partial_deliver(qty_to_deliver=3.0)
        order.invalidate_cache(fnames=["delivery_state"], ids=order.ids)
        self.assertIn(order.delivery_state, ("partial", "delivered"))

    def test_action_confirm_invalid_state_raises(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        order.action_confirm()
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_action_deliver_invalid_state_raises(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        self.assertEqual(order.state, "draft")
        with self.assertRaises(UserError):
            order.action_deliver()

    def test_action_partial_deliver_invalid_state_raises(self):
        order = self._create_sale_order(self.product_storable, qty=10.0)
        self.assertEqual(order.state, "draft")
        with self.assertRaises(UserError):
            order.action_partial_deliver()

    def test_multiple_orders_independent_state(self):
        order1 = self._create_sale_order(self.product_storable, qty=10.0)
        order2 = self._create_sale_order(self.product_storable, qty=5.0)
        order1.action_confirm()
        order2.action_confirm()
        self.assertEqual(order1.delivery_state, "pending")
        self.assertEqual(order2.delivery_state, "pending")

        pickings1 = order1.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
        for picking in pickings1:
            for move in picking.move_ids:
                move.quantity_done = move.product_uom_qty
            picking.button_validate()

        order1.invalidate_cache(fnames=["delivery_state"], ids=order1.ids)
        order2.invalidate_cache(fnames=["delivery_state"], ids=order2.ids)
        self.assertEqual(order1.delivery_state, "delivered")
        self.assertEqual(order2.delivery_state, "pending")
