#!/usr/bin/env python3
"""Render report.md and run-review.md strictly from the result payload.

No fact is introduced here: every line is a formatting of a field that already
exists in result.json.
"""

import sys

sys.dont_write_bytecode = True


def _cell(value, limit=120):
    text = "" if value is None else str(value)
    text = text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _quote(text):
    text = "" if text is None else str(text)
    lines = text.splitlines() or [""]
    return "\n".join("> " + line for line in lines)


def _list(values):
    return "、".join(str(value) for value in values) if values else "无"


def render_report(payload):
    case_id = payload.get("case_id") or "unknown"
    status = payload.get("status") or "unknown"
    question = payload.get("question") or "（未提供研究问题）"
    sub_questions = payload.get("sub_questions") or []
    sources = payload.get("sources") or []
    screening = payload.get("screening") or []
    themes = payload.get("themes") or []
    evidence = payload.get("evidence") or []
    claims = payload.get("claims") or []
    conflicts = payload.get("conflicts") or []
    coverage = payload.get("coverage") or {}
    synthesis = payload.get("synthesis") or {}
    limitations = payload.get("limitations") or []
    uncertainty = payload.get("uncertainty") or []
    run_log = payload.get("run_log") or []
    stats = payload.get("stats") or {}

    out = []
    out.append("# 文献综述运行报告（自动生成）")
    out.append("")
    out.append("- 输入标识（case_id）：`%s`" % case_id)
    out.append("- 运行状态：`%s`" % status)
    out.append("- 研究问题：%s" % question)
    out.append("- 来源数：%d；证据行：%d；论断：%d；冲突：%d；覆盖缺口：%d" % (
        len(sources), len(evidence), len(claims), len(conflicts), len(coverage.get("gaps") or [])))
    out.append("- 筛选：纳入 %d、排除 %d；主题：%d 个" % (
        sum(1 for entry in screening if entry.get("decision") == "include"),
        sum(1 for entry in screening if entry.get("decision") == "exclude"), len(themes)))
    out.append("")
    out.append("## 1. 子问题与覆盖")
    out.append("")
    items = coverage.get("items") or []
    if items:
        out.append("| 子问题 | 覆盖状态 | 来源数 | 证据数 | 论断数 | 冲突 |")
        out.append("|---|---|---|---|---|---|")
        for item in items:
            out.append("| %s：%s | %s | %s | %s | %s | %s |" % (
                _cell(item.get("sub_question_id"), 20),
                _cell(item.get("question"), 100),
                _cell(item.get("status"), 20),
                _cell(item.get("source_count"), 10),
                _cell(item.get("evidence_count"), 10),
                _cell(item.get("claim_count"), 10),
                _cell(_list(item.get("conflict_ids")), 40)))
    else:
        out.append("未生成子问题。")
    out.append("")
    out.append("## 2. 筛选（screening）")
    out.append("")
    if screening:
        out.append("| 来源 | 轮次 | 决定 | 准则代码 | 准则来源 | 准则原文 | 核对字段 | 理由 |")
        out.append("|---|---|---|---|---|---|---|---|")
        for entry in screening:
            out.append("| %s | %s | %s | `%s` | `%s` | %s | %s | %s |" % (
                _cell(entry.get("source_id"), 20),
                _cell(entry.get("round"), 10),
                _cell(entry.get("decision"), 12),
                _cell(entry.get("criterion_code"), 40),
                _cell(entry.get("criterion_source"), 40),
                _cell(entry.get("criteria_text"), 80),
                _cell(_list(entry.get("checked_fields")), 60),
                _cell(entry.get("reason"), 160)))
    else:
        out.append("本次运行未生成筛选记录。")
    out.append("")
    out.append("## 3. 来源清单")
    out.append("")
    if sources:
        out.append("| 来源 | 标题 | 年份 | 类型 | 可靠性 | 定位前缀 | 低置信度 |")
        out.append("|---|---|---|---|---|---|---|")
        for source in sources:
            reliability = source.get("reliability") or {}
            out.append("| %s | %s | %s | %s | %s | `%s` | %s |" % (
                _cell(source.get("source_id"), 20),
                _cell(source.get("title"), 90),
                _cell(source.get("year"), 10),
                _cell(source.get("study_type"), 40),
                _cell(reliability.get("level"), 20),
                _cell(source.get("locator_prefix") or source.get("origin"), 80),
                "是" if source.get("low_confidence") else "否"))
    else:
        out.append("未读取到来源。")
    out.append("")
    out.append("## 4. 证据与论断")
    out.append("")
    if claims:
        evidence_map = {row.get("evidence_id"): row for row in evidence}
        for claim in claims:
            row = evidence_map.get(claim.get("evidence_id"), {})
            out.append("### %s（%s / %s）" % (
                claim.get("claim_id"), claim.get("sub_question_id"),
                claim.get("support_level")))
            out.append("")
            out.append("- 立场：`%s`" % claim.get("direction"))
            out.append("- 引用定位：`%s`" % claim.get("locator"))
            out.append("- 引文核验：`%s`" % ("通过" if claim.get("quote_verified") else "未通过"))
            if claim.get("conflict_ids"):
                out.append("- 关联冲突：%s" % _list(claim.get("conflict_ids")))
            out.append("- 论断：%s" % claim.get("text"))
            out.append("- 原文：")
            out.append("")
            out.append(_quote(claim.get("quote")))
            out.append("")
            if row and row.get("section"):
                out.append("- 证据段落：`%s`（section=%s，confidence=%s）" % (
                    row.get("locator"), row.get("section"), row.get("confidence")))
                out.append("")
    else:
        out.append("本次运行未生成可定位论断。")
        out.append("")
    out.append("## 5. 主题归纳（Theme induction）")
    out.append("")
    if themes:
        for theme in themes:
            out.append("### %s：%s" % (theme.get("theme_id"), theme.get("theme")))
            out.append("")
            out.append("- 定义：%s" % (theme.get("definition") or ""))
            out.append("- 成员文献：%s" % _list(theme.get("member_sources")))
            out.append("- 支撑结论：%s" % _list(theme.get("supporting_claim_ids")))
            out.append("- 证据强度：`%s`（%s）" % (
                theme.get("evidence_strength"), theme.get("strength_basis") or ""))
            out.append("- 边界：%s" % (theme.get("boundary") or ""))
            out.append("")
    else:
        out.append("本次运行未归纳出主题。")
        out.append("")
    out.append("## 6. 冲突（未裁决）")
    out.append("")
    if conflicts:
        for conflict in conflicts:
            out.append("### %s（%s）" % (conflict.get("conflict_id"),
                                        conflict.get("sub_question_id")))
            out.append("")
            out.append("- 类型：`%s`；处理：%s" % (conflict.get("type"), conflict.get("handling")))
            out.append("- 结论：`%s`" % conflict.get("resolution"))
            for position in conflict.get("positions") or []:
                out.append("- %s（%s，%s）[%s | %s]：%s" % (
                    position.get("claim_id"), position.get("source_id"),
                    position.get("stance_label"), position.get("source_id"),
                    position.get("locator"), _quote(position.get("quote")).replace("\n", " ")))
            for difference in conflict.get("factual_differences") or []:
                out.append("- 事实差异 %s：%s" % (
                    difference.get("field"),
                    " vs ".join("%s:%s" % pair for pair in (difference.get("values") or {}).items())))
            out.append("")
    else:
        out.append("未检测到相反结论的并列冲突。")
        out.append("")
    out.append("## 7. 覆盖与空白")
    out.append("")
    summary = coverage.get("summary") or {}
    out.append("子问题 %s 个：covered %s、thin %s、gap %s。" % (
        summary.get("sub_questions", 0), summary.get("covered", 0),
        summary.get("thin", 0), summary.get("gap", 0)))
    gaps = coverage.get("gaps") or []
    if gaps:
        for gap in gaps:
            out.append("- **%s**（%s）：在 %s 个来源中无定位证据；理由 `%s`。" % (
                gap.get("gap_id"), gap.get("sub_question_id"),
                gap.get("searched_sources"), gap.get("reason")))
    else:
        out.append("- 无覆盖缺口。")
    out.append("")
    out.append("## 8. 综合叙述")
    out.append("")
    for section in synthesis.get("sections") or []:
        out.append("### %s" % section.get("heading"))
        out.append("")
        out.append(section.get("text") or "")
        out.append("")
        if section.get("claim_ids"):
            out.append("- 涉及论断：%s" % _list(section.get("claim_ids")))
            out.append("")
    out.append("引用格式：%s" % (synthesis.get("citation_format") or ""))
    out.append("")
    out.append("## 9. 局限与不确定性")
    out.append("")
    if limitations:
        for item in limitations:
            out.append("- `%s`：%s" % (item.get("type"), item.get("detail")))
    else:
        out.append("- 无记录的局限。")
    out.append("")
    if uncertainty:
        for item in uncertainty:
            out.append("- 不确定性 `%s`：%s" % (item.get("type"), item.get("detail")))
    else:
        out.append("- 无记录的不确定性。")
    out.append("")
    out.append("## 10. 运行日志")
    out.append("")
    if run_log:
        for entry in run_log:
            out.append("- `%s`（%s）：%s" % (
                entry.get("step"), entry.get("status"), entry.get("detail")))
    else:
        out.append("- 无运行日志。")
    out.append("")
    out.append("## 11. 统计")
    out.append("")
    if stats:
        for key in sorted(stats.keys()):
            out.append("- `%s`: %s" % (key, stats[key]))
    else:
        out.append("- 无统计字段。")
    out.append("")
    out.append("---")
    out.append("")
    out.append("本报告仅由 `result.json` 的字段渲染，未引入 `result.json` 之外的任何事实。")
    out.append("")
    return "\n".join(out)


def render_review(payload):
    case_id = payload.get("case_id") or "unknown"
    status = payload.get("status") or "unknown"
    question = payload.get("question") or "（未提供研究问题）"
    claims = payload.get("claims") or []
    sources = payload.get("sources") or []
    conflicts = payload.get("conflicts") or []
    coverage = payload.get("coverage") or {}
    uncertainty = payload.get("uncertainty") or []
    verification = payload.get("verification") or {}
    contract = payload.get("output_contract_fields") or {}
    manifest = payload.get("input_manifest") or []
    errors = payload.get("errors") or []
    run_log = payload.get("run_log") or []

    out = []
    out.append("# 运行复核（run-review）")
    out.append("")
    out.append("本文件由本次运行的 `result.json` 渲染，供复核者逐条检查输入标识、主结果、证据定位、运行状态与不确定性。")
    out.append("")
    out.append("## 1. 输入身份")
    out.append("")
    out.append("- `case_id`：`%s`" % case_id)
    out.append("- `status`：`%s`" % status)
    out.append("- 研究问题：%s" % question)
    out.append("- 来源数：%d；证据行：%d；论断：%d" % (
        len(sources), len(payload.get("evidence") or []), len(claims)))
    out.append("")
    if manifest:
        out.append("| 输入文件 | 类型 | 字节 | SHA-256（前 16 位） | 状态 | 来源数 |")
        out.append("|---|---|---|---|---|---|")
        for item in manifest:
            out.append("| `%s` | %s | %s | `%s` | %s | %s |" % (
                _cell(item.get("path"), 80), _cell(item.get("kind"), 20),
                _cell(item.get("bytes"), 20), _cell(item.get("sha256"), 16),
                _cell(item.get("status"), 30), _cell(item.get("source_count"), 10)))
    else:
        out.append("未记录输入文件清单。")
    out.append("")
    out.append("## 2. 主结果")
    out.append("")
    for item in coverage.get("items") or []:
        out.append("- %s（%s）：来源 %s、证据 %s、论断 %s、冲突 %s" % (
            item.get("sub_question_id"), item.get("status"), item.get("source_count"),
            item.get("evidence_count"), item.get("claim_count"),
            _list(item.get("conflict_ids"))))
    if not (coverage.get("items") or []):
        out.append("- 无子问题覆盖记录。")
    screening = payload.get("screening") or []
    themes = payload.get("themes") or []
    out.append("- 筛选记录 %d 条：纳入 %d、排除 %d" % (
        len(screening),
        sum(1 for entry in screening if entry.get("decision") == "include"),
        sum(1 for entry in screening if entry.get("decision") == "exclude")))
    for entry in screening:
        out.append("  - %s（round %s）：%s / `%s`" % (
            entry.get("source_id"), entry.get("round"), entry.get("decision"),
            entry.get("criterion_code")))
    out.append("- 主题 %d 个" % len(themes))
    for theme in themes:
        out.append("  - %s：%s（成员 %s；结论 %s）" % (
            theme.get("theme_id"), theme.get("theme"),
            _list(theme.get("member_sources")), _list(theme.get("supporting_claim_ids"))))
    out.append("")
    out.append("## 3. 证据定位索引（逐条核验）")
    out.append("")
    if claims:
        out.append("| 论断 | 子问题 | 支撑等级 | 来源 | locator | 引文核验 |")
        out.append("|---|---|---|---|---|---|")
        for claim in claims:
            out.append("| %s | %s | %s | %s | `%s` | %s |" % (
                _cell(claim.get("claim_id"), 16), _cell(claim.get("sub_question_id"), 20),
                _cell(claim.get("support_level"), 20), _cell(claim.get("source_id"), 20),
                _cell(claim.get("locator"), 120),
                "通过" if claim.get("quote_verified") else "未通过"))
        out.append("")
        for claim in claims:
            out.append("### %s" % claim.get("claim_id"))
            out.append("")
            out.append("- locator：`%s`" % claim.get("locator"))
            out.append("- quote（用于逐字比对）：")
            out.append("")
            out.append(_quote(claim.get("quote")))
            out.append("")
    else:
        out.append("本次运行没有可核验的论断。")
        out.append("")
    out.append("## 4. 冲突与空白")
    out.append("")
    if conflicts:
        for conflict in conflicts:
            out.append("- `%s`（%s）：resolution=%s；positions=%s" % (
                conflict.get("conflict_id"), conflict.get("sub_question_id"),
                conflict.get("resolution"),
                _list([position.get("claim_id") for position in conflict.get("positions") or []])))
    else:
        out.append("- 无冲突记录。")
    gaps = coverage.get("gaps") or []
    if gaps:
        for gap in gaps:
            out.append("- 缺口 `%s`（%s）：%s" % (
                gap.get("gap_id"), gap.get("sub_question_id"), gap.get("reason")))
    else:
        out.append("- 无覆盖缺口记录。")
    out.append("")
    out.append("## 5. 不确定性")
    out.append("")
    if uncertainty:
        for item in uncertainty:
            out.append("- `%s`：%s" % (item.get("type"), item.get("detail")))
    else:
        out.append("- 无不确定性记录。")
    out.append("")
    out.append("## 6. 输出契约核对")
    out.append("")
    provided = contract.get("provided") or []
    present = contract.get("present") or {}
    mapping = contract.get("mapping") or {}
    if provided:
        out.append("| 契约字段 | 是否存在 | 映射到 |")
        out.append("|---|---|---|")
        for name in provided:
            out.append("| `%s` | %s | %s |" % (
                _cell(name, 60), "是" if present.get(name) else "否",
                _cell(mapping.get(name, "direct"), 60)))
    else:
        out.append("输入未提供 output_contract 字段。")
    out.append("")
    out.append("## 7. 自检结果")
    out.append("")
    for key in sorted(verification.keys()):
        if key == "checks" and isinstance(verification.get(key), dict):
            out.append("- `checks`:")
            for check_key in sorted(verification[key].keys()):
                out.append("  - `%s`: %s" % (check_key, verification[key][check_key]))
        else:
            out.append("- `%s`: %s" % (key, verification[key]))
    out.append("")
    if errors:
        out.append("### 错误记录")
        out.append("")
        for error in errors:
            out.append("- `%s` / `%s`：%s" % (
                error.get("stage"), error.get("type"), error.get("message")))
        out.append("")
    out.append("## 8. 复核步骤")
    out.append("")
    out.append("1. 核对 `case_id`、输入文件哈希与 `input_manifest`，确认复核对象是同一批输入。")
    out.append("2. 对每条 claim，用 `locator` 打开对应来源字段/页码，逐字比对 `quote`；不一致则修正或删除该 claim。")
    out.append("3. 检查 `support_level` 是否高于证据实际强度（单来源不得写成 `strong`）。")
    out.append("4. 检查 `conflicts` 是否仍为 `unresolved`，双方引文是否都保留，未被改写成单边叙事。")
    out.append("5. 检查每个 `gap` 子问题是否同时出现在 `coverage.gaps`、`limitations` 与 `uncertainty`。")
    out.append("6. 检查 `output_contract` 每个字段是否存在于 `result.json` 顶层；未知字段见 `contract_extras`。")
    out.append("7. 将复核结论写回本文件；不要引入 `result.json` 与输入材料之外的事实。")
    out.append("")
    out.append("## 9. 运行日志")
    out.append("")
    for entry in run_log:
        out.append("- `%s`（%s）：%s" % (entry.get("step"), entry.get("status"), entry.get("detail")))
    out.append("")
    out.append("---")
    out.append("")
    out.append("本文件仅由 `result.json` 渲染；如与 `result.json` 不一致，以 `result.json` 与原始输入为准。")
    out.append("")
    return "\n".join(out)
