# Copyright 2024 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    """
    销售订单模型增强，修复多公司环境下确认订单时的发货单生成问题。
    """
    _inherit = 'sale.order'

    def action_confirm(self):
        """
        覆盖标准的 action_confirm 方法，在执行前正确处理多公司环境上下文和缓存。
        """
        # 记录开始
        _logger.debug(
            "Starting sale.order.action_confirm for orders: %s (ids: %s)",
            self.mapped('name'), self.ids
        )

        # 步骤 1: 确保订单行的缓存是最新的
        for order in self:
            # 精确失效与产品和路线相关的字段缓存
            order.order_line.invalidate_cache_for_fields(
                ['product_id', 'product_uom', 'route_id', 'tax_id'],
                specific_records=order.order_line
            )

        # 步骤 2: 保存原始上下文，执行原生确认逻辑
        original_context = dict(self.env.context)

        try:
            # 调用父类方法执行标准确认逻辑
            result = super(SaleOrder, self).action_confirm()

            # 步骤 3: 验证发货单是否正确生成
            for order in self:
                # 如果需要发货但没有生成，记录警告并尝试再次生成
                if order.picking_policy and not order.picking_ids:
                    _logger.warning(
                        "Potential issue: Sale Order %s confirmed but no pickings generated! "
                        "Attempting regeneration...",
                        order.name
                    )
                    # 尝试在正确的公司环境中重新触发生成
                    order._regenerate_missing_pickings()

            return result

        except Exception as e:
            _logger.error(
                "Error during sale order confirmation for orders %s: %s",
                self.ids, str(e), exc_info=True
            )
            raise

    def _regenerate_missing_pickings(self):
        """
        尝试重新生成缺失的发货单。
        使用安全的环境切换方法确保正确的公司上下文。
        """
        self.ensure_one()

        # 获取安全的环境，确保公司上下文正确
        safe_order = self.safe_with_company(self.company_id)

        # 使用 sale_stock 模块的原生逻辑重新生成
        if hasattr(safe_order, '_action_confirm'):
            # 重新触发确认后的物流动作
            safe_order._action_confirm()

        # 验证结果
        if safe_order.picking_ids:
            _logger.info(
                "Successfully regenerated pickings for sale order %s: %s",
                self.name, safe_order.picking_ids.mapped('name')
            )
        else:
            _logger.error(
                "Failed to regenerate pickings for sale order %s even after retry!",
                self.name
            )


class SaleOrderLine(models.Model):
    """
    销售订单行模型增强，添加精确的缓存失效方法。
    """
    _inherit = 'sale.order.line'

    def write(self, vals):
        """
        覆盖 write 方法，在修改产品等关键字段时自动处理缓存失效。
        """
        # 检查是否修改了可能影响路线或计算的关键字段
        cache_affecting_fields = ['product_id', 'product_uom', 'route_id']
        needs_cache_invalidation = any(field in vals for field in cache_affecting_fields)

        # 调用父类方法
        result = super(SaleOrderLine, self).write(vals)

        # 如果修改了关键字段，精确失效相关缓存
        if needs_cache_invalidation:
            self.invalidate_cache_for_fields(cache_affecting_fields)
            # 同时失效关联订单的相关缓存
            self.mapped('order_id').invalidate_cache_for_fields(['picking_ids', 'delivery_state'])

        return result
