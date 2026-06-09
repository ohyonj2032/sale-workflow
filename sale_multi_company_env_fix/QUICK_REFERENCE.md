# 快速参考卡片

## ❌ 错误做法

```python
# 1. 链式调用会破坏上下文
record.sudo().with_company(company).do_something()

# 2. 直接打印 env.context 可能误导
print(self.env.context)

# 3. 全量缓存失效影响性能
self.invalidate_cache()
```

## ✅ 正确做法

### 环境切换
```python
# 方法 1：分步执行
record_with_company = record.with_company(company)
result = record_with_company.sudo().do_something()

# 方法 2：使用安全方法
result = record.safe_sudo_with_company(company).do_something()

# 或
result = record.safe_with_company(company).sudo().do_something()
```

### 缓存管理
```python
# 精确失效特定字段缓存
record.invalidate_cache_for_fields(['product_id', 'route_id'])
```

### 调试
```python
# 记录详细上下文信息
record.log_context_trace("My debug message")

# 获取完整跟踪信息
trace = record.get_full_context_trace()
print(f"Company: {trace['company_id']}, Allowed: {trace['allowed_company_ids']}")
```

## 核心问题根因速查

### 1. 为什么 `sudo().with_company()` 有问题？
- `sudo()` 创建新环境，重置 `allowed_company_ids`
- `with_company()` 只设置 `company_id`，不恢复 `allowed_company_ids`
- 导致 `sale_stock` 搜索发货类型时返回空，静默跳过生成

### 2. 为什么会有缓存幽灵？
- 修改关联字段不自动失效相关计算字段缓存
- 预取缓存继续返回旧数据
- 全量清除 `invalidate_cache()` 粗暴且影响性能

### 3. 为什么打印 `self.env.context` 会误导？
- 显示的是上下文副本，不反映实际传播路径
- 底层调用可能重新创建环境
- 使用 `log_context_trace()` 查看完整信息

## 检查清单

在多公司环境中修改代码前，请确认：

- [ ] 环境切换是否使用了 `safe_with_company()` 或 `safe_sudo_with_company()`？
- [ ] 修改产品等关键字段后是否调用了 `invalidate_cache_for_fields()`？
- [ ] 调试时是否使用了 `log_context_trace()` 而非直接打印 context？
- [ ] 是否遵循了"先切换公司，再 sudo"的顺序？
