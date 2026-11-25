# 深度研究文献综述 Skill（deep-research-evidence-review）

给定一批文献/材料，生成**可进入科研讨论的文献综述草稿**：每条论断绑定到可核验的
`locator` 与逐字 `quote`，显式保留冲突与覆盖缺口，并输出机器可读结果与对账产物。

- 仅依赖 Python 3.10+ 标准库；不联网；同一输入两次运行逐字节一致。
- 不补造文献、不把缺失证据写成领域结论。

## 1. 快速开始

在 `06_code/submission` 目录下：

```bash
python -B scripts/run_skill.py --input examples/demo-case --work /app/work --out /app/output
```

`examples/demo-case` 是合成的演示案例（3 个来源、1 组未裁决冲突、1 个子问题缺口）。
更细的说明见 `examples/quickstart.md`。

## 2. 输入契约

```text
<input>/
  case.json          # 必需；缺失或损坏时按空输入处理，仍退出 0
  task.md            # 可选；case.json 无研究问题时兜底
  materials/         # 可选；递归扫描 json/jsonl/xml/csv/tsv/txt/md/pdf
```

`case.json` 常用字段（均可缺省，工具做容错与别名匹配）：

```json
{
  "case_id": "case-001",
  "research_question": "研究问题",
  "sub_questions": [{"id": "Q1", "question": "子问题"}],
  "sources": [{"source_id": "S1", "title": "...", "abstract": "...", "doi": "...", "year": 2024}],
  "criteria": {"include": "...", "exclude": "..."},
  "output_contract": {"report": "string", "findings": "array", "status": "string"}
}
```

`output_contract` 的每个字段都会出现在 `result.json` 顶层：同名字段优先，其次别名映射
（`report`→`synthesis`、`findings`→`claims`、`references`→`sources`、`citations`→`evidence`、
`gaps`→`coverage`、`notes`→`uncertainty`）；未知字段保留为 `best_effort` 并记入
`contract_extras`，不静默丢弃。

## 3. 输出产物

| 文件 | 角色 | 内容 |
|---|---|---|
| `review_draft.md` | **交付主体** | 综述草稿正文，仅由 `synthesis.sections` 渲染 |
| `result.json` | 结构化版本 | 全部字段：来源、筛选、证据、论断、冲突、覆盖、自检、PRISMA |
| `report.md` | 运行报告 | 人类可读的表格化报告（含筛选与统计外壳） |
| `run-review.md` | 复核索引 | 逐条 claim 的 locator/quote、契约核对与复核步骤 |
| `synthesis_matrix.csv` | 对账表 | claim × 来源 × locator × 主题 × 引文 |
| `screening_log.csv` | 对账表 | 每条来源的筛选决定、准则代码与理由 |
| `prisma_flow.svg` | 流程图 | identified→duplicates→screened→excluded→included |
| `provenance.json` | 溯源 | `source_map`（来源 sha256、被引 claim）+ `claim_map`（定位与主题） |
| `validation.json` | 校验摘要 | `gates[]`、`self_check[]`、`validator_verdict` 与错误 |
| `research_report.docx` | 可编辑草稿 | 纯标准库 OOXML 生成的 Word 文档 |

## 4. `result.json` 关键字段

- `prisma`：`n_identified`、`n_duplicates`、`n_screened`、`n_excluded_by_code`、`n_included`。
- `quote_check_summary`：`checked`、`verified`、`not_found`（`not_found` 必须为 0 才算通过）。
- `boundary`：`scanned`、`ok`；扫描正文中的越界措辞（全球首创/填补空白/实验已完成/world-first 等）。
- `gates[]`：`case_contract`、`quote_integrity`、`strength_consistency`、`prisma_balance`。
- `self_check[]`：`item`、`template_value`、`match` 逐项自检。
- `validator_verdict`：`pass` / `fail`，与 `verification.all_checks_passed` 绑定。
- `uncertainty[].human_confirm`：每条不确定性都标记需人工确认。

## 5. 证据与写作口径

- 每条 claim 必须来自一条 evidence，携带 `source_id`、`locator`、逐字 `quote`。
- `quote` 必须是来源文本的精确子串；不一致即 `not_found`，判为失败。
- 支撑等级：`strong` / `moderate` / `limited` / `contested`；不得超出证据强度。
- 冲突固定 `resolution=unresolved`，双方引文并列，不选边。
- `established` 主题不得包含相反/混合证据。
- gap 子问题只能写“未检索到可定位证据，不作结论”。

## 6. 限制

- 结论范围等于输入语料范围；不验证文献真实性、撤稿状态或更新版本。
- 段落级证据摘录，不做全文方法学质量评价、偏倚评估或双人独立筛选。
- PDF 文本为启发式抽取；字符过少或编码异常时标 `low_confidence=true`。

## 7. 异常处理

所有异常路径都写出 `result.json` 并退出 0。详见 `docs/ERROR_HANDLING.md`。

## 8. 文件布局

```text
submission/
  SKILL.md
  README.md
  worklog.md
  requirements.txt
  GITHUB_URL.txt
  docs/
    ERROR_HANDLING.md
  scripts/
    run_skill.py          # 永不让 harness 崩溃的薄包装器
    sk_entry.py           # CLI、编排、契约映射、自检与写出
    sk_ingest.py          # 输入/来源/证据抽取
    sk_analyze.py         # claim/冲突/覆盖/主题/综合
    sk_render.py          # review_draft.md、report.md、run-review.md
    sk_artifacts.py       # CSV/SVG/provenance/validation/docx
  references/
    research-protocol.md
    claim-evidence-binding.md
    conflicts-and-coverage.md
  assets/
    policy.json
  examples/
    demo-case/case.json
    quickstart.md
    example-result.json
```

约束：仅标准库；无网络；确定性；无 `__pycache__`。
