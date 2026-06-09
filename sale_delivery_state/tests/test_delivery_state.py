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

    def test_delivery_done_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            for line in self.order.order_line:
                if line._is_delivery():
                    continue
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

class TestCreditHold(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create({
            "name": "Test Credit Partner",
            "use_partner_credit_limit": True,
            "credit_limit": 100.0,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Expensive Product",
            "type": "consu",
            "list_price": 150.0,
        })
        cls.order = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "order_line": [(0, 0, {
                "product_id": cls.product.id,
                "product_uom_qty": 1,
                "price_unit": 150.0,
            })]
        })

    def test_credit_hold_flow(self):
        # 1. New order freeze
        self.order.action_confirm()
        self.assertEqual(self.order.state, "credit_hold")
        
        # 2. Test context isolation (normal user RPC bypass)
        with self.assertRaises(Exception):
            self.order.write({"state": "sale"})
            
        # 3. Release hold
        self.env.user.groups_id |= self.env.ref("sale_delivery_state.group_credit_manager")
        self.order.action_release_credit()
        self.assertEqual(self.order.state, "sale")

    def test_pre_init_hook_migration(self):
        # 1. Simulate pre-installation DB state
        # Force order into 'sale' state without triggering confirmation
        self.order.write({"state": "sale"})
        
        # 2. Run hook
        from ..hooks import _migrate_credit_hold_orders
        with mock.patch.object(self.env.cr, 'commit'):
            _migrate_credit_hold_orders(self.env)
        
        # 3. Verify migration
        self.order.invalidate_recordset()
        self.assertEqual(self.order.state, "credit_hold")
        
        # 4. Release and check pickings
        self.env.user.groups_id |= self.env.ref("sale_delivery_state.group_credit_manager")
        self.order.action_release_credit()
        self.assertEqual(self.order.state, "sale")
