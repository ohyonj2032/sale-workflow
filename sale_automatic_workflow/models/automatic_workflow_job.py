# Copyright 2011 Akretion Sébastien BEAU <sebastien.beau@akretion.com>
# Copyright 2013 Camptocamp SA (author: Guewen Baconnier)
# Copyright 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from contextlib import contextmanager

from odoo import api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


@contextmanager
def savepoint(cr):
    """Open a savepoint on the cursor, then yield.

    Warning: using this method, the exceptions are logged then discarded.
    """
    try:
        with cr.savepoint():
            yield
    except Exception:
        _logger.exception("Error during an automatic workflow action.")


class AutomaticWorkflowJob(models.Model):
    """Scheduler that will play automatically the validation of
    invoices, pickings..."""

    _name = "automatic.workflow.job"
    _description = (
        "Scheduler that will play automatically the validation of"
        " invoices, pickings..."
    )

    def _get_company_context_for_record(self, record):
        """
        Odoo 16 中，当 sudo() 与 with_company() 链式调用时，存在一个幽灵 Bug：
        sudo() 创建的新环境会基于 SUPERUSER 的上下文重建，其中可能不包含
        allowed_company_ids，或者包含一个由 ir.cron 调用方传入的不完整集合。
        随后 with_company(company) 会将 allowed_company_ids 强行覆盖为
        [company.id]，这会导致：

        1. 环境中的 env.companies 被限制为单一公司
        2. 后续 stock.picking.type / stock.rule / stock.warehouse 的搜索
           因 _check_company_auto 自动过滤机制，只能看到该公司的记录
        3. 若该公司的发货类型/路线未配置，search 返回空记录集
        4. procurement._run() → _get_rule() 找不到规则，静默跳过发货单生成

        本方法提供安全的公司上下文合并策略：
        - 保留环境中已有的 allowed_company_ids
        - 将 record.company_id 加入（若尚未在其中）
        - 显式传递 allowed_company_ids 而非依赖 with_company() 的覆盖行为

        Args:
            record: 包含 company_id 的业务记录（sale.order / account.move）

        Returns:
            dict: 合并后的上下文字典，可直接传入 with_context()
        """
        company = record.company_id
        company_id = company.id if company else self.env.company.id
        current_allowed = self.env.context.get("allowed_company_ids")
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
        return {"allowed_company_ids": new_allowed}

    def _switch_to_record_company(self, record):
        """
        为指定记录构建带有正确多公司上下文的新记录集。

        替代有问题的 record.with_company() 调用：
        - 使用 _get_company_context_for_record() 获取合并后的上下文
        - 显式传递 allowed_company_ids 避免被 with_company 覆盖
        - 同时处理 sudo() 场景下的上下文传播

        Args:
            record: 要切换公司环境的记录

        Returns:
            带有正确多公司上下文的新记录集
        """
        company_ctx = self._get_company_context_for_record(record)
        return record.with_context(**company_ctx)

    def _invalidate_record_and_children_cache(self, record):
        """
        Odoo 16 的 ORM 缓存按 (model, field, record_id) 三级索引，共享于同一
        psycopg2 游标内。当同事务中有其他代码路径（如前端 write）修改了关联
        字段后，缓存虽被标记更新，但在以下场景下可能读取到陈旧数据：

        1. 计算字段的级联依赖：product_id 变更 → route_ids 重新计算，
           但 route_ids 的结果缓存条目可能未被触发逐出
        2. 跨记录集引用：通过 sale.order 加载的 order_line 缓存条目，
           与通过 sale.order.line 直接查询的条目是同一份缓存，
           但 related 字段的中间层可能未刷新
        3. flush() 时序问题：write 先写入 DB 再更新缓存，
           若中间有其他线程/游标操作，可能导致缓存与 DB 不一致

        本方法执行精确的缓存失效：
        - 先 invalidate_recordset() 清除记录集所有字段缓存
        - 针对可能产生 stale 关联计算的关键字段做二次保障

        注意：此方法仅对当前 env（及其共享游标的 env）生效，
        不会影响不同游标的独立事务。
        """
        record.invalidate_recordset()
        if record._name == "sale.order":
            order_lines = record.mapped("order_line")
            if order_lines:
                order_lines.invalidate_recordset()
                for line in order_lines:
                    if line.product_id:
                        line.product_id.invalidate_recordset(
                            fnames=["route_ids", "categ_id"]
                        )

    def _do_validate_sale_order(self, sale, domain_filter):
        """Validate a sales order, filter ensure no duplication"""
        if not self.env["sale.order"].search_count(
            [("id", "=", sale.id)] + domain_filter
        ):
            return f"{sale.display_name} {sale} job bypassed"
        sale = self._switch_to_record_company(sale)
        self._invalidate_record_and_children_cache(sale)
        _logger.debug(
            "Confirming sale order %s with allowed_company_ids=%s",
            sale.name,
            sale.env.context.get("allowed_company_ids"),
        )
        sale.action_confirm()
        return f"{sale.display_name} {sale} confirmed successfully"

    def _do_send_order_confirmation_mail(self, sale):
        """Send order confirmation mail, while filtering to make sure the order is
        confirmed with _do_validate_sale_order() function"""
        if not self.env["sale.order"].search_count(
            [("id", "=", sale.id), ("state", "=", "sale")]
        ):
            return f"{sale.display_name} {sale} job bypassed"
        if sale.user_id:
            sale = sale.with_user(sale.user_id)
        sale._send_order_confirmation_mail()
        return f"{sale.display_name} {sale} send order confirmation mail successfully"

    @api.model
    def _validate_sale_orders(self, order_filter):
        sale_obj = self.env["sale.order"]
        sales = sale_obj.search(order_filter)
        _logger.debug("Sale Orders to validate: %s", sales.ids)
        for sale in sales:
            with savepoint(self.env.cr):
                self._do_validate_sale_order(sale, order_filter)
                if self.env.context.get("send_order_confirmation_mail"):
                    self._do_send_order_confirmation_mail(sale)

    def _do_create_invoice(self, sale, domain_filter):
        """Create an invoice for a sales order, filter ensure no duplication"""
        if not self.env["sale.order"].search_count(
            [("id", "=", sale.id)] + domain_filter
        ):
            return f"{sale.display_name} {sale} job bypassed"
        sale = self._switch_to_record_company(sale)
        self._invalidate_record_and_children_cache(sale)
        payment = self.env["sale.advance.payment.inv"].create(
            {"sale_order_ids": sale.ids}
        )
        payment.with_context(active_model="sale.order").create_invoices()
        return f"{sale.display_name} {sale} create invoice successfully"

    @api.model
    def _create_invoices(self, create_filter):
        sale_obj = self.env["sale.order"]
        sales = sale_obj.search(create_filter)
        _logger.debug("Sale Orders to create Invoice: %s", sales.ids)
        for sale in sales:
            with savepoint(self.env.cr):
                self._do_create_invoice(sale, create_filter)

    def _do_validate_invoice(self, invoice, domain_filter):
        """Validate an invoice, filter ensure no duplication"""
        if not self.env["account.move"].search_count(
            [("id", "=", invoice.id)] + domain_filter
        ):
            return f"{invoice.display_name} {invoice} job bypassed"
        invoice = self._switch_to_record_company(invoice)
        invoice.invalidate_recordset()
        _logger.debug(
            "Posting invoice %s with allowed_company_ids=%s",
            invoice.name,
            invoice.env.context.get("allowed_company_ids"),
        )
        invoice.action_post()
        return f"{invoice.display_name} {invoice} validate invoice successfully"

    @api.model
    def _validate_invoices(self, validate_invoice_filter):
        move_obj = self.env["account.move"]
        invoices = move_obj.search(validate_invoice_filter)
        _logger.debug("Invoices to validate: %s", invoices.ids)
        for invoice in invoices:
            with savepoint(self.env.cr):
                self._do_validate_invoice(invoice, validate_invoice_filter)

    def _do_sale_done(self, sale, domain_filter):
        """Lock a sales order, filter ensure no duplication"""
        if not self.env["sale.order"].search_count(
            [("id", "=", sale.id)] + domain_filter
        ):
            return f"{sale.display_name} {sale} job bypassed"
        sale = self._switch_to_record_company(sale)
        self._invalidate_record_and_children_cache(sale)
        sale.action_lock()
        return f"{sale.display_name} {sale} locked successfully"

    @api.model
    def _sale_done(self, sale_done_filter):
        sales = self.env["sale.order"].search(sale_done_filter)
        _logger.debug("Sale Orders to done: %s", sales.ids)
        for sale in sales:
            with savepoint(self.env.cr):
                self._do_sale_done(sale, sale_done_filter)

    def _prepare_dict_account_payment(self, invoice):
        partner_type = (
            invoice.move_type in ("out_invoice", "out_refund")
            and "customer"
            or "supplier"
        )
        return {
            "reconciled_invoice_ids": [(6, 0, invoice.ids)],
            "amount": invoice.amount_residual,
            "partner_id": invoice.partner_id.id,
            "partner_type": partner_type,
            "date": fields.Date.context_today(self),
            "currency_id": invoice.currency_id.id,
        }

    @api.model
    def _register_payments(self, payment_filter):
        invoice_obj = self.env["account.move"]
        invoices = invoice_obj.search(payment_filter)
        _logger.debug("Invoices to Register Payment: %s", invoices.ids)
        for invoice in invoices:
            with savepoint(self.env.cr):
                self._register_payment_invoice(invoice)
        return

    def _register_payment_invoice(self, invoice):
        payment = self.env["account.payment"].create(
            self._prepare_dict_account_payment(invoice)
        )
        payment.action_post()

        domain = [
            ("account_type", "in", ("asset_receivable", "liability_payable")),
            ("reconciled", "=", False),
        ]
        payment_lines = payment.move_id.line_ids.filtered_domain(domain)
        lines = invoice.line_ids
        for account in payment_lines.account_id:
            (payment_lines + lines).filtered_domain(
                [("account_id", "=", account.id), ("reconciled", "=", False)]
            ).reconcile()
        return payment

    @api.model
    def _handle_pickings(self, sale_workflow):
        pass

    def _sale_workflow_domain(self, workflow):
        return [("workflow_process_id", "=", workflow.id)]

    @api.model
    def run_with_workflow(self, sale_workflow):
        workflow_domain = self._sale_workflow_domain(sale_workflow)
        if sale_workflow.validate_order:
            self.with_context(
                send_order_confirmation_mail=sale_workflow.send_order_confirmation_mail
            )._validate_sale_orders(
                safe_eval(sale_workflow.order_filter_id.domain) + workflow_domain
            )
        self._handle_pickings(sale_workflow)
        if sale_workflow.create_invoice:
            self._create_invoices(
                safe_eval(sale_workflow.create_invoice_filter_id.domain)
                + workflow_domain
            )
        if sale_workflow.validate_invoice:
            self._validate_invoices(
                safe_eval(sale_workflow.validate_invoice_filter_id.domain)
                + workflow_domain
            )
        if sale_workflow.sale_done:
            self._sale_done(
                safe_eval(sale_workflow.sale_done_filter_id.domain) + workflow_domain
            )

        if sale_workflow.register_payment:
            self._register_payments(
                safe_eval(sale_workflow.payment_filter_id.domain) + workflow_domain
            )

    @api.model
    def _workflow_process_to_run_domain(self):
        return []

    @api.model
    def run(self):
        """Must be called from ir.cron"""
        sale_workflow_process = self.env["sale.workflow.process"]
        domain = self._workflow_process_to_run_domain()
        for sale_workflow in sale_workflow_process.search(domain):
            self.run_with_workflow(sale_workflow)
        return True