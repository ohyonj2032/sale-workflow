# Copyright 2024 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import common, tagged
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestEnvironmentUtils(common.TransactionCase):

    def setUp(self):
        super().setUp()

        # 创建测试公司
        self.company_1 = self.env['res.company'].create({
            'name': 'Test Company 1',
        })
        self.company_2 = self.env['res.company'].create({
            'name': 'Test Company 2',
        })

        # 创建测试用户，允许访问两个公司
        self.test_user = self.env['res.users'].create({
            'name': 'Test User',
            'login': 'testuser',
            'company_id': self.company_1.id,
            'company_ids': [(6, 0, [self.company_1.id, self.company_2.id])],
        })

        # 创建测试产品
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'type': 'product',
            'company_id': False,  # 共享产品
        })

    def test_safe_with_company_preserves_allowed_companies(self):
        """测试 safe_with_company 正确保留 allowed_company_ids"""
        # 使用测试用户的环境
        env = self.env(user=self.test_user)
        sale_order_obj = env['sale.order']

        # 创建测试订单
        order = sale_order_obj.create({
            'partner_id': self.test_user.partner_id.id,
            'company_id': self.company_1.id,
        })

        # 初始环境检查
        self.assertIn(self.company_1.id, order.env.context.get('allowed_company_ids', []))
        self.assertIn(self.company_2.id, order.env.context.get('allowed_company_ids', []))

        # 使用安全方法切换到公司2
        order_with_company_2 = order.safe_with_company(self.company_2)

        # 验证结果
        self.assertEqual(order_with_company_2.env.company.id, self.company_2.id)

        # 关键验证：两个公司都应该在 allowed_company_ids 中
        allowed_companies = order_with_company_2.env.context.get('allowed_company_ids', [])
        self.assertIn(self.company_1.id, allowed_companies)
        self.assertIn(self.company_2.id, allowed_companies)

    def test_safe_sudo_with_company_works_correctly(self):
        """测试 safe_sudo_with_company 方法正确工作"""
        # 创建订单
        order = self.env['sale.order'].create({
            'partner_id': self.env.user.partner_id.id,
            'company_id': self.company_1.id,
        })

        # 使用安全方法
        sudo_order = order.safe_sudo_with_company(self.company_2)

        # 验证
        self.assertTrue(sudo_order.env.su)  # 应该是 sudo
        self.assertEqual(sudo_order.env.company.id, self.company_2.id)
        # 应该保留 allowed_company_ids
        allowed = sudo_order.env.context.get('allowed_company_ids', [])
        self.assertIn(self.company_1.id, allowed)
        self.assertIn(self.company_2.id, allowed)

    def test_cache_invalidation_for_fields(self):
        """测试精确的缓存失效"""
        # 创建订单和订单行
        order = self.env['sale.order'].create({
            'partner_id': self.env.user.partner_id.id,
            'company_id': self.company_1.id,
        })
        order_line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'name': 'Test Line',
            'product_uom_qty': 1,
        })

        # 创建另一个产品用于测试
        product2 = self.env['product.product'].create({
            'name': 'Test Product 2',
            'type': 'product',
        })

        # 修改产品
        order_line.write({'product_id': product2.id})

        # 精确失效缓存
        order_line.invalidate_cache_for_fields(['product_id', 'route_id'])

        # 验证产品已更新（无异常即通过）
        self.assertEqual(order_line.product_id.id, product2.id)

    def test_context_trace_returns_complete_info(self):
        """测试 get_full_context_trace 返回完整信息"""
        order = self.env['sale.order'].create({
            'partner_id': self.env.user.partner_id.id,
            'company_id': self.company_1.id,
        })

        trace = order.get_full_context_trace()

        # 验证包含所有必要信息
        self.assertIn('context', trace)
        self.assertIn('company_id', trace)
        self.assertIn('user_id', trace)
        self.assertIn('allowed_company_ids', trace)
        self.assertIn('uid', trace)
        self.assertIn('su', trace)
        self.assertIn('model_name', trace)
        self.assertIn('record_ids', trace)
