# 异常处理（ERROR_HANDLING）

本 Skill 的入口（`scripts/run_skill.py`）永远退出码 0，并且总是尝试写出
`result.json`、`review_draft.md`、`report.md`、`run-review.md` 与其余产物。
失败时写出**诚实的失败状态**，不伪造成功结果。

## 1. 输入层

| 情形 | 识别方式 | 处置 | 状态 |
|---|---|---|---|
| `case.json` 缺失 | 输入目录无 `case.json` | 按空输入继续；`input_manifest` 插入 `status=missing` | `insufficient_input` |
| `case.json` 非法 JSON | `json.loads` 抛 `ValueError` | 记 `errors[stage=load_case]`；无材料时 `failed` | `failed` / `partial` |
| 只有 `task.md` | `case.json` 无研究问题 | 取 `task.md` 首条有效正文作为问题 | 视来源而定 |
| 研究问题缺失 | 问题为空 | 记 `uncertainty[type=no_question]`；不作结论 | `insufficient_input` |
| 材料不可读 | 损坏 JSON/XML/CSV、二进制 PDF | 记 `errors` + `limitations[unreadable_material]`；其余来源继续 | 可降为 `partial` |
| 材料格式不支持 | 后缀不在白名单 | `input_manifest.status=other`；不进入来源 | 不影响其余 |
| PDF 文本过少/编码异常 | 字符数或异常字符比例阈值 | `low_confidence=true` + `confidence_notes`；相关 claim 最多 `limited` | 可降为 `partial` |
| 输出目录不可写 | `mkdir` / 写入失败 | 依次回退到 `--work`、当前目录；仍失败仅向 stderr 报错 | 任意 |

## 2. 筛选层

| 情形 | 处置 |
|---|---|
| 未声明 `criteria` | 不臆造标准；全部来源标 `criteria_not_declared` 并纳入，记 `criteria_not_supplied` |
| 重复记录（DOI/标题/全文指纹） | 保留首条，其余 `duplicate_of` + `included_in_evidence=false`，不重复计入 |
| 无原始结局数据 / 非实证设计 | 排除，`criterion_code=no_primary_outcome` 或 `non_empirical_design` |
| 排除项无理由 | 触发 `screening_exclusions_have_reason` 失败，`validator_verdict=fail` |

## 3. 证据与论断层

| 情形 | 处置 |
|---|---|
| 某子问题无定位证据 | `coverage.status=gap`；同时写入 `coverage.gaps`、`limitations`、`uncertainty`；不作结论 |
| `quote` 非原文精确子串 | `quote_check_summary.not_found>0`；`quote_integrity` gate 失败 |
| claim 缺 locator/quote | 不生成 claim（`claims_have_locator` / `claims_have_quote` 失败） |
| 相反结论并存 | 生成 `conflicts`，`resolution=unresolved`，双方并列；参与 claim 标 `contested` |
| 单来源写成 `strong` | `strength_consistency` 检查；`established` 主题不得含相反/混合证据 |
| 越界措辞 | `boundary.ok=false`，`validator_verdict=fail`（词表：全球首创/填补空白/实验已完成/world-first 等） |

## 4. 自检与门禁

- `self_check[]`：逐项 `item/template_value/match`。
- `gates[]`：`case_contract`、`quote_integrity`、`strength_consistency`、`prisma_balance`。
- `validator_verdict` 与 `verification.all_checks_passed` 绑定：任一检查失败即 `fail`。
- 失败不中断交付：仍写出全部产物，供复核者定位问题。

## 5. 复核者行动

1. 读 `validation.json` 的 `gates` 与 `self_check`，定位失败项。
2. 对 `quote_check_summary.not_found>0` 的 claim，按 `locator` 打开原文逐字比对，修正或删除。
3. 对 `boundary.hits`，删除越界措辞或改为“本批次证据范围内”的表述。
4. 对 `prisma` 不平衡，检查去重与排除是否漏记理由。
