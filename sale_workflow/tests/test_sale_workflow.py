from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

class TestSaleWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestSaleWorkflow, cls).setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Test Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'Test Product',
            'type': 'consu',
        })
        cls.sale_order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 10,
                'price_unit': 100.0,
            })],
        })

    def test_action_confirm(self):
        """Test confirmation logic"""
        self.sale_order.action_confirm()
        self.assertEqual(self.sale_order.state, 'sale', 'State should be confirmed')

    def test_partial_delivery_transition(self):
        """Test partial delivery transition logic"""
        self.sale_order.action_confirm()
        self.sale_order.state = 'partial'
        self.assertEqual(self.sale_order.state, 'partial', 'State should be partial')
        
        self.sale_order.action_deliver()
        self.assertEqual(self.sale_order.state, 'delivered', 'State should be delivered after partial')

    def test_invalid_delivery(self):
        """Test invalid delivery from draft state"""
        self.assertEqual(self.sale_order.state, 'draft')
        with self.assertRaises(UserError):
            self.sale_order.action_deliver()
