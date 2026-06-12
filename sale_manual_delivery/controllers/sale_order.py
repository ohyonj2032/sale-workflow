# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import http
from odoo.http import request


class SaleOrderController(http.Controller):

    @http.route(
        "/api/sale/order/<int:order_id>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def get_sale_order(self, order_id, **kwargs):
        order = request.env["sale.order"].browse(order_id)
        if not order.exists():
            return request.make_json_response(
                {"error": "Sale order not found"}, status=404
            )
        if not request.env.user._is_internal():
            return request.make_json_response(
                {"error": "Access denied"}, status=403
            )
        return request.make_json_response(
            {
                "id": order.id,
                "name": order.name,
                "state": order.state,
                "state_label": order._fields["state"].convert_to_export(
                    order.state, order
                ),
                "partner_id": order.partner_id.name,
                "amount_total": order.amount_total,
                "lines": [
                    {
                        "id": line.id,
                        "product": line.product_id.name,
                        "qty_delivered": line.qty_delivered,
                        "qty_to_deliver": line.product_uom_qty - line.qty_delivered,
                    }
                    for line in order.order_line
                ],
            }
        )

    @http.route(
        "/api/sale/order/<int:order_id>/deliver",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def action_deliver(self, order_id, **kwargs):
        order = request.env["sale.order"].browse(order_id)
        if not order.exists():
            return {"error": "Sale order not found"}
        order.action_manual_delivery_wizard()
        wizard = (
            request.env["manual.delivery"]
            .with_context(
                active_model="sale.order",
                active_ids=order.ids,
            )
            .create({})
        )
        if wizard.line_ids:
            wizard.confirm()
        return {
            "success": True,
            "picking_count": len(order.picking_ids),
            "state": order.state,
        }
