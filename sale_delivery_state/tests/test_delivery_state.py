# Copyright 2018 Akretion (http://www.akretion.com).
# @author Benoît GUILLOT <benoit.guillot@akretion.com>
# Copyright 2018 Camptocamp
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest import mock

from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, new_test_user, tagged

from odoo.addons.sale_delivery_state.hooks import pre_init_hook


@tagged("post_install", "-at_install")
class TestDeliveryState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.order = cls.env.ref("sale_delivery_state.sale_order_1")
        cls.delivery_cost = cls.env["product.product"].create(
            {"name": "delivery", "type": "service"}
        )
        cls.service_product = cls.env["product.product"].create(
            {"name": "service", "type": "service"}
        )
        cls.credit_product = cls.env["product.product"].create(
            {
                "name": "Credit Controlled Product",
                "type": "consu",
                "is_storable": True,
                "uom_id": cls.env.ref("uom.product_uom_unit").id,
                "uom_po_id": cls.env.ref("uom.product_uom_unit").id,
                "list_price": 60.0,
            }
        )
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.credit_product, cls.stock_location, 1000
        )
        cls.sales_user = new_test_user(
            cls.env,
            "credit_hold_sales_user",
            "sales_team.group_sale_salesman,stock.group_stock_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.credit_manager = new_test_user(
            cls.env,
            "credit_hold_manager",
            (
                "sales_team.group_sale_manager,"
                "stock.group_stock_user,"
                "sale_delivery_state.group_sale_credit_manager"
            ),
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )

    def _mock_delivery(self, delivery_prod=None):
        delivery_prod = delivery_prod or self.delivery_cost
        return mock.patch.object(
            type(self.env["sale.order.line"]),
            "_is_delivery",
            lambda self: self.product_id == delivery_prod,
        )

    def _add_delivery_cost_line(self):
        self.env["sale.order.line"].create(
            {
                "order_id": self.order.id,
                "name": "Delivery cost",
                "product_id": self.delivery_cost.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": 10.0,
            }
        )

    def _add_service_line(self, skip_sale_delivery_state=False):
        self.env["sale.order.line"].create(
            {
                "order_id": self.order.id,
                "name": "Service",
                "product_id": self.service_product.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": 10.0,
                "skip_sale_delivery_state": skip_sale_delivery_state,
            }
        )

    def _set_partner_credit(self, partner, amount):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET credit = %s WHERE id = %s",
            (amount, partner.commercial_partner_id.id),
        )
        self.env.invalidate_all()

    def _create_credit_sale_order(self, partner, user=None, price_unit=60.0):
        user = user or self.env.user
        return (
            self.env["sale.order"]
            .with_user(user)
            .create(
                {
                    "partner_id": partner.id,
                    "partner_invoice_id": partner.id,
                    "partner_shipping_id": partner.id,
                    "user_id": user.id,
                    "company_id": self.company.id,
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "name": self.credit_product.name,
                                "product_id": self.credit_product.id,
                                "product_uom_qty": 1,
                                "product_uom": self.credit_product.uom_id.id,
                                "price_unit": price_unit,
                            },
                        )
                    ],
                }
            )
        )

    def test_no_delivery(self):
        self.assertFalse(self.order.delivery_status)

    def test_unprocessed_delivery(self):
        self.order.action_confirm()
        self.assertEqual(self.order.delivery_status, "pending")

    def test_partially(self):
        self.order.action_confirm()
        self.order.order_line[0].qty_delivered = 2
        self.assertEqual(self.order.delivery_status, "partial")

    def test_delivery_done(self):
        self.order.action_confirm()
        for line in self.order.order_line:
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "full")

    def test_no_delivery_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.assertFalse(self.order.delivery_status)

    def test_unprocessed_delivery_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            self.assertEqual(self.order.delivery_status, "pending")

    def test_partially_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            self.order.order_line[0].qty_delivered = 2
            self.assertEqual(self.order.delivery_status, "partial")

    def test_forced_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            self.order.order_line[0].qty_delivered = 2
            self.order.force_delivery_state = True
            self.assertEqual(self.order.delivery_status, "full")

    def test_delivery_done_delivery_cost(self):
        self._add_delivery_cost_line()
        with self._mock_delivery():
            self.order.action_confirm()
            for line in self.order.order_line:
                if line._is_delivery():
                    continue
                line.qty_delivered = line.product_uom_qty
            self.assertEqual(self.order.delivery_status, "full")

    def test_skip_service_line(self):
        self._add_service_line()
        self.order.action_confirm()
        for line in self.order.order_line:
            if line.product_id == self.service_product:
                continue
            line.qty_delivered = line.product_uom_qty
        self.assertEqual(self.order.delivery_status, "partial")
        self.order.order_line.filtered(
            lambda a: a.product_id and a.product_id == self.service_product
        ).write({"skip_sale_delivery_state": True})
        self.assertEqual(self.order.delivery_status, "full")

    def test_credit_hold_confirmation_and_release(self):
        partner = self.env["res.partner"].create(
            {"name": "Credit Hold Partner", "credit_limit": 100.0}
        )
        self._set_partner_credit(partner, 60.0)
        order = self._create_credit_sale_order(
            partner, user=self.credit_manager, price_unit=50.0
        )

        order.action_confirm()

        self.assertEqual(order.state, "credit_hold")
        self.assertFalse(order.picking_ids)
        self.assertTrue(order.procurement_group_id)

        order.with_user(self.credit_manager).action_release_credit()

        self.assertEqual(order.state, "sale")
        self.assertEqual(len(order.picking_ids), 1)
        picking = order.picking_ids
        self.assertEqual(picking.sale_id, order)
        self.assertEqual(picking.group_id, order.procurement_group_id)
        self.assertEqual(picking.move_ids.sale_line_id.order_id, order)

    def test_credit_hold_write_requires_context_and_group(self):
        partner = self.env["res.partner"].create(
            {"name": "Credit Hold Protected Partner", "credit_limit": 100.0}
        )
        self._set_partner_credit(partner, 80.0)
        order = self._create_credit_sale_order(
            partner, user=self.sales_user, price_unit=30.0
        )

        order.with_user(self.sales_user).action_confirm()
        self.assertEqual(order.state, "credit_hold")

        with self.assertRaises(UserError):
            order.with_user(self.credit_manager).write({"state": "sale"})
        with self.assertRaises(UserError):
            order.with_user(self.sales_user).write({"state": "sale"})
        with self.assertRaises(AccessError):
            order.with_user(self.sales_user).with_context(allow_credit_release=True).write(
                {"state": "sale"}
            )

        order.with_user(self.credit_manager).action_release_credit()
        self.assertEqual(order.state, "sale")

    def test_pre_init_hook_migrates_historical_sale_orders(self):
        partner = self.env["res.partner"].create(
            {"name": "Historical Credit Hold Partner", "credit_limit": 100.0}
        )
        safe_partner = self.env["res.partner"].create(
            {"name": "Historical Safe Partner", "credit_limit": 200.0}
        )
        self._set_partner_credit(partner, 0.0)
        self._set_partner_credit(safe_partner, 0.0)
        migrated_order = self._create_credit_sale_order(
            partner, user=self.credit_manager, price_unit=30.0
        )
        safe_order = self._create_credit_sale_order(
            safe_partner, user=self.credit_manager, price_unit=30.0
        )

        migrated_order.action_confirm()
        safe_order.action_confirm()
        self.assertEqual(migrated_order.state, "sale")
        self.assertEqual(safe_order.state, "sale")
        self.assertTrue(migrated_order.picking_ids)
        self.assertTrue(safe_order.picking_ids)

        self._set_partner_credit(partner, 80.0)
        self._set_partner_credit(safe_partner, 50.0)

        pre_init_hook(self.env)
        migrated_order.invalidate_recordset(["state"])
        safe_order.invalidate_recordset(["state"])

        self.assertEqual(migrated_order.state, "credit_hold")
        self.assertEqual(safe_order.state, "sale")

        existing_picking = migrated_order.picking_ids
        migrated_order.with_user(self.credit_manager).action_release_credit()
        self.assertEqual(migrated_order.state, "sale")
        self.assertEqual(migrated_order.picking_ids, existing_picking)
