# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

class TestSaleAdvancedWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestSaleAdvancedWorkflow, cls).setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        
        # Set the threshold parameter to 10000.0 for tests
        cls.env['ir.config_parameter'].sudo().set_param('sale_advanced_workflow.review_threshold', '10000.0')

        # Create a partner
        cls.partner = cls.env['res.partner'].create({'name': 'Test Partner'})

        # Create a product
        cls.product = cls.env['product.product'].create({
            'name': 'Test Product',
            'type': 'service',
            'list_price': 100.0,
            'invoice_policy': 'order',
        })

    def _create_sale_order(self, qty, price):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'price_unit': price,
            })],
        })
        return order

    def test_01_is_over_threshold(self):
        """Test the compute field is_over_threshold"""
        # Amount = 5000.0 (<= 10000.0)
        order_low = self._create_sale_order(50, 100.0)
        self.assertFalse(order_low.is_over_threshold, "Order amount is not over threshold")

        # Amount = 15000.0 (> 10000.0)
        order_high = self._create_sale_order(150, 100.0)
        self.assertTrue(order_high.is_over_threshold, "Order amount is over threshold")

    def test_02_action_pending_review_draft_state(self):
        """Test action_pending_review raises error if order is not confirmed"""
        order = self._create_sale_order(150, 100.0) # > 10000.0, state is 'draft'
        with self.assertRaises(UserError) as e:
            order.action_pending_review()
        self.assertIn('Only confirmed orders', str(e.exception))

    def test_03_action_pending_review_below_threshold(self):
        """Test action_pending_review raises error if amount is below threshold"""
        order = self._create_sale_order(50, 100.0) # 5000 <= 10000
        order.action_confirm() # State becomes 'sale'
        
        with self.assertRaises(UserError) as e:
            order.action_pending_review()
        self.assertIn('Order amount must exceed the threshold', str(e.exception))

    def test_04_action_pending_review_success(self):
        """Test successful action_pending_review"""
        order = self._create_sale_order(150, 100.0) # 15000 > 10000
        order.action_confirm() # State becomes 'sale'
        
        # Initially no invoices
        self.assertEqual(order.invoice_count, 0, "Order should not have invoices initially")
        
        # Trigger the workflow
        order.action_pending_review()
        
        # Check state
        self.assertEqual(order.state, 'pending_review', "Order state should be 'pending_review'")
        
        # Check invoice generation
        self.assertGreater(order.invoice_count, 0, "Order should have generated invoices")
