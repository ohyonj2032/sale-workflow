# Copyright 2018 Akretion (http://www.akretion.com).
# @author Pierrick BRUN <pierrick.brun@akretion.com>
# Copyright 2018 Camptocamp
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# Copyright 2023 Manuel Regidor <manuel.regidor@sygel.es>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.tools import float_compare, float_is_zero


class SaleOrder(models.Model):
    _inherit = "sale.order"

    DELIVERY_STATE = [
        ("pending", "Not Delivered"),
        ("started", "Started"),
        ("partial", "Partially Delivered"),
        ("full", "Fully Delivered"),
    ]

    delivery_status = fields.Selection(
        selection=DELIVERY_STATE,
        compute="_compute_oca_delivery_status",
        store=True,
        tracking=True,
    )

    force_delivery_state = fields.Boolean(
        help=(
            "Allow to enforce done state of delivery, for instance if some"
            " quantities were cancelled"
        ),
    )

    def _get_delivery_state_transitions(self):
        return {
            "pending": ["started"],
            "started": ["partial", "pending"],
            "partial": ["full", "pending"],
            "full": [],
        }

    def _is_valid_delivery_transition(self, from_state, to_state):
        transitions = self._get_delivery_state_transitions()
        return to_state in transitions.get(from_state, [])

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            if order.state == "sale":
                order._compute_oca_delivery_status()
        return res

    def action_deliver(self):
        for order in self:
            if order.state not in ("sale", "done"):
                continue
            if order.delivery_status == "full":
                continue
            order._compute_oca_delivery_status()

    def _all_qty_delivered(self):
        self.ensure_one()
        sale_lines = self.order_line.filtered(
            lambda rec: not rec._is_delivery() and not rec.skip_sale_delivery_state
        )
        precision = self.env["decimal.precision"].precision_get(
            "Product Unit of Measure"
        )
        return all(
            float_compare(
                line.qty_delivered, line.product_uom_qty, precision_digits=precision
            )
            >= 0
            for line in sale_lines
        )

    def _partially_delivered(self):
        self.ensure_one()
        sale_lines = self.order_line.filtered(
            lambda rec: not rec._is_delivery() and not rec.skip_sale_delivery_state
        )
        precision = self.env["decimal.precision"].precision_get(
            "Product Unit of Measure"
        )
        return any(
            not float_is_zero(line.qty_delivered, precision_digits=precision)
            for line in sale_lines
        )

    @api.depends(
        "order_line.qty_delivered",
        "order_line.skip_sale_delivery_state",
        "state",
        "force_delivery_state",
    )
    def _compute_oca_delivery_status(self):
        for order in self:
            if order.state in ("draft", "cancel"):
                order.delivery_status = None
            elif order.force_delivery_state or order._all_qty_delivered():
                order.delivery_status = "full"
            elif order._partially_delivered():
                order.delivery_status = "partial"
            elif order._is_delivery_status_started():
                order.delivery_status = "started"
            else:
                order.delivery_status = "pending"

    def _is_delivery_status_started(self):
        has_pickings = "picking_ids" in self._fields
        return has_pickings and any(p.state == "done" for p in self.picking_ids)

    def action_force_delivery_state(self):
        self.write({"force_delivery_state": True})

    def action_unforce_delivery_state(self):
        self.write({"force_delivery_state": False})