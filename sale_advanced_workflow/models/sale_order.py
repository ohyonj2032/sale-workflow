from odoo import api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    state = fields.Selection(
        selection_add=[("pending_review", "Pending Review")],
        ondelete={"pending_review": "set default"},
    )

    can_pending_review = fields.Boolean(
        compute="_compute_can_pending_review",
    )

    review_threshold = fields.Float(
        string="Review Threshold",
        compute="_compute_review_threshold",
    )

    @api.depends_context("company")
    def _compute_review_threshold(self):
        ICP = self.env["ir.config_parameter"].sudo()
        for order in self:
            order.review_threshold = float(
                ICP.get_param("sale_advanced_workflow.review_threshold", 10000.0)
            )

    @api.depends("state", "amount_total")
    def _compute_can_pending_review(self):
        for order in self:
            order.can_pending_review = (
                order.state == "sale"
                and order.amount_total > order.review_threshold
            )

    def action_pending_review(self):
        for order in self:
            if order.state != "sale":
                raise UserError(
                    self.env._(
                        "Only confirmed sale orders can be submitted for review."
                    )
                )
            threshold = order.review_threshold
            if order.amount_total <= threshold:
                raise UserError(
                    self.env._(
                        "The order amount (%(amount)s) must exceed the review "
                        "threshold (%(threshold)s) to submit for review.",
                        amount=order.amount_total,
                        threshold=threshold,
                    )
                )
            order._create_invoices(grouped=False)
        self.write({"state": "pending_review"})
        return True
