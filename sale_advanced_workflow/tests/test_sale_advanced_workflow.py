# Copyright 2025 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestSaleAdvancedWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_product_6")
        cls.pricelist = cls.env.ref("product.list0", False)
        if not cls.pricelist:
            cls.pricelist = cls.env["product.pricelist"].create(
                {"name": "Public Pricelist"}
            )

    def _create_sale_order(self, product_qty=2, price_unit=100.0):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    Command.create(
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": product_qty,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": price_unit,
                        }
                    )
                ],
                "pricelist_id": self.pricelist.id,
            }
        )

    def _set_threshold(self, value):
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_advanced_workflow.pending_review_threshold", str(value)
        )

    def test_action_pending_review_above_threshold(self):
        self._set_threshold(100.0)
        order = self._create_sale_order(product_qty=2, price_unit=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        order.action_pending_review()
        self.assertEqual(order.state, "pending_review")

    def test_action_pending_review_below_threshold_raises(self):
        self._set_threshold(500.0)
        order = self._create_sale_order(product_qty=2, price_unit=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        with self.assertRaises(UserError):
            order.action_pending_review()
        self.assertEqual(order.state, "sale")

    def test_action_pending_review_in_draft_raises(self):
        self._set_threshold(0.0)
        order = self._create_sale_order(product_qty=2, price_unit=100.0)
        self.assertEqual(order.state, "draft")
        with self.assertRaises(UserError):
            order.action_pending_review()

    def test_action_pending_review_creates_invoice(self):
        self._set_threshold(0.0)
        order = self._create_sale_order(product_qty=2, price_unit=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        order.action_pending_review()
        self.assertEqual(order.state, "pending_review")
        self.assertTrue(order.invoice_ids)
        self.assertEqual(order.invoice_ids.move_type, "out_invoice")