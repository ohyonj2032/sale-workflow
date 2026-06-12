# Copyright 2024 Akretion (http://www.akretion.com).
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import math

from odoo.tools.misc import split_every
from odoo.tools.sql import column_exists, create_column

_logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def pre_init_hook(env):
    _setup_new_columns(env.cr)
    _migrate_credit_hold_orders(env)


def _setup_new_columns(cr):
    if not column_exists(cr, "sale_order", "credit_hold"):
        _logger.info("Create sale_order column credit_hold")
        create_column(cr, "sale_order", "credit_hold", "boolean")
        cr.execute("UPDATE sale_order SET credit_hold = False")
    if not column_exists(cr, "res_partner", "credit_limit"):
        _logger.info("Create res_partner column credit_limit")
        create_column(cr, "res_partner", "credit_limit", "float")
        cr.execute("UPDATE res_partner SET credit_limit = 0")


def _migrate_credit_hold_orders(env):
    cr = env.cr
    cr.execute(
        """
        SELECT so.id
        FROM sale_order so
        JOIN res_partner rp ON so.partner_id = rp.id
        WHERE so.state = 'sale'
          AND rp.credit_limit > 0
          AND (
              COALESCE((
                  SELECT SUM(so2.amount_total)
                  FROM sale_order so2
                  WHERE so2.partner_id IN (
                      SELECT rp2.id
                      FROM res_partner rp2
                      WHERE rp2.commercial_partner_id = rp.commercial_partner_id
                        OR rp2.id = rp.commercial_partner_id
                  )
                  AND so2.state IN ('sale', 'done')
              ), 0)
          ) > rp.credit_limit
        ORDER BY so.id
        """
    )
    order_ids = [row[0] for row in cr.fetchall()]
    if not order_ids:
        _logger.info("No sale orders to migrate to credit_hold state.")
        return
    _logger.info(
        "Migrating %s sale orders to credit_hold state...", len(order_ids)
    )
    nb_chunks = math.ceil(len(order_ids) / BATCH_SIZE)
    for i, chunk_ids in enumerate(split_every(BATCH_SIZE, order_ids), 1):
        _logger.info("... %s / %s", i, nb_chunks)
        cr.execute(
            """
            UPDATE sale_order
            SET state = 'credit_hold', credit_hold = True
            WHERE id IN %s
            """,
            (tuple(chunk_ids),),
        )
        cr.commit()
    _logger.info(
        "Migration complete. %s orders migrated to credit_hold.", len(order_ids)
    )


def post_init_hook(env):
    cr = env.cr
    if column_exists(cr, "sale_order", "credit_hold"):
        cr.execute(
            "SELECT id FROM sale_order WHERE credit_hold = True AND state = 'credit_hold'"
        )
        order_ids = [row[0] for row in cr.fetchall()]
        if order_ids:
            _logger.info(
                "Recomputing fields for %s credit-held orders...", len(order_ids)
            )
            orders = env["sale.order"].with_context(
                prefetch_fields=False
            ).browse(order_ids)
            orders._compute_credit_hold()
