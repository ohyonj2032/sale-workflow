import logging

from odoo.tools.sql import column_exists, create_column

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def pre_init_hook(env):
    cr = env.cr
    _add_credit_limit_column(cr)
    _add_credit_hold_columns(cr)
    _migrate_credit_hold_orders(cr)


def _add_credit_limit_column(cr):
    if not column_exists(cr, "res_partner", "credit_limit"):
        _logger.info("Creating res_partner.credit_limit column")
        create_column(cr, "res_partner", "credit_limit", "numeric")


def _add_credit_hold_columns(cr):
    if not column_exists(cr, "sale_order", "credit_hold_released_date"):
        _logger.info("Creating sale_order.credit_hold_released_date column")
        create_column(cr, "sale_order", "credit_hold_released_date", "timestamp")
    if not column_exists(cr, "sale_order", "credit_hold_released_by"):
        _logger.info("Creating sale_order.credit_hold_released_by column")
        create_column(cr, "sale_order", "credit_hold_released_by", "int4")


def _migrate_credit_hold_orders(cr):
    if not _has_account_move_line(cr):
        _logger.info(
            "account_move_line table not available, skipping credit hold migration"
        )
        return
    _logger.info("Starting credit hold migration for historical sale orders")
    total_updated = 0
    last_id = 0
    while True:
        cr.execute(
            """
            WITH partner_credit AS (
                SELECT
                    aml.partner_id,
                    SUM(aml.balance) AS total_credit
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                WHERE aml.account_type = 'asset_receivable'
                    AND am.state = 'posted'
                    AND aml.parent_state = 'posted'
                GROUP BY aml.partner_id
            )
            SELECT so.id
            FROM sale_order so
            JOIN res_partner rp ON so.partner_id = rp.id
            JOIN partner_credit pc ON rp.id = pc.partner_id
            WHERE so.state = 'sale'
                AND so.id > %s
                AND rp.credit_limit > 0
                AND pc.total_credit > rp.credit_limit
            ORDER BY so.id
            LIMIT %s
            """,
            (last_id, BATCH_SIZE),
        )
        rows = cr.fetchall()
        if not rows:
            break
        order_ids = [r[0] for r in rows]
        last_id = order_ids[-1]
        cr.execute(
            """
            UPDATE sale_order
            SET state = 'credit_hold'
            WHERE id = ANY(%s)
            """,
            (order_ids,),
        )
        total_updated += len(order_ids)
        cr.commit()
        _logger.info(
            "Migrated %s orders to credit_hold (total: %s, last_id: %s)",
            len(order_ids),
            total_updated,
            last_id,
        )
    _logger.info("Credit hold migration completed. Total updated: %s", total_updated)


def _has_account_move_line(cr):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'account_move_line'
        )
        """
    )
    return cr.fetchone()[0]