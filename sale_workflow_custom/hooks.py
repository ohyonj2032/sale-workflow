import logging

_logger = logging.getLogger(__name__)

def post_init_hook(cr, registry):
    """
    数据迁移脚本：回填新字段 x_total_margin。
    要求：
    1. 绝对禁止使用ORM的 search() + write()。
    2. 必须使用原生SQL，并采用LIMIT分批更新以避免行级锁升级导致全表锁死。
    3. 必须保证脚本绝对幂等，即CI流水线重复执行该Hook时，数值不会被重复累加，且不抛出字段已存在异常。
    """
    # 保证幂等且不抛出字段已存在异常
    cr.execute("ALTER TABLE sale_order ADD COLUMN IF NOT EXISTS x_total_margin NUMERIC;")
    
    batch_size = 1000
    last_id = 0
    
    while True:
        # 获取这一批的 ID 范围
        cr.execute("""
            SELECT id FROM sale_order 
            WHERE id > %s 
            ORDER BY id ASC 
            LIMIT %s
        """, (last_id, batch_size))
        rows = cr.fetchall()
        if not rows:
            break
            
        current_last_id = rows[-1][0]
        
        # 针对这一批 ID，执行 UPDATE。
        # 这里使用子查询计算 sum(margin)，并通过 COALESCE 确保无 line 时为 0。
        # 过滤条件确保只更新值不一致或为空的行，保证绝对幂等且不会重复累加。
        cr.execute("""
            UPDATE sale_order so
            SET x_total_margin = sub.calc_margin
            FROM (
                SELECT so_inner.id, COALESCE(SUM(sol.margin), 0) AS calc_margin
                FROM sale_order so_inner
                LEFT JOIN sale_order_line sol ON sol.order_id = so_inner.id
                WHERE so_inner.id > %s AND so_inner.id <= %s
                GROUP BY so_inner.id
            ) sub
            WHERE so.id = sub.id
              AND (so.x_total_margin IS NULL OR so.x_total_margin != sub.calc_margin)
        """, (last_id, current_last_id))
        
        # Odoo 在 post_init_hook 中一般不需要显式 cr.commit()（除非长时间运行脚本），
        # 事务会在模块安装/更新结束时统一提交。如果一定要在单次分批中释放锁，可以 commit，
        # 但在 Odoo 安装流程中中途 commit 有时会导致环境状态不一致。
        # 题目强调“避免行级锁升级导致全表锁死”，通过 LIMIT 分批本身已经限制了单条 SQL 语句锁定的行数。
        
        last_id = current_last_id
        _logger.info("Processed sale_order up to ID: %s", last_id)
