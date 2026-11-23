---
name: deep-research-evidence-review
description: "面向文献综述与深度研究的证据链工作流：把研究问题拆成子问题，逐条收集来源与段落证据，将每条论断绑定到可核验的 locator 与原文引句，显式保留冲突与覆盖缺口，并输出 result.json、report.md 与 run-review.md。适用于给定文献/材料批次的系统筛选、证据矩阵与带引用综述；不联网、不补造文献。"
---

# 深度研究文献综述 Skill

## 用途

把一批给定材料（`case.json` + `task.md` + 材料文件）转成可复核的文献综述：

- 研究问题与子问题分解；
- 多来源、段落级证据抽取；
- 每条论断绑定 `source_id`、`locator` 与逐字 `quote`；
- 来源间矛盾显式并列，不静默裁决；
- 逐子问题覆盖评估（covered / thin / gap）；
- 结构化综合叙述、局限、不确定性与运行日志；
- 输出 `result.json`、`report.md`、`run-review.md` 三个可交付物。

本 Skill 只做“给定语料内的证据整理”，不做联网检索，不补造文献，不把缺失证据写成领域结论。

## 适用条件

- 已提供研究问题（或 `task.md` 可提取问题）与至少一份材料；
- 材料形态为 `json` / `jsonl` / `ndjson` / `xml` / `csv` / `tsv` / `txt` / `md` / `pdf`；
- 需要逐条引用、证据定位、冲突保留与覆盖缺口审计；
- 需要离线、确定性、仅标准库运行的环境。

## 不适用场景

- 要求联网检索、补全外部文献、验证文献真实性或撤稿状态；
- 要求做全文方法学质量评价、偏倚风险评估、GRADE 分级或双人独立筛选；
- 输入只有研究问题、没有任何来源，却要求给出领域结论；
- 要求生成真实临床/政策建议并据此作决策；
- 要求修改或裁决互相矛盾的原始研究结论（本 Skill 只并列呈现）。

## 输入形态

```text
<input>/
  case.json          # 必需；缺失时按空输入处理，仍退出 0
  task.md            # 可选；case.json 无研究问题时兜底
  materials/         # 可选；递归读取支持的格式
```

`case.json` 常用字段（均可缺省，工具会做容错与别名匹配）：

```json
{
  "case_id": "case-001",
  "research_question": "研究问题",
  "sub_questions": [{"id": "Q1", "question": "子问题"}],
  "sources": [
    {"source_id": "S1", "title": "...", "abstract": "...", "doi": "...", "year": 2024,
     "venue": "...", "study_type": "...", "reliability": "high"}
  ],
  "criteria": {"include": "...", "exclude": "..."},
  "output_contract": {
    "report": "string", "findings": "array", "references": "array",
    "citations": "array", "gaps": "array", "notes": "array", "status": "string"
  }
}
```

材料文件会被递归读取；JSON/JSONL/CSV/XML 中的记录型条目逐条成为来源，纯文本与 Markdown 按段落/小节切分，PDF 使用内置增量文本抽取并带低置信度标记。

## 调用方式

标准运行命令（写在容器 `/skills/weekly-skill` 时）：

```bash
python /skills/weekly-skill/scripts/run_skill.py --input /input --work /app/work --out /app/output
```

本包内相对路径运行：

```bash
python scripts/run_skill.py --input /input --work /app/work --out /app/output
```

演示案例：

```bash
python scripts/run_skill.py --input examples/demo-case --work /app/work --out /app/output
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--input` | `/input` | 输入目录，或直接指向 `case.json` |
| `--work` | `/app/work` | 工作目录（只用于兜底与中间状态） |
| `--out` | `/app/output` | 输出目录，或直接指向 `result.json` |
| `--output` | 同上 | `--out` 的别名 |

脚本总是退出码 0，并总是尝试写出 `result.json`、`report.md`、`run-review.md`。即使输入为空或损坏，也会写出诚实的状态与错误记录。

## 检索与证据流程

流程固定为六步，全部离线、确定性：

1. **Question decomposition（问题拆解）**
   - 从 `case.json` 读取研究问题；缺失时取 `task.md` 第一条有效正文。
   - 优先采用案例提供的 `sub_questions`；未提供时按“核心证据 / 方法与数据 / 反面证据 / 边界与空白”生成过程性子问题，并标注 `sub_questions_derived=true`。
2. **Source collection（来源收集）**
   - 读取 case 记录与输入目录全部支持格式材料。
   - 每条来源保留 `source_id`、标题、年份、venue、DOI、类型、定位前缀与可靠性（high / medium / low / unknown），可靠性依据写入 `reliability.basis`。
   - 按 DOI、规范化标题、全文哈希去重；重复项标 `duplicate_of`，不进入证据选择。
3. **Evidence extraction（证据抽取）**
   - 按字段/小节切句，跳过 references、acknowledgements、funding 等非证据段落。
   - 每个子问题按词项重叠 + IDF 选择有区分度的 passage；每子问题最多 8 条，每来源最多 2 条。
   - PDF 为增量启发式抽取；字符过少、加密或异常字符比例高时标 `low_confidence=true`。
4. **Claim binding（论断绑定）**
   - 每条 claim 必须来自一条 evidence，携带 `locator`、`quote`、`evidence_id`。
   - `quote` 必须是来源文本的精确子串；生成后逐条做子串校验。
   - 没有 locator 或 quote 的内容不会成为 claim。
5. **Conflict resolution（冲突处理）**
   - 同一子问题内出现 supports 与 refutes/mixed 时生成 conflict。
   - 双方 quote、locator、来源与事实差异并列保留；`resolution` 固定 `unresolved`。
   - 不选边、不平均、不把反面证据改写为套话。
6. **Synthesis（综合）**
   - 章节：范围 → 逐子问题 → 冲突 → 覆盖与空白 → 结论口径与不确定性。
   - 每个实质句带 claim 级引用；gap 子问题明确“不作结论”。

## 结论口径与引用格式

**claim 级引用，不是段落级、不是文献级。** 每条论断形如：

```json
{
  "claim_id": "C001",
  "text": "[S1] 标题：支持性证据——“原文引句”",
  "support_level": "moderate",
  "direction": "supports",
  "evidence_id": "E001",
  "locator": "case.json#/sources/0#abstract#s1",
  "locators": ["case.json#/sources/0#abstract#s1"],
  "quote": "原文精确子串",
  "quote_verified": true
}
```

行内引用格式：

```text
[S1 | case.json#/sources/0#abstract#s1]
```

支撑等级：

| 等级 | 口径 |
|---|---|
| `strong` | ≥2 个独立高可靠来源在同一子问题同向一致，且无冲突 |
| `moderate` | 一条高可靠来源的精确引用，或 ≥2 条一致来源 |
| `limited` | 单来源、题录级、低置信度文本或证据较弱 |
| `contested` | 同一子问题存在未裁决冲突，双方引文必须同时出现 |

写作要求：

- 一句实质结论对应一条 claim；综述中的每个实质句都附 `[source_id | locator]`。
- 表述强度不得超过 `support_level`。
- 不允许“研究表明……”却无法回指到 claim 的句子。
- 不允许把 gap 写成“证据有限但趋势明显”；只能写“本批次未检索到可定位证据，不作结论”。

## 冲突与不确定性处理

- 冲突判定：先移除 `no significant` / `no difference` 等否定短语，再匹配正负线索，避免把“无显著差异”误判为“显著”。
- 冲突呈现：`conflicts[].positions` 并列双方 claim、quote、locator；`factual_differences` 只列元数据中确实不同的字段；`possible_explanations` 标注为 caveat，不声称已解释。
- 冲突影响：参与冲突的 claim 的 `support_level` 置为 `contested`；冲突同时进入 `synthesis`、`limitations`、`uncertainty`。
- 不确定性类型固定：`unresolved_conflict`、`evidence_gap`、`low_confidence_text`、`missing_metadata`、`duplicate_sources`、`unreadable_material`、`sub_questions_derived`、`criteria_not_supplied`、`no_sources`、`no_question`、`partial_run`、`failed_run`。
- 覆盖阈值（可在 `assets/policy.json` 调整）：covered = ≥2 来源且 ≥2 条证据；thin = ≥1 来源且 ≥1 条；gap = 0 条。

## 报告结构

`result.json` 顶层固定包含：

```text
case_id, input_id, status, question, sub_questions, sources, evidence, claims,
conflicts, coverage, synthesis, limitations, uncertainty, run_log, criteria,
method, input_manifest, verification, stats, errors, contract_extras,
output_contract_fields
```

同时逐字满足案例 `output_contract` 的每个字段：

- 直接同名字段优先；
- 别名映射：`report`/`summary` → `synthesis`；`findings` → `claims`；`references` → `sources`；`citations` → `evidence`；`gaps` → `coverage`；`notes` → `uncertainty`；`status` → `status`；
- 未知字段 best-effort 保留（`produced=false` + 说明）并记入 `contract_extras`，不静默丢弃。

`report.md` 章节：

1. 子问题与覆盖
2. 来源清单
3. 证据与论断（含逐字引文与 locator）
4. 冲突（未裁决）
5. 覆盖与空白
6. 综合叙述
7. 局限与不确定性
8. 运行日志
9. 统计

`run-review.md` 章节：

1. 输入身份（case_id、文件哈希、输入清单）
2. 主结果（逐子问题覆盖）
3. 证据定位索引（逐条 claim 的 locator、quote、核验状态）
4. 冲突与空白
5. 不确定性
6. 输出契约核对
7. 自检结果（claim 数、locator/quote 覆盖、引文子串校验、冲突未裁决、gap 三处一致性）
8. 复核步骤
9. 运行日志

`report.md` 与 `run-review.md` 只由 `result.json` 字段渲染，不引入额外事实。

## 异常处理

| 情形 | 行为 |
|---|---|
| 无来源（无 case 记录、无可读材料） | `status=insufficient_input`；`uncertainty` 记 `no_sources`；不生成 claim；仍写三个输出文件并退出 0 |
| 来源不可读（损坏 JSON/XML/CSV、二进制 PDF） | 记录 `errors` 与 `limitations.unreadable_material`；其余来源继续；`status` 可降为 `partial` |
| 来源互相矛盾 | 生成 `conflicts`，`resolution=unresolved`；双方并列，不裁决；claim 标 `contested` |
| 覆盖不足（某子问题无证据） | `coverage.status=gap`；同时写入 `coverage.gaps`、`limitations`（`evidence_gap`）、`uncertainty`；综合部分明确不作结论 |
| 研究问题缺失 | 若 `task.md` 可提取问题则使用；否则 `status=insufficient_input`，并记 `no_question` |
| `case.json` 损坏 | `status=failed`（若无可用材料）；写出结构化失败结果、错误与限制；退出 0 |
| 输出目录不可写 | 依次回退到 `--work`、当前目录；仍失败则仅向 stderr 报错并退出 0 |
| PDF 低置信度 | `low_confidence=true` + `confidence_notes`；相关 claim 最多 `limited`；记入 `uncertainty` |

状态定义：`success`（有问题、有来源、≥1 条可定位 claim）、`partial`（来源过少或低置信度占比高）、`insufficient_input`（无问题/来源/证据）、`failed`（输入损坏或流程异常）。任何状态都退出码 0。

## 自检清单

运行后必须逐项确认：

- [ ] `result.json` 可解析，`case_id`、`status` 存在；
- [ ] `output_contract` 每个字段都在顶层，未知字段在 `contract_extras`；
- [ ] 每条 claim 有 `evidence_id`、`locator`/`locators`、`quote`；
- [ ] 每条 claim 的 `quote` 是对应 evidence 文本的精确子串（`quote_verified=true`）；
- [ ] 每个非 gap 子问题至少有一条 claim；每个 gap 子问题在 `coverage.gaps`、`limitations`、`uncertainty` 三处都有记录；
- [ ] 每个 conflict 的 `resolution=unresolved`，双方 positions 都存在；
- [ ] `report.md` 中的 claim/source/conflict/gap 编号与 `result.json` 一致；
- [ ] `run-review.md` 的输入哈希、locator 索引、契约核对、自检结果完整；
- [ ] 空输入与损坏输入均退出 0，且状态诚实；
- [ ] 包内无 `__pycache__`、无网络调用、无第三方依赖。

## Agent 执行说明（必须遵守）

1. 先运行：

   ```bash
   python /skills/weekly-skill/scripts/run_skill.py --input /input --work /app/work --out /app/output
   ```

2. 读取 `/app/output/result.json`。**不要直接相信 claim 文本**；对每条 claim：
   - 取 `evidence_id`，在 `evidence[]` 中找到对应段落；
   - 用 `locator` 打开原始来源字段/页面；
   - 逐字比对 `quote` 是否为原文精确子串；
   - 若不一致：修正该 claim 或删除；**不得新增无法回链的论断**。

3. 检查 `support_level`：单来源不得写成 `strong`；存在冲突的 claim 必须是 `contested`。

4. 检查冲突：所有 `conflicts[].resolution` 必须仍为 `unresolved`；不得把双方合并成单边结论。

5. 检查 gap：`coverage.status=gap` 的子问题只能写“未检索到可定位证据，不作结论”，不得用“趋势”“仍需研究”替代。

6. 完成复核后，写出/更新 `/app/output/run-review.md`，至少包含：
   - 输入标识（`case_id`、输入文件哈希）；
   - 主结果（逐子问题覆盖与 claim 数）；
   - 每条 claim 的 `claim_id`、`locator`、`quote`、逐字核验结果；
   - 冲突与 gap 清单；
   - 运行状态与不确定性；
   - 输出契约核对；
   - 自检结果与仍需人工处理的事项。

7. `report.md` 已由 `result.json` 自动渲染。如确需补充叙述，只能使用 `result.json` 中已有的事实与引文，不得引入新来源、新数字或新结论。

8. 如果脚本因环境限制失败，仍应保留并检查它写出的失败 `result.json`、`report.md`、`run-review.md`；不得伪造成功结果。

## 文件布局

```text
submission/
  SKILL.md
  GITHUB_URL.txt
  scripts/
    run_skill.py          # 永不让 harness 崩溃的薄包装器
    sk_entry.py           # CLI 与编排、契约映射、自检、写出
    sk_ingest.py          # 输入/来源/证据抽取（含 PDF）
    sk_analyze.py         # claim/冲突/覆盖/综合/局限
    sk_render.py          # report.md 与 run-review.md 渲染
  references/
    research-protocol.md
    claim-evidence-binding.md
    conflicts-and-coverage.md
  assets/
    policy.json           # 支撑等级、覆盖阈值、可靠性权重、双语词表
  examples/
    demo-case/
      case.json
      quickstart.md
```

约束：仅 Python 标准库；不联网；确定性；≤50 个文件；单文件 ≤500KB；总计 ≤2MB；无符号链接；无 `__pycache__`。
