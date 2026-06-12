# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo.tests.common import TransactionCase

from odoo.addons.sale_manual_delivery.hook import post_init_hook


class TestPostInitHook(TransactionCase):
    """Tests for the :func:`post_init_hook` SQL backfill.

    ``post_init_hook`` only runs at module *installation* time, so a
    standard ``TransactionCase`` — which operates on an already-installed
    database — can never observe it directly. We therefore:

    1. simulate the historical dirty state ("column exists but rows are
       NULL") by running ``ALTER TABLE`` / ``UPDATE`` in raw SQL, and
    2. invoke the hook manually via ``post_init_hook(self.env)``, and
    3. assert backfilled values, both immediately and after a second
       invocation (to prove idempotency).

    This mirrors exactly the scenario encountered during incremental
    deployments on a live database.
    """

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
            }
        )
        cls.product2 = cls.env["product.product"].create(
            {
                "name": "Test Post-Init Hook Product 2",
                "type": "consu",
                "is_storable": True,
                "list_price": 50.0,
            }
        )
        # purchase_price lives on sale.order.line as the cost used for
        # margin computation — record a non-zero value on the template so
        # every line we create below has a deterministic, non-trivial
        # margin we can assert against.
        cls.product.standard_price = 40.0
        cls.product2.standard_price = 10.0
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 1000
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product2, cls.stock_location, 1000
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _create_order(self, lines, delivered_qty=None):
        """Create a SO, optionally confirm & deliver ``delivered_qty`` on
        every line. ``lines`` is a list of ``(product, qty, price_unit,
        purchase_price)`` tuples."""
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "name": p.name,
                            "product_id": p.id,
                            "product_uom_qty": qty,
                            "product_uom": p.uom_id.id,
                            "price_unit": price,
                            "purchase_price": cost,
                        },
                    )
                    for p, qty, price, cost in lines
                ],
            }
        )
        if delivered_qty is not None:
            order.action_confirm()
            for picking in order.picking_ids:
                picking.action_assign()
                for ml in picking.move_line_ids:
                    ml.quantity = delivered_qty or ml.product_uom_qty
                picking.button_validate()
        # Flush so the SQL hook sees the rows it needs to update.
        self.env.flush_all()
        return order

    def _simulate_dirty_state(self, *orders):
        """Simulate the historical dirty state on the given orders:

        * Force ``x_total_margin`` to ``NULL`` for the given orders, so
          the hook actually has something to backfill (otherwise every
          row would already carry the ORM default of ``0.0``).
        * Re-run ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` — the same
          statement the hook opens with — to prove it does not fail even
          when the column already exists.
        """
        self.env.flush_all()
        for order in orders:
            self.env.cr.execute(
                "UPDATE sale_order SET x_total_margin = NULL WHERE id = %s",
                (order.id,),
            )
        # Must not raise: column already exists, IF NOT EXISTS catches it.
        self.env.cr.execute(
            "ALTER TABLE sale_order ADD COLUMN IF NOT EXISTS x_total_margin numeric;"
        )
        self.env.invalidate_all()

    def _raw_margin(self, order):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT x_total_margin FROM sale_order WHERE id = %s",
            (order.id,),
        )
        row = self.env.cr.fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------
    def test_backfill_delivered_order(self):
        """Single delivered SO, single line — positive margin.

        price_unit=100, purchase_price=40, qty_delivered=10
        -> expected x_total_margin = (100 - 40) * 10 = 600
        """
        order = self._create_order(
            [(self.product, 10, 100.0, 40.0)], delivered_qty=10
        )
        self._simulate_dirty_state(order)
        self.assertIsNone(self._raw_margin(order))

        post_init_hook(self.env)

        self.assertEqual(self._raw_margin(order), 600.0)

    def test_backfill_multi_line_order(self):
        """A single SO with two lines: margin must be aggregated.

        line1: (100 - 40) * 5 = 300
        line2: (50  - 10) * 4 = 160
        x_total_margin = 460
        """
        order = self._create_order(
            [
                (self.product, 5, 100.0, 40.0),
                (self.product2, 4, 50.0, 10.0),
            ],
            delivered_qty=4,
        )
        self._simulate_dirty_state(order)

        post_init_hook(self.env)

        self.assertEqual(self._raw_margin(order), 460.0)

    def test_backfill_zero_on_undelivered_and_empty(self):
        """Undelivered / empty orders must converge to 0.0, not stay NULL."""
        undelivered = self._create_order(
            [(self.product, 10, 100.0, 40.0)],
        )
        empty = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_invoice_id": self.partner.id,
                "partner_shipping_id": self.partner.id,
            }
        )
        self._simulate_dirty_state(undelivered, empty)

        post_init_hook(self.env)

        self.assertEqual(self._raw_margin(undelivered), 0.0)
        self.assertEqual(self._raw_margin(empty), 0.0)

    def test_idempotent_on_repeated_call(self):
        """Calling the hook twice must yield the *same* result and must
        not double-count lines, nor raise on the ``ADD COLUMN``."""
        order = self._create_order(
            [(self.product, 10, 100.0, 40.0)], delivered_qty=10
        )
        self._simulate_dirty_state(order)

        post_init_hook(self.env)
        first_call_result = self._raw_margin(order)
        self.assertEqual(first_call_result, 600.0)

        post_init_hook(self.env)
        second_call_result = self._raw_margin(order)
        self.assertEqual(second_call_result, 600.0)
        self.assertEqual(first_call_result, second_call_result)

    def test_skips_already_backfilled_rows(self):
        """Rows whose x_total_margin is already set must *not* be rewritten.

        This guards against regressions where someone removes the
        ``WHERE x_total_margin IS NULL`` guard: the sentinel value
        (42.42) would be overwritten.
        """
        order = self._create_order(
            [(self.product, 10, 100.0, 40.0)], delivered_qty=10
        )
        # Put a *non-NULL* sentinel instead of the dirty-state NULL so
        # the hook's ``IS NULL`` guard leaves the row alone.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sale_order SET x_total_margin = 42.42 WHERE id = %s",
            (order.id,),
        )
        self.env.invalidate_all()

        post_init_hook(self.env)

        self.assertEqual(self._raw_margin(order), 42.42)
