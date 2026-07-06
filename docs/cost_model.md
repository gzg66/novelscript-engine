# 成本模型 · NovelScript Engine

> 关联 PRD §5.5 SCALE-07。MVP 阶段用估算公式；Full Scale 后填入实测值。

## 按阶段 Token 估算（gpt-5.4，示意）

| 阶段 | 调用次数（S1·26集） | 输入 token/次 | 输出 token/次 | 备注 |
|------|---------------------|---------------|---------------|------|
| S0_engine | 1 map-reduce ~15 chunks | ~8k | ~2k | 全书一次 |
| S1 | 2 | ~12k | ~3k | premise + bible |
| S2 | 1 | ~15k | ~4k | 全书级 |
| S3 | 1/季 | ~10k | ~6k | S1 一季 |
| S4 | 26 | ~6k | ~2k | 逐集 |
| S5 | 26 | ~8k | ~4k | 逐集 |
| Reviewer | ~30% 集次 | ~4k | ~1k | 条件触发 |
| Fidelity | 1 季 + 26 集 | ~2k | ~0.5k | 结构化输出 |

**S1 MVP 粗算**：约 1.5M–2.5M input tokens + 0.4M–0.7M output tokens（含 1 次修复循环）。

## Full Scale（~120 集）预算上限（配置项）

```yaml
budget:
  max_usd: 500          # 可配置硬上限
  warn_usd: 350
  on_exceed: throttle   # throttle | pause | best_effort_only
  checkpoint_every_n_episodes: 10
```

## 并发与成本

| workers | 相对耗时 | 相对成本 |
|---------|----------|----------|
| 4（默认）| 1.0× | 1.0× |
| 8 | ~0.55× | 1.0×（token 不变）|

超预算策略：自动降并发 → 跳过 LLM Review（保留 Checker）→ 暂停并告警。

## 实测记录（待填）

| 运行 ID | 范围 | 实际 token | 实际 USD | 耗时 | 备注 |
|---------|------|------------|----------|------|------|
| — | — | — | — | — | MVP P3 后填入 |
