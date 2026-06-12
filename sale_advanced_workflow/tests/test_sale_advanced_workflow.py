from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestSaleAdvancedWorkflow(TestSaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.company_data["product_order_no"]
        cls.product.invoice_policy = "order"

    @classmethod
    def _create_sale_order(cls, price_unit):
        return cls.env["sale.order"].with_context(tracking_disable=True).create(
            {
                "partner_id": cls.partner_a.id,
                "partner_invoice_id": cls.partner_a.id,
                "partner_shipping_id": cls.partner_a.id,
                "pricelist_id": cls.company_data["default_pricelist"].id,
                "order_line": [
                    Command.create(
                        {
                            "name": cls.product.name,
                            "product_id": cls.product.id,
                            "product_uom_qty": 1.0,
                            "product_uom": cls.product.uom_id.id,
                            "price_unit": price_unit,
                            "tax_id": False,
                        }
                    )
                ],
            }
        )

    def test_action_pending_review_requires_threshold(self):
        sale_order = self._create_sale_order(500.0)
        sale_order.action_confirm()

        with self.assertRaises(UserError):
            sale_order.action_pending_review()

        self.assertEqual(sale_order.state, "sale")
        self.assertFalse(sale_order.invoice_ids)

    def test_action_pending_review_creates_invoice_and_updates_state(self):
        sale_order = self._create_sale_order(1500.0)
        sale_order.action_confirm()

        result = sale_order.action_pending_review()

        self.assertTrue(result)
        self.assertEqual(sale_order.state, "pending_review")
        self.assertTrue(sale_order.invoice_ids)
        self.assertEqual(sale_order.invoice_ids.mapped("move_type"), ["out_invoice"])
