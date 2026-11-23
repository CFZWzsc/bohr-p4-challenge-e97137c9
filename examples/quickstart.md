# Quickstart（演示案例）

本目录是一个**合成演示**，不是真实临床证据。它用 3 个来源展示：一条相互矛盾的结论（S1 vs S2）、一个有意保留的覆盖缺口（Q3）、以及 claim 级 locator 与逐字引文。

## 1. 运行

在 `06_code/submission` 目录下：

```bash
python scripts/run_skill.py \
  --input examples/demo-case \
  --work /app/work \
  --out /app/output
```

Windows 本地可用任意临时目录：

```powershell
python scripts/run_skill.py --input examples/demo-case --work .\tmp_work --out .\tmp_out
```

也可以只给 `result.json` 路径：

```bash
python scripts/run_skill.py --input examples/demo-case --out /app/output/result.json
```

## 2. 期望输出

演示案例的预期结构（数值以实际运行为准）：

- `status = success`
- `sources` 3 条，`evidence` 5 条，`claims` 5 条
- `conflicts` 1 组：Q1 的 S1“显著降低 HbA1c” vs S2“无显著差异”，`resolution = unresolved`
- `coverage`：Q1 covered、Q2 covered、Q3 gap
- Q3 同时出现在 `coverage.gaps`、`limitations`（`type=evidence_gap`）与 `uncertainty`
- 7 个 `output_contract` 字段全部出现在 `result.json` 顶层：
  `report`、`findings`、`references`、`citations`、`gaps`、`notes`、`status`

## 3. 输入形态

```text
<input>/
  case.json          # 必需（缺失时按空输入处理，仍退出 0）
  task.md            # 可选，case.json 无研究问题时兜底
  materials/         # 可选，json/jsonl/xml/csv/txt/md/pdf
```

`case.json` 最小字段：

```json
{
  "case_id": "case-001",
  "research_question": "研究问题",
  "sub_questions": [{"id": "Q1", "question": "子问题"}],
  "sources": [{"source_id": "S1", "title": "...", "abstract": "...", "doi": "...", "year": 2024}],
  "output_contract": {"report": "string", "findings": "array", "status": "string"}
}
```

## 4. 输出文件

| 文件 | 用途 |
|---|---|
| `result.json` | 机器可读完整结果（question、sub_questions、sources、evidence、claims、conflicts、coverage、synthesis、limitations、uncertainty、run_log） |
| `report.md` | 人类可读报告，仅由 `result.json` 渲染 |
| `run-review.md` | 逐条 claim 的 locator/quote 核验索引、契约核对与复核步骤 |

## 5. 复核演示

1. 打开 `result.json`，找到 `claims[0].locator`（形如 `case.json#/sources/0#abstract#s1`）。
2. 打开 `case.json` 的 `sources[0].abstract`，逐字比对 `claims[0].quote`。
3. 确认 Q1 的两条相反 claim 都出现在 `conflicts[0].positions`，且 `resolution` 为 `unresolved`。
4. 确认 Q3 在 `coverage.items` 中为 `gap`，并在 `coverage.gaps`、`limitations`、`uncertainty` 中都有记录。
5. 确认 `report.md` 中的 claim 编号、来源编号、冲突编号与 `result.json` 一致。

## 6. 常见问题

- **Q3 为什么是 gap？** 输入中没有任何来源报告 65 岁以上、长期（≥12 个月）或心血管结局。工具不会用“仍待研究”掩盖缺口，而是显式记录。
- **为什么 S1/S2 的冲突没有被裁决？** 工具只做证据并列与事实差异呈现；裁决需要全文方法学评价或人工判断。
- **PDF 为什么会标低置信度？** 内置解析器只做启发式文本抽取；字符过少、加密或异常字符比例高时会标 `low_confidence=true`，相关论断最多 `limited`。
