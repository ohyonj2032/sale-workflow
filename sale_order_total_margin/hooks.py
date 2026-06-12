import logging

_logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def _x_total_margin_column_exists(cr):
    cr.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
            AND table_name = 'sale_order'
            AND column_name = 'x_total_margin'
        """
    )
    return bool(cr.fetchone())


def post_init_hook(env):
    cr = env.cr
    if not _x_total_margin_column_exists(cr):
        _logger.info(
            "Skip x_total_margin backfill because sale_order.x_total_margin is missing"
        )
        return

    updated_rows = 0
    while True:
        cr.execute("SET LOCAL lock_timeout = '5s'")
        cr.execute(
            """
            WITH batch AS (
                SELECT id
                FROM sale_order
                WHERE x_total_margin IS NULL
                ORDER BY id
                LIMIT %s
            ),
            updated_margin AS (
                SELECT
                    so.id,
                    COALESCE(
                        SUM(
                            CASE
                                WHEN sol.display_type IS NULL THEN
                                    sol.price_subtotal
                                    - (
                                        sol.product_uom_qty
                                        * COALESCE(pt.standard_price, 0)
                                    )
                                ELSE 0
                            END
                        ),
                        0
                    ) AS updated_total
                FROM sale_order AS so
                JOIN batch ON batch.id = so.id
                LEFT JOIN sale_order_line AS sol ON sol.order_id = so.id
                LEFT JOIN product_product AS pp ON pp.id = sol.product_id
                LEFT JOIN product_template AS pt ON pt.id = pp.product_tmpl_id
                GROUP BY so.id
            )
            UPDATE sale_order AS so
            SET x_total_margin = updated_margin.updated_total
            FROM updated_margin
            WHERE so.id = updated_margin.id
            """,
            (BATCH_SIZE,),
        )
        if cr.rowcount <= 0:
            break
        updated_rows += cr.rowcount

    _logger.info("Backfilled x_total_margin for %s sale orders", updated_rows)
