import json

from odoo import Command
from odoo.addons.sale.tests.common import TestSaleCommonBase
from odoo.tests import Form
from odoo.tests.common import HttpCase, tagged


class TestSaleManualDelivery(TestSaleCommonBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Manual Delivery Customer"})
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.product2 = cls.env.ref("product.product_delivery_02")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.manual_delivery_team = cls.env["crm.team"].create(
            {"name": "Manual Delivery Team", "manual_delivery": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product2, cls.stock_location, 100
        )
        cls.env["res.lang"]._activate_lang("it_IT")

    def _create_sale_order_with_form(self, line_specs, team=None, manual_delivery=None):
        order_form = Form(self.env["sale.order"])
        order_form.partner_id = self.partner
        preview_lines = []
        if team:
            order_form.team_id = team
        if manual_delivery is not None:
            order_form.manual_delivery = manual_delivery
        for product, quantity in line_specs:
            with order_form.order_line.new() as line_form:
                line_form.product_id = product
                preview_lines.append(
                    {
                        "name": line_form.name,
                        "product_uom": line_form.product_uom,
                        "price_unit": line_form.price_unit,
                        "product_uom_qty": quantity,
                    }
                )
                line_form.product_uom_qty = quantity
        return order_form, preview_lines

    def _save_sale_order(self, line_specs, team=None, manual_delivery=None):
        order_form, preview_lines = self._create_sale_order_with_form(
            line_specs, team=team, manual_delivery=manual_delivery
        )
        return order_form.save(), preview_lines

    def _manual_delivery_wizard(self, records, vals=None):
        vals = vals or {}
        return (
            self.env["manual.delivery"]
            .with_context(active_model=records._name, active_ids=records.ids)
            .create(vals)
        )

    def _set_move_done_quantity(self, move, quantity):
        move_line_field = "qty_done"
        if move.move_line_ids and move_line_field not in move.move_line_ids._fields:
            move_line_field = "quantity"
        if move.move_line_ids:
            move.move_line_ids[:1].write({move_line_field: quantity})
            return
        for move_field in ("quantity_done", "qty_done", "quantity"):
            if move_field in move._fields:
                move.write({move_field: quantity})
                return
        raise AssertionError("No field available to set done quantity")

    def _validate_picking(self, picking, quantities_by_line_id):
        picking.action_assign()
        for move in picking.move_ids:
            quantity = quantities_by_line_id.get(move.sale_line_id.id)
            if quantity is None:
                continue
            self._set_move_done_quantity(move, quantity)
        result = picking.button_validate()
        if isinstance(result, dict):
            wizard = Form(
                self.env[result["res_model"]].with_context(**result.get("context", {}))
            ).save()
            if hasattr(wizard, "process"):
                wizard.process()
            elif hasattr(wizard, "process_cancel_backorder"):
                wizard.process_cancel_backorder()
        picking.invalidate_recordset()

    def test_form_onchange_multiline_sale_order(self):
        order_form, preview_lines = self._create_sale_order_with_form(
            [(self.product, 5.0), (self.product2, 3.0)],
            team=self.manual_delivery_team,
        )
        self.assertEqual(order_form.partner_invoice_id, self.partner)
        self.assertEqual(order_form.partner_shipping_id, self.partner)
        self.assertTrue(order_form.manual_delivery)
        for preview, product in zip(preview_lines, [self.product, self.product2]):
            self.assertEqual(preview["product_uom"], product.uom_id)
            self.assertEqual(preview["price_unit"], product.list_price)
            self.assertTrue(preview["name"])
        order = order_form.save()
        self.assertTrue(order.manual_delivery)
        self.assertEqual(order.team_id, self.manual_delivery_team)
        self.assertEqual(len(order.order_line), 2)
        for line, preview in zip(order.order_line, preview_lines):
            self.assertEqual(line.name, preview["name"])
            self.assertEqual(line.product_uom, preview["product_uom"])
            self.assertEqual(line.price_unit, preview["price_unit"])
            self.assertEqual(line.product_uom_qty, preview["product_uom_qty"])

    def test_manual_delivery_creates_real_picking_and_updates_qty_delivered(self):
        order, _preview_lines = self._save_sale_order(
            [(self.product, 5.0), (self.product2, 2.0)],
            team=self.manual_delivery_team,
        )
        self.assertEqual(order.state, "draft")
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.picking_ids)
        wizard = self._manual_delivery_wizard(order)
        self.assertEqual(len(wizard.line_ids), 2)
        wizard.line_ids.filtered(lambda line: line.order_line_id == order.order_line[0]).write(
            {"quantity": 5.0}
        )
        wizard.line_ids.filtered(lambda line: line.order_line_id == order.order_line[1]).write(
            {"quantity": 2.0}
        )
        wizard.confirm()
        order.invalidate_recordset()
        self.assertEqual(len(order.picking_ids), 1)
        picking = order.picking_ids
        self.assertEqual(
            set(picking.move_ids.mapped("sale_line_id").ids),
            set(order.order_line.ids),
        )
        self.assertEqual(
            sum(picking.move_ids.mapped("product_uom_qty")),
            sum(order.order_line.mapped("product_uom_qty")),
        )
        self._validate_picking(
            picking,
            {
                order.order_line[0].id: 5.0,
                order.order_line[1].id: 2.0,
            },
        )
        order.invalidate_recordset()
        order.order_line.invalidate_recordset()
        self.assertEqual(order.picking_ids.state, "done")
        self.assertEqual(order.order_line[0].qty_delivered, 5.0)
        self.assertEqual(order.order_line[1].qty_delivered, 2.0)
        self.assertFalse(order.has_pending_delivery)

    def test_partial_manual_delivery_keeps_order_open_and_quantities_consistent(self):
        order, _preview_lines = self._save_sale_order(
            [(self.product, 5.0), (self.product2, 3.0)],
            team=self.manual_delivery_team,
        )
        order.action_confirm()
        wizard = self._manual_delivery_wizard(order)
        first_line = order.order_line[0]
        second_line = order.order_line[1]
        wizard.line_ids.filtered(lambda line: line.order_line_id == first_line).write(
            {"quantity": 2.0}
        )
        wizard.line_ids.filtered(lambda line: line.order_line_id == second_line).write(
            {"quantity": 0.0}
        )
        wizard.confirm()
        order.invalidate_recordset()
        self.assertEqual(order.state, "sale")
        self.assertEqual(len(order.picking_ids), 1)
        picking = order.picking_ids
        self.assertEqual(picking.move_ids.mapped("sale_line_id"), first_line)
        self._validate_picking(picking, {first_line.id: 2.0})
        order.invalidate_recordset()
        order.order_line.invalidate_recordset()
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.has_pending_delivery)
        self.assertEqual(first_line.qty_delivered, 2.0)
        self.assertEqual(second_line.qty_delivered, 0.0)
        self.assertEqual(first_line.qty_procured, 2.0)
        self.assertEqual(first_line.qty_to_procure, 3.0)
        self.assertEqual(second_line.qty_procured, 0.0)
        self.assertEqual(second_line.qty_to_procure, 3.0)

    def test_sale_order_state_label_is_translated_in_italian(self):
        order, _preview_lines = self._save_sale_order(
            [(self.product, 1.0)], team=self.manual_delivery_team
        )
        order.action_confirm()
        selection = dict(
            order._fields["state"]._description_selection(
                order.with_context(lang="it_IT").env
            )
        )
        self.assertEqual(selection[order.state], "Ordine di vendita")
        self.assertNotEqual(selection[order.state], "Sales Order")


@tagged("post_install", "-at_install")
class TestSaleManualDeliveryApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Sale API Customer"})
        cls.product = cls.env.ref("product.product_delivery_01")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )
        cls.api_user = cls.env["res.users"].create(
            {
                "name": "Sale API User",
                "login": "sale_api_user",
                "password": "sale_api_password",
                "groups_id": [
                    Command.set(
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("sales_team.group_sale_manager").id,
                        ]
                    )
                ],
            }
        )
        order_form = Form(cls.env["sale.order"])
        order_form.partner_id = cls.partner
        with order_form.order_line.new() as line_form:
            line_form.product_id = cls.product
            line_form.product_uom_qty = 2.0
        cls.order = order_form.save()

    def test_sale_order_api_returns_403_for_public_requests(self):
        response = self.url_open(
            f"/sale_manual_delivery/api/sale_orders/{self.order.id}", timeout=30
        )
        self.assertEqual(response.status_code, 403)

    def test_sale_order_api_returns_order_payload_for_authenticated_user(self):
        self.authenticate("sale_api_user", "sale_api_password")
        response = self.url_open(
            f"/sale_manual_delivery/api/sale_orders/{self.order.id}", timeout=30
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.text)
        self.assertEqual(payload["id"], self.order.id)
        self.assertEqual(payload["state"], self.order.state)
        self.assertFalse(payload["manual_delivery"])
        self.assertEqual(len(payload["lines"]), 1)
        self.assertEqual(payload["lines"][0]["product_id"], self.product.id)
        self.assertEqual(payload["lines"][0]["qty_ordered"], 2.0)
