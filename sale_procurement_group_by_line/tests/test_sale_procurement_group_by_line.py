# Copyright 2013-2014 Camptocamp SA - Guewen Baconnier
# © 2016-20 ForgeFlow S.L. (https://www.forgeflow.com)
# © 2016 Serpent Consulting Services Pvt. Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import Form
from odoo.tests.common import TransactionCase

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestSaleProcurementGroupByLine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_model = cls.env["product.product"]
        cls.product_ctg_model = cls.env["product.category"]
        cls.proc_group_model = cls.env["procurement.group"]
        cls.sale_model = cls.env["sale.order"]
        cls.order_line_model = cls.env["sale.order.line"]
        cls.location_model = cls.env["stock.location"]
        cls.route_model = cls.env["stock.route"]
        cls.rule_model = cls.env["stock.rule"]
        cls.customer = cls.env.ref("base.res_partner_2")
        cls.warehouse_id = cls.env.ref("stock.warehouse0")
        cls.product_ctg = cls._create_product_category()
        cls.new_product1 = cls._create_product("test_product1")
        cls.new_product2 = cls._create_product("test_product2")
        cls.internal_dest = cls.location_model.create(
            {
                "name": "Internal Consumed-in-Testing",
                "usage": "internal",
                "location_id": cls.warehouse_id.view_location_id.id,
            }
        )
        cls.internal_route = cls.route_model.create(
            {
                "name": "Stock -> Internal Test Dest",
                "product_selectable": True,
                "sequence": 1,
            }
        )
        cls.rule_model.create(
            {
                "name": "Stock -> Internal Consumed-in-Testing",
                "route_id": cls.internal_route.id,
                "location_src_id": cls.warehouse_id.lot_stock_id.id,
                "location_dest_id": cls.internal_dest.id,
                "action": "pull",
                "procure_method": "make_to_stock",
                "picking_type_id": cls.warehouse_id.out_type_id.id,
                "warehouse_id": cls.warehouse_id.id,
            }
        )
        cls.product_internal_dest = cls.product_model.create(
            {
                "name": "test_product_internal_dest",
                "categ_id": cls.product_ctg.id,
                "is_storable": True,
                "route_ids": [(6, 0, [cls.internal_route.id])],
            }
        )
        cls.customer_internal = cls.customer.copy(
            {"property_stock_customer": cls.internal_dest.id}
        )
        cls.sale = cls._create_sale_order()

    @classmethod
    def _create_product_category(cls):
        product_ctg = cls.product_ctg_model.create({"name": "test_product_ctg"})
        return product_ctg

    @classmethod
    def _create_product(cls, name):
        product = cls.product_model.create(
            {"name": name, "categ_id": cls.product_ctg.id, "is_storable": True}
        )
        return product

    @classmethod
    def _create_sale_order(cls):
        cls.sale = cls.sale_model.create(
            {
                "partner_id": cls.customer.id,
                "warehouse_id": cls.warehouse_id.id,
                "picking_policy": "direct",
            }
        )
        cls.line1 = cls.order_line_model.create(
            {
                "order_id": cls.sale.id,
                "product_id": cls.new_product1.id,
                "product_uom_qty": 10.0,
                "name": "Sale Order Line Demo1",
            }
        )
        cls.line2 = cls.order_line_model.create(
            {
                "order_id": cls.sale.id,
                "product_id": cls.new_product2.id,
                "product_uom_qty": 5.0,
                "name": "Sale Order Line Demo2",
            }
        )
        return cls.sale

    def test_01_procurement_group_by_line(self):
        self.sale.action_confirm()
        self.assertEqual(
            self.line2.procurement_group_id,
            self.line1.procurement_group_id,
            """Both Sale Order line should belong
                         to Procurement Group""",
        )
        self.picking_ids = self.env["stock.picking"].search(
            [("group_id", "in", self.line2.procurement_group_id.ids)]
        )
        self.picking_ids.move_ids.write({"quantity": 5})
        wiz_act = self.picking_ids.button_validate()
        wiz = Form(
            self.env[wiz_act["res_model"]].with_context(**wiz_act["context"])
        ).save()
        wiz.process()
        self.assertTrue(self.picking_ids, "Procurement Group should have picking")

    def test_02_action_launch_procurement_rule_1(self):
        group_id = self.proc_group_model.create(
            {"move_type": "one", "sale_id": self.sale.id, "name": self.sale.name}
        )
        self.line1.procurement_group_id = group_id
        self.line2.procurement_group_id = group_id
        self.sale.action_confirm()
        self.assertEqual(self.sale.state, "sale")
        self.assertEqual(len(self.line1.move_ids), 1)
        self.assertEqual(self.line1.move_ids.name, self.line1.product_id.display_name)
        self.assertEqual(len(self.line2.move_ids), 1)
        self.assertEqual(self.line2.move_ids.name, self.line2.product_id.display_name)

    def test_03_action_launch_procurement_rule_2(self):
        group_id = self.proc_group_model.create(
            {"move_type": "one", "sale_id": self.sale.id, "name": self.sale.name}
        )
        self.line1.procurement_group_id = group_id
        self.line2.procurement_group_id = False
        self.sale.action_confirm()
        self.assertEqual(self.line2.procurement_group_id, group_id)

    def test_04_action_launch_procurement_rule_3(self):
        group_id = self.proc_group_model.create(
            {"move_type": "one", "sale_id": self.sale.id, "name": self.sale.name}
        )
        self.line1.procurement_group_id = False
        self.line2.procurement_group_id = False
        self.sale.action_confirm()
        self.assertNotEqual(self.line1.procurement_group_id, group_id)
        self.assertEqual(
            self.line1.procurement_group_id, self.line2.procurement_group_id
        )

    def test_05_merged_stock_moves_from_same_procurement(self):
        self.sale.action_confirm()
        self.sale.order_line[1].product_uom_qty = 0.0
        self.assertEqual(
            len(self.sale.picking_ids), 1, "Negative stock move should me merged"
        )

    def test_06_update_sale_order_line_respect_procurement_group(self):
        self.sale.action_confirm()
        proc_group = self.sale.order_line[1].procurement_group_id
        self.assertEqual(len(self.line1.move_ids), 1)
        self.sale.order_line[1].product_uom_qty += 1
        self.assertEqual(self.sale.order_line[1].procurement_group_id, proc_group)
        self.assertEqual(len(self.line1.move_ids), 1)

    def test_07_no_duplicate_procurement_final_location_is_internal(self):
        sale = self.sale_model.create(
            {
                "partner_id": self.customer_internal.id,
                "warehouse_id": self.warehouse_id.id,
                "picking_policy": "direct",
            }
        )
        line = self.order_line_model.create(
            {
                "order_id": sale.id,
                "product_id": self.product_internal_dest.id,
                "product_uom_qty": 3.0,
                "name": "Internal Dest Line",
            }
        )
        sale.action_confirm()
        moves = line.move_ids.filtered(lambda m: m.state != "cancel")
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves.product_uom_qty, 3.0)
        self.assertEqual(moves.location_final_id, self.internal_dest)


class TestSaleProcurementGroupByLineMultiCompany(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.main_company = cls.env.ref("base.main_company")
        cls.other_company = cls.setup_other_company(
            name="Procurement Group By Line Company",
            currency_id=cls.env.ref("base.EUR").id,
            country_id=cls.env.ref("base.fr").id,
        )["company"]
        cls.env.user.company_ids |= cls.other_company
        cls.env.user.company_id = cls.main_company
        cls.customer = cls.env["res.partner"].create({"name": "Procurement Customer"})
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.other_company.id)], limit=1
        )
        cls.service_product = cls.env["product.product"].with_company(
            cls.other_company
        ).create(
            {
                "name": "Procurement Service",
                "type": "service",
                "list_price": 10.0,
            }
        )
        cls.stock_product = cls.env["product.product"].with_company(
            cls.other_company
        ).create(
            {
                "name": "Procurement Storable",
                "type": "consu",
                "is_storable": True,
                "list_price": 20.0,
            }
        )
        inventory = cls.env["stock.quant"].with_company(cls.other_company).create(
            {
                "product_id": cls.stock_product.id,
                "location_id": cls.warehouse.lot_stock_id.id,
                "inventory_quantity": 5.0,
            }
        )
        inventory._apply_inventory()

    def _create_other_company_sale(self):
        return self.env["sale.order"].with_company(self.other_company).create(
            {
                "partner_id": self.customer.id,
                "company_id": self.other_company.id,
                "warehouse_id": self.warehouse.id,
                "picking_policy": "direct",
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.service_product.id,
                            "name": self.service_product.name,
                            "product_uom": self.service_product.uom_id.id,
                            "product_uom_qty": 1.0,
                            "price_unit": self.service_product.list_price,
                        },
                    )
                ],
            }
        )

    def test_08_product_switch_keeps_company_scoped_procurement(self):
        sale = self._create_other_company_sale()
        line = sale.order_line
        self.assertEqual(line.product_id.type, "service")
        line.write(
            {
                "product_id": self.stock_product.id,
                "name": self.stock_product.name,
                "product_uom": self.stock_product.uom_id.id,
                "price_unit": self.stock_product.list_price,
            }
        )
        self.assertEqual(line.product_id.type, "consu")
        sale.sudo().with_context(allowed_company_ids=[self.main_company.id]).with_company(
            self.main_company
        ).action_confirm()
        self.assertEqual(sale.state, "sale")
        self.assertTrue(sale.picking_ids)
        self.assertEqual(sale.picking_ids.picking_type_id.company_id, self.other_company)
