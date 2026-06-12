from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    credit_limit = fields.Monetary(
        string="Credit Limit",
        currency_field="company_currency_id",
        tracking=True,
        help="Maximum credit allowed for this partner. "
        "When exceeded, new sale orders will be put on credit hold.",
    )

    @api.model
    def _commercial_fields(self):
        commercial_fields = super()._commercial_fields()
        commercial_fields.append("credit_limit")
        return commercial_fields