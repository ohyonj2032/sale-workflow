from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    state = fields.Selection(
        selection_add=[
            ('partial', 'Partial Delivery'),
            ('delivered', 'Delivered'),
        ],
        ondelete={
            'partial': 'set default',
            'delivered': 'set default',
        }
    )

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        return res

    def action_deliver(self):
        for order in self:
            if order.state not in ['sale', 'partial']:
                raise UserError(_('Delivery can only be processed for confirmed or partially delivered orders.'))
            order.state = 'delivered'
        return True
