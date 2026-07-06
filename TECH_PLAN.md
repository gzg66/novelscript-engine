# 技术方案 · 分季分集精编管线的稳定实现

> 目标：把 `workspace_script/` 里 S0–S5 的手工产物，变成一条**可稳定复现、可局部重跑、可审计**的自动化管线。
> 约束：沿用本项目既有栈——OpenAI SDK-only（`gpt-5.4/5.5`），最小依赖，产物 = Markdown 主 + JSON 镜像。
> 复用而非重造：`stage0_upstream.py` 已跑通的稳定性范式（Map/Reduce + 流式 + partial 原子落盘 + 缓存跳过 + 重试）直接搬。

---

## 1. 为什么需要"工作流 + Agent"，而不是一个大 prompt

单次大 prompt 让 LLM"读 131 章 → 直接吐分集剧本"必然不稳定：上下文超限、结构漂移、无法局部修、失败即全废。编剧工作本身就是**分阶段收敛 + 每阶段带质量门**的，技术实现必须同构：

- **工作流（确定性编排）**：负责阶段顺序、扇出/扇入、缓存、重试、落盘——这些不能交给模型即兴决定。
- **Agent（模型创作）**：负责每个阶段内的"写草稿 / 自检 / 修复"这类需要判断的创作动作。
- **质量门（Gate）**：夹在生成和落盘之间，把可机器判的问题（结构/覆盖/来源索引）先拦掉，再让 LLM review 判戏剧质量。

一句话：**确定性的部分用代码锁死，创作性的部分交给 Agent，两者之间用 Gate 把关。**

---

## 2. 阶段依赖图（DAG）

```
              novel.txt + stage0/{outline,characters}.md
                              │
             ┌────────────────┴────────────────┐
        S0_brief (人工/半自动)            S0_engine (LLM, 全书 map-reduce)
             └────────────────┬────────────────┘
                              ▼
        S1_premise (LLM) ──► S1_character_bible (LLM, 吃 characters.md)
                              ▼
                     S2_season_map (LLM, 全书级, 人在环拍板) ★关键结构门
                              ▼
              ┌───────────────┼───────────────┐   (按季扇出)
        S3_episode_list[s]  ...             (每季一次)
                              ▼                     (按集扇出 / pipeline)
        ┌─────────────────────────────────────────┐
        │  每集独立 pipeline (无 barrier):          │
        │  S4_beat_sheet[ep] ─► S5_script[ep]       │
        └─────────────────────────────────────────┘
                              ▼
                  交棒 museframe: content_analysis → ...
```

- **纵向严格串行**：S0→S1→S2 是全书级、逐级收敛，前一阶段是后一阶段的输入，必须串行 + 人在环。
- **S2 是关键结构门**：季断点是全局决策，**必须人工拍板**后才解锁 S3（技术上=一个"等待人工 approve"的闸门）。
- **横向可并发**：S3 各季之间、S4/S5 各集之间彼此独立 → 扇出并发（复用 stage0 的 `ThreadPoolExecutor`）。
- **每集用 pipeline 而非 barrier**：`beat_sheet[ep] → script[ep]` 是每集独立的两段链，EP01 写 script 时 EP02 还能在写 beat_sheet，不必等所有 beat_sheet 完成。

---

## 3. 核心复用：既有代码资产

| 复用项 | 来源 | 在本管线的用途 |
|---|---|---|
| `generate_text(system, user, *, stream, write_path, temperature, model)` | `src/design_assets/clients.py:31` | 唯一 LLM 原语；所有阶段的 Agent 调用都走它 |
| Map/Reduce + 并发 + 缓存跳过 + 重试范式 | `stages/stage0_upstream.py` | S0_engine 做全书扫描时直接照搬；S3-S5 扇出借其 `ThreadPoolExecutor` 结构 |
| **partial 文件 → rename 原子落盘** | `stage0_upstream.py:298-310` | 每个阶段产物落盘的统一方式（写 `.partial`，成功才 `rename`，杜绝半截文件被当成缓存）|
| **已存在且非空则 skip** | `stage0_upstream.py:294` | 局部重跑的基础：改了 S2 只重跑 S2 之后，S0/S1 命中缓存秒过 |
| `settings`（模型/路径/超时从 .env） | `src/design_assets/config.py` | 全管线配置来源，`text_model` 可切 gpt-5.4/5.5 |
| stage0 产物 `outline.md`/`characters.md` | `workspace/stage0_upstream/` | S0_engine / S1 / S2 的输入底稿 |
| museframe `script_generate` Scene 格式 | 既有管线 | S5 的输出契约（转换门的目标 schema）|

**结论**：LLM 客户端、并发、重试、原子落盘、缓存——全部已有。本管线要新写的只是**每阶段的 prompt + Gate + 编排脚本**。

---

## 4. 每个阶段的统一执行范式（Agent Loop）

对标 museframe 的"固定 stage + 自由工具"，但本项目用**最小实现**（不引入完整 AgentLoop 框架，避免重造）。每个阶段是一个函数，内部跑一个有界的"生成→自检→修复"小循环：

```
stage(ctx):
    if out.exists() and passes_gate(out):        # 缓存命中直接返回
        return out
    for attempt in 1..N:
        draft = generate_text(system=PROMPT[stage], user=render(ctx),
                              stream=True, write_path=out.partial)   # 复用 clients.py
        report = run_checker(draft)               # ① 确定性 Python 机考
        if report.hard_fail and attempt < N:
            ctx = ctx.with_feedback(report)       # 回灌确定性问题, 局部修
            continue
        review = llm_review(draft, ctx)           # ② LLM review (戏剧质量)
        if review.needs_revise and attempt < N:
            ctx = ctx.with_feedback(review); continue
        json_mirror = convert_to_json(draft)      # ③ 转换门 (S2/S3/S5 需要)
        atomic_commit(out.partial → out)          # 复用 rename 原子落盘
        return out
    commit_best_effort(out)                       # max attempts 后标记 best-effort 落盘
```

三层 Gate（越往下越贵，先便宜的拦）：

### ① 确定性 Python 机考（checker）— 免费、先跑
纯正则/结构校验，不花 token。各阶段的硬规则：

| 阶段 | checker 规则（硬失败=hard_fail）|
|---|---|
| S0_engine | 必含"核心爽点/名场面必保清单/可删支线"三节；名场面表 ≥ N 行且每行有"为什么不能压缩" |
| S1_premise | 含"一句话命题"；主角逐季蜕变表行数 == 季数 |
| S1_character_bible | 每个一线角色含"想要/不愿承认/会改变"三字段；含配角合并方案节 |
| S2_season_map | 季数 == 约定值(5)；章节区间**连续无缺口、无重叠**、并集覆盖 1..131；每季五字段齐全；每季有"下一季钩子" |
| S3_episode_list | 每集含 集号/覆盖章/核心冲突/主角的选择/集尾钩子 5 列；覆盖章节并集 == 本季区间 |
| S4_beat_sheet | 每集 4–8 个 beat；每 beat 有"戏剧功能"和"外化处理"；有集尾钩子落点 |
| S5_script | 每 Scene 含来源索引/地点时间/出场角色/场景目标/冲突阻力/情绪弧线/时长目标 + Beat 表；**来源索引必须落在本集覆盖章节范围内**；关键英文对白保留（正则查引号原文）|

> 覆盖率/连续性校验是 S2/S3 的命门——机器能 100% 判，绝不交给 LLM。这直接对应 museframe 的 `source_lines.md` 确定性编号思路。

### ② LLM review — 判机器判不了的
用 `generate_text` 起一个"审片人"角色，输出结构化裁决 `{verdict: pass|revise, issues: [...]}`。各阶段 review 焦点：

- S0_engine：抓的是"追更理由"还是"剧情摘要"？必保清单有没有误删承载人物魅力的桥段？
- S2_season_map：每季末主角是否"变成了不同的人"？季末钩子成不成立？（五条判断标准的自动化提问）
- S3/S4：每集/每 beat 有没有"钩子+一个变化"？主角选择是否比上一集更难？
- S5：每场戏有冲突/推进关系/改变信息差吗？心理是否已外化（不是旁白直说）？

### ③ 转换门 — MD → JSON 镜像
S2/S3/S5 需要下游程序消费，生成后用一次 `generate_text`（低温）把 MD 转成约定 JSON schema，转换失败即视为草稿结构不合格 → 打回。S5 的 JSON 目标 schema **对齐 museframe `script_generate` 的 Scene 结构**（这是交棒契约）。

---

## 5. 人在环（HITL）闸门

不是所有阶段都全自动。按"决策的全局性/不可逆性"分级：

| 阶段 | 模式 | 说明 |
|---|---|---|
| S0_brief | **人工为主** | 改编边界（形态/集长/尺度）本就是人的决策，脚本只做模板填充 |
| S0_engine / S1 | 自动 + 抽查 | LLM 产出，人工抽查必保清单/人物三件事 |
| **S2_season_map** | **强制人工 approve** | 季断点是全局性、影响后面所有集的决策——脚本产出后**阻塞**，等人工确认（改章节区间/季命题）再解锁 S3 |
| S3 分集清单 | 自动 + 人工微调 | 逐季产出，人工调"哪些集该合并/拆分" |
| S4/S5 | 自动 + 试播集人工验收 | EP01-03 试播集必须人工过"三成立"（主角/世界/想看下一集），通过后再批量推 |

技术实现：闸门 = 检查一个 `approved.flag` 文件是否存在。脚本跑到 S2 后写出 `S2_season_map.md` 并停；人工编辑满意后 `touch S2.approved`，重跑脚本时 S2 命中缓存、闸门放行、继续 S3。零框架成本。

---

## 6. 目录与产物布局

```
workspace_script/
  # 全书级 (S0-S2), 各一份
  S0_adaptation_brief.md
  S0_story_engine.md      (+ .json 镜像)
  S1_series_premise.md
  S1_character_bible.md   (+ .json 镜像)
  S2_season_map.md        (+ .json 镜像)   ★ 需 S2.approved
  # 逐季 (S3)
  seasons/s1/episode_list.md   (+ .json)
  seasons/s2/...
  # 逐集 (S4-S5)
  seasons/s1/ep01/beat_sheet.md
  seasons/s1/ep01/script.md    (+ script.json  ← museframe 输入契约)
  seasons/s1/ep02/...
  # 运行审计
  .runs/{stage}/{run_id}/{prompt.txt, draft.partial, checker.json, review.json, trace.jsonl}
  approved/{S2.approved, s1_pilot.approved}
```

- 权威状态在文件系统（对标 museframe"文件中心"理念），内存只做运行期加速。
- `.runs/` 保留每次生成的 prompt 审计副本、checker/review 结果、trace——失败可回放、可沉淀成评测数据。

---

## 7. 实现落点：两个候选（保持 S0 附录里的结论）

### 候选 A：落在 temp_for_design_assets（推荐先行）
- 新增 `src/design_assets/stages/` 下 `s0_engine.py / s1_premise.py / s1_bible.py / s2_season_map.py / s3_episodes.py / s4_beats.py / s5_script.py`，各暴露一个 `run(ctx)`。
- 新增一个 `script_pipeline.py` 编排器：串 S0→S2（带 approve 闸门），再扇出 S3，再对每集跑 `beat→script` pipeline。
- 复用 `clients.generate_text` / `config.settings` / stage0 的并发+重试+原子落盘 helper（可把 `_map_one`/`_reduce_stream`/`atomic commit` 提取成 `stages/_common.py` 共享）。
- **优点**：与既有 stage0 天然衔接、依赖最小、当天可跑。**代价**：Gate 是自研最小实现，审计能力弱于 museframe。

### 候选 B：落在 museframe
- 新增 AgentLoop 阶段 `season_planning`(S2) + `episode_breakdown`(S3-S5)，接在现有 `content_analysis` 之前。
- 复用其 `.runs/` workspace、checker/review/conversion gate、trace 全套框架。
- **优点**：质量门与可审计性最强、和下游 `content_analysis→script_generate→segment_storyboard` 同进程无缝。**代价**：接入成本高、跨项目。

> 建议：**先用候选 A 在 temp 打穿 Dragon's Ice 全流程验证方法论**，稳定后如需生产级审计再迁 museframe（候选 B）。

---

## 8. 稳定性要点清单（照做即稳）

1. **原子落盘**：一律 `.partial` → 成功才 `rename`，杜绝半截产物污染缓存（复用 stage0 现成逻辑）。
2. **幂等/可局部重跑**：`out.exists() and passes_gate(out)` → skip；改哪阶段只重跑其后。
3. **确定性先于智能**：覆盖率/连续性/字段齐全用 Python 机考 100% 拦，绝不指望 prompt 自觉。
4. **有界修复循环**：每阶段 max N 次（建议 3），先 `replace`/局部反馈修，结构性失败才整段 regenerate；超限走 best-effort 落盘 + 标记。
5. **上下文控制**：S0_engine 用 map-reduce 避免全书塞爆上下文；S3-S5 每次只喂"本季/本集"相关切片 + 上游摘要，不塞全书。
6. **温度分层**：创作阶段(S2-S5 draft) `temperature≈0.5`；checker 修复/JSON 转换 `≈0.2`。
7. **人在环闸门**：S2 和试播集强制 approve，flag 文件控制，避免错误结构被批量放大。
8. **交棒契约锁定**：S5 的 `script.json` schema 固定对齐 museframe Scene 结构，用转换门校验，保证下游能直接吃。

---

## 9. （可选）用编排工作流跑一次的伪脚本

若采用候选 A，编排器主干（伪代码，非最终实现）：

```python
# script_pipeline.py  (伪代码)
def main():
    ctx = load_inputs(novel="dataset/Dragon Ice.txt",
                      outline="workspace/stage0_upstream/outline.md",
                      chars="workspace/stage0_upstream/characters.md")

    run_stage("s0_engine", ctx)                    # 全书 map-reduce
    run_stage("s1_premise", ctx)
    run_stage("s1_bible", ctx)                     # 吃 characters.md

    run_stage("s2_season_map", ctx)                # 产出后阻塞
    gate("approved/S2.approved")                   # 等人工拍板

    seasons = parse_seasons("S2_season_map.json")
    with ThreadPoolExecutor(max_workers=4) as pool:        # 各季并发
        for s in seasons:
            pool.submit(run_stage, "s3_episodes", ctx.for_season(s))

    gate("approved/s1_pilot.approved")             # 先做 S1 试播集人工验收
    eps = parse_episodes("seasons/s1/episode_list.json")
    with ThreadPoolExecutor(max_workers=4) as pool:        # 各集 pipeline 并发
        for ep in eps:                             # 每集: beat → script, 无 barrier
            pool.submit(run_episode_pipeline, ctx.for_episode(ep))
```

`run_stage` / `run_episode_pipeline` 内部就是第 4 节的统一 Agent Loop 范式。所有 IO 走既有 `generate_text` 和 stage0 的原子落盘 helper。
```
