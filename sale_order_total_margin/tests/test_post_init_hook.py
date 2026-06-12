from decimal import Decimal

from odoo.addons.sale_order_total_margin.hooks import post_init_hook
from odoo.tests.common import TransactionCase


class TestPostInitHook(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Margin Hook Partner"})
        cls.product_a = cls.env["product.product"].create(
            {
                "name": "Margin Hook Product A",
                "standard_price": 40.0,
                "list_price": 100.0,
                "type": "consu",
            }
        )
        cls.product_b = cls.env["product.product"].create(
            {
                "name": "Margin Hook Product B",
                "standard_price": 10.0,
                "list_price": 25.0,
                "type": "consu",
            }
        )

    def _create_order(self, order_lines):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": order_lines,
            }
        )

    def _set_dirty_state(self, orders):
        self.env.flush_all()
        self.env.cr.execute(
            "ALTER TABLE sale_order ADD COLUMN IF NOT EXISTS x_total_margin numeric"
        )
        self.env.cr.execute(
            "UPDATE sale_order SET x_total_margin = NULL WHERE id IN %s",
            (tuple(orders.ids),),
        )
        self.env.invalidate_all()

    def _set_margin_value(self, order, value):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sale_order SET x_total_margin = %s WHERE id = %s",
            (value, order.id),
        )
        self.env.invalidate_all()

    def _read_margin_value(self, order):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT x_total_margin FROM sale_order WHERE id = %s",
            (order.id,),
        )
        return self.env.cr.fetchone()[0]

    def test_post_init_hook_backfills_null_margin_once(self):
        migrated_order = self._create_order(
            [
                (
                    0,
                    0,
                    {
                        "name": self.product_a.name,
                        "product_id": self.product_a.id,
                        "product_uom_qty": 2,
                        "product_uom": self.product_a.uom_id.id,
                        "price_unit": 100.0,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "name": self.product_b.name,
                        "product_id": self.product_b.id,
                        "product_uom_qty": 3,
                        "product_uom": self.product_b.uom_id.id,
                        "price_unit": 25.0,
                    },
                ),
                (0, 0, {"display_type": "line_note", "name": "Ignored note"}),
            ]
        )
        preserved_order = self._create_order(
            [
                (
                    0,
                    0,
                    {
                        "name": self.product_b.name,
                        "product_id": self.product_b.id,
                        "product_uom_qty": 1,
                        "product_uom": self.product_b.uom_id.id,
                        "price_unit": 25.0,
                    },
                )
            ]
        )

        self._set_dirty_state(migrated_order | preserved_order)
        self._set_margin_value(preserved_order, Decimal("77.0"))

        post_init_hook(self.env)

        self.assertEqual(self._read_margin_value(migrated_order), Decimal("165.0"))
        self.assertEqual(self._read_margin_value(preserved_order), Decimal("77.0"))

        post_init_hook(self.env)

        self.assertEqual(self._read_margin_value(migrated_order), Decimal("165.0"))
        self.assertEqual(self._read_margin_value(preserved_order), Decimal("77.0"))
