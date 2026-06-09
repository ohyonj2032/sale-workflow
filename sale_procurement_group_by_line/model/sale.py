# Copyright 2013-2014 Camptocamp SA - Guewen Baconnier
# © 2016-20 ForgeFlow S.L. (https://www.forgeflow.com)
# © 2016 Serpent Consulting Services Pvt. Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models
from odoo.tools.float_utils import float_compare


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    procurement_group_id = fields.Many2one(
        "procurement.group", "Procurement group", copy=False
    )

    def _get_procurement_group(self):
        super()._get_procurement_group()
        return self.procurement_group_id or False

    def _get_procurement_group_key(self):
        """Return a key with priority to be used to regroup lines in multiple
        procurement groups

        """
        return 8, self.order_id.id

    def _with_procurement_company_scope(self):
        self.ensure_one()
        return self.with_context(allowed_company_ids=[self.company_id.id]).with_company(
            self.company_id
        )

    def _invalidate_known_fields(self, records, field_names):
        existing_fields = [field_name for field_name in field_names if field_name in records._fields]
        if existing_fields:
            records.invalidate_recordset(existing_fields)

    def _invalidate_procurement_cache(self, products=None, orders=None):
        orders = orders or self.mapped("order_id")
        products = products or self.mapped("product_id")
        product_templates = products.mapped("product_tmpl_id")
        warehouses = orders.mapped("warehouse_id")
        self._invalidate_known_fields(
            self,
            [
                "company_id",
                "order_id",
                "product_id",
                "product_uom",
                "product_uom_qty",
                "procurement_group_id",
                "route_id",
                "move_ids",
            ],
        )
        self._invalidate_known_fields(
            orders,
            [
                "company_id",
                "warehouse_id",
                "partner_shipping_id",
                "picking_policy",
                "procurement_group_id",
                "order_line",
            ],
        )
        self._invalidate_known_fields(
            products,
            ["type", "uom_id", "route_ids", "product_tmpl_id", "categ_id"],
        )
        self._invalidate_known_fields(product_templates, ["route_ids", "categ_id"])
        self._invalidate_known_fields(warehouses, ["company_id", "out_type_id", "route_ids"])

    def write(self, vals):
        orders = self.mapped("order_id")
        products = self.mapped("product_id")
        res = super().write(vals)
        if {"product_id", "product_uom", "product_uom_qty", "route_id"}.intersection(vals):
            self._invalidate_procurement_cache(products=products | self.mapped("product_id"), orders=orders)
        return res

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """
        Launch procurement group run method.
        """
        if self._context.get("skip_procurement"):
            return True
        self._invalidate_procurement_cache()
        precision = self.env["decimal.precision"].precision_get(
            "Product Unit of Measure"
        )
        procurements = {}
        groups = {}
        procured_line_ids = set()
        if not previous_product_uom_qty:
            previous_product_uom_qty = {}
        for line in self:
            line = line._with_procurement_company_scope()
            if (
                line.state != "sale"
                or line.order_id.locked
                or line.product_id.type != "consu"
            ):
                continue
            qty = line._get_qty_procurement(previous_product_uom_qty) or 0.0
            if (
                float_compare(qty, line.product_uom_qty, precision_digits=precision)
                == 0
            ):
                continue

            group_id = line._get_procurement_group()

            for order_line in line.order_id.order_line:
                g_id = order_line.procurement_group_id or False
                if g_id:
                    groups[order_line._get_procurement_group_key()] = g_id
            if not group_id:
                group_id = groups.get(line._get_procurement_group_key())

            if not group_id:
                vals = line._prepare_procurement_group_vals()
                group_id = line.env["procurement.group"].create(vals)
                line.order_id.procurement_group_id = group_id
            else:
                updated_vals = {}
                if group_id.partner_id != line.order_id.partner_shipping_id:
                    updated_vals.update(
                        {"partner_id": line.order_id.partner_shipping_id.id}
                    )
                if group_id.move_type != line.order_id.picking_policy:
                    updated_vals.update({"move_type": line.order_id.picking_policy})
                if updated_vals:
                    group_id.write(updated_vals)
            line.procurement_group_id = group_id

            values = line._prepare_procurement_values(group_id=group_id)
            product_qty = line.product_uom_qty - qty

            line_uom = line.product_uom
            quant_uom = line.product_id.uom_id
            origin = (
                f"{line.order_id.name} - {line.order_id.client_order_ref}"
                if line.order_id.client_order_ref
                else line.order_id.name
            )
            product_qty, procurement_uom = line_uom._adjust_uom_quantities(
                product_qty, quant_uom
            )
            procurements.setdefault(line.company_id.id, {"company": line.company_id, "values": []})[
                "values"
            ] += line._create_procurements(
                product_qty, procurement_uom, origin, values
            )
            procured_line_ids.add(line.id)
            previous_product_uom_qty[line.id] = line.product_uom_qty
        for data in procurements.values():
            self.with_context(allowed_company_ids=[data["company"].id]).with_company(
                data["company"]
            ).env["procurement.group"].run(data["values"])
        orders = self.mapped("order_id")
        for order in orders:
            order = order.with_context(allowed_company_ids=[order.company_id.id]).with_company(
                order.company_id
            )
            pickings_to_confirm = order.picking_ids.filtered(
                lambda p: p.state not in ["cancel", "done"]
            )
            if pickings_to_confirm:
                pickings_to_confirm.action_confirm()
        remaining_lines = self - self.browse(procured_line_ids)
        result = True
        for company in remaining_lines.mapped("company_id"):
            company_lines = remaining_lines.filtered(
                lambda line, company=company: line.company_id == company
            )
            scoped_lines = company_lines.with_context(
                sale_group_by_line=True,
                allowed_company_ids=[company.id],
            ).with_company(company)
            result = super(SaleOrderLine, scoped_lines)._action_launch_stock_rule(
                previous_product_uom_qty=previous_product_uom_qty
            )
        return result
