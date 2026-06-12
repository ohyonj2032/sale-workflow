# Copyright 2024 Akretion (http://www.akretion.com).
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    state = fields.Selection(
        selection_add=[
            ("credit_hold", "Credit Hold"),
        ],
        ondelete={"credit_hold": "set default"},
    )

    credit_hold = fields.Boolean(
        compute="_compute_credit_hold",
        store=True,
    )

    @api.depends("state")
    def _compute_credit_hold(self):
        for order in self:
            order.credit_hold = order.state == "credit_hold"

    def _check_credit_limit(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner.credit_limit or partner.credit_limit <= 0:
            return False
        credit_used = partner._get_credit_used()
        return (credit_used + self.amount_total) > partner.credit_limit

    def _action_confirm(self):
        if self.env.context.get("bypass_credit_check"):
            return super()._action_confirm()
        credit_hold_orders = self.filtered(lambda o: o._check_credit_limit())
        if credit_hold_orders:
            credit_hold_orders.write({"state": "credit_hold"})
            credit_hold_orders._compute_credit_hold()
        normal_orders = self - credit_hold_orders
        result = self.env["sale.order"]
        if normal_orders:
            result = super(SaleOrder, normal_orders)._action_confirm()
        return result | credit_hold_orders

    def action_release_credit(self):
        for order in self:
            if order.state != "credit_hold":
                raise UserError(
                    _("Only credit-held orders can be released.")
                )
        return self.with_context(bypass_credit_check=True)._action_confirm()

    def write(self, vals):
        if (
            vals.get("state") == "sale"
            and not self.env.context.get("bypass_credit_check")
        ):
            for order in self:
                if order.state == "credit_hold":
                    if not self.env.user.has_group(
                        "sale_credit_hold.group_credit_manager"
                    ):
                        raise UserError(
                            _(
                                "You cannot change a credit-held order to sale "
                                "state. Use the 'Release Credit' button instead."
                            )
                        )
        return super().write(vals)
