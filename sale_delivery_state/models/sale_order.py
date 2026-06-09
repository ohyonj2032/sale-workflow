# Copyright 2018 Akretion (http://www.akretion.com).
# @author Pierrick BRUN <pierrick.brun@akretion.com>
# Copyright 2018 Camptocamp
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# Copyright 2023 Manuel Regidor <manuel.regidor@sygel.es>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
# Copyright 2026 Credit Hold Enhancement

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def _selection_state(self):
        """Return the state selection with ``credit_hold`` injected after ``sale``.

        This callable is referenced by the ``state`` field declaration so that
        the extra state is registered without breaking the ones defined by the
        ``sale`` addon or any third-party addon sitting in between in the
        module resolution order.
        """
        # Mirror the state list used by Odoo's ``sale`` module.
        base = [
            ("draft", _("Quotation")),
            ("sent", _("Quotation Sent")),
            ("sale", _("Sales Order")),
            ("done", _("Locked")),
            ("cancel", _("Cancelled")),
        ]
        if any(key == "credit_hold" for key, _label in base):
            return base
        try:
            idx = next(i for i, (key, _label) in enumerate(base) if key == "sale")
        except StopIteration:
            idx = len(base)
        extended = list(base)
        extended.insert(idx + 1, ("credit_hold", _("Credit Hold")))
        return extended

    # ``state`` is inherited from sale.order. We redeclare it so that our
    # custom callable ``_selection_state`` is used, which injects the
    # ``credit_hold`` value. Other attributes are intentionally preserved.
    state = fields.Selection(
        selection=_selection_state,
        string="Status",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
        default="draft",
    )

    credit_hold = fields.Boolean(
        string="Credit Hold",
        help="Technical flag, that order is blocked due to customer credit limit exceeded.",
        copy=False,
        readonly=True,
    )

    credit_hold_reason = fields.Char(
        string="Credit Hold Reason",
        help="Reason why the order was put on credit hold.",
        copy=False,
        readonly=True,
    )

    credit_hold_date = fields.Datetime(
        string="Credit Hold Date",
        help="Date when the order was put on credit hold.",
        copy=False,
        readonly=True,
    )

    delivery_status = fields.Selection(
        # Compute method have a different name then the field because
        # the method _compute_delivery_status already exist in odoo sale_stock
        compute="_compute_oca_delivery_status",
        store=True,
        # Respect the same order as in sale_stock
        # Including the 'started' state
        # that is not used here but we compute it
        # if pickings are available, to be compatible.
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
        """
        Returns True if all line have qty_delivered >= to ordered quantities

        If `delivery` module is installed, ignores the lines with delivery costs

        :returns: boolean
        """
        self.ensure_one()
        # Skip delivery costs lines
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
        """
        Returns True if at least one line is delivered

        :returns: boolean
        """
        self.ensure_one()
        # Skip delivery costs lines
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
        # Loose dep on sale_stock. Feel free to customize this method
        # to add your own logic or to create sale_stock glue module.
        # NOTE: as the delivery_status is stored the update of a picking
        # won't have any effect here. Hence, if you really want to
        # fully support the started state, you should trigger the update
        # of the sale order when a picking is updated.
        # For now, we don't care that much as this state was not used before.
        has_pickings = "picking_ids" in self._fields
        return has_pickings and any(p.state == "done" for p in self.picking_ids)

    def action_force_delivery_state(self):
        self.write({"force_delivery_state": True})

    def action_unforce_delivery_state(self):
        self.write({"force_delivery_state": False})

    # --------------------------------------------------------------
    # Credit hold business logic
    # --------------------------------------------------------------

    def _partner_credit_exceeded(self):
        """Return True if the customer has exceeded its credit limit.

        The check is performed on the commercial partner. It considers the
        current order amount + the already invoiced open balance vs. the defined
        credit_limit on the partner.
        """
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        credit_limit = partner.credit_limit or 0.0
        if not credit_limit:
            return False
        total_amount = self.amount_total or 0.0
        try:
            credit = partner.credit or 0.0
            debit = partner.debit or 0.0
            open_balance = debit - credit
        except Exception:
            open_balance = 0.0
        consumed = open_balance + total_amount
        precision = self.env["decimal.precision"].precision_get("Account")
        return float_compare(consumed, credit_limit, precision_digits=precision) > 0

    def _check_credit_hold(self):
        """Check if this order should be blocked on credit hold.

        :returns: True means the order must be set to credit_hold state.
        """
        self.ensure_one()
        if self.state not in ("draft", "sent"):
            return False
        return self._partner_credit_exceeded()

    def write(self, vals):
        """ORM-level protection: forbid unprivileged users to forcibly change the
        ``state`` from ``credit_hold`` back to ``sale`` without going through
        ``action_release_credit``.
        """
        if vals.get("state"):
            new_state = vals["state"]
            for order in self.filtered(lambda r: r.state == "credit_hold"):
                if new_state == "sale" and not self.env.context.get(
                    "bypass_credit_hold_protection"
                ):
                    if not self.user_has_groups(
                        "sale_delivery_state.group_credit_manager"
                    ):
                        raise AccessError(
                            _(
                                "You are not allowed to release an order from credit "
                                "hold. Please contact a credit manager."
                            )
                        )
        return super().write(vals)

    def _action_confirm(self, sync_step=False):
        """Override to inject credit hold check BEFORE the native flow.

        When the credit limit is exceeded, we short-circuit the normal flow
        (which would otherwise create stock pickings via ``sale_stock``) and
        leave the order in ``credit_hold`` state. The method still returns the
        same record set as the native implementation to keep the signature
        compatible with third-party addons overriding it.
        """
        to_hold = self.browse()
        remaining = self.browse()
        for order in self:
            if order._check_credit_hold():
                to_hold |= order
            else:
                remaining |= order

        if to_hold:
            to_hold.write(
                {
                    "state": "credit_hold",
                    "credit_hold": True,
                    "credit_hold_reason": _("Credit limit exceeded"),
                    "credit_hold_date": fields.Datetime.now(),
                }
            )
            _logger.info(
                "Sale orders %s put on credit hold (credit limit exceeded)",
                to_hold.ids,
            )

        if remaining:
            # ``super`` handles the creation of stock pickings via sale_stock
            super(SaleOrder, remaining)._action_confirm(sync_step=sync_step)
        return self

    def action_release_credit(self):
        """Release credit hold and trigger the delayed stock picking generation."""
        self.ensure_one()
        if self.state != "credit_hold":
            return
        if not self.user_has_groups("sale_delivery_state.group_credit_manager"):
            raise AccessError(
                _(
                    "You are not allowed to release orders from credit hold. "
                    "Please contact a credit manager."
                )
            )
        self = self.with_context(bypass_credit_hold_protection=True)
        self.write(
            {
                "state": "sale",
                "credit_hold": False,
                "credit_hold_reason": False,
                "credit_hold_date": False,
            }
        )
        # Invoke the native confirm logic directly, bypassing the credit hold
        # override, so that pickings are generated by ``sale_stock``.
        super(SaleOrder, self)._action_confirm(sync_step=True)
