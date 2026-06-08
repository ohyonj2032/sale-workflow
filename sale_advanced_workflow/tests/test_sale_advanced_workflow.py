# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestSaleAdvancedWorkflow(TransactionCase):

    def setUp(self):
        super(TestSaleAdvancedWorkflow, self).setUp()
        self.SaleOrder = self.env['sale.order']
        self.partner = self.env['res.partner'].create({'name': 'Test Partner'})
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'type': 'consu',
            'list_price': 1000.0,
        })

    def test_action_pending_review_success(self):
        order = self.SaleOrder.create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 20,
                'price_unit': 1000.0,
            })]
        })
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertGreater(order.amount_total, order.review_threshold)
        
        order.action_pending_review()
        self.assertEqual(order.state, 'pending_review')

    def test_action_pending_review_not_confirmed(self):
        order = self.SaleOrder.create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 1000.0,
            })]
        })
        self.assertEqual(order.state, 'draft')
        
        with self.assertRaises(UserError):
            order.action_pending_review()

    def test_action_pending_review_below_threshold(self):
        order = self.SaleOrder.create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 5,
                'price_unit': 1000.0,
            })]
        })
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertLess(order.amount_total, order.review_threshold)
        
        with self.assertRaises(UserError):
            order.action_pending_review()
