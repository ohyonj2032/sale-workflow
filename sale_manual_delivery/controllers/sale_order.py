# Copyright 2017 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import http
from odoo.http import request


class SaleOrderController(http.Controller):
    _name = "sale.manual.delivery.controller"

    @http.route(
        "/sale_manual_delivery/order/<int:order_id>",
        type="json",
        auth="user",
        methods=["GET"],
    )
    def get_order(self, order_id):
        order = request.env["sale.order"].sudo().browse(order_id)
        if not order.exists():
            return {"error": "Not found"}
        return {
            "id": order.id,
            "name": order.name,
            "state": order.state,
            "manual_delivery": order.manual_delivery,
            "has_pending_delivery": order.has_pending_delivery,
        }

    @http.route(
        "/sale_manual_delivery/order/<int:order_id>/lines",
        type="json",
        auth="user",
        methods=["GET"],
    )
    def get_order_lines(self, order_id):
        order = request.env["sale.order"].sudo().browse(order_id)
        if not order.exists():
            return {"error": "Not found"}
        lines = []
        for line in order.order_line:
            lines.append(
                {
                    "id": line.id,
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.product_uom_qty,
                    "qty_delivered": line.qty_delivered,
                    "qty_to_procure": line.qty_to_procure,
                    "qty_procured": line.qty_procured,
                }
            )
        return {"lines": lines}