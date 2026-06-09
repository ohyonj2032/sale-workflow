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

    @api.model
    def _with_company_safe(self, record, company):
        """Safely switch company context preserving all allowed companies.

        ROOT CAUSE FIX for the ghost bug where sudo().with_company() chaining
        causes allowed_company_ids to be incorrectly overwritten.

        In Odoo 16, the native with_company() implementation reconstructs
        allowed_company_ids by taking the current context's value and
        reordering it. This creates a critical bug when chained with sudo():

        1. sudo() creates a new environment with su=True, preserving the
           context but changing the user to SUPERUSER_ID
        2. with_company() then reads allowed_company_ids from the context
        3. If the context's allowed_company_ids was already modified by a
           previous sudo() call, or if the sudo user's company_ids differs
           from the original user's, the reconstructed allowed_company_ids
           will be incorrect
        4. This causes subsequent searches for stock.picking.type,
           stock.rule, stock.warehouse to return empty recordsets due to
           ir.rule company-based filtering, silently skipping delivery
           order generation without any error or rollback

        This method ensures:
        1. The target company is set as the active company (first position)
        2. All companies from the user's access are preserved in
           allowed_company_ids, not just those in the current context
        3. No companies are silently dropped from allowed_company_ids
        4. The record's environment is properly isolated for multi-company
           operations without breaking sale_stock's native call stack
        """
        company_id = company.id if company else False
        current_allowed = record.env.context.get("allowed_company_ids", [])
        if not current_allowed:
            current_allowed = record.env.user.company_ids.ids
        new_allowed = [company_id] + [
            cid for cid in current_allowed if cid != company_id
        ]
        return record.with_context(allowed_company_ids=new_allowed)

    @api.model
    def _invalidate_sale_order_cache(self, sale):
        """Targeted ORM cache invalidation for sale order and related records.

        ORM CACHE GHOST FIX: When order line products are dynamically modified
        within the same transaction (e.g., changing product_id before
        confirmation), the ORM field cache retains stale data for the old
        product's fields (type, route_ids, is_storable). This causes
        _action_launch_stock_rule to read outdated values and silently skip
        delivery order generation.

        The stale cache manifests as:
        - line.product_id.type returns the OLD product's type (e.g., 'service')
        - line.product_id.route_ids returns the OLD product's routes
        - Since 'service' type lines are skipped with `continue`, no
          procurement is created and no picking is generated
        - The order state still transitions to 'sale' because action_confirm()
          does not verify that pickings were actually created

        This method performs TARGETED cache invalidation rather than the
        brute-force env.invalidate_all(), avoiding unnecessary cache clearing
        for unrelated records and fields.

        Specific invalidation targets:
        - sale.order: order_line (One2many dependency)
        - sale.order.line: product_id, product_uom, product_uom_qty
          (fields that trigger procurement logic)
        - product.product: type, route_ids, is_storable
          (fields used in _action_launch_stock_rule filtering)
        - product.template: type, route_ids, is_storable
          (template-level fields that product.product delegates to)
        """
        sale.invalidate_recordset(fnames=["order_line"])
        for line in sale.order_line:
            line.invalidate_recordset(
                fnames=["product_id", "product_uom", "product_uom_qty"]
            )
            if line.product_id:
                line.product_id.invalidate_recordset(
                    fnames=["type", "route_ids", "is_storable"]
                )
                line.product_id.product_tmpl_id.invalidate_recordset(
                    fnames=["type", "route_ids", "is_storable"]
                )

    def _do_validate_sale_order(self, sale, domain_filter):
        """Validate a sales order, filter ensure no duplication"""
        if not self.env["sale.order"].search_count(
            [("id", "=", sale.id)] + domain_filter
        ):
            return f"{sale.display_name} {sale} job bypassed"
        self._invalidate_sale_order_cache(sale)
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
                self._do_validate_sale_order(
                    self._with_company_safe(sale, sale.company_id), order_filter
                )
                if self.env.context.get("send_order_confirmation_mail"):
                    self._do_send_order_confirmation_mail(sale)

    def _do_create_invoice(self, sale, domain_filter):
        """Create an invoice for a sales order, filter ensure no duplication"""
        if not self.env["sale.order"].search_count(
            [("id", "=", sale.id)] + domain_filter
        ):
            return f"{sale.display_name} {sale} job bypassed"
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
                self._do_create_invoice(
                    self._with_company_safe(sale, sale.company_id), create_filter
                )

    def _do_validate_invoice(self, invoice, domain_filter):
        """Validate an invoice, filter ensure no duplication"""
        if not self.env["account.move"].search_count(
            [("id", "=", invoice.id)] + domain_filter
        ):
            return f"{invoice.display_name} {invoice} job bypassed"
        invoice.action_post()
        return f"{invoice.display_name} {invoice} validate invoice successfully"

    @api.model
    def _validate_invoices(self, validate_invoice_filter):
        move_obj = self.env["account.move"]
        invoices = move_obj.search(validate_invoice_filter)
        _logger.debug("Invoices to validate: %s", invoices.ids)
        for invoice in invoices:
            with savepoint(self.env.cr):
                self._do_validate_invoice(
                    self._with_company_safe(invoice, invoice.company_id),
                    validate_invoice_filter,
                )

    def _do_sale_done(self, sale, domain_filter):
        """Lock a sales order, filter ensure no duplication"""
        if not self.env["sale.order"].search_count(
            [("id", "=", sale.id)] + domain_filter
        ):
            return f"{sale.display_name} {sale} job bypassed"
        sale.action_lock()
        return f"{sale.display_name} {sale} locked successfully"

    @api.model
    def _sale_done(self, sale_done_filter):
        sales = self.env["sale.order"].search(sale_done_filter)
        _logger.debug("Sale Orders to done: %s", sales.ids)
        for sale in sales:
            with savepoint(self.env.cr):
                self._do_sale_done(
                    self._with_company_safe(sale, sale.company_id), sale_done_filter
                )

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
