# Copyright 2024 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""
使用示例 - 展示如何正确修复多公司环境切换问题
"""

from odoo import models, api


class BadExample(models.Model):
    """
    ❌ 错误的示例 - 不要这样做！
    """
    _name = 'bad.example'
    _inherit = ['environment.utils']  # 继承环境工具类

    def problematic_method(self, company_id):
        """
        ❌ 错误：sudo().with_company() 链式调用
        这会导致 allowed_company_ids 被错误覆盖！
        """
        # 获取记录并执行环境切换
        record = self.env['some.model'].browse(1)

        # 错误的调用链
        result = record.sudo().with_company(company_id).do_something()

        return result


class GoodExample(models.Model):
    """
    ✅ 正确的示例 - 推荐做法
    """
    _name = 'good.example'
    _inherit = ['environment.utils']

    def fixed_method_1(self, company_id):
        """
        ✅ 方法 1：先切换公司，再 sudo（分步执行）
        """
        record = self.env['some.model'].browse(1)

        # 正确的做法：分步执行
        record_with_company = record.with_company(company_id)
        sudo_record = record_with_company.sudo()
        result = sudo_record.do_something()

        return result

    def fixed_method_2(self, company_id):
        """
        ✅ 方法 2：使用 safe_with_company() 和 safe_sudo_with_company()
        """
        record = self.env['some.model'].browse(1)

        # 使用模块提供的安全方法
        result = record.safe_sudo_with_company(company_id).do_something()

        return result

    def fixed_method_3(self, company_id):
        """
        ✅ 方法 3：使用 safe_with_company() 然后再 sudo
        """
        record = self.env['some.model'].browse(1)

        # 分步使用安全方法
        safe_record = record.safe_with_company(company_id)
        sudo_safe = safe_record.sudo()
        result = sudo_safe.do_something()

        return result


class CacheExample(models.Model):
    """
    ORM 缓存正确处理示例
    """
    _name = 'cache.example'
    _inherit = ['environment.utils']

    def update_product_and_routes(self, order_line):
        """
        正确处理缓存失效的示例
        """
        # 修改产品
        new_product = self.env['product.product'].browse(42)
        order_line.write({'product_id': new_product.id})

        # ✅ 正确：精确失效相关字段的缓存，而非全量清除
        order_line.invalidate_cache_for_fields(
            ['product_id', 'route_id', 'product_uom', 'tax_id']
        )

        # 现在继续处理，会读取最新数据
        order_line._compute_routes()  # 会使用最新的产品数据

    def debug_context_example(self, record):
        """
        正确的调试方法示例
        """
        # ❌ 错误：直接打印 context 可能误导
        print(self.env.context)  # 不够全面

        # ✅ 正确：使用 log_context_trace() 或 get_full_context_trace()
        record.log_context_trace("Before company switch")

        # 执行一些操作
        record = record.safe_with_company(self.company_id)

        record.log_context_trace("After company switch")

        # 或者获取详细信息进行分析
        trace_info = record.get_full_context_trace()
        print(f"Company: {trace_info['company_id']}")
        print(f"Allowed: {trace_info['allowed_company_ids']}")


class SaleOrderExample(models.Model):
    """
    销售订单处理示例
    """
    _name = 'sale.order.example'
    _inherit = ['environment.utils', 'sale.order']

    def custom_confirm_with_company_change(self):
        """
        在确认订单时需要切换公司的场景
        """
        for order in self:
            # 记录初始状态
            order.log_context_trace("Initial state before confirmation")

            # 首先确保缓存是最新的
            order.order_line.invalidate_cache_for_fields(['product_id', 'route_id'])

            # 如果需要在另一个公司执行某些操作
            target_company = order.company_id.parent_id
            if target_company:
                # 使用安全方法切换公司
                company_specific_record = order.safe_with_company(target_company)
                company_specific_record.log_context_trace("Switched to target company")

                # 执行需要在该公司上下文中执行的操作
                company_specific_record._some_company_specific_logic()

            # 回到原公司确认订单
            order.log_context_trace("Back to original company for confirmation")

            # 调用确认方法
            order.action_confirm()
