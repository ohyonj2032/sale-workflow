# Copyright 2026 Credit Hold Enhancement
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest import mock

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestCreditHold(TransactionCase):
    """Verify the credit-hold mechanism introduced by sale_delivery_state.

    Tests are organized in two tracks:

    * "green path" tests that exercise the feature with new orders created
      from the current module state (state machine injection, ``_action_confirm``
      override, delayed picking generation, permission checks).
    * "backward compatibility" tests that simulate a database that was already
      populated before the module is installed, exercise the ``pre_init_hook``
      migration logic and check that stock pickings are correctly re-linked
      after a release.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.Product = cls.env["product.product"]
        cls.Partner = cls.env["res.partner"]
        cls.Order = cls.env["sale.order"]

        cls.product = cls.Product.create(
            {"name": "Widget", "type": "product", "list_price": 100.0}
        )

        # Partner with a low credit limit => orders above it will be blocked.
        cls.partner_risky = cls.Partner.create(
            {"name": "Risky Customer", "credit_limit": 200.0}
        )
        # Partner with no credit limit => orders always go through.
        cls.partner_safe = cls.Partner.create(
            {"name": "Safe Customer", "credit_limit": 0.0}
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_order(self, partner, qty=1, price_unit=None):
        price_unit = price_unit or self.product.list_price
        order = self.Order.create(
            {
                "partner_id": partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": qty,
                            "price_unit": price_unit,
                        },
                    )
                ],
            }
        )
        return order

    # ------------------------------------------------------------------
    # Track 1 – new order flow
    # ------------------------------------------------------------------
    def test_state_selection_extended(self):
        """The credit_hold value must be present in the state selection."""
        selection = dict(self.env["sale.order"].fields_get(["state"])["state"]["selection"])
        self.assertIn("credit_hold", selection)

    def test_order_within_credit_limit_confirms_normally(self):
        """Orders that do not exceed the credit limit must flow normally."""
        order = self._make_order(self.partner_safe, qty=1)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.credit_hold)
        # The native stock flow must have generated pickings.
        if "picking_ids" in order._fields:
            self.assertTrue(order.picking_ids)

    def test_order_above_credit_limit_is_held_and_no_picking_created(self):
        """Orders that exceed the credit limit must be put on hold WITHOUT
        creating stock pickings."""
        order = self._make_order(self.partner_risky, qty=10)
        self.assertGreater(order.amount_total, self.partner_risky.credit_limit)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        self.assertTrue(order.credit_hold)
        if "picking_ids" in order._fields:
            self.assertFalse(
                order.picking_ids,
                "No pickings should be generated while the order is on hold",
            )

    def test_release_credit_hold_generates_pickings(self):
        """Releasing an order on hold must eventually generate pickings."""
        order = self._make_order(self.partner_risky, qty=10)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        # Simulate a user with the credit_manager group.
        credit_manager = (
            self.env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Credit Manager",
                    "login": "credit_manager_test",
                    "groups_id": [
                        (4, self.env.ref("sale_delivery_state.group_credit_manager").id)
                    ],
                }
            )
        )
        order.with_user(credit_manager).action_release_credit()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.credit_hold)
        if "picking_ids" in order._fields:
            self.assertTrue(order.picking_ids, "Pickings must be generated on release")

    def test_write_state_raises_for_unprivileged_user(self):
        """ORM-level ``write`` must forbid unprivileged users from bypassing the
        hold mechanism by setting state='sale' directly."""
        order = self._make_order(self.partner_risky, qty=10)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        unprivileged = (
            self.env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Salesman",
                    "login": "salesman_test",
                    "groups_id": [(4, self.env.ref("base.group_user").id)],
                }
            )
        )
        with self.assertRaises(AccessError):
            order.with_user(unprivileged).write({"state": "sale"})

    # ------------------------------------------------------------------
    # Track 2 – backward compatibility with pre_init_hook
    # ------------------------------------------------------------------
    def test_pre_init_hook_migrates_historic_orders(self):
        """Orders that were already in 'sale' state and whose customer is over
        the credit limit must be flagged as credit_hold at install time."""
        # Build a scenario manually (we can't actually run pre_init_hook again
        # from inside a test because the columns already exist – but we can
        # simulate it by writing old rows and re-running the migration helper).
        from sale_delivery_state.hooks import _migrate_credit_hold_orders

        order = self._make_order(self.partner_risky, qty=10)
        # Force the state to what would have been the state before the module
        # was installed, i.e. directly 'sale' without credit flag.
        self.env.cr.execute(
            """
            UPDATE sale_order
               SET state = 'sale',
                   credit_hold = NULL,
                   credit_hold_reason = NULL,
                   credit_hold_date = NULL
             WHERE id = %s
            """,
            (order.id,),
        )
        _migrate_credit_hold_orders(self.env)
        self.env.cr.commit()  # the helper commits per chunk; make sure data is flushed
        order.invalidate_recordset()
        self.assertEqual(order.state, "credit_hold")
        self.assertTrue(order.credit_hold)

    def test_pre_init_hook_ignores_normal_orders(self):
        """Orders within the credit limit must be left untouched."""
        from sale_delivery_state.hooks import _migrate_credit_hold_orders

        order = self._make_order(self.partner_safe, qty=1)
        order.action_confirm()
        initial_state = order.state
        _migrate_credit_hold_orders(self.env)
        order.invalidate_recordset()
        self.assertEqual(order.state, initial_state)

    def test_migrated_order_can_be_released_and_relinks_pickings(self):
        """Once an order migrated from a legacy database is released, the
        delayed confirm path must create the stock pickings and link them."""
        from sale_delivery_state.hooks import _migrate_credit_hold_orders

        order = self._make_order(self.partner_risky, qty=10)
        self.env.cr.execute(
            """
            UPDATE sale_order
               SET state = 'sale',
                   credit_hold = NULL,
                   credit_hold_reason = NULL,
                   credit_hold_date = NULL
             WHERE id = %s
            """,
            (order.id,),
        )
        _migrate_credit_hold_orders(self.env)
        order.invalidate_recordset()
        self.assertEqual(order.state, "credit_hold")
        order.action_release_credit()
        self.assertEqual(order.state, "sale")
        if "picking_ids" in order._fields:
            self.assertTrue(
                order.picking_ids,
                "Release of a migrated order must generate the stock picking",
            )
            for picking in order.picking_ids:
                self.assertEqual(picking.state, "assigned" if picking.state != "done" else picking.state)
