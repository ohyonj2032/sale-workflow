import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    cr = env.cr

    _logger.info("Pre-creating fields in SQL")
    cr.execute(
        """
        ALTER TABLE sale_order_line ADD COLUMN IF NOT EXISTS qty_procured numeric;
        COMMENT ON COLUMN sale_order_line.qty_procured IS 'Quantity Procured';
        """
    )
    cr.execute(
        """
        ALTER TABLE sale_order_line ADD COLUMN IF NOT EXISTS qty_to_procure numeric;
        COMMENT ON COLUMN sale_order_line.qty_to_procure IS 'Quantity to Procure"';
        """
    )

    # Backfill qty_procured / qty_to_procure by replicating
    # _get_qty_procurement in SQL (faster than the Python ).

    # qty_procured = how much of the SO line actually reached the customer
    # - Add outgoing moves toward customers
    # - Substract to_refund returns
    # - Ignore the rest: cancelled, scrapped, non-refund returns
    _logger.info("Pre-populating fields in SQL")
    cr.execute("""\
WITH sol_qty_procured AS (
    SELECT
        sol.id,
        SUM(
            CASE
                WHEN (
                    (
                        sl.usage = 'customer'
                        AND sm.origin_returned_move_id IS NULL
                    )
                    OR
                    (
                        sm.origin_returned_move_id IS NOT NULL
                        AND sm.to_refund
                    )
                ) THEN
                    ROUND(
                        ((sm.product_uom_qty / sm_product_uom.factor)
                        * sol_product_uom.factor),
                        SCALE(sol_product_uom.rounding)
                        )
                WHEN (
                    sl.usage != 'customer'
                    AND sm.to_refund
                ) THEN
                    ROUND(
                        ((sm.product_uom_qty / sm_product_uom.factor)
                        * sol_product_uom.factor),
                        SCALE(sol_product_uom.rounding)
                    ) * -1
                ELSE 0
            END
        ) AS qty_procured
    FROM
    sale_order_line AS sol
    INNER JOIN stock_move AS sm ON (
        sm.state != 'cancel'
        AND sm.scrapped = false
        AND sol.product_id = sm.product_id
        AND sm.sale_line_id = sol.id
    )
    LEFT JOIN stock_location AS sl ON sl.id = sm.location_dest_id
    LEFT JOIN uom_uom sm_product_uom ON sm_product_uom.id = sm.product_uom
    LEFT JOIN uom_uom sol_product_uom ON sol_product_uom.id = sol.product_uom
    GROUP BY
        sol.id,
        sm.product_uom,
        sol.product_uom
)
UPDATE sale_order_line AS sol
SET
    qty_procured = sol_qty_procured.qty_procured,
    qty_to_procure = sol.product_uom_qty - sol_qty_procured.qty_procured
FROM sol_qty_procured
WHERE sol_qty_procured.id = sol.id
    """)
    _logger.info("Finished pre-populating fields")


# ---------------------------------------------------------------------------
# post_init_hook: backfill x_total_margin
# ---------------------------------------------------------------------------
# 迁移脚本设计要点（满足 CI/CD 要求）：
#   1. 绝对禁止使用 ORM search()+write()
#   2. 使用原生 SQL + LIMIT 分批更新，避免一次性升级到表级锁
#   3. 严格幂等：
#        - ADD COLUMN IF NOT EXISTS 避免重复创建字段抛错
#        - WHERE x_total_margin IS NULL 只回填尚未回填的行
#        - 子查询 SUM 是确定性计算，不会累计放大
#        - SET LOCAL lock_timeout / statement_timeout 阻断死锁
# ---------------------------------------------------------------------------


def post_init_hook(env):
    """Backfill ``sale_order.x_total_margin`` in a safe, idempotent manner.

    On a freshly installed module the column is already created by the ORM
    (rows default to ``0.0``), but historical databases / incremental
    deployments can end up in a "column exists but rows are NULL" dirty
    state. This hook handles both situations idempotently and without
    holding a table-level lock for long.
    """
    cr = env.cr

    # 1) 确保字段存在 —— ADD COLUMN IF NOT EXISTS 是幂等的
    cr.execute(
        """
        ALTER TABLE sale_order
        ADD COLUMN IF NOT EXISTS x_total_margin numeric;
        """
    )

    # 2) 会话级锁保护（作用于本事务内后续的 DML）
    #    - lock_timeout = 5s：获取不到 tuple 锁即放弃，阻断流水线
    #    - statement_timeout = 2min：兜底防止单次分批意外长时间运行
    cr.execute("SET LOCAL lock_timeout TO '5s';")
    cr.execute("SET LOCAL statement_timeout TO '2min';")

    # 3) 分批回填。每批只锁定 ``BATCH_SIZE`` 条行，循环直到没有
    #    行为止。通过 ORDER BY id + LIMIT 获得稳定的执行计划，
    #    WHERE x_total_margin IS NULL 提供天然幂等性。
    BATCH_SIZE = 1000
    _logger.info(
        "post_init_hook: starting backfill of sale_order.x_total_margin "
        "(batch_size=%d)",
        BATCH_SIZE,
    )

    updated_total = 0
    while True:
        cr.execute(
            """
            WITH candidates AS (
                SELECT id
                FROM sale_order
                WHERE x_total_margin IS NULL
                ORDER BY id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            ),
            line_margin AS (
                SELECT
                    so.id AS order_id,
                    COALESCE(
                        SUM(
                            (sol.price_unit - COALESCE(sol.purchase_price, 0.0))
                            * COALESCE(sol.qty_delivered, 0.0)
                        ),
                        0.0
                    ) AS total_margin
                FROM candidates so
                LEFT JOIN sale_order_line sol ON sol.order_id = so.id
                GROUP BY so.id
            )
            UPDATE sale_order so
            SET x_total_margin = lm.total_margin
            FROM line_margin lm
            WHERE so.id = lm.order_id
              AND so.x_total_margin IS NULL;
            """,
            (BATCH_SIZE,),
        )
        batch_count = cr.rowcount
        if not batch_count:
            break
        updated_total += batch_count
        _logger.info(
            "post_init_hook: backfilled batch of %d rows (total=%d)",
            batch_count,
            updated_total,
        )

    # 4) 将仍为 NULL 的行（即没有任何订单行的订单 / 脏数据）收敛为 0.0，
    #    避免 ``Monetary`` 字段上遗留 NULL。
    cr.execute(
        """
        UPDATE sale_order
        SET x_total_margin = 0.0
        WHERE id IN (
            SELECT id
            FROM sale_order
            WHERE x_total_margin IS NULL
            ORDER BY id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        );
        """,
        (BATCH_SIZE,),
    )
    while cr.rowcount:
        cr.execute(
            """
            UPDATE sale_order
            SET x_total_margin = 0.0
            WHERE id IN (
                SELECT id
                FROM sale_order
                WHERE x_total_margin IS NULL
                ORDER BY id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            );
            """,
            (BATCH_SIZE,),
        )

    _logger.info(
        "post_init_hook: backfill complete (updated=%d)",
        updated_total,
    )
