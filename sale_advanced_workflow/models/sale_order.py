# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    state = fields.Selection(
        selection_add=[('pending_review', 'Pending Review')],
        ondelete={'pending_review': 'set default'}
    )

    is_over_threshold = fields.Boolean(
        string='Is Over Threshold',
        compute='_compute_is_over_threshold',
        store=True
    )

    @api.depends('amount_total')
    def _compute_is_over_threshold(self):
        for order in self:
            # We can use a configurable threshold, default to 10000.0
            threshold_str = self.env['ir.config_parameter'].sudo().get_param('sale_advanced_workflow.review_threshold', default='10000.0')
            try:
                threshold = float(threshold_str)
            except ValueError:
                threshold = 10000.0
            order.is_over_threshold = order.amount_total > threshold

    def action_pending_review(self):
        for order in self:
            if order.state != 'sale':
                raise UserError(_('Only confirmed orders can be sent for review.'))
            if not order.is_over_threshold:
                raise UserError(_('Order amount must exceed the threshold to enter pending review state.'))
            
            # Generate invoice
            # In Odoo 16, _create_invoices is used to create invoices from sale orders
            order._create_invoices()
            
            # Change state
            order.state = 'pending_review'
