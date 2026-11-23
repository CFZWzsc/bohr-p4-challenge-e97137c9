# 冲突、空白与不确定性（Conflicts, Gaps and Uncertainty）

## 1. 什么算冲突

同一子问题下同时出现以下两类**非中性**立场时，记为冲突：

| 立场 | 判定线索（示例，大小写不敏感） |
|---|---|
| supports | improve / improved / reduce / reduced / effective / significant / benefit / 改善 / 降低 / 有效 / 显著 / 优于 |
| refutes | no significant / not significant / no difference / no effect / ineffective / worse / 无效 / 无显著 / 无差异 / 不支持 / 恶化 |
| mixed | 同一 passage 同时包含上述两类线索 |

判定前先移除 `no significant`、`no difference` 等否定短语，避免把“无显著差异”误判为“显著”。中立描述（背景、方法、依从性）不参与冲突。

## 2. 冲突如何呈现

`conflicts[]` 每条包含：

- `conflict_id`、`sub_question_id`、`type`（默认 `opposing_conclusions`）；
- `positions[]`：claim_id、source_id、stance、quote、locator；
- `factual_differences`：来源之间可核对的事实差异（年份、研究设计、venue、样本量、时长等），只在元数据确实不同时列出；
- `possible_explanations`：标注为 `caveat`，只说明“设计/人群/剂量/测量差异可能解释分歧”，不声称已解释；
- `handling`：并列保留，不选边；
- `resolution`：固定 `unresolved`。

参与冲突的 claim 的 `support_level` 设为 `contested`。冲突同时写入 `synthesis` 的“分歧与冲突”节、`limitations` 与 `uncertainty`。

## 3. 覆盖状态

| 状态 | 条件 | 写作规则 |
|---|---|---|
| `covered` | ≥2 来源且 ≥2 条证据 | 可综合，但须逐条引用 |
| `thin` | ≥1 来源且 ≥1 条证据 | 可提及，必须写明“单来源/证据有限” |
| `gap` | 0 条证据 | 不作结论，写入 `coverage.gaps`、`limitations`、`uncertainty` |

`coverage.items[]` 每个子问题一条，含 `source_count`、`evidence_count`、`claim_count`、`conflict_ids`、`gaps`。`coverage.summary` 给出 covered/thin/gap 计数。`coverage.gaps[]` 是可直接引用的缺口清单。

## 4. 空白的写法

空白必须落到具体证据缺口，不能写“未来仍需更多研究”就结束。允许的写法：

> Q3（65 岁以上老年患者的长期心血管结局）在本次输入的 3 个来源中未检索到可定位证据；覆盖状态为 gap，因此不对该问题作结论。该缺口已列入 `coverage.gaps` 与 `limitations`。

不允许的写法：

> 虽然证据有限，但趋势表明间歇性禁食对老年患者有益。

后者把 gap 当作弱证据，越过证据范围扩展结论。

## 5. 不确定性类型

`uncertainty[]` 使用固定 `type`，便于机器复核：

| type | 触发条件 |
|---|---|
| `unresolved_conflict` | 存在未裁决冲突 |
| `evidence_gap` | 某子问题无定位证据 |
| `low_confidence_text` | PDF 提取字符过少或含异常字符 |
| `missing_metadata` | 来源缺 DOI/年份/venue 等 |
| `duplicate_sources` | 检测到重复来源 |
| `unreadable_material` | 文件无法读取或解析 |
| `sub_questions_derived` | 案例未提供子问题，由流程生成 |
| `criteria_not_supplied` | 案例未提供纳排/范围标准 |
| `no_sources` / `no_question` | 输入缺失 |
| `partial_run` / `failed_run` | 状态降级原因 |

## 6. 运行状态

| status | 含义 |
|---|---|
| `success` | 有问题、有来源、至少一条可定位 claim；缺口与冲突照常报告 |
| `partial` | 有部分可定位证据，但来源过少、低置信度文本占比高或问题缺失 |
| `insufficient_input` | 没有可用的研究问题、来源或证据 |
| `failed` | 输入损坏或流程异常；仍会写出结构化的 `result.json`、`report.md`、`run-review.md` |

任何状态都退出码 0（除非输出目录完全不可写，此时仅向 stderr 报错），不伪造成功。
