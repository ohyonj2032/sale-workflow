# Copyright 2024 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models, SUPERUSER_ID
from odoo.tools import config
import logging

_logger = logging.getLogger(__name__)


class EnvironmentUtils(models.AbstractModel):
    """
    环境工具类，解决多公司环境切换和ORM缓存问题。
    提供安全的环境切换、精确的缓存失效和调试跟踪方法。
    """
    _name = 'environment.utils'
    _description = 'Environment Utilities'

    @api.model
    def safe_with_company(self, company_id, preserve_context=True):
        """
        安全的 with_company 替代方法，避免与 sudo() 链式调用导致的上下文覆盖问题。

        :param company_id: 目标公司 ID 或公司记录集
        :param preserve_context: 是否保留当前环境的 allowed_company_ids 和其他上下文
        :return: 安全切换后的环境
        """
        self.ensure_one()

        # 获取当前环境的完整上下文
        current_context = dict(self.env.context)

        # 确保 allowed_company_ids 被正确保留
        allowed_company_ids = current_context.get('allowed_company_ids', [])
        if not allowed_company_ids and hasattr(self.env.user, 'company_ids'):
            allowed_company_ids = self.env.user.company_ids.ids
        if isinstance(company_id, models.BaseModel):
            company_id = company_id.id

        # 确保目标公司在 allowed_company_ids 中
        if allowed_company_ids and company_id not in allowed_company_ids:
            allowed_company_ids = allowed_company_ids + [company_id]

        # 构建新的上下文
        new_context = current_context.copy() if preserve_context else {}
        new_context.update({
            'company_id': company_id,
            'allowed_company_ids': allowed_company_ids,
            'disable_company_context_fix': False,  # 标记允许修复生效
        })

        # 创建新的环境，直接设置公司，不通过 with_company()
        new_env = self.env(context=new_context)
        return self.with_env(new_env)

    @api.model
    def safe_sudo_with_company(self, company_id, preserve_context=True):
        """
        安全的 sudo().with_company() 替代方法。
        先切换公司，再 sudo，避免上下文被错误重置。

        :param company_id: 目标公司 ID 或公司记录集
        :param preserve_context: 是否保留当前环境的上下文
        :return: 安全切换后的 sudo 环境
        """
        # 第一步：先安全切换公司
        record_with_company = self.safe_with_company(company_id, preserve_context=preserve_context)
        # 第二步：再 sudo
        return record_with_company.sudo()

    def invalidate_cache_for_fields(self, field_names, specific_records=None):
        """
        针对特定字段和记录进行精确的缓存失效，而非全量清除。

        :param field_names: 字段名称列表
        :param specific_records: 可选，指定需要失效缓存的记录集，默认对当前记录集
        """
        records = specific_records or self
        if not records:
            return

        # 记录调试信息
        _logger.debug(
            "Invalidating cache for fields %s on records %s (ids: %s)",
            field_names, records._name, records.ids
        )

        # 1. 针对计算字段，使用 Odoo 标准的 invalidate_cache
        for record in records:
            for field_name in field_names:
                if field_name in record._fields:
                    field = record._fields[field_name]
                    if field.compute:
                        # 这是一个计算字段，使其失效
                        record.invalidate_cache([field_name])

        # 2. 对于关联字段，清除相关的预取缓存
        for field_name in field_names:
            if field_name in records._fields:
                field = records._fields[field_name]
                if field.type in ('many2one', 'one2many', 'many2many'):
                    # 关联字段，清除 prefetch 缓存
                    if hasattr(records, '_prefetch'):
                        if records._prefetch.get(records._name):
                            if field_name in records._prefetch[records._name]:
                                del records._prefetch[records._name][field_name]

        # 3. 强制刷新记录，确保后续读取是最新数据
        if hasattr(records, 'flush_recordset'):
            records.flush_recordset()
        elif hasattr(records, 'flush'):
            records.flush()

    def get_full_context_trace(self):
        """
        获取完整的上下文跟踪信息，用于调试。
        比直接打印 self.env.context 更准确，显示底层传播细节。

        :return: 包含详细上下文信息的字典
        """
        env = self.env
        return {
            'context': dict(env.context),
            'company_id': env.company.id if env.company else None,
            'company_ids': [c.id for c in env.companies] if env.companies else [],
            'user_id': env.user.id if env.user else None,
            'allowed_company_ids': env.context.get('allowed_company_ids'),
            'uid': env.uid,
            'su': env.su,
            'model_name': self._name,
            'record_ids': self.ids,
        }

    def log_context_trace(self, message="Context trace:"):
        """
        记录详细的上下文跟踪日志，用于调试。

        :param message: 日志消息前缀
        """
        trace = self.get_full_context_trace()
        _logger.info(
            "%s\n  Context: %s\n  Company: %s (Allowed: %s)\n  User: %s (SU: %s)\n  Record: %s %s",
            message,
            trace['context'],
            trace['company_id'],
            trace['allowed_company_ids'],
            trace['user_id'],
            trace['su'],
            trace['model_name'],
            trace['record_ids']
        )
