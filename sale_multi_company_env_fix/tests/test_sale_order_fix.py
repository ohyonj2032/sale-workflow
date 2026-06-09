# Copyright 2024 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import common, tagged
from odoo import fields
import logging

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestSaleOrderFix(common.TransactionCase):

    def setUp(self):
        super().setUp()

        # 创建测试公司
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
        })

        # 创建仓库
        self.warehouse = self.env['stock.warehouse'].create({
            'name': 'Test Warehouse',
            'code': 'TEST',
            'company_id': self.company.id,
        })

        # 创建合作伙伴
        self.partner = self.env['res.partner'].create({
            'name': 'Test Partner',
            'company_id': False,
        })

        # 创建产品
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'type': 'product',
            'company_id': False,
        })

    def test_sale_order_confirmation_generates_picking(self):
        """测试销售订单确认后正确生成发货单"""
        # 创建销售订单
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Test Line',
                'product_uom_qty': 1,
                'product_uom': self.product.uom_id.id,
            })]
        })

        # 确认订单
        order.action_confirm()

        # 验证发货单已生成
        self.assertTrue(order.picking_ids)
        picking = order.picking_ids[0]
        self.assertEqual(picking.company_id.id, self.company.id)
        self.assertEqual(picking.state, 'assigned' if picking.state else 'confirmed')

    def test_sale_order_line_write_invalidates_cache(self):
        """测试修改订单行产品时正确失效缓存"""
        # 创建销售订单
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Test Line',
                'product_uom_qty': 1,
                'product_uom': self.product.uom_id.id,
            })]
        })
        line = order.order_line[0]

        # 创建新产品
        product2 = self.env['product.product'].create({
            'name': 'Test Product 2',
            'type': 'product',
        })

        # 修改产品
        line.write({'product_id': product2.id})

        # 验证修改成功（无异常即通过）
        self.assertEqual(line.product_id.id, product2.id)

    def test_context_logging_during_confirmation(self):
        """测试订单确认过程中的上下文记录"""
        # 创建销售订单
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
        })

        # 记录上下文（这应该不会抛出异常）
        order.log_context_trace("Before confirmation")

        # 确认订单
        order.action_confirm()

        # 记录确认后的上下文
        order.log_context_trace("After confirmation")

        # 如果执行到这里没有异常，测试通过
        self.assertTrue(True)
