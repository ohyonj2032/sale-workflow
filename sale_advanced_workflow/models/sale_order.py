# Copyright 2025 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    state = fields.Selection(
        selection_add=[("pending_review", "Pending Review")],
        ondelete={"pending_review": "set default"},
    )

    show_pending_review_button = fields.Boolean(
        compute="_compute_show_pending_review_button",
        compute_sudo=True,
    )

    def _get_pending_review_threshold(self):
        ICP = self.env["ir.config_parameter"].sudo()
        return float(
            ICP.get_param("sale_advanced_workflow.pending_review_threshold", "0.0")
        )

    @api.depends("state", "amount_total")
    def _compute_show_pending_review_button(self):
        threshold = self._get_pending_review_threshold()
        for order in self:
            order.show_pending_review_button = (
                order.state == "sale" and order.amount_total > threshold
            )

    def action_pending_review(self):
        self.ensure_one()
        threshold = self._get_pending_review_threshold()
        if self.amount_total <= threshold:
            raise UserError(
                _(
                    "The order total amount (%(amount).2f) does not exceed "
                    "the threshold (%(threshold).2f). "
                    "Cannot send to pending review.",
                    amount=self.amount_total,
                    threshold=threshold,
                )
            )
        self._create_invoices()
        self.write({"state": "pending_review"})