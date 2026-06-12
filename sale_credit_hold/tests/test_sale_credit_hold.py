from unittest import mock

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleCreditHold(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        cls.partner = cls.env["res.partner"].create(
            {"name": "Test Customer", "credit_limit": 1000.0}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "type": "consu",
                "list_price": 100.0,
            }
        )

        cls.credit_manager_group = cls.env.ref(
            "sale_credit_hold.group_credit_manager"
        )
        cls.credit_manager_user = cls.env["res.users"].create(
            {
                "name": "Credit Manager",
                "login": "credit_manager",
                "groups_id": [
                    Command.set(
                        [
                            cls.env.ref("sales_team.group_sale_manager").id,
                            cls.credit_manager_group.id,
                        ]
                    )
                ],
            }
        )
        cls.normal_user = cls.env["res.users"].create(
            {
                "name": "Normal User",
                "login": "normal_user",
                "groups_id": [
                    Command.set(
                        [cls.env.ref("sales_team.group_sale_manager").id]
                    )
                ],
            }
        )

    def _create_sale_order(self, partner=None, product=None, qty=10, price=100.0):
        partner = partner or self.partner
        product = product or self.product
        return self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    Command.create(
                        {
                            "name": product.name,
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom": product.uom_id.id,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )

    def _create_invoice_and_confirm(self, partner, amount):
        move = (
            self.env["account.move"]
            .with_user(self.credit_manager_user)
            .create(
                {
                    "move_type": "out_invoice",
                    "partner_id": partner.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": "Test Line",
                                "quantity": 1,
                                "price_unit": amount,
                            }
                        )
                    ],
                }
            )
        )
        move.action_post()
        return move

    def test_01_confirm_normal_order_no_credit_limit(self):
        """Test that a normal order without credit limit confirms normally."""
        partner_no_limit = self.env["res.partner"].create(
            {"name": "No Limit Customer", "credit_limit": 0.0}
        )
        order = self._create_sale_order(partner=partner_no_limit)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.credit_hold)

    def test_02_confirm_order_within_credit_limit(self):
        """Test that an order within credit limit confirms normally."""
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.credit_hold)

    def test_03_confirm_order_exceeds_credit_limit(self):
        """Test that an order exceeding credit limit goes to credit_hold."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        self.assertTrue(order.credit_hold)

    def test_04_no_picking_created_on_credit_hold(self):
        """Test that no pickings are created when order is on credit_hold."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        if "picking_ids" in order._fields:
            self.assertFalse(
                order.picking_ids,
                "No pickings should be created for credit hold orders",
            )

    def test_05_release_credit_hold_by_credit_manager(self):
        """Test that credit manager can release credit hold."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        order.with_user(self.credit_manager_user).action_release_credit()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.credit_hold)
        self.assertTrue(order.credit_hold_released_date)
        self.assertEqual(order.credit_hold_released_by, self.credit_manager_user)

    def test_06_normal_user_cannot_release_credit_hold(self):
        """Test that normal user cannot release credit hold."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        with self.assertRaises(UserError):
            order.with_user(self.normal_user).action_release_credit()

    def test_07_picking_created_after_release(self):
        """Test that picking is created after credit hold is released."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        order.with_user(self.credit_manager_user).action_release_credit()
        self.assertEqual(order.state, "sale")

        if "picking_ids" in order._fields:
            self.assertTrue(
                order.picking_ids,
                "Pickings should be created after releasing credit hold",
            )

    def test_08_write_method_prevents_unauthorized_state_change(self):
        """Test that write method prevents unauthorized state changes."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        with self.assertRaises(UserError):
            order.with_user(self.normal_user).write({"state": "sale"})

    def test_09_write_method_bypass_via_context(self):
        """Test that context bypass flag allows state changes."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        order.with_context(bypass_credit_hold_check=True).write({"state": "sale"})
        self.assertEqual(order.state, "sale")

    def test_10_already_confirmed_order_not_affected(self):
        """Test that already confirmed orders are not affected by credit check."""
        partner_no_limit = self.env["res.partner"].create(
            {"name": "No Limit", "credit_limit": 0.0}
        )
        order = self._create_sale_order(partner=partner_no_limit)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

        order.partner_id.credit_limit = 100.0
        order._compute_credit_hold()
        self.assertFalse(order.credit_hold)

    def test_11_draft_order_resets_credit_hold(self):
        """Test that resetting to draft clears credit_hold flag."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        order.action_cancel()
        order.action_draft()
        self.assertEqual(order.state, "draft")
        self.assertFalse(order.credit_hold)

    def test_12_action_confirm_with_credit_hold_context(self):
        """Test that action_confirm returns correctly when credit hold is triggered."""
        self._create_invoice_and_confirm(self.partner, 900.0)
        order = self._create_sale_order(qty=5, price=100.0)
        result = order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

    def test_13_credit_limit_zero_means_no_limit(self):
        """Test that credit_limit of 0 means no credit check."""
        partner = self.env["res.partner"].create(
            {"name": "Zero Limit", "credit_limit": 0.0}
        )
        self._create_invoice_and_confirm(partner, 900.0)
        order = self._create_sale_order(partner=partner)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_14_credit_limit_negative_means_no_limit(self):
        """Test that negative credit_limit means no credit check."""
        partner = self.env["res.partner"].create(
            {"name": "Negative Limit", "credit_limit": -1.0}
        )
        self._create_invoice_and_confirm(partner, 900.0)
        order = self._create_sale_order(partner=partner)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_15_action_release_credit_on_non_credit_hold_order(self):
        """Test that releasing credit on non-credit-hold order is a no-op."""
        order = self._create_sale_order()
        order.action_confirm()
        self.assertEqual(order.state, "sale")

        result = order.with_user(
            self.credit_manager_user
        ).action_release_credit()
        self.assertTrue(result)

    def test_16_commercial_partner_credit_limit(self):
        """Test that child partner inherits credit limit from commercial partner."""
        parent = self.env["res.partner"].create(
            {"name": "Parent", "credit_limit": 500.0, "is_company": True}
        )
        child = self.env["res.partner"].create(
            {
                "name": "Child",
                "parent_id": parent.id,
                "is_company": False,
            }
        )
        self._create_invoice_and_confirm(parent, 400.0)
        order = self._create_sale_order(partner=child, qty=3, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

    def test_17_partial_credit_hold_multiple_orders(self):
        """Test that only orders exceeding credit limit are put on hold."""
        partner_no_limit = self.env["res.partner"].create(
            {"name": "No Limit", "credit_limit": 0.0}
        )
        self._create_invoice_and_confirm(self.partner, 900.0)

        order1 = self._create_sale_order(partner=partner_no_limit)
        order2 = self._create_sale_order(partner=self.partner, qty=5, price=100.0)

        (order1 | order2).action_confirm()
        self.assertEqual(order1.state, "sale")
        self.assertEqual(order2.state, "credit_hold")


@tagged("post_install", "-at_install")
class TestSaleCreditHoldMigration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        cls.partner = cls.env["res.partner"].create(
            {"name": "Migration Customer", "credit_limit": 500.0}
        )
        cls.partner_no_limit = cls.env["res.partner"].create(
            {"name": "No Limit Customer", "credit_limit": 0.0}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "type": "consu",
                "list_price": 100.0,
            }
        )

    def _create_sale_order(self, partner, qty=10, price=100.0):
        return self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    Command.create(
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": qty,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )

    def _create_invoice_and_confirm(self, partner, amount):
        move = (
            self.env["account.move"]
            .create(
                {
                    "move_type": "out_invoice",
                    "partner_id": partner.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": "Test Line",
                                "quantity": 1,
                                "price_unit": amount,
                            }
                        )
                    ],
                }
            )
        )
        move.action_post()
        return move

    def test_migration_pre_init_hook(self):
        """Test the pre_init_hook migration logic."""
        self._create_invoice_and_confirm(self.partner, 600.0)
        self._create_invoice_and_confirm(self.partner_no_limit, 600.0)

        order_should_migrate = self._create_sale_order(self.partner)
        order_should_not_migrate = self._create_sale_order(
            self.partner_no_limit
        )

        order_should_migrate.action_confirm()
        order_should_not_migrate.action_confirm()

        self.assertEqual(order_should_migrate.state, "credit_hold")
        self.assertEqual(order_should_not_migrate.state, "sale")

        order_should_migrate.with_context(bypass_credit_hold_check=True).write(
            {"state": "sale"}
        )
        self.env.cr.commit()

        self.assertEqual(order_should_migrate.state, "sale")

        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env.cr)

        order_should_migrate.invalidate_cache(["state"], [order_should_migrate.id])
        order_should_not_migrate.invalidate_cache(["state"], [order_should_not_migrate.id])

        self.assertEqual(
            order_should_migrate.state,
            "credit_hold",
            "Order with credit exceeded should be migrated to credit_hold",
        )
        self.assertEqual(
            order_should_not_migrate.state,
            "sale",
            "Order without credit limit should remain in sale state",
        )

    def test_migration_simulates_pre_install_state(self):
        """Test migration simulates orders that were in 'sale' state before
        the module was installed."""
        self._create_invoice_and_confirm(self.partner, 800.0)

        order = self._create_sale_order(self.partner)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        order.with_context(bypass_credit_hold_check=True).write(
            {"state": "sale"}
        )
        self.env.cr.commit()
        self.assertEqual(order.state, "sale")

        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env.cr)

        order.invalidate_cache(["state"], [order.id])

        self.assertEqual(
            order.state,
            "credit_hold",
            "Order should be migrated back to credit_hold",
        )

    def test_migration_does_not_affect_draft_orders(self):
        """Test that migration does not affect draft orders."""
        self._create_invoice_and_confirm(self.partner, 800.0)

        order = self._create_sale_order(self.partner)
        self.assertEqual(order.state, "draft")

        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env.cr)

        self.assertEqual(
            order.state,
            "draft",
            "Draft orders should not be affected by migration",
        )

    def test_migration_does_not_affect_cancelled_orders(self):
        """Test that migration does not affect cancelled orders."""
        self._create_invoice_and_confirm(self.partner, 800.0)

        order = self._create_sale_order(self.partner)
        order.action_confirm()
        order.with_context(bypass_credit_hold_check=True).write(
            {"state": "sale"}
        )
        order.action_cancel()
        self.env.cr.commit()
        self.assertEqual(order.state, "cancel")

        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env.cr)

        order.invalidate_cache(["state"], [order.id])

        self.assertEqual(
            order.state,
            "cancel",
            "Cancelled orders should not be affected by migration",
        )

    def test_migration_batch_processing(self):
        """Test that migration handles large batches correctly."""
        self._create_invoice_and_confirm(self.partner, 800.0)

        orders = self.env["sale.order"]
        for _ in range(5):
            order = self._create_sale_order(self.partner)
            order.action_confirm()
            order.with_context(bypass_credit_hold_check=True).write(
                {"state": "sale"}
            )
            orders |= order

        self.env.cr.commit()
        for order in orders:
            self.assertEqual(order.state, "sale")

        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env.cr)

        for order in orders:
            order.invalidate_cache(["state"], [order.id])
            self.assertEqual(
                order.state,
                "credit_hold",
                f"Order {order.id} should be migrated to credit_hold",
            )


@tagged("post_install", "-at_install")
class TestSaleCreditHoldStockIntegration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        cls.partner = cls.env["res.partner"].create(
            {"name": "Stock Test Customer", "credit_limit": 500.0}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Stock Test Product",
                "type": "consu",
                "list_price": 100.0,
            }
        )
        cls.credit_manager_user = cls.env["res.users"].create(
            {
                "name": "Credit Manager Stock",
                "login": "credit_manager_stock",
                "groups_id": [
                    Command.set(
                        [
                            cls.env.ref("sales_team.group_sale_manager").id,
                            cls.env.ref(
                                "sale_credit_hold.group_credit_manager"
                            ).id,
                        ]
                    )
                ],
            }
        )

    def _create_sale_order(self, partner=None, qty=10, price=100.0):
        partner = partner or self.partner
        return self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    Command.create(
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_uom_qty": qty,
                            "product_uom": self.product.uom_id.id,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )

    def _create_invoice_and_confirm(self, partner, amount):
        move = (
            self.env["account.move"]
            .create(
                {
                    "move_type": "out_invoice",
                    "partner_id": partner.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": "Test Line",
                                "quantity": 1,
                                "price_unit": amount,
                            }
                        )
                    ],
                }
            )
        )
        move.action_post()
        return move

    def test_release_credit_hold_creates_picking(self):
        """Test that releasing credit hold creates stock pickings."""
        self._create_invoice_and_confirm(self.partner, 600.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        if "picking_ids" not in order._fields:
            return

        self.assertFalse(
            order.picking_ids,
            "No pickings should exist while on credit hold",
        )

        order.with_user(self.credit_manager_user).action_release_credit()

        self.assertTrue(
            order.picking_ids,
            "Pickings should be created after credit hold release",
        )

    def test_release_credit_hold_picking_state(self):
        """Test picking state after credit hold release."""
        self._create_invoice_and_confirm(self.partner, 600.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")

        order.with_user(self.credit_manager_user).action_release_credit()
        self.assertEqual(order.state, "sale")

        if "picking_ids" in order._fields and order.picking_ids:
            picking = order.picking_ids[0]
            self.assertIn(
                picking.state,
                ["draft", "waiting", "confirmed", "assigned"],
                "Picking should be in a valid initial state after release",
            )

    def test_credit_hold_release_fields_set(self):
        """Test that release tracking fields are properly set."""
        self._create_invoice_and_confirm(self.partner, 600.0)
        order = self._create_sale_order(qty=5, price=100.0)
        order.action_confirm()

        order.with_user(self.credit_manager_user).action_release_credit()

        self.assertIsNotNone(order.credit_hold_released_date)
        self.assertEqual(order.credit_hold_released_by, self.credit_manager_user)
        self.assertFalse(order.credit_hold)