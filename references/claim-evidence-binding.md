# 论断—证据绑定规范（Claim–Evidence Binding）

## 1. 证据表字段

`result.json` 的 `evidence[]` 每行是一条可独立复核的原文段落：

| 字段 | 含义 |
|---|---|
| `evidence_id` | 全局唯一，如 `E001` |
| `source_id` | 来源标识，如 `S1` |
| `sub_question_ids` | 该证据被哪些子问题使用 |
| `section` | title / abstract / results / conclusion / text 等 |
| `locator` | 可回查定位串（见第 2 节） |
| `quote` | 来源文本的精确子串，不补写、不改写 |
| `text` | 完整 passage；`quote` 为其截断时仍保持子串关系 |
| `char_start` | 在 section 内的字符偏移 |
| `confidence` | `high` / `medium` / `low` / `title_only` |
| `terms_matched` | 与子问题命中的词项，便于复核检索逻辑 |
| `score` | 确定性相关度分数 |

## 2. locator 语法

| 来源形态 | locator 示例 | 回查方式 |
|---|---|---|
| case.json 记录字段 | `case.json#/sources/0#abstract#s1` | 打开 case.json → sources[0] → abstract 的第 1 句 |
| JSONL | `materials/records.jsonl#line=4#abstract#s2` | 第 4 行对象的 abstract 第 2 句 |
| CSV | `materials/table.csv#row=3#abstract#s1` | 第 3 条数据行的 abstract 第 1 句 |
| Markdown/TXT | `materials/notes.md#sec=2#s3` | 第 2 个小节第 3 句 |
| PDF | `materials/paper.pdf#p3#s1` | 第 3 页（流近似）第 1 句 |
| XML | `materials/records.xml#/records/record[2]#abstract#s1` | 第 2 个 record 的 abstract 第 1 句 |

`s1`、`s2` 是**该 section 内按出现顺序编号的句子**，从 1 开始。定位串既是人类可读路径，也是 `run-review.md` 中逐条核对的主键。

## 3. 论断字段

`result.json` 的 `claims[]`：

| 字段 | 要求 |
|---|---|
| `claim_id` | 唯一，如 `C001` |
| `text` | 由来源标题 + 立场标签 + 引文摘要构成，不加入引文之外的事实 |
| `sub_question_id` | 必须指向一个子问题 |
| `support_level` | `strong` / `moderate` / `limited` / `contested` |
| `direction` | `supports` / `refutes` / `mixed` / `neutral` |
| `evidence_id` | 必须存在于 `evidence[]` |
| `locator` / `locators` | 至少一个，来自对应 evidence |
| `quote` | 必须是对应 evidence 文本的精确子串 |
| `quote_verified` | 运行时计算；`true` 表示子串校验通过 |
| `conflict_ids` | 若参与冲突，列出冲突编号 |

## 4. 写作口径

- **一句实质结论 = 一条 claim**；综述段落中的每个实质句都附 `[source_id | locator]`。
- 表述强度必须与 `support_level` 一致：
  - `strong`：多来源一致；
  - `moderate`：单条高可靠来源或两条一致来源；
  - `limited`：单来源、题录级或低置信度文本；
  - `contested`：存在未裁决冲突，必须同时给出双方引文。
- 不允许出现“研究表明……”但无法回指到 claim 的句子。
- 不允许把 `gap` 子问题写成“证据有限但趋势明显”；只能写“本批次未检索到可定位证据，不作结论”。

## 5. 复核步骤

1. 打开 `result.json`，对每条 claim 取 `evidence_id`，确认 evidence 的 `locator` 与 `quote` 存在。
2. 按 locator 打开来源文件/字段，逐字比对 `quote`。
3. 检查 `support_level` 是否高于证据实际强度（尤其是单来源被写成 `strong`）。
4. 检查所有 `contested` claim 是否在 `conflicts[]` 中成对出现。
5. 在 `run-review.md` 记录每条 claim 的 `quote_verified` 结果；不通过则修正 claim 或删除，不得保留无法回链的论断。
