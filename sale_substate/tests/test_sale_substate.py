# Copyright 2019 Akretion Mourad EL HADJ MIMOUNE
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestSaleSubstate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order_model = cls.env["sale.order"]
        cls.partner = cls.env.ref("base.res_partner_1")
        cls.product = cls.env.ref("product.product_product_25")
        cls.substate_under_nego = cls.env.ref("sale_substate.base_substate_under_nego")
        cls.substate_valid_docs = cls.env.ref("sale_substate.base_substate_valid_docs")
        cls.substate_in_delivery = cls.env.ref("sale_substate.base_substate_in_delivery")
        cls.substate_delivered = cls.env.ref("sale_substate.base_substate_delivered")

    @classmethod
    def _create_sale_order(cls):
        return cls.order_model.create(
            {
                "name": "Test sale substate workflow",
                "partner_id": cls.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "product_uom_qty": 2,
                            "product_uom": cls.product.uom_id.id,
                            "name": cls.product.display_name,
                            "price_unit": 120.0,
                        },
                    )
                ],
            }
        )

    def test_sale_order_substate(self):
        order = self._create_sale_order()

        self.assertEqual(order.state, "draft")
        self.assertEqual(order.substate_id, self.substate_under_nego)

        with self.assertRaises(ValidationError):
            order.substate_id = self.substate_valid_docs

        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertEqual(order.substate_id, self.substate_valid_docs)

        order._action_cancel()
        self.assertEqual(order.state, "cancel")
        self.assertFalse(order.substate_id)

    def test_delivery_substate_flow(self):
        order = self._create_sale_order()

        order.action_confirm()
        self.assertEqual(order.delivery_status, "pending")
        self.assertEqual(order.substate_id, self.substate_valid_docs)

        order.order_line.qty_delivered = 1.0
        order.action_deliver()
        self.assertEqual(order.delivery_status, "partial")
        self.assertEqual(order.substate_id, self.substate_in_delivery)

        order.order_line.qty_delivered = order.order_line.product_uom_qty
        order.action_deliver()
        self.assertEqual(order.delivery_status, "full")
        self.assertEqual(order.substate_id, self.substate_delivered)
