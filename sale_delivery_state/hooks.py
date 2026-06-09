# Copyright 2023 Akretion (https://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# Copyright 2024 Manuel Regidor <manuel.regidor@sygel.es>
# Copyright 2025 Camptocamp SA
# @author: Simone Orsi <simahawk@gmail.com>
# @author: Sébastien Alix <sebastien.alix@camptocamp.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import logging
import math

from odoo.tools.misc import split_every
from odoo.tools.sql import column_exists, create_column

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    _setup_new_columns(env.cr)
    _migrate_credit_hold_orders(env)

def _migrate_credit_hold_orders(env):
    cr = env.cr
    _logger.info("Migrating historic orders to credit_hold state if credit limit exceeded")
    
    # Check if `use_partner_credit_limit` exists (in Odoo 16 it's on res.partner)
    if not column_exists(cr, "res_partner", "use_partner_credit_limit"):
        return
        
    cr.execute("SELECT id FROM sale_order WHERE state = 'sale'")
    order_ids = [row[0] for row in cr.fetchall()]
    
    batch_size = 500
    for i in range(0, len(order_ids), batch_size):
        batch = order_ids[i:i+batch_size]
        orders = env['sale.order'].browse(batch)
        for order in orders:
            if order.partner_id.use_partner_credit_limit and (
                order.partner_id.credit + order.amount_total > order.partner_id.credit_limit
            ):
                # Cancel associated pickings
                if 'picking_ids' in order._fields:
                    order.picking_ids.action_cancel()
                order.write({'state': 'credit_hold'})
        cr.commit()

def _setup_new_columns(cr):
    if not column_exists(cr, "sale_order", "delivery_status"):
        _logger.info("Create sale_order column delivery_status")
        create_column(cr, "sale_order", "delivery_status", "varchar")
    if not column_exists(cr, "sale_order_line", "skip_sale_delivery_state"):
        _logger.info("Create sale_order_line column skip_sale_delivery_state")
        create_column(cr, "sale_order_line", "skip_sale_delivery_state", "boolean")
        cr.execute("UPDATE sale_order_line SET skip_sale_delivery_state = False")


def post_init_hook(env):
    # Recompute '<sale.order>.delivery_status' by chunk to keep a constant
    # memory consumption
    order_model = env["sale.order"].with_context(prefetch_fields=False)
    rec_ids = order_model.search([]).ids
    _logger.info("Recompute 'delivery_status' on %s sale orders...", len(rec_ids))
    chunk_size = 2000
    nb_chunks = math.ceil(len(rec_ids) / chunk_size)
    for i, chunk_ids in enumerate(split_every(chunk_size, rec_ids), 1):
        _logger.info("... %s / %s", i, nb_chunks)
        records = order_model.browse(chunk_ids)
        records._compute_oca_delivery_status()
        env.cr.commit()
        env.invalidate_all()
