# Copyright 2023 Akretion (https://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# Copyright 2024 Manuel Regidor <manuel.regidor@sygel.es>
# Copyright 2025 Camptocamp SA
# @author: Simone Orsi <simahawk@gmail.com>
# @author: Sébastien Alix <sebastien.alix@camptocamp.com>
# Copyright 2026 Credit Hold Enhancement
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import logging
import math

from odoo.tools.misc import split_every
from odoo.tools.sql import column_exists, create_column

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """Ensure backward compatibility with existing ``sale.order`` rows.

    Steps performed at install time:

    1. Create the ``delivery_status`` / ``skip_sale_delivery_state`` columns if
       missing (fast, avoids a full ORM schema rebuild).
    2. Create the ``credit_hold`` / ``credit_hold_reason`` / ``credit_hold_date``
       columns if missing.
    3. Migrate existing orders that were already in ``state='sale'`` AND whose
       commercial partner has a credit limit that would be exceeded today. Those
       orders are flagged with ``credit_hold`` and ``state='credit_hold'`` so the
       new feature works seamlessly on an existing database. The migration is
       executed in chunks to avoid holding long row-level locks.

    The raw SQL approach used here intentionally bypasses the ORM: at this stage
    the module's model classes are not yet loaded into the registry, which also
    means ORM-level ``write`` protections are not active. Direct SQL also keeps
    the operation very fast on large databases.
    """
    cr = env.cr
    _setup_new_columns(cr)
    _migrate_credit_hold_orders(env)


def _setup_new_columns(cr):
    """Create the columns we are adding at the SQL level before the ORM runs."""
    if not column_exists(cr, "sale_order", "delivery_status"):
        _logger.info("Create sale_order column delivery_status")
        create_column(cr, "sale_order", "delivery_status", "varchar")
    if not column_exists(cr, "sale_order_line", "skip_sale_delivery_state"):
        _logger.info("Create sale_order_line column skip_sale_delivery_state")
        create_column(cr, "sale_order_line", "skip_sale_delivery_state", "boolean")
        cr.execute("UPDATE sale_order_line SET skip_sale_delivery_state = False")

    for col, typ in (
        ("credit_hold", "boolean"),
        ("credit_hold_reason", "varchar"),
        ("credit_hold_date", "timestamp"),
    ):
        if not column_exists(cr, "sale_order", col):
            _logger.info("Create sale_order column %s", col)
            create_column(cr, "sale_order", col, typ)


def _migrate_credit_hold_orders(env):
    """Migrate historic orders that exceed their customer's credit limit.

    We only change rows that are currently in ``state='sale'`` and whose customer
    has a ``credit_limit`` set AND whose consumed credit (open balance + order
    total) is over the limit. The migration is executed in small chunks and
    commits after each one to keep the time-window of row-level locks small.
    """
    cr = env.cr
    # The sub-query is intentionally stable/stateless so that chunked updates
    # produce the same deterministic result regardless of the chunk size.
    candidate_sql = """
        SELECT so.id
          FROM sale_order so
          JOIN res_partner p    ON p.id = so.partner_id
          JOIN res_partner pc   ON pc.id = p.commercial_partner_id
         WHERE so.state = 'sale'
           AND pc.credit_limit > 0
           AND (COALESCE(pc.debit, 0) - COALESCE(pc.credit, 0)
                + COALESCE(so.amount_total, 0)) > pc.credit_limit
    """
    cr.execute(candidate_sql)
    ids = [row[0] for row in cr.fetchall()]
    if not ids:
        _logger.info("No historical sale orders require credit hold migration")
        return

    _logger.info(
        "Credit hold migration: %d orders will be flagged as credit_hold", len(ids)
    )
    chunk_size = 500
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        cr.execute(
            """
            UPDATE sale_order
               SET state = 'credit_hold',
                   credit_hold = TRUE,
                   credit_hold_reason = 'Credit limit exceeded (migration)',
                   credit_hold_date = (now() at time zone 'UTC')
             WHERE id IN (SELECT unnest(%s::int[]))
            """,
            (chunk,),
        )
        cr.commit()  # commit after chunk to release locks early
        _logger.info(
            "Credit hold migration: chunk %d/%d done (%d rows)",
            (i // chunk_size) + 1,
            math.ceil(len(ids) / chunk_size),
            len(chunk),
        )


def post_init_hook(env):
    """Recompute stored computed fields in chunks to keep memory under control."""
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
