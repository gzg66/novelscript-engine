# workspace_script · 小说 → 剧本（分季分集）精编

本目录是"宏观编剧结构层"的产出，补在 AI 漫剧主干流程「全书内容分析」与「单集剧本→分镜」之间。
方法论见计划文件：`/Users/my-mini/.claude/plans/cp-idempotent-whistle.md`。

## 文档与 Schema

| 文档 | 路径 |
|------|------|
| **PRD（产品需求）** | [docs/PRD.md](docs/PRD.md) |
| 技术方案 | [TECH_PLAN.md](TECH_PLAN.md) |
| 成本模型 | [docs/cost_model.md](docs/cost_model.md) |
| Script Schema | [schemas/script.schema.v1.json](schemas/script.schema.v1.json) |
| 交棒 Schema | [schemas/museframe_scene.v1.json](schemas/museframe_scene.v1.json) |

## 六阶段与产物

| 阶段 | 产物 | 粒度 | 说明 |
|---|---|---|---|
| **S0** 改编简报 + 故事引擎 | [S0_adaptation_brief.md](S0_adaptation_brief.md) · [S0_story_engine.md](S0_story_engine.md) | 全书一次 | 定改编边界 + 冷拆解找"读者为何追更"的发动机 |
| **S1** 改编命题 + 人物圣经 | [S1_series_premise.md](S1_series_premise.md) · [S1_character_bible.md](S1_character_bible.md) | 全书一次 | 一句话定义全剧 + 人物可表演化（三件事）+ 配角合并 |
| **S2** 季图谱 | [S2_season_map.md](S2_season_map.md) | 全书一次 | 131 章重组为 5 季，每季命题/危机/选择/钩子/反派线 |
| **S3** 分集清单 | [S3_episode_list_s1.md](S3_episode_list_s1.md) | 逐季（已做 S1）| S1 切成 26 集短集，每集冲突/选择/集尾钩子 |
| **S4** 分集节拍表 | [S4_beat_sheet_ep01-03.md](S4_beat_sheet_ep01-03.md) | 逐集（已做 EP01-03）| 每集起承转合 + 信息差 + 内心戏外化 + 钩子落点 |
| **S5** 分集场次剧本 | [S5_script_ep01.md](S5_script_ep01.md) · [S5_script_ep02.md](S5_script_ep02.md) · [S5_script_ep03.md](S5_script_ep03.md) | 逐集（已做 EP01-03）| 场次级剧本，对齐 museframe Scene 格式，可拍可交棒 |

## 数据流

```
Dragon Ice.txt (131章) + stage0(outline.md/characters.md)
  → S0 → S1 → S2(季图谱) → S3(分集清单) → S4(节拍表) → S5(场次剧本)
                                                              └─→ 交棒 museframe:
                                                                  content_analysis → script_generate → segment_storyboard
```

**关键接口**：`S5_script_epNN.md` 的 Scene 格式 = museframe `script_generate` 的输入。本层与既有分镜管线不重叠、正好衔接。

## 本次完成范围（用户指定：先做1全书级，再做2试播集）

- ✅ **S0–S2 全书级产物**：改编简报、故事引擎、命题、人物圣经、5 季图谱。
- ✅ **S1 分集清单**（S3）：完整 26 集。
- ✅ **试播集 EP01–03**（S4 节拍表 + S5 场次剧本）。

## 下一步可选

1. 推 S1 剩余集（EP04–26）的节拍表与场次剧本。
2. 把 `S5_script_ep01.md` 送 museframe 做端到端交棒验证。
3. 复制方法到 S2–S5 其余四季的季内 S3–S5。
4. 为 S2/S3 补 JSON 镜像，供下游程序化消费。

## 输入底稿（复用，未改动）
- `../workspace/stage0_upstream/outline.md`（全书 logline / 起承转合 / 13 章节组 beats）
- `../workspace/stage0_upstream/characters.md`（角色库事实底稿）
- `../dataset/Dragon Ice.txt`（原著全文）
