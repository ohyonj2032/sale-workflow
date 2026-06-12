# Copyright 2024 Akretion (http://www.akretion.com).
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    credit_limit = fields.Float(
        string="Credit Limit",
        help="Maximum allowed credit for this partner. "
        "Set to 0 to disable credit checks.",
    )

    credit_used = fields.Float(
        string="Credit Used",
        compute="_compute_credit_used",
        store=False,
        help="Total amount of confirmed sale orders for this partner.",
    )

    @api.depends_context("company")
    def _compute_credit_used(self):
        SaleOrder = self.env["sale.order"]
        for partner in self:
            commercial = partner.commercial_partner_id
            domain = [
                ("partner_id", "child_of", commercial.id),
                ("state", "in", ["sale", "done"]),
            ]
            orders = SaleOrder.search(domain)
            partner.credit_used = sum(orders.mapped("amount_total"))

    def _get_credit_used(self):
        self.ensure_one()
        commercial = self.commercial_partner_id
        domain = [
            ("partner_id", "child_of", commercial.id),
            ("state", "in", ["sale", "done"]),
        ]
        orders = self.env["sale.order"].search(domain)
        return sum(orders.mapped("amount_total"))
