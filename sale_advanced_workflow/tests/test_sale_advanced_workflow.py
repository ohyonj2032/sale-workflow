from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.base.tests.common import BaseCommon


@tagged("post_install", "-at_install")
class TestSaleAdvancedWorkflow(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Test Partner"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "list_price": 15000.0,
                "type": "consu",
                "invoice_policy": "order",
            }
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "sale_advanced_workflow.review_threshold", 10000.0
        )

    def _create_sale_order(self, price_unit=15000.0, qty=1):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    Command.create(
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": qty,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": price_unit,
                        }
                    )
                ],
            }
        )

    def test_state_transition_above_threshold(self):
        order = self._create_sale_order(price_unit=15000.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.can_pending_review)
        order.action_pending_review()
        self.assertEqual(order.state, "pending_review")

    def test_state_transition_below_threshold(self):
        order = self._create_sale_order(price_unit=5000.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.can_pending_review)
        with self.assertRaises(UserError):
            order.action_pending_review()

    def test_state_transition_not_confirmed(self):
        order = self._create_sale_order(price_unit=15000.0)
        self.assertEqual(order.state, "draft")
        with self.assertRaises(UserError):
            order.action_pending_review()

    def test_invoice_created_on_pending_review(self):
        order = self._create_sale_order(price_unit=15000.0)
        order.action_confirm()
        invoice_count_before = len(order.invoice_ids)
        order.action_pending_review()
        invoice_count_after = len(order.invoice_ids)
        self.assertGreater(invoice_count_after, invoice_count_before)

    def test_can_pending_review_computation(self):
        order = self._create_sale_order(price_unit=5000.0)
        self.assertEqual(order.state, "draft")
        self.assertFalse(order.can_pending_review)
        order.action_confirm()
        self.assertFalse(order.can_pending_review)
        order.order_line[0].price_unit = 15000.0
        self.assertTrue(order.can_pending_review)

    def test_review_threshold_from_config(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_advanced_workflow.review_threshold", 5000.0
        )
        order = self._create_sale_order(price_unit=8000.0)
        order.action_confirm()
        self.assertTrue(order.can_pending_review)
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_advanced_workflow.review_threshold", 10000.0
        )
