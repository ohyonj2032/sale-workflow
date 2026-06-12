import json

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.http import request


class SaleOrderController(http.Controller):
    @http.route(
        "/sale_manual_delivery/api/sale_orders/<int:order_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def sale_order(self, order_id):
        if request.env.user._is_public():
            raise Forbidden()
        order = request.env["sale.order"].search([("id", "=", order_id)], limit=1)
        if not order:
            raise NotFound()
        payload = {
            "id": order.id,
            "name": order.name,
            "state": order.state,
            "manual_delivery": order.manual_delivery,
            "picking_count": len(order.picking_ids),
            "lines": [
                {
                    "id": line.id,
                    "product_id": line.product_id.id,
                    "qty_ordered": line.product_uom_qty,
                    "qty_delivered": line.qty_delivered,
                    "qty_to_procure": getattr(line, "qty_to_procure", 0.0),
                }
                for line in order.order_line
            ],
        }
        return request.make_response(
            json.dumps(payload), headers=[("Content-Type", "application/json")]
        )
