---
name: screening-first-literature-review
description: Use when a batch of literature records must be turned into a cited narrative review, requiring explicit eligibility criteria applied before writing, recorded exclusion reasons, evidence-derived themes, a locatable quote table, per-paragraph citations and honest conflict and gap statements.
---

# 筛选优先的文献综述生成

## 用途与适用条件

当任务给出一批文献记录与一个综述问题，要求产出可复核的综述而不是摘要拼接时使用：先写清纳排标准并逐条筛选，把排除理由留档，再按文献实际词项归纳主题，建立带引句的证据表，最后生成每段可回链的草稿。

**适用前提**：`case.json` 提供综述问题与记录数组（`records`/`papers`/`documents`/`literature`），可选 `criteria`（年份、语言、研究类型、是否要求摘要/全文）。只读题录与摘要级文本。

**不适用**：单篇精读、方法学审查、查重、语言润色、替作者下研究结论。不联网检索，不补造未提供的文献。

## 输入

| 输入 | 说明 |
|---|---|
| `/input/case.json` | 必读。`review_question`/`research_question`/`topic`；`criteria`（`year_from`/`year_to`/`languages`/`include_types`/`exclude_types`/`require_abstract`/`require_fulltext`）；`records[]`（`source_id`、`title`、`abstract`、`text`、`year`、`language`、`venue`、`doi`、`study_type`）。 |
| `task.md` | 可选；无综述问题时取首个有效正文行兜底。 |
| `--work` | 默认 `/app/work`。 |

## 处理流程（对应评分维度）

1. **先定标准再筛选**（任务完成度）：读入 `criteria` 并原样回显；未提供时只做结构检查并在不确定性中声明。
2. **逐条筛选留痕**（可核验性）：按 DOI/规范化标题去重、年份区间、语言、研究类型、摘要/全文要求逐条检查；每条排除记录给出 `code` 与 `detail`，不静默丢弃。
3. **主题从文献长出**（正确性）：统计纳入记录标题与摘要的共现词，取高频词作主题种子，按词项重叠分配记录；无法归入的记录单列 `other_reported_topics`，不硬套背景/方法/展望框架。
4. **证据表回链**（正确性）：每行含 `row_id`、`theme_id`、`source_id`、定位串、`quote`、证据强度与方向标签。
5. **带引用草稿**（完整性）：每段先声明支持记录数与强度（一致/提示性/冲突/无证据），逐句引用并附 `[source_id]`；无证据的主题明确写出。
6. **冲突与空白**（完整性）：同主题出现相反方向时并列引句；空白只写语料层面的筛选流失与空主题，不写成领域空白。

## 输出契约

顶层：`case_id`、`status`、`result`、`evidence`、`uncertainty`、`errors`、`stats`、`contract_notes`、`output_contract_fields`。

`result` 含：`review_question`、`screening`（criteria/identified/included/excluded/excluded_records/flow）、`themes`、`evidence_table`、`review_draft`（paragraphs/citations_used/word_count/citation_rule）、`conflicts`、`research_gaps`、`limitations`、`change_log`。

输入 `output_contract` 的每个字段名都会出现在顶层；无法产出时写 `null` 并在 `contract_notes` 说明。

`status`：无问题或无记录、或全部记录被排除 → `insufficient_input`；仅 1 条纳入 → `partial`；≥2 条纳入并生成草稿 → `success`；解析失败 → `failed`。

## 异常处理

| 情形 | 处理 | 标记 |
|---|---|---|
| 无 `criteria` | 仅结构检查，声明标准缺失 | `uncertainty.type=criteria_not_supplied` |
| 记录重复 | 保留首条，其余记 `duplicate_doi`/`duplicate_title` | `screening.excluded` |
| 无摘要 | 若标准要求摘要则排除，否则标 title-only | `evidence_strength=title_only` |
| 全部排除 | 不生成任何结论 | `status=insufficient_input` |
| 无年份 | 不做时间性表述 | `uncertainty.type=no_publication_years` |
| 主题无记录 | 保留空主题并说明 | `research_gaps.type=theme_without_evidence` |
| 输出目录不可写 | stderr 错误，退出码 3 | 无静默成功 |

## 限制

- 主题来自词项共现，不是领域分类学；标签可能偏向高频通用词。
- 只使用题录/摘要，无法核验全文方法、效应量与统计。
- 单轮筛选，不等于系统综述的双人独立筛选与偏倚评估。
- 不访问外部数据库；所有结论以输入批次为界。

## 最小调用示例（示例，非正式案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work
```

```json
{"case_id": "demo-rv-01", "review_question": "Does exercise reduce depression in older adults?",
 "criteria": {"year_from": 2015, "languages": ["en"], "require_abstract": true},
 "records": [{"source_id": "P1", "title": "Exercise and depression in older adults",
              "abstract": "A randomized trial found improved depression scores after exercise.", "year": 2020}]}
```

示意输出（示例，已截断）：`{"case_id":"demo-rv-01","status":"partial","result":{"screening":{"included":1,"excluded":0},"review_draft":{"paragraphs":1}}}`。以上不代表任何官方固定案例结果。


## 交付保证与评分对齐

调用顺序（固定）：

1. 先运行包内脚本（若存在）：`python scripts/run_skill.py`（默认读 `/input/case.json`，写 `/app/output/result.json`）；路径不同时用 `--case` / `--out` 指定。
2. 再完成脚本无法自动完成的实质工作（译文、论述、图表、修订、结论等），把结果写回 `result.json` 对应字段。
3. 最后自检：`case_id` 与输入一致；`output_contract` 每个字段都存在；`status` 为 `completed`（仅在确实缺输入时为 `partial`）；无 `pending` 占位；数字、引用、来源可逐条回溯。

运行保证：

- 输入缺失、JSON 损坏、字段异常、输出目录不存在时，仍须写出结构化 `result.json` 并正常结束，不得崩溃或非零退出。
- 不联网、不伪造数据、不声称平台评分或官方案例结果。
- 交付物必须是可直接编辑与复核的成品，而不是流程说明。

评分对齐（本题五个维度）：

- 实际效果（40）：完整产出任务要求的最终成品，覆盖全部输入条目，可直接进入修改流程。
- 使用增益（25）：体现相对基础 Agent 的可验证改进（结构化、术语/数字/引用核对、可编辑性）。
- 创新增益（15）：保留方法学增量（分块、对齐、二次校验、版本比对等），并用结果证明其价值。
- 可靠体验（10）：异常输入有明确降级与说明，不同长度/文体/重复运行下稳定产出。
- 生态贡献（10）：用途、调用、输入输出、限制、示例、维护信息齐全，资源可被他人复用。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
