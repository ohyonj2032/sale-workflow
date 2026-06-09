================================
Sale Multi-Company Environment Fix
================================

这个模块解决了 Odoo 16 多公司销售订单确认时的幽灵 Bug。

问题根因诊断
============

1. 环境切换上下文错误覆盖
--------------------------

**问题：** 当使用 `sudo().with_company(company)` 链式调用时，会导致当前环境中的 `allowed_company_ids` 上下文被错误地覆盖。

**根因分析：**
- Odoo 16 中，`sudo()` 方法会创建一个新的环境，重新初始化上下文，丢失原有的 `allowed_company_ids`
- 随后调用的 `with_company()` 仅设置 `company_id`，但不会正确恢复 `allowed_company_ids`
- 这导致后续代码在错误的公司上下文下执行，尤其是 `sale_stock` 模块在搜索发货类型时
- 当 `allowed_company_ids` 被错误设置后，搜索 `stock.picking.type` 会返回空记录集
- 原生逻辑在找不到发货类型时会"静默跳过"发货单生成，不报错也不回滚

**关键问题代码模式：**
.. code-block:: python

    # 错误做法
    record.sudo().with_company(company).some_method()

    # 这会导致 allowed_company_ids 被覆盖！

2. ORM 缓存幽灵问题
--------------------

**问题：** 同事务中动态修改关联字段（如产品）后，依赖该字段计算的逻辑会读取到陈旧缓存数据。

**根因分析：**
- Odoo ORM 有多层缓存机制：记录缓存、计算字段缓存、预取缓存
- 修改关联字段后，相关的计算字段和预取缓存不会自动失效
- 基于产品路线的判断等逻辑会继续使用旧数据
- 简单的 `invalidate_cache()` 是全量清除，影响性能且容易误杀

3. 正确的环境隔离实现
----------------------

**解决方案：**

**方法 1 - 先切换公司再 sudo（推荐）：**
.. code-block:: python

    from odoo import api, models

    class MyModel(models.Model):
        _inherit = 'my.model'

        def my_method(self):
            # 正确做法：先切换公司，再 sudo
            company = self.company_id
            record_with_company = self.with_company(company)
            sudo_record = record_with_company.sudo()
            sudo_record.some_method()

**方法 2 - 使用本模块提供的安全方法：**
.. code-block:: python

    # 使用本模块的 safe_sudo_with_company()
    record.safe_sudo_with_company(company_id).some_method()

    # 或者分步使用 safe_with_company()
    record.safe_with_company(company_id).sudo().some_method()

4. 调试陷阱与正确追踪方法
--------------------------

**调试陷阱：**
直接打印 `self.env.context` 会严重误导排查方向，因为：
- 显示的是当前对象的上下文副本
- 不反映底层调用栈中的实际传播路径
- ORM 方法内部可能重新创建环境而不显示

**正确的调试手段：**

1. 使用本模块提供的 `log_context_trace()` 方法：
.. code-block:: python

    record.log_context_trace("Before company switch:")
    # 执行操作...
    record.log_context_trace("After company switch:")

2. 使用 Odoo 内置的调试工具：
.. code-block:: python

    import logging
    _logger = logging.getLogger(__name__)
    _logger.info("Context: %s, Company: %s, Allowed: %s",
                 self.env.context,
                 self.env.company.id,
                 self.env.context.get('allowed_company_ids'))

3. 监控数据库查询，查看实际的 company_id 过滤条件。

安装与使用
==========

1. 将此模块放置在您的 addons 目录中
2. 在 Odoo 中安装该模块
3. 重构您的代码，使用 `safe_with_company()` 和 `safe_sudo_with_company()` 替代原有的链式调用
4. 使用 `invalidate_cache_for_fields()` 进行精确的缓存失效
5. 使用 `log_context_trace()` 进行调试

API 参考
========

safe_with_company(company_id, preserve_context=True)
    安全的 with_company 替代方法，保留 allowed_company_ids。

safe_sudo_with_company(company_id, preserve_context=True)
    安全的 sudo().with_company() 替代方法。

invalidate_cache_for_fields(field_names, specific_records=None)
    针对特定字段和记录进行精确的缓存失效。

log_context_trace(message="Context trace:")
    记录详细的上下文跟踪日志。

get_full_context_trace()
    获取完整的上下文跟踪信息。

测试用例示例
============

.. code-block:: python

    class TestSaleMultiCompanyEnvFix(TransactionCase):
        def test_safe_sudo_with_company(self):
            # 创建测试用户和公司
            company1 = self.env['res.company'].create({'name': 'Company 1'})
            company2 = self.env['res.company'].create({'name': 'Company 2'})

            # 创建销售订单
            order = self.env['sale.order'].create({
                'partner_id': self.env.user.partner_id.id,
                'company_id': company1.id,
            })

            # 使用安全方法切换公司
            result = order.safe_sudo_with_company(company2)

            # 验证 allowed_company_ids 是否正确
            self.assertIn(company1.id, result.env.context.get('allowed_company_ids', []))
            self.assertIn(company2.id, result.env.context.get('allowed_company_ids', []))
            self.assertEqual(result.env.company.id, company2.id)

        def test_cache_invalidation(self):
            # 创建销售订单和订单行
            order = self.env['sale.order'].create({...})
            line = order.order_line[0]

            # 修改产品
            new_product = self.env['product.product'].create({...})
            line.write({'product_id': new_product.id})

            # 验证缓存是否正确失效
            # ...

已知问题与限制
==============

- 本模块不使用已废弃的 `force_company` 参数
- 与标准 Odoo 16 API 完全兼容
- 建议在多公司环境中始终使用本模块提供的安全方法

贡献者
======

* Odoo Community Association (OCA)

维护者
======

本模块由 OCA 维护。

致谢
====

感谢所有为发现和分析此问题做出贡献的开发者。
