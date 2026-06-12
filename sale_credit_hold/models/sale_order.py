from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    state = fields.Selection(
        selection_add=[("credit_hold", "Credit Hold")],
        ondelete={"credit_hold": "set default"},
    )

    credit_hold = fields.Boolean(
        string="Credit Hold",
        compute="_compute_credit_hold",
        store=True,
        tracking=True,
        help="Technical field indicating the order is on credit hold",
    )
    credit_hold_released_date = fields.Datetime(
        string="Credit Hold Released Date",
        readonly=True,
        copy=False,
    )
    credit_hold_released_by = fields.Many2one(
        comodel_name="res.users",
        string="Credit Hold Released By",
        readonly=True,
        copy=False,
    )

    @api.depends("state", "partner_id.credit_limit", "partner_id.credit")
    def _compute_credit_hold(self):
        for order in self:
            if order.state == "credit_hold":
                order.credit_hold = True
            elif order.state in ("draft", "sent", "cancel"):
                order.credit_hold = False
            else:
                order.credit_hold = False

    def _get_credit_hold_state_name(self):
        return "credit_hold"

    def _check_partner_credit_limit(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner.credit_limit:
            return False
        if partner.credit_limit <= 0:
            return False
        return partner.credit > partner.credit_limit

    def _action_confirm(self):
        credit_hold_orders = self.browse()
        normal_orders = self.browse()
        for order in self:
            if order.state not in ("draft", "sent"):
                normal_orders |= order
            elif order._check_partner_credit_limit():
                credit_hold_orders |= order
            else:
                normal_orders |= order

        if normal_orders:
            res = super(SaleOrder, normal_orders)._action_confirm()
        else:
            res = True

        if credit_hold_orders:
            credit_hold_orders._set_credit_hold_state()

        return res

    def _set_credit_hold_state(self):
        now = fields.Datetime.now()
        for order in self:
            order.write({"state": "credit_hold", "date_order": now})

    def action_release_credit(self):
        if not self.env.user.has_group(
            "sale_credit_hold.group_credit_manager"
        ):
            raise UserError(
                _("Only Credit Managers can release credit-hold orders.")
            )
        orders_to_release = self.filtered(
            lambda o: o.state == "credit_hold"
        )
        if not orders_to_release:
            return True
        orders_to_release.write(
            {
                "state": "sale",
                "credit_hold_released_date": fields.Datetime.now(),
                "credit_hold_released_by": self.env.user.id,
            }
        )
        orders_to_release._trigger_credit_hold_procurement()
        return True

    def _trigger_credit_hold_procurement(self):
        for order in self:
            order.order_line._action_launch_stock_rule()
            msg = _(
                "Credit hold released by %(user)s. "
                "Procurement and delivery processes have been triggered.",
                user=self.env.user.name,
            )
            order.message_post(body=msg)

    def action_confirm(self):
        credit_hold_orders = self.filtered(
            lambda o: o.state in ("draft", "sent")
            and o._check_partner_credit_limit()
        )
        if credit_hold_orders:
            return self._action_confirm()
        return super().action_confirm()

    def write(self, vals):
        if "state" in vals and vals["state"] == "sale":
            _bypass = self.env.context.get("bypass_credit_hold_check")
            _release = self.env.context.get("credit_hold_release")
            if not _bypass and not _release:
                for order in self:
                    if order.state == "credit_hold":
                        if not self.env.user.has_group(
                            "sale_credit_hold.group_credit_manager"
                        ):
                            raise UserError(
                                _(
                                    "Cannot change state from credit_hold to sale "
                                    "for order '%(name)s'. Only Credit Managers "
                                    "can release credit-hold orders via the "
                                    "'Release Credit Hold' action.",
                                    name=order.display_name,
                                )
                            )
        return super().write(vals)