# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    state = fields.Selection(selection_add=[
        ('pending_review', '待审核')
    ], ondelete={'pending_review': 'set default'})

    review_threshold = fields.Float(
        string='审核阈值',
        default=10000.0,
        help='订单金额超过此阈值需要审核'
    )

    def action_pending_review(self):
        for order in self:
            if order.state != 'sale':
                raise UserError(_('只有已确认的订单才能提交审核'))
            
            if order.amount_total <= order.review_threshold:
                raise UserError(_('订单金额 %.2f 未超过审核阈值 %.2f，无需审核') % (order.amount_total, order.review_threshold))
            
            order.write({'state': 'pending_review'})
            
            if not order.invoice_ids:
                order._create_invoices()
                
        return True
