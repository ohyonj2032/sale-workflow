from odoo import fields, models, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_total_margin = fields.Float(
        string='Total Margin',
        compute='_compute_x_total_margin',
        store=True,
    )

    @api.depends('order_line.margin')
    def _compute_x_total_margin(self):
        for order in self:
            order.x_total_margin = sum(order.order_line.mapped('margin'))
