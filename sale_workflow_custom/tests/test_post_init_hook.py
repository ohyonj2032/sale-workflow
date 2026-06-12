from odoo.tests.common import TransactionCase
from odoo.addons.sale_workflow_custom.hooks import post_init_hook

class TestPostInitHook(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 创建测试依赖的基础数据
        cls.partner = cls.env['res.partner'].create({'name': 'Test Hook Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'Test Hook Product',
            'type': 'consu',
        })

    def test_post_init_hook_migration(self):
        """
        测试 post_init_hook 数据迁移脚本。
        在已安装模块的测试环境中，手动调用该Hook。
        调用前通过ALTER TABLE模拟“字段存在但数据为空”的历史脏状态。
        """
        # 创建一个销售订单并包含明细
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.product.id,
                    'price_unit': 100.0,
                    'purchase_price': 70.0, # 如果 sale_margin 模块存在，margin 会基于此计算，通常 margin = 30
                }),
                (0, 0, {
                    'product_id': self.product.id,
                    'price_unit': 200.0,
                    'purchase_price': 150.0, # margin = 50
                })
            ]
        })
        
        # 强制设置 line 的 margin，避免因其他依赖计算失败
        order.order_line[0].margin = 30.0
        order.order_line[1].margin = 50.0

        # 1. 模拟历史脏状态：通过 ALTER TABLE 确保字段存在，并将其数据置空 (NULL)
        self.env.cr.execute("ALTER TABLE sale_order ADD COLUMN IF NOT EXISTS x_total_margin NUMERIC;")
        self.env.cr.execute("UPDATE sale_order SET x_total_margin = NULL WHERE id = %s", (order.id,))
        
        # 验证置空是否成功（必须直接查库，因为 ORM 缓存可能有值）
        self.env.cr.execute("SELECT x_total_margin FROM sale_order WHERE id = %s", (order.id,))
        res = self.env.cr.fetchone()
        self.assertIsNone(res[0], "The x_total_margin should be NULL before the hook runs.")

        # 2. 手动调用 post_init_hook
        post_init_hook(self.env.cr, self.registry)

        # 3. 断言 SQL 更新的正确性
        # 由于 Hook 使用了原生 SQL 更新，ORM 层的缓存并不知道数据已改变，必须清空缓存。
        order.invalidate_recordset(['x_total_margin'])
        
        # 预期总利润为 30.0 + 50.0 = 80.0
        self.assertEqual(order.x_total_margin, 80.0, "x_total_margin was not correctly backfilled.")

        # 4. 测试幂等性：再次调用 Hook，检查值是否被重复累加
        post_init_hook(self.env.cr, self.registry)
        order.invalidate_recordset(['x_total_margin'])
        self.assertEqual(order.x_total_margin, 80.0, "The hook is not idempotent, value was modified upon second run.")
