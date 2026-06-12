from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_total_margin = fields.Monetary(
        compute="_compute_x_total_margin",
        currency_field="currency_id",
        store=True,
        readonly=True,
        copy=False,
    )

    @api.depends(
        "order_line.display_type",
        "order_line.price_subtotal",
        "order_line.product_uom_qty",
        "order_line.product_id",
        "order_line.product_id.standard_price",
    )
    def _compute_x_total_margin(self):
        for order in self:
            order.x_total_margin = sum(
                line.price_subtotal
                - (line.product_uom_qty * line.product_id.standard_price)
                for line in order.order_line
                if not line.display_type
            )
