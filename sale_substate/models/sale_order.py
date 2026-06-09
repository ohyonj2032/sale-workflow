# Copyright 2019 Akretion
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    delivery_state = fields.Selection(
        selection=[
            ("no", "Nothing to Deliver"),
            ("pending", "Pending Delivery"),
            ("partial", "Partially Delivered"),
            ("delivered", "Fully Delivered"),
        ],
        string="Delivery State",
        compute="_compute_delivery_state",
        store=True,
        readonly=True,
        default="no",
        tracking=True,
        help="Indicates whether the sale order delivery progress based on picking state.",
    )

    @api.depends(
        "state",
        "picking_ids",
        "picking_ids.state",
        "order_line.qty_delivered",
        "order_line.product_uom_qty",
    )
    def _compute_delivery_state(self):
        for order in self:
            if order.state not in ("sale", "done"):
                order.delivery_state = "no"
                continue
            lines = order.order_line.filtered(
                lambda l: l.product_id and l.product_id.type != "service"
            )
            if not lines or all(l.product_uom_qty <= 0 for l in lines):
                order.delivery_state = "no"
                continue
            total = sum(l.product_uom_qty for l in lines)
            delivered = sum(l.qty_delivered for l in lines)
            if delivered <= 0:
                order.delivery_state = "pending"
            elif delivered < total:
                order.delivery_state = "partial"
            else:
                order.delivery_state = "delivered"

    def action_confirm(self):
        for order in self:
            if order.state not in ("draft", "sent"):
                raise UserError(
                    _("Only draft or sent orders can be confirmed.")
                )
        res = super().action_confirm()
        for order in self:
            order._update_delivery_state_after_confirm()
        return res

    def _update_delivery_state_after_confirm(self):
        self.ensure_one()
        if not self._origin:
            return
        self.env.add_to_compute(self._fields["delivery_state"], self)

    def action_deliver(self):
        self.ensure_one()
        if self.state not in ("sale",):
            raise UserError(
                _("Only confirmed sale orders can be delivered.")
            )
        pickings = self.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel")
        )
        if not pickings:
            raise UserError(_("No pending pickings found for this sale order."))
        for picking in pickings:
            for move in picking.move_ids:
                if move.state in ("done", "cancel"):
                    continue
                move.quantity_done = move.product_uom_qty
            picking.button_validate()
        self.invalidate_cache(fnames=["delivery_state"], ids=self.ids)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_partial_deliver(self, qty_to_deliver=None):
        self.ensure_one()
        if self.state not in ("sale",):
            raise UserError(
                _("Only confirmed sale orders can be partially delivered.")
            )
        pickings = self.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel")
        )
        if not pickings:
            raise UserError(_("No pending pickings found for this sale order."))
        for picking in pickings:
            for move in picking.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
            ):
                if qty_to_deliver is not None and qty_to_deliver > 0:
                    move.quantity_done = min(qty_to_deliver, move.product_uom_qty)
                else:
                    move.quantity_done = move.product_uom_qty / 2 if move.product_uom_qty > 0 else 0
            picking.button_validate()
        self.invalidate_cache(fnames=["delivery_state"], ids=self.ids)
        return {"type": "ir.actions.client", "tag": "reload"}
