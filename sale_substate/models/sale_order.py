# Copyright 2019 Akretion
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class BaseSubstateType(models.Model):
    _inherit = "base.substate.type"

    model = fields.Selection(
        selection_add=[("sale.order", "Sale order")], ondelete={"sale.order": "cascade"}
    )


class SaleOrder(models.Model):
    _inherit = ["sale.order", "base.substate.mixin"]
    _name = "sale.order"

    def _get_workflow_substate(self):
        self.ensure_one()
        if self.state != "sale":
            return False
        if self.delivery_status == "full":
            return self.env.ref("sale_substate.base_substate_delivered")
        if self.delivery_status in ("partial", "started"):
            return self.env.ref("sale_substate.base_substate_in_delivery")
        return self.env.ref("sale_substate.base_substate_valid_docs")

    def _update_workflow_substate(self):
        for order in self:
            target_substate = order._get_workflow_substate()
            if target_substate and order.substate_id != target_substate:
                order.substate_id = target_substate

    def action_confirm(self):
        res = super().action_confirm()
        self._update_workflow_substate()
        return res

    def action_deliver(self):
        self._update_workflow_substate()
        return True
