import logging
import time

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
LOCK_TIMEOUT_SECONDS = 5


def post_init_hook(env):
    cr = env.cr

    _logger.info(
        "[sale_manual_delivery] post_init_hook: backfilling x_total_margin"
    )

    cr.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'sale_order'
              AND column_name = 'x_total_margin'
        );
    """)
    if not cr.fetchone()[0]:
        _logger.info(
            "[sale_manual_delivery] x_total_margin column does not exist, "
            "skipping backfill."
        )
        return

    cr.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM sale_order
            WHERE x_total_margin IS NULL
               OR x_total_margin = 0
        );
    """)
    needs_backfill = cr.fetchone()[0]
    if not needs_backfill:
        _logger.info(
            "[sale_manual_delivery] x_total_margin already populated, "
            "nothing to do."
        )
        return

    _logger.info(
        "[sale_manual_delivery] starting batch backfill of x_total_margin"
    )

    cr.execute("""
        SET LOCAL lock_timeout = '%s s';
    """, (LOCK_TIMEOUT_SECONDS,))

    total_updated = 0
    while True:
        batch_start = time.monotonic()

        cr.execute("""
            WITH candidates AS (
                SELECT so.id
                FROM sale_order so
                WHERE so.x_total_margin IS NULL
                   OR so.x_total_margin = 0
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            ),
            margin_calc AS (
                SELECT
                    so.id AS order_id,
                    COALESCE(
                        SUM(
                            sol.price_subtotal
                            - (sol.purchase_price * sol.product_uom_qty)
                        ),
                        0
                    ) AS total_margin
                FROM sale_order so
                INNER JOIN candidates c ON c.id = so.id
                LEFT JOIN sale_order_line sol ON sol.order_id = so.id
                GROUP BY so.id
            )
            UPDATE sale_order so
            SET x_total_margin = mc.total_margin
            FROM margin_calc mc
            WHERE so.id = mc.order_id
              AND (so.x_total_margin IS NULL OR so.x_total_margin = 0)
            RETURNING so.id;
        """, (BATCH_SIZE,))

        updated_ids = cr.fetchall()
        batch_count = len(updated_ids)
        total_updated += batch_count

        batch_elapsed = time.monotonic() - batch_start

        if batch_count > 0:
            _logger.info(
                "[sale_manual_delivery] backfilled %d rows (total: %d), "
                "batch took %.3fs",
                batch_count,
                total_updated,
                batch_elapsed,
            )

        if batch_elapsed > LOCK_TIMEOUT_SECONDS:
            _logger.error(
                "[sale_manual_delivery] CRITICAL: batch update took %.3fs, "
                "exceeding lock_timeout of %ds. Aborting to prevent "
                "deadlock / full-table lock escalation.",
                batch_elapsed,
                LOCK_TIMEOUT_SECONDS,
            )
            raise RuntimeError(
                f"x_total_margin backfill batch exceeded lock timeout: "
                f"{batch_elapsed:.3f}s > {LOCK_TIMEOUT_SECONDS}s. "
                f"Pipeline aborted."
            )

        if batch_count < BATCH_SIZE:
            break

    _logger.info(
        "[sale_manual_delivery] post_init_hook finished. "
        "Total rows backfilled: %d",
        total_updated,
    )
