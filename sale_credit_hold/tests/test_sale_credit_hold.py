# Copyright 2024 Akretion (http://www.akretion.com).
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import column_exists

_logger = logging.getLogger(__name__)


class TestSaleCreditHold(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test Credit Partner",
                "credit_limit": 1000.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "type": "consu",
            }
        )
        cls.credit_manager_group = cls.env.ref(
            "sale_credit_hold.group_credit_manager"
        )
        cls.user_credit_manager = cls.env["res.users"].create(
            {
                "name": "Credit Manager",
                "login": "credit_manager",
                "email": "credit_manager@test.com",
                "groups_id": [
                    (4, cls.credit_manager_group.id),
                    (4, cls.env.ref("sales_team.group_sale_manager").id),
                ],
            }
        )
        cls.user_sale_user = cls.env["res.users"].create(
            {
                "name": "Sale User",
                "login": "sale_user",
                "email": "sale_user@test.com",
                "groups_id": [
                    (4, cls.env.ref("sales_team.group_sale_salesman").id),
                ],
            }
        )

    def _create_sale_order(self, partner=None, amount=500.0):
        partner = partner or self.partner
        order = self.env["sale.order"].create(
            {
                "partner_id": partner.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "name": "Test Line",
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": amount,
            }
        )
        return order

    def test_order_confirm_no_credit_limit(self):
        partner = self.env["res.partner"].create(
            {
                "name": "No Limit Partner",
                "credit_limit": 0,
            }
        )
        order = self._create_sale_order(partner=partner, amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_order_confirm_within_credit_limit(self):
        self.partner.credit_limit = 10000.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_order_confirm_exceeds_credit_limit(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        self.assertTrue(order.credit_hold)

    def test_order_confirm_exceeds_with_existing_orders(self):
        self.partner.credit_limit = 1000.0
        order1 = self._create_sale_order(amount=600.0)
        order1.with_context(bypass_credit_check=True).action_confirm()
        self.assertEqual(order1.state, "sale")
        order2 = self._create_sale_order(amount=500.0)
        order2.action_confirm()
        self.assertEqual(order2.state, "credit_hold")

    def test_credit_hold_no_picking_created(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        self.assertFalse(order.picking_ids)

    def test_release_credit_creates_picking(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        self.assertFalse(order.picking_ids)
        order.with_user(self.user_credit_manager).action_release_credit()
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.picking_ids)

    def test_release_credit_picking_origin(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        self.assertEqual(order.state, "sale")
        for picking in order.picking_ids:
            self.assertEqual(picking.origin, order.name)

    def test_release_credit_picking_sale_id(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        self.assertEqual(order.state, "sale")
        for picking in order.picking_ids:
            self.assertEqual(picking.sale_id, order)

    def test_release_credit_only_credit_hold(self):
        order = self._create_sale_order(amount=500.0)
        self.partner.credit_limit = 10000.0
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        with self.assertRaises(UserError):
            order.action_release_credit()

    def test_write_block_state_change_without_permission(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        with self.assertRaises(UserError):
            order.with_user(self.user_sale_user).write({"state": "sale"})

    def test_write_allow_state_change_with_bypass(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        order.with_context(bypass_credit_check=True).write({"state": "sale"})
        self.assertEqual(order.state, "sale")

    def test_credit_hold_computed_field(self):
        self.partner.credit_limit = 100.0
        order = self._create_sale_order(amount=500.0)
        self.assertFalse(order.credit_hold)
        order.action_confirm()
        self.assertTrue(order.credit_hold)

    def test_partner_credit_used(self):
        self.partner.credit_limit = 10000.0
        order = self._create_sale_order(amount=500.0)
        order.with_context(bypass_credit_check=True).action_confirm()
        self.assertAlmostEqual(self.partner.credit_used, 500.0, places=2)

    def test_partner_credit_used_multiple_orders(self):
        self.partner.credit_limit = 10000.0
        order1 = self._create_sale_order(amount=300.0)
        order1.with_context(bypass_credit_check=True).action_confirm()
        order2 = self._create_sale_order(amount=200.0)
        order2.with_context(bypass_credit_check=True).action_confirm()
        self.assertAlmostEqual(self.partner.credit_used, 500.0, places=2)

    def test_partner_credit_limit_zero_no_hold(self):
        self.partner.credit_limit = 0
        order = self._create_sale_order(amount=99999.0)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_commercial_partner_credit_check(self):
        parent_partner = self.env["res.partner"].create(
            {
                "name": "Parent Company",
                "credit_limit": 100.0,
                "is_company": True,
            }
        )
        child_partner = self.env["res.partner"].create(
            {
                "name": "Child Contact",
                "parent_id": parent_partner.id,
                "credit_limit": 0,
            }
        )
        order = self._create_sale_order(partner=child_partner, amount=500.0)
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")


class TestSaleCreditHoldMigration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Migration Test Partner",
                "credit_limit": 500.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Migration Test Product",
                "type": "consu",
            }
        )

    def _create_confirmed_order(self, amount=600.0):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "name": "Test Line",
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": amount,
            }
        )
        order.with_context(bypass_credit_check=True).action_confirm()
        return order

    def test_pre_init_hook_migrates_over_limit_orders(self):
        order = self._create_confirmed_order(amount=600.0)
        self.assertEqual(order.state, "sale")
        order.write({"state": "sale"})
        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env)
        order.invalidate_recordset()
        self.assertEqual(order.state, "credit_hold")
        self.assertTrue(order.credit_hold)

    def test_pre_init_hook_keeps_under_limit_orders(self):
        self.partner.credit_limit = 10000.0
        order = self._create_confirmed_order(amount=600.0)
        self.assertEqual(order.state, "sale")
        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env)
        order.invalidate_recordset()
        self.assertEqual(order.state, "sale")

    def test_pre_init_hook_no_limit_partner(self):
        self.partner.credit_limit = 0
        order = self._create_confirmed_order(amount=600.0)
        self.assertEqual(order.state, "sale")
        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env)
        order.invalidate_recordset()
        self.assertEqual(order.state, "sale")

    def test_pre_init_hook_draft_orders_unchanged(self):
        self.partner.credit_limit = 100.0
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "name": "Test Line",
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": 600.0,
            }
        )
        self.assertEqual(order.state, "draft")
        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env)
        order.invalidate_recordset()
        self.assertEqual(order.state, "draft")

    def test_pre_init_hook_setup_columns(self):
        from odoo.addons.sale_credit_hold.hooks import _setup_new_columns

        _setup_new_columns(self.env.cr)
        self.assertTrue(
            column_exists(self.env.cr, "sale_order", "credit_hold")
        )
        self.assertTrue(
            column_exists(self.env.cr, "res_partner", "credit_limit")
        )

    def test_migration_then_release(self):
        order = self._create_confirmed_order(amount=600.0)
        self.assertEqual(order.state, "sale")
        from odoo.addons.sale_credit_hold.hooks import _migrate_credit_hold_orders

        _migrate_credit_hold_orders(self.env)
        order.invalidate_recordset()
        self.assertEqual(order.state, "credit_hold")
        credit_manager = self.env.ref("sale_credit_hold.group_credit_manager")
        manager_user = self.env["res.users"].create(
            {
                "name": "Migration Manager",
                "login": "migration_manager",
                "email": "migration_manager@test.com",
                "groups_id": [
                    (4, credit_manager.id),
                    (4, self.env.ref("sales_team.group_sale_manager").id),
                ],
            }
        )
        order.with_user(manager_user).action_release_credit()
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.picking_ids)


class TestSaleCreditHoldPicking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Picking Test Partner",
                "credit_limit": 100.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Picking Test Product",
                "type": "consu",
            }
        )
        cls.credit_manager_group = cls.env.ref(
            "sale_credit_hold.group_credit_manager"
        )
        cls.user_credit_manager = cls.env["res.users"].create(
            {
                "name": "Picking Credit Manager",
                "login": "picking_credit_manager",
                "email": "picking_credit_manager@test.com",
                "groups_id": [
                    (4, cls.credit_manager_group.id),
                    (4, cls.env.ref("sales_team.group_sale_manager").id),
                ],
            }
        )

    def _create_sale_order(self, amount=500.0):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "name": "Test Line",
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "product_uom": self.env.ref("uom.product_uom_unit").id,
                "price_unit": amount,
            }
        )
        return order

    def test_picking_not_created_on_credit_hold(self):
        order = self._create_sale_order()
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        self.assertEqual(len(order.picking_ids), 0)

    def test_picking_created_after_release(self):
        order = self._create_sale_order()
        order.action_confirm()
        self.assertEqual(order.state, "credit_hold")
        order.with_user(self.user_credit_manager).action_release_credit()
        self.assertEqual(order.state, "sale")
        self.assertEqual(len(order.picking_ids), 1)

    def test_picking_sale_id_after_release(self):
        order = self._create_sale_order()
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        picking = order.picking_ids
        self.assertEqual(picking.sale_id, order)

    def test_picking_origin_after_release(self):
        order = self._create_sale_order()
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        picking = order.picking_ids
        self.assertEqual(picking.origin, order.name)

    def test_picking_move_line_sale_line_id(self):
        order = self._create_sale_order()
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        picking = order.picking_ids
        for move in picking.move_ids:
            self.assertEqual(move.sale_line_id.order_id, order)

    def test_picking_partner_id_after_release(self):
        order = self._create_sale_order()
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        picking = order.picking_ids
        self.assertEqual(picking.partner_id, order.partner_id)

    def test_normal_order_picking_immediate(self):
        self.partner.credit_limit = 0
        order = self._create_sale_order()
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertEqual(len(order.picking_ids), 1)

    def test_picking_location_id_after_release(self):
        order = self._create_sale_order()
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        picking = order.picking_ids
        self.assertEqual(
            picking.location_id,
            order.warehouse_id.lot_stock_id,
        )

    def test_picking_picking_type_id_after_release(self):
        order = self._create_sale_order()
        order.action_confirm()
        order.with_user(self.user_credit_manager).action_release_credit()
        picking = order.picking_ids
        self.assertEqual(
            picking.picking_type_id,
            order.warehouse_id.out_type_id,
        )
