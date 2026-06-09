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


CREDIT_HOLD_CHUNK_SIZE = 2000


def pre_init_hook(env):
    _setup_new_columns(env.cr)
    _migrate_credit_hold_orders(env.cr)


def _setup_new_columns(cr):
    if not column_exists(cr, "sale_order", "delivery_status"):
        _logger.info("Create sale_order column delivery_status")
        create_column(cr, "sale_order", "delivery_status", "varchar")
    if not column_exists(cr, "sale_order_line", "skip_sale_delivery_state"):
        _logger.info("Create sale_order_line column skip_sale_delivery_state")
        create_column(cr, "sale_order_line", "skip_sale_delivery_state", "boolean")
        cr.execute("UPDATE sale_order_line SET skip_sale_delivery_state = False")


def _migrate_credit_hold_orders(cr, chunk_size=CREDIT_HOLD_CHUNK_SIZE):
    if not column_exists(cr, "res_partner", "credit") or not column_exists(
        cr, "res_partner", "credit_limit"
    ):
        _logger.info("Skip credit hold migration because partner credit fields are missing")
        return
    total = 0
    while True:
        cr.execute(
            """
            WITH batch AS (
                SELECT so.id
                FROM sale_order so
                JOIN res_partner partner ON partner.id = so.partner_id
                JOIN res_partner commercial_partner
                    ON commercial_partner.id = COALESCE(
                        partner.commercial_partner_id, partner.id
                    )
                WHERE so.state = 'sale'
                    AND COALESCE(commercial_partner.credit_limit, 0) > 0
                    AND COALESCE(commercial_partner.credit, 0)
                        + COALESCE(so.amount_total, 0)
                        > COALESCE(commercial_partner.credit_limit, 0)
                ORDER BY so.id
                LIMIT %s
                FOR UPDATE OF so SKIP LOCKED
            )
            UPDATE sale_order so
            SET state = 'credit_hold'
            FROM batch
            WHERE so.id = batch.id
            RETURNING so.id
            """,
            (chunk_size,),
        )
        moved_ids = [row[0] for row in cr.fetchall()]
        if not moved_ids:
            break
        total += len(moved_ids)
        _logger.info("Migrated %s sale orders to credit_hold", total)
        cr.commit()
    if total:
        _logger.info("Completed credit hold migration for %s sale orders", total)


def post_init_hook(env):
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
