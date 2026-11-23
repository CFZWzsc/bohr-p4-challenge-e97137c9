# 研究协议（Research Protocol）

本文件说明 `scripts/sk_entry.py` 实际执行的六步流程。流程只读取输入目录中的文件，不联网、不调用模型、不使用随机数；同一输入重复运行得到同一结果（文件哈希、计数与排序均确定）。

## 1. 问题拆解（question decomposition）

1. 从 `case.json` 的 `research_question` / `review_question` / `question` / `topic` / `objective` 等字段读取研究问题；缺失时取 `task.md` 第一条有效正文行。
2. 若案例提供 `sub_questions` / `subquestions` / `questions` / `research_questions` / `decomposition`，逐条采用（保留其 `id` 与文本）。
3. 若未提供，按“直接证据 / 方法与数据 / 反面证据 / 边界与空白”四个过程维度生成子问题，并在 `uncertainty` 中标注 `sub_questions_derived=true`。这些子问题只用于检索定位，不引入领域事实。

## 2. 来源收集（source collection）

- 读取 `case.json` 中记录型数组（`records` / `papers` / `documents` / `literature` / `sources` / `items` / `corpus` 等）。
- 递归扫描输入目录内的 `json`、`jsonl`/`ndjson`、`xml`、`csv`/`tsv`、`txt`、`md`、`pdf` 材料；`case.json` 与 `task.md` 不作为材料重复计数。
- 每条来源保留标识、标题、年份、venue、DOI、类型、定位前缀与可靠性等级。可靠性按元数据打分：DOI、venue、年份、同行评审标记、研究设计；分为 `high` / `medium` / `low` / `unknown`，并把打分依据写入 `reliability.basis`。
- 按 DOI、规范化标题、全文哈希去重；重复项保留在 `sources` 并标 `duplicate_of`，但不进入证据选择。

## 3. 证据抽取（evidence extraction）

- 每条来源按字段（title / abstract / methods / results / conclusion / text 等）或文件段落切成句子级 passage，记录 `locator`、字符偏移、section、置信度。
- 跳过 references、acknowledgements、funding 等非证据段落。
- PDF 使用内置增量解析：解压 FlateDecode 流、读取 BT/ET 文本操作符、按流（近似页）截断到 20 万字符。提取字符过少、包含加密标记或不可打印字符比例过高时，`low_confidence=true`，相关论断最多为 `limited`。
- 每个子问题用词项重叠 + 逆文档频率（IDF）选择 passage：必须有“有区分度”的词项命中；仅在子问题全部为高频通用词时退回普通重叠。每子问题最多 8 条、每来源最多 2 条。

## 4. 论断绑定（claim binding）

- 每条论断只能由一条已定位 passage 生成，包含 `claim_id`、`text`、`support_level`、`locator`/`locators`、`quote`、`evidence_id`。
- `quote` 是来源文本的精确子串；生成后由 `verification.quotes_verified_substring` 逐条校验。没有 locator 或 quote 的内容不会成为论断。
- 支撑等级按 `assets/policy.json`：`strong` / `moderate` / `limited` / `contested`。没有证据的子问题不生成 `unsupported` 论断，而是进入覆盖缺口。

## 5. 冲突处理（conflict resolution）

- 对同一子问题内的非中性论断做立场判定：`supports`（改善/有效/显著）对 `refutes`（无显著差异/无效/更差）或 `mixed`。
- 两类立场同时出现时生成 `conflict`，并列保留双方 quote、locator、来源与事实性差异（年份、设计、venue 等），`resolution` 固定为 `unresolved`。
- 不选边、不平均、不把反面证据改写为“仍需研究”的套话。冲突同时进入 `synthesis`、`limitations`、`uncertainty`。

## 6. 综合与报告（synthesis）

- `synthesis.sections` 依次包含：范围、逐子问题综合、冲突、覆盖与空白、结论口径与不确定性。
- 每个实质句带 claim 级引用：`[S1 | case.json#/sources/0#abstract#s1]`。
- 结论只覆盖 `coverage.status != gap` 的子问题；gap 子问题明确写“不作结论”。
- `report.md` 与 `run-review.md` 仅由 `result.json` 字段渲染，不引入额外事实。

## 覆盖阈值

| 状态 | 条件（默认） | 含义 |
|---|---|---|
| covered | ≥2 来源且 ≥2 条证据 | 可进入综合 |
| thin | ≥1 来源且 ≥1 条证据 | 可提及但需标注证据不足 |
| gap | 0 条证据 | 不作结论，写入覆盖缺口与局限 |

阈值可在 `assets/policy.json` 的 `coverage` 中修改；修改后需重跑并保留新的 `run-review.md`。
