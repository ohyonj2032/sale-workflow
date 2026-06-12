from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    PENDING_REVIEW_THRESHOLD = 1000.0

    state = fields.Selection(
        selection_add=[("pending_review", "Pending Review")],
        ondelete={
            "pending_review": lambda records: records.write({"state": "sale"})
        },
    )
    can_pending_review = fields.Boolean(compute="_compute_can_pending_review")

    @api.depends("state", "amount_total")
    def _compute_can_pending_review(self):
        for order in self:
            order.can_pending_review = (
                order.state == "sale"
                and order.amount_total > order._get_pending_review_threshold()
            )

    def _get_pending_review_threshold(self):
        self.ensure_one()
        return self.PENDING_REVIEW_THRESHOLD

    def action_pending_review(self):
        for order in self:
            if order.state != "sale":
                raise UserError(
                    _("Only confirmed orders can be moved to pending review.")
                )
            threshold = order._get_pending_review_threshold()
            if order.amount_total <= threshold:
                raise UserError(
                    _(
                        "Only orders above %(threshold).2f can be moved to pending review."
                    )
                    % {"threshold": threshold}
                )
            invoices = order._create_invoices()
            if not invoices:
                raise UserError(
                    _("No invoice could be created for this sales order.")
                )
            order.state = "pending_review"
        return True
