# Copyright 2018 Akretion (http://www.akretion.com).
# @author Pierrick BRUN <pierrick.brun@akretion.com>
# Copyright 2018 Camptocamp
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# Copyright 2023 Manuel Regidor <manuel.regidor@sygel.es>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero


class SaleOrder(models.Model):
    _inherit = "sale.order"

    state = fields.Selection(
        selection_add=[("credit_hold", "Credit Hold")],
        ondelete={"credit_hold": "set default"},
    )

    delivery_status = fields.Selection(
        compute="_compute_oca_delivery_status",
        store=True,
        selection=[
            ("pending", "Not Delivered"),
            ("started", "Started"),
            ("partial", "Partially Delivered"),
            ("full", "Fully Delivered"),
        ],
    )

    force_delivery_state = fields.Boolean(
        help=(
            "Allow to enforce done state of delivery, for instance if some"
            " quantities were cancelled"
        ),
    )

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

    def _get_credit_partner(self):
        self.ensure_one()
        return self.partner_id.commercial_partner_id

    def _get_credit_limit_amount(self):
        self.ensure_one()
        partner = self._get_credit_partner()
        if "credit_limit" not in partner._fields:
            return 0.0
        return partner.credit_limit or 0.0

    def _get_credit_exposure_amount(self):
        self.ensure_one()
        partner = self._get_credit_partner()
        if "credit" not in partner._fields:
            return 0.0
        return (partner.credit or 0.0) + self.amount_total

    def _is_credit_hold_required(self):
        self.ensure_one()
        limit_amount = self._get_credit_limit_amount()
        if not limit_amount:
            return False
        return float_compare(
            self._get_credit_exposure_amount(),
            limit_amount,
            precision_rounding=self.currency_id.rounding,
        ) > 0

    def _action_confirm(self):
        credit_hold_orders = self.filtered(lambda order: order._is_credit_hold_required())
        res = super(
            SaleOrder,
            self.with_context(credit_hold_order_ids=credit_hold_orders.ids),
        )._action_confirm()
        if credit_hold_orders:
            credit_hold_orders.with_context(allow_credit_release=True).write(
                {"state": "credit_hold"}
            )
        return res

    def _has_active_pickings(self):
        self.ensure_one()
        if "picking_ids" not in self._fields:
            return False
        return bool(self.picking_ids.filtered(lambda picking: picking.state != "cancel"))

    def action_release_credit(self):
        if not self.env.user.has_group("sale_delivery_state.group_sale_credit_manager"):
            raise AccessError(
                _("Only users in the Credit Manager group can release a credit hold.")
            )
        held_orders = self.filtered(lambda order: order.state == "credit_hold")
        if not held_orders:
            return True
        held_orders.with_context(allow_credit_release=True).write({"state": "sale"})
        held_orders.filtered(lambda order: not order._has_active_pickings()).order_line._action_launch_stock_rule()
        return True

    def write(self, vals):
        if vals.get("state") == "sale":
            held_orders = self.filtered(lambda order: order.state == "credit_hold")
            if held_orders and not self.env.context.get("allow_credit_release"):
                raise UserError(
                    _(
                        "Use the Release Credit action to move a frozen sales order back to Sale."
                    )
                )
            if held_orders and not self.env.user.has_group(
                "sale_delivery_state.group_sale_credit_manager"
            ):
                raise AccessError(
                    _(
                        "Only users in the Credit Manager group can release a credit hold."
                    )
                )
        return super().write(vals)

    def action_force_delivery_state(self):
        self.write({"force_delivery_state": True})

    def action_unforce_delivery_state(self):
        self.write({"force_delivery_state": False})
