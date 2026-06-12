# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo.tests.common import TransactionCase

from odoo.addons.sale_manual_delivery.hook import (
    ensure_column_safe,
    post_init_hook,
)


class TestPostInitHook(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {"name": "Test Post-Init Hook Partner"}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Post-Init Hook Product",
                "type": "consu",
                "is_storable": True,
                "list_price": 100.0,
                "standard_price": 60.0,
            }
        )
        cls.product_no_cost = cls.env["product.product"].create(
            {
                "name": "Test Post-Init Hook Product No Cost",
                "type": "consu",
                "is_storable": True,
                "list_price": 50.0,
                "standard_price": 0.0,
            }
        )
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 1000
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product_no_cost, cls.stock_location, 1000
        )

    def _create_order(self, lines_data):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": data["product"].name,
                            "product_id": data["product"].id,
                            "product_uom_qty": data["qty"],
                            "product_uom": data["product"].uom_id.id,
                            "price_unit": data["product"].list_price,
                        },
                    )
                    for data in lines_data
                ],
            }
        )

    def _ensure_column_and_nullify(self):
        self.env.flush_all()
        ensure_column_safe(self.env.cr)
        self.env.cr.execute(
            "UPDATE sale_order_line SET x_total_margin = NULL"
        )
        self.env.invalidate_all()

    def _read_margin(self, line):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT x_total_margin FROM sale_order_line WHERE id = %s",
            (line.id,),
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None

    def test_post_init_hook_backfill_margin(self):
        order = self._create_order(
            [
                {"product": self.product, "qty": 5},
                {"product": self.product_no_cost, "qty": 3},
            ]
        )
        order.action_confirm()
        line_with_cost = order.order_line.filtered(
            lambda l: l.product_id == self.product
        )
        line_no_cost = order.order_line.filtered(
            lambda l: l.product_id == self.product_no_cost
        )

        self._ensure_column_and_nullify()

        self.assertIsNone(self._read_margin(line_with_cost))
        self.assertIsNone(self._read_margin(line_no_cost))

        post_init_hook(self.env)

        self.assertEqual(
            self._read_margin(line_with_cost),
            200.0,
        )
        self.assertEqual(
            self._read_margin(line_no_cost),
            150.0,
        )

    def test_post_init_hook_idempotent(self):
        order = self._create_order(
            [{"product": self.product, "qty": 2}]
        )
        order.action_confirm()
        line = order.order_line

        self._ensure_column_and_nullify()
        self.assertIsNone(self._read_margin(line))

        post_init_hook(self.env)
        first_value = self._read_margin(line)
        self.assertEqual(first_value, 80.0)

        post_init_hook(self.env)
        second_value = self._read_margin(line)
        self.assertEqual(second_value, 80.0)

    def test_post_init_hook_partial_backfill(self):
        order = self._create_order(
            [
                {"product": self.product, "qty": 1},
                {"product": self.product_no_cost, "qty": 7},
            ]
        )
        order.action_confirm()
        line_with_cost = order.order_line.filtered(
            lambda l: l.product_id == self.product
        )
        line_no_cost = order.order_line.filtered(
            lambda l: l.product_id == self.product_no_cost
        )

        self._ensure_column_and_nullify()

        self.env.cr.execute(
            "UPDATE sale_order_line SET x_total_margin = 999.0 WHERE id = %s",
            (line_with_cost.id,),
        )
        self.env.invalidate_all()

        post_init_hook(self.env)

        self.assertEqual(
            self._read_margin(line_with_cost),
            999.0,
        )
        self.assertEqual(
            self._read_margin(line_no_cost),
            350.0,
        )

    def test_post_init_hook_ensure_column_safe_repeatable(self):
        ensure_column_safe(self.env.cr)
        ensure_column_safe(self.env.cr)
        ensure_column_safe(self.env.cr)

        self.env.cr.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'sale_order_line'
            AND column_name = 'x_total_margin'
            """
        )
        self.assertTrue(self.env.cr.fetchone())