# Copyright 2013-2014 Camptocamp SA - Guewen Baconnier
# © 2016-20 ForgeFlow S.L. (https://www.forgeflow.com)
# © 2016 Serpent Consulting Services Pvt. Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import fields, models
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    procurement_group_id = fields.Many2one(
        "procurement.group", "Procurement group", copy=False
    )

    def _get_procurement_group(self):
        super()._get_procurement_group()
        return self.procurement_group_id or False

    def _get_procurement_group_key(self):
        """Return a key with priority to be used to regroup lines in multiple
        procurement groups

        """
        return 8, self.order_id.id

    def _ensure_company_context(self, line):
        """
        替代 line.with_company(line.company_id) 的安全公司上下文切换。

        with_company() 会将 allowed_company_ids 强行覆盖为 [company_id]，
        在 sudo() 后调用的场景下，这会丢失环境中已有的多公司权限上下文，
        导致后续 stock.picking.type / stock.rule 的 _check_company_auto
        搜索过滤掉所有未归属于该单公司的记录，返回空结果，从而静默跳过
        发货单的生成。

        本方法使用合并策略：
        - 保留环境中已有的 allowed_company_ids
        - 确保 line.company_id 在其中
        - 不依赖 with_company() 的覆盖行为
        """
        company = line.company_id
        company_id = company.id if company else self.env.company.id
        current_allowed = line.env.context.get("allowed_company_ids")
        if current_allowed is None:
            user_companies = self.env.user.company_ids.ids
            if user_companies:
                new_allowed = list(user_companies)
            elif self.env.company:
                new_allowed = [self.env.company.id]
            else:
                new_allowed = []
        else:
            new_allowed = list(current_allowed)
        if company_id not in new_allowed:
            new_allowed.append(company_id)
        return line.with_context(allowed_company_ids=new_allowed)

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """
        Launch procurement group run method.

        Fix: 在同事务中动态修改订单行产品后，ORM 的字段级缓存
        （按 (model, field, record_id) 三层索引）可能持有陈旧的
        product_id、route_ids 等字段值，导致基于产品路线判断的
        采购逻辑读取到过期数据。

        修复策略：
        1. 在遍历之前，对整个记录集执行 invalidate_recordset()，
           强制下次字段访问时重新从数据库加载
        2. 额外对关联的 product.product 记录集的关键字段
           (route_ids, categ_id) 执行精确缓存失效
        3. 使用 _ensure_company_context 替代 with_company()，
           避免 allowed_company_ids 被覆盖
        """
        if self._context.get("skip_procurement"):
            return True

        self.invalidate_recordset()
        for line in self:
            if line.product_id:
                line.product_id.invalidate_recordset(
                    fnames=["route_ids", "categ_id"]
                )

        precision = self.env["decimal.precision"].precision_get(
            "Product Unit of Measure"
        )
        procurements = []
        groups = {}
        procured_line_ids = set()
        if not previous_product_uom_qty:
            previous_product_uom_qty = {}
        for line in self:
            line = self._ensure_company_context(line)
            if (
                line.state != "sale"
                or line.order_id.locked
                or line.product_id.type != "consu"
            ):
                continue
            qty = line._get_qty_procurement(previous_product_uom_qty) or 0.0
            if (
                float_compare(qty, line.product_uom_qty, precision_digits=precision)
                == 0
            ):
                continue

            group_id = line._get_procurement_group()

            for order_line in line.order_id.order_line:
                g_id = order_line.procurement_group_id or False
                if g_id:
                    groups[order_line._get_procurement_group_key()] = g_id
            if not group_id:
                group_id = groups.get(line._get_procurement_group_key())

            if not group_id:
                vals = line._prepare_procurement_group_vals()
                group_id = self.env["procurement.group"].create(vals)
                line.order_id.procurement_group_id = group_id
            else:
                updated_vals = {}
                if group_id.partner_id != line.order_id.partner_shipping_id:
                    updated_vals.update(
                        {"partner_id": line.order_id.partner_shipping_id.id}
                    )
                if group_id.move_type != line.order_id.picking_policy:
                    updated_vals.update({"move_type": line.order_id.picking_policy})
                if updated_vals:
                    group_id.write(updated_vals)
            line.procurement_group_id = group_id

            values = line._prepare_procurement_values(group_id=group_id)
            product_qty = line.product_uom_qty - qty

            line_uom = line.product_uom
            quant_uom = line.product_id.uom_id
            origin = (
                f"{line.order_id.name} - {line.order_id.client_order_ref}"
                if line.order_id.client_order_ref
                else line.order_id.name
            )
            product_qty, procurement_uom = line_uom._adjust_uom_quantities(
                product_qty, quant_uom
            )
            procurements += line._create_procurements(
                product_qty, procurement_uom, origin, values
            )
            procured_line_ids.add(line.id)
            previous_product_uom_qty[line.id] = line.product_uom_qty
        if procurements:
            _logger.debug(
                "Running procurements for %d lines with "
                "allowed_company_ids=%s",
                len(procurements),
                self.env.context.get("allowed_company_ids"),
            )
            self.env["procurement.group"].run(procurements)
        orders = self.mapped("order_id")
        for order in orders:
            pickings_to_confirm = order.picking_ids.filtered(
                lambda p: p.state not in ["cancel", "done"]
            )
            if pickings_to_confirm:
                pickings_to_confirm.action_confirm()
        remaining_lines = self - self.browse(procured_line_ids)
        return super(
            SaleOrderLine, remaining_lines.with_context(sale_group_by_line=True)
        )._action_launch_stock_rule(previous_product_uom_qty=previous_product_uom_qty)