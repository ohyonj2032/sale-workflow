# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo.tests.common import TransactionCase

from odoo.addons.sale_manual_delivery.post_init_hook import post_init_hook


class TestPostInitHook(TransactionCase):
    """Tests for the post_init_hook that backfills x_total_margin.

    Because post_init_hook only runs during module installation, a normal
    TransactionCase cannot exercise it directly. These tests simulate the
    "module already installed but column data is empty" dirty state by:

    1. Ensuring the x_total_margin column exists (ALTER TABLE).
    2. Populating sale.order and sale.order.line records with known values.
    3. Forcing x_total_margin to NULL / 0 via raw SQL (dirty state).
    4. Manually invoking post_init_hook(env).
    5. Asserting the SQL update produced the correct margin values.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {"name": "Test Post-Init Hook Partner"}
        )
        cls.product_a = cls.env["product.product"].create(
            {
                "name": "Test Product A",
                "type": "consu",
                "list_price": 100.0,
            }
        )
        cls.product_b = cls.env["product.product"].create(
            {
                "name": "Test Product B",
                "type": "consu",
                "list_price": 50.0,
            }
        )

        cls.env.cr.execute("""
            ALTER TABLE sale_order
            ADD COLUMN IF NOT EXISTS x_total_margin numeric;
        """)

    def _read_margin(self, order):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT x_total_margin FROM sale_order WHERE id = %s",
            (order.id,),
        )
        return self.env.cr.fetchone()[0]

    def _set_margin(self, order, value):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sale_order SET x_total_margin = %s WHERE id = %s",
            (value, order.id),
        )
        self.env.invalidate_all()

    def _create_order_with_lines(self, lines_data):
        """Create a sale order with lines.

        lines_data: list of dicts with keys:
            product, qty, price_unit, purchase_price
        """
        order_lines = []
        for ld in lines_data:
            order_lines.append(
                (
                    0,
                    0,
                    {
                        "name": ld["product"].name,
                        "product_id": ld["product"].id,
                        "product_uom_qty": ld["qty"],
                        "product_uom": ld["product"].uom_id.id,
                        "price_unit": ld["price_unit"],
                        "purchase_price": ld["purchase_price"],
                    },
                )
            )
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": order_lines,
            }
        )

    def test_post_init_hook_backfill_positive_margin(self):
        """Margin > 0: price_subtotal exceeds purchase cost.

        Line: qty=10, price_unit=100, purchase_price=60
        Expected margin = 10 * 100 - 10 * 60 = 400
        """
        order = self._create_order_with_lines(
            [
                {
                    "product": self.product_a,
                    "qty": 10,
                    "price_unit": 100.0,
                    "purchase_price": 60.0,
                }
            ]
        )

        self._set_margin(order, None)
        post_init_hook(self.env)

        margin = self._read_margin(order)
        self.assertEqual(margin, 400.0)

    def test_post_init_hook_backfill_negative_margin(self):
        """Margin < 0: selling below purchase cost.

        Line: qty=5, price_unit=30, purchase_price=50
        Expected margin = 5 * 30 - 5 * 50 = -100
        """
        order = self._create_order_with_lines(
            [
                {
                    "product": self.product_b,
                    "qty": 5,
                    "price_unit": 30.0,
                    "purchase_price": 50.0,
                }
            ]
        )

        self._set_margin(order, None)
        post_init_hook(self.env)

        margin = self._read_margin(order)
        self.assertEqual(margin, -100.0)

    def test_post_init_hook_backfill_zero_margin(self):
        """Margin == 0: price equals purchase cost.

        Line: qty=3, price_unit=80, purchase_price=80
        Expected margin = 3 * 80 - 3 * 80 = 0
        """
        order = self._create_order_with_lines(
            [
                {
                    "product": self.product_a,
                    "qty": 3,
                    "price_unit": 80.0,
                    "purchase_price": 80.0,
                }
            ]
        )

        self._set_margin(order, None)
        post_init_hook(self.env)

        margin = self._read_margin(order)
        self.assertEqual(margin, 0.0)

    def test_post_init_hook_backfill_multiple_lines(self):
        """Multiple lines in one order.

        Line 1: qty=10, price_unit=100, purchase_price=60 -> margin 400
        Line 2: qty=5,  price_unit=50,  purchase_price=30 -> margin 100
        Expected total margin = 500
        """
        order = self._create_order_with_lines(
            [
                {
                    "product": self.product_a,
                    "qty": 10,
                    "price_unit": 100.0,
                    "purchase_price": 60.0,
                },
                {
                    "product": self.product_b,
                    "qty": 5,
                    "price_unit": 50.0,
                    "purchase_price": 30.0,
                },
            ]
        )

        self._set_margin(order, None)
        post_init_hook(self.env)

        margin = self._read_margin(order)
        self.assertEqual(margin, 500.0)

    def test_post_init_hook_idempotent(self):
        """Running the hook twice must not double-accumulate values.

        After the first run, x_total_margin = 400.
        Running again must keep it at 400, not 800.
        """
        order = self._create_order_with_lines(
            [
                {
                    "product": self.product_a,
                    "qty": 10,
                    "price_unit": 100.0,
                    "purchase_price": 60.0,
                }
            ]
        )

        self._set_margin(order, None)
        post_init_hook(self.env)
        margin_first = self._read_margin(order)
        self.assertEqual(margin_first, 400.0)

        post_init_hook(self.env)
        margin_second = self._read_margin(order)
        self.assertEqual(margin_second, 400.0)

    def test_post_init_hook_skips_already_populated(self):
        """Orders with a non-zero x_total_margin must be left untouched.

        We set a sentinel value (999) and verify the hook does not
        overwrite it.
        """
        order = self._create_order_with_lines(
            [
                {
                    "product": self.product_a,
                    "qty": 10,
                    "price_unit": 100.0,
                    "purchase_price": 60.0,
                }
            ]
        )

        self._set_margin(order, 999.0)
        post_init_hook(self.env)

        margin = self._read_margin(order)
        self.assertEqual(margin, 999.0)

    def test_post_init_hook_no_column_no_error(self):
        """If x_total_margin column does not exist, the hook must not raise.

        We drop the column (if it exists in this test transaction) and
        verify the hook returns cleanly.
        """
        self.env.cr.execute("""
            ALTER TABLE sale_order DROP COLUMN IF EXISTS x_total_margin;
        """)

        try:
            post_init_hook(self.env)
        except Exception as exc:
            self.fail(f"post_init_hook raised unexpectedly: {exc}")

    def test_post_init_hook_order_without_lines(self):
        """An order with no lines should get margin = 0.

        The COALESCE in the SQL ensures SUM(NULL) becomes 0.
        """
        order = self.env["sale.order"].create(
            {"partner_id": self.partner.id}
        )

        self._set_margin(order, None)
        post_init_hook(self.env)

        margin = self._read_margin(order)
        self.assertEqual(margin, 0.0)
