#!/usr/bin/env python3
"""Claim binding, conflict detection, coverage assessment and synthesis.

All outputs are derived mechanically from located evidence rows. No claim is
created without an evidence row, a locator and an exact quoted span.
"""

import sys

sys.dont_write_bytecode = True

from collections import Counter

STANCE_LABEL = {
    "supports": "支持性证据",
    "refutes": "相反或无差异证据",
    "mixed": "混合证据",
    "neutral": "背景或方法信息",
}
FACT_FIELDS = ("year", "study_type", "venue", "population", "sample_size", "duration", "language")


def _short(text, limit):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _citation(source_id, locator):
    return "[%s | %s]" % (source_id, locator)


def build_claims(evidence, pairs, sources, sub_questions, policy):
    source_map = {source["source_id"]: source for source in sources}
    evidence_map = {row["evidence_id"]: row for row in evidence}
    subq_map = {item["sub_question_id"]: item for item in sub_questions}
    max_claims = int(policy.get("evidence", {}).get("max_claims", 120) or 120)
    claims = []
    for pair in pairs:
        if len(claims) >= max_claims:
            break
        row = evidence_map.get(pair["evidence_id"])
        source = source_map.get(pair["source_id"])
        subq = subq_map.get(pair["sub_question_id"])
        if not row or not source or not subq:
            continue
        stance = row.get("stance") or "neutral"
        title = _short(source.get("title") or source["source_id"], 70)
        quote_short = _short(row["quote"], 220)
        text = "[%s] %s：%s——“%s”" % (
            source["source_id"], title, STANCE_LABEL.get(stance, "相关信息"), quote_short)
        claims.append({
            "claim_id": "C%03d" % (len(claims) + 1),
            "text": text,
            "sub_question_id": subq["sub_question_id"],
            "support_level": "limited",
            "direction": stance,
            "evidence_id": row["evidence_id"],
            "source_id": source["source_id"],
            "locator": row["locator"],
            "locators": [row["locator"]],
            "quote": row["quote"],
            "quote_verified": row["quote"] in (row.get("text") or ""),
            "evidence_confidence": row.get("confidence", "high"),
            "conflict_ids": [],
        })
    conflicts = detect_conflicts(claims, source_map, subq_map)
    conflict_members = {}
    for conflict in conflicts:
        for position in conflict["positions"]:
            conflict_members.setdefault(position["claim_id"], []).append(conflict["conflict_id"])
    for claim in claims:
        claim["conflict_ids"] = conflict_members.get(claim["claim_id"], [])
    assign_support_levels(claims, conflict_members, source_map, sub_questions)
    return claims, conflicts


def detect_conflicts(claims, source_map, subq_map):
    by_subq = {}
    for claim in claims:
        by_subq.setdefault(claim["sub_question_id"], []).append(claim)
    conflicts = []
    for subq in subq_map.values():
        subq_id = subq["sub_question_id"]
        group = by_subq.get(subq_id, [])
        stances = {claim["direction"] for claim in group}
        if "supports" not in stances or not ({"refutes", "mixed"} & stances):
            continue
        relevant = [claim for claim in group if claim["direction"] in {"supports", "refutes", "mixed"}]
        if len(relevant) < 2:
            continue
        involved_ids = sorted({claim["source_id"] for claim in relevant})
        differences = factual_differences(involved_ids, source_map)
        positions = []
        for claim in relevant[:6]:
            positions.append({
                "claim_id": claim["claim_id"],
                "source_id": claim["source_id"],
                "stance": claim["direction"],
                "stance_label": STANCE_LABEL.get(claim["direction"], claim["direction"]),
                "quote": claim["quote"],
                "locator": claim["locator"],
            })
        conflict = {
            "conflict_id": "CF%02d" % (len(conflicts) + 1),
            "sub_question_id": subq_id,
            "question": subq["question"],
            "type": "opposing_conclusions",
            "positions": positions,
            "factual_differences": differences,
            "possible_explanations": [{
                "basis": "metadata_and_method_caveat",
                "caveat": True,
                "text": "设计、人群、干预时长或结局测量的差异可能解释分歧；本运行不裁决，也不据此选择一方。",
            }],
            "handling": "并列保留双方证据与定位，不选边、不合并、不平均；需人工或全文方法学评价才能裁决。",
            "resolution": "unresolved",
            "unresolved": True,
        }
        conflicts.append(conflict)
    return conflicts


def factual_differences(source_ids, source_map):
    differences = []
    for field in FACT_FIELDS:
        values = {}
        for source_id in source_ids:
            source = source_map.get(source_id, {})
            value = source.get(field)
            if value in (None, "", [], {}):
                value = (source.get("meta") or {}).get(field)
            if value not in (None, "", [], {}):
                values[source_id] = str(value)
        if len(set(values.values())) > 1:
            differences.append({"field": field, "values": values})
    return differences


def assign_support_levels(claims, conflict_members, source_map, sub_questions):
    subq_order = [item["sub_question_id"] for item in sub_questions]
    for claim in claims:
        if claim["claim_id"] in conflict_members:
            claim["support_level"] = "contested"
            continue
        source = source_map.get(claim["source_id"], {})
        reliability = (source.get("reliability") or {}).get("level", "unknown")
        confidence = claim.get("evidence_confidence", "high")
        if confidence in {"low", "title_only"} or reliability in {"low", "unknown"}:
            claim["support_level"] = "limited"
            continue
        if reliability == "high" and confidence == "high" and len(claim["quote"]) >= 60:
            claim["support_level"] = "moderate"
        else:
            claim["support_level"] = "limited"
    # Convergence can raise claims to strong when >=2 high-reliability sources
    # in the same sub-question share the same non-neutral direction and no
    # conflict is present.
    for subq_id in subq_order:
        group = [claim for claim in claims if claim["sub_question_id"] == subq_id]
        if any(claim["claim_id"] in conflict_members for claim in group):
            continue
        for direction in ("supports", "refutes"):
            same = [claim for claim in group if claim["direction"] == direction]
            sources = {claim["source_id"] for claim in same
                       if (source_map.get(claim["source_id"], {}).get("reliability") or {}).get("level") == "high"}
            if len(sources) >= 2:
                for claim in same:
                    if claim["source_id"] in sources:
                        claim["support_level"] = "strong"


def build_coverage(sub_questions, evidence, claims, conflicts, sources, policy):
    settings = policy.get("coverage", {})
    covered = settings.get("covered", {}) or {}
    thin = settings.get("thin", {}) or {}
    min_sources_covered = int(covered.get("min_sources", 2) or 2)
    min_evidence_covered = int(covered.get("min_evidence", 2) or 2)
    min_sources_thin = int(thin.get("min_sources", 1) or 1)
    min_evidence_thin = int(thin.get("min_evidence", 1) or 1)
    source_total = len([source for source in sources if source.get("included_in_evidence", True)])
    evidence_by_subq = {}
    for row in evidence:
        for subq_id in row.get("sub_question_ids", []):
            evidence_by_subq.setdefault(subq_id, []).append(row)
    claims_by_subq = {}
    for claim in claims:
        claims_by_subq.setdefault(claim["sub_question_id"], []).append(claim)
    conflicts_by_subq = {}
    for conflict in conflicts:
        conflicts_by_subq.setdefault(conflict["sub_question_id"], []).append(conflict["conflict_id"])
    items = []
    gaps = []
    for subq in sub_questions:
        subq_id = subq["sub_question_id"]
        ev = evidence_by_subq.get(subq_id, [])
        cl = claims_by_subq.get(subq_id, [])
        subs = {row["source_id"] for row in ev}
        if not ev:
            status = "gap"
        elif len(subs) >= min_sources_covered and len(ev) >= min_evidence_covered:
            status = "covered"
        elif len(subs) >= min_sources_thin and len(ev) >= min_evidence_thin:
            status = "thin"
        else:
            status = "gap"
        missing = []
        if status == "gap":
            missing.append("locatable evidence for this sub-question")
        elif status == "thin":
            missing.append("independent corroboration (>=%d sources and >=%d evidence rows)" %
                           (min_sources_covered, min_evidence_covered))
        item = {
            "sub_question_id": subq_id,
            "question": subq["question"],
            "status": status,
            "source_count": len(subs),
            "evidence_count": len(ev),
            "claim_count": len(cl),
            "source_ids": sorted(subs),
            "conflict_ids": conflicts_by_subq.get(subq_id, []),
            "missing": missing,
            "support_levels": dict(Counter(claim["support_level"] for claim in cl)),
        }
        items.append(item)
        if status == "gap":
            gaps.append({
                "gap_id": "G%02d" % (len(gaps) + 1),
                "sub_question_id": subq_id,
                "question": subq["question"],
                "reason": "no_located_evidence",
                "searched_sources": source_total,
                "evidence_count": 0,
            })
    summary = {
        "sub_questions": len(sub_questions),
        "covered": sum(1 for item in items if item["status"] == "covered"),
        "thin": sum(1 for item in items if item["status"] == "thin"),
        "gap": sum(1 for item in items if item["status"] == "gap"),
        "sources": source_total,
        "evidence_rows": len(evidence),
        "claims": len(claims),
    }
    return {
        "items": items,
        "gaps": gaps,
        "summary": summary,
        "thresholds": {
            "covered_min_sources": min_sources_covered,
            "covered_min_evidence": min_evidence_covered,
            "thin_min_sources": min_sources_thin,
            "thin_min_evidence": min_evidence_thin,
        },
    }


def build_synthesis(question, sub_questions, evidence, claims, conflicts, coverage,
                    sources, uncertainty, status):
    sections = []
    source_ids = [source["source_id"] for source in sources
                  if source.get("included_in_evidence", True)]
    sections.append({
        "section_id": "scope",
        "heading": "研究问题与证据范围",
        "text": ("本报告回答：“%s”。输入包含 %d 个来源（进入证据选择 %d 个）、%d 个子问题。"
                 "所有结论仅以本批次可定位证据为界，不联网补充，也不超出材料作领域级推断。") % (
                     question or "（未提供研究问题）", len(sources), len(source_ids),
                     len(sub_questions)),
        "claim_ids": [],
        "citations": sorted(set(_citation(source["source_id"],
                                          source.get("locator_prefix", source.get("origin", "source")))
                                for source in sources if source.get("included_in_evidence", True))),
        "support_level": "context",
        "caveats": ["结论范围等于输入语料范围。"],
    })
    evidence_map = {row["evidence_id"]: row for row in evidence}
    claims_by_subq = {}
    for claim in claims:
        claims_by_subq.setdefault(claim["sub_question_id"], []).append(claim)
    coverage_map = {item["sub_question_id"]: item for item in coverage.get("items", [])}
    for subq in sub_questions:
        subq_id = subq["sub_question_id"]
        group = claims_by_subq.get(subq_id, [])
        item = coverage_map.get(subq_id, {})
        if not group:
            text = ("针对 %s（%s），在本批次 %d 个来源中未检索到可定位证据，覆盖状态为 gap。"
                    "本运行不对该子问题作结论；该缺口已列入 coverage.gaps、limitations 与 uncertainty。") % (
                        subq_id, subq["question"], len(sources))
            sections.append({
                "section_id": "subq_%s" % subq_id,
                "heading": "%s（gap）" % subq_id,
                "text": text,
                "claim_ids": [],
                "citations": [],
                "support_level": "unsupported",
                "caveats": ["gap：不跨越证据范围扩展结论。"],
            })
            continue
        sentences = []
        for claim in group:
            row = evidence_map.get(claim["evidence_id"], {})
            locator = claim.get("locator") or row.get("locator", "")
            sentences.append("%s %s（%s；support=%s）" % (
                claim["text"], _citation(claim["source_id"], locator),
                claim["claim_id"], claim["support_level"]))
        if item.get("conflict_ids"):
            sentences.append("该子问题存在未裁决分歧（%s），双方证据并列保留，本运行不选边。" %
                             "、".join(item["conflict_ids"]))
        level = "contested" if item.get("conflict_ids") else (
            "moderate" if item.get("status") == "covered" else "limited")
        sections.append({
            "section_id": "subq_%s" % subq_id,
            "heading": "%s：%s" % (subq_id, item.get("status", "thin")),
            "text": "针对 %s（%s）：%s" % (subq_id, subq["question"], " ".join(sentences)),
            "claim_ids": [claim["claim_id"] for claim in group],
            "citations": ["%s | %s" % (claim["source_id"], claim.get("locator", "")) for claim in group],
            "support_level": level,
            "caveats": (["conflict_unresolved"] if item.get("conflict_ids") else []),
        })
    conflict_sentences = []
    conflict_claims = []
    conflict_citations = []
    for conflict in conflicts:
        parts = []
        for position in conflict["positions"]:
            parts.append("%s（%s）报告%s：“%s” %s" % (
                position["source_id"], position["claim_id"],
                position["stance_label"], position["quote"],
                _citation(position["source_id"], position["locator"])))
            conflict_claims.append(position["claim_id"])
            conflict_citations.append("%s | %s" % (position["source_id"], position["locator"]))
        difference_text = ""
        if conflict.get("factual_differences"):
            difference_text = " 可核对的事实差异：" + "；".join(
                "%s=%s" % (entry["field"], " vs ".join("%s:%s" % pair for pair in entry["values"].items()))
                for entry in conflict["factual_differences"]) + "。"
        conflict_sentences.append("%s（%s）：%s。%s处理：%s" % (
            conflict["conflict_id"], conflict["sub_question_id"], "；".join(parts),
            difference_text, conflict["handling"]))
    if conflict_sentences:
        sections.append({
            "section_id": "conflicts",
            "heading": "分歧与冲突（未裁决）",
            "text": " ".join(conflict_sentences),
            "claim_ids": sorted(set(conflict_claims)),
            "citations": sorted(set(conflict_citations)),
            "support_level": "contested",
            "caveats": ["未裁决：不选边、不平均、不把反面证据改写为套话。"],
        })
    gap_text = ("本次输入共 %d 个子问题：covered %d、thin %d、gap %d。") % (
        coverage["summary"]["sub_questions"], coverage["summary"]["covered"],
        coverage["summary"]["thin"], coverage["summary"]["gap"])
    if coverage.get("gaps"):
        gap_text += " 缺口：" + "；".join(
            "%s（%s）在 %d 个来源中无定位证据" % (
                gap["sub_question_id"], _short(gap["question"], 80), gap["searched_sources"])
            for gap in coverage["gaps"]) + "。"
    sections.append({
        "section_id": "coverage",
        "heading": "覆盖与空白",
        "text": gap_text,
        "claim_ids": [],
        "citations": [],
        "support_level": "context",
        "caveats": ["空白按具体证据缺口呈现，不使用泛化套话。"],
    })
    uncertainty_types = sorted({entry.get("type", "") for entry in uncertainty if entry.get("type")})
    conclusion = ("运行状态为 %s。可作有限综合的子问题：" % status)
    covered_ids = [item["sub_question_id"] for item in coverage.get("items", [])
                   if item["status"] in {"covered", "thin"}]
    if covered_ids:
        conclusion += "、".join(covered_ids) + "；其余子问题不作结论。"
    else:
        conclusion += "无（所有子问题均无足够定位证据）。"
    conclusion += " 不确定性类型：" + ("、".join(uncertainty_types) if uncertainty_types else "无") + "。"
    sections.append({
        "section_id": "conclusion",
        "heading": "结论口径与不确定性",
        "text": conclusion,
        "claim_ids": [],
        "citations": [],
        "support_level": "context",
        "caveats": ["结论不得超出 covered/thin 子问题与已定位证据。"],
    })
    narrative = "\n\n".join("## %s\n%s" % (section["heading"], section["text"]) for section in sections)
    return {
        "sections": sections,
        "narrative": narrative,
        "citation_format": "[source_id | locator]，例如 [S1 | case.json#/sources/0#abstract#s1]",
        "claim_level": True,
        "status_note": "synthesis 由 claims/evidence/coverage 机械生成，未引入 result.json 之外的字段。",
    }


def build_limitations(question, sources, evidence, conflicts, coverage, duplicates,
                      unreadable, derived, criteria_declared, status, low_confidence_sources):
    limitations = []
    limitations.append({
        "type": "corpus_bounded",
        "detail": "所有结论仅基于输入材料，未联网检索；结论范围等于本批次语料范围。",
    })
    limitations.append({
        "type": "passage_level_evidence",
        "detail": "证据为段落级摘录与引用，未做全文方法学质量评价、偏倚评估或双人独立筛选。",
    })
    limitations.append({
        "type": "no_network",
        "detail": "运行环境无网络访问，不能验证文献是否真实存在、是否被撤稿或是否有更新版本。",
    })
    for gap in coverage.get("gaps", []):
        limitations.append({
            "type": "evidence_gap",
            "sub_question_id": gap["sub_question_id"],
            "detail": "子问题 %s（%s）在 %d 个来源中未检索到可定位证据，覆盖状态为 gap，未作结论。" % (
                gap["sub_question_id"], _short(gap["question"], 100), gap["searched_sources"]),
        })
    if conflicts:
        limitations.append({
            "type": "unresolved_conflict",
            "detail": "%d 组冲突未裁决；双方证据与定位已并列保留，需人工或全文方法学评价。" % len(conflicts),
        })
    if low_confidence_sources:
        limitations.append({
            "type": "low_confidence_text",
            "detail": "%d 个来源的文本提取置信度低（如 PDF 字符过少或编码异常），相关论断最多为 limited。" %
                      len(low_confidence_sources),
        })
    if duplicates:
        limitations.append({
            "type": "duplicate_sources",
            "detail": "检测到 %d 个重复来源；已保留首条并标记 duplicate_of，未进入证据选择。" % len(duplicates),
        })
    if unreadable:
        limitations.append({
            "type": "unreadable_material",
            "detail": "%d 个材料无法读取或解析；已在 errors/input_manifest 中记录，未静默跳过。" % len(unreadable),
        })
    if derived:
        limitations.append({
            "type": "sub_questions_derived",
            "detail": "案例未提供子问题，流程按过程维度生成；子问题只用于检索定位，不构成领域判断。",
        })
    if not criteria_declared:
        limitations.append({
            "type": "criteria_not_supplied",
            "detail": "案例未提供纳排或范围标准；本次按输入批次全量定位证据，未做外部筛选。",
        })
    if status in {"partial", "insufficient_input", "failed"}:
        limitations.append({
            "type": "partial_result",
            "detail": "运行状态为 %s；结果只覆盖已成功读取并定位的部分，不能视为完整综述。" % status,
        })
    return limitations


def build_uncertainty(question, sources, conflicts, coverage, duplicates, unreadable,
                      derived, criteria_declared, low_confidence_sources, status):
    uncertainty = []
    if not question:
        uncertainty.append({"type": "no_question", "detail": "未找到研究问题，无法校验主题与证据范围。"})
    if not sources:
        uncertainty.append({"type": "no_sources", "detail": "未读取到任何来源，无法形成证据链。"})
    for conflict in conflicts:
        uncertainty.append({
            "type": "unresolved_conflict",
            "sub_question_id": conflict["sub_question_id"],
            "conflict_id": conflict["conflict_id"],
            "detail": "子问题 %s 存在相反结论，已并列保留，未裁决。" % conflict["sub_question_id"],
        })
    for gap in coverage.get("gaps", []):
        uncertainty.append({
            "type": "evidence_gap",
            "sub_question_id": gap["sub_question_id"],
            "gap_id": gap["gap_id"],
            "detail": "子问题 %s 在输入材料中无定位证据，未作结论。" % gap["sub_question_id"],
        })
    for source in low_confidence_sources:
        uncertainty.append({
            "type": "low_confidence_text",
            "source_id": source["source_id"],
            "detail": "来源 %s 的文本置信度为低：%s" % (
                source["source_id"], "、".join(source.get("confidence_notes") or ["unspecified"])),
        })
    missing_meta = [source["source_id"] for source in sources
                    if source.get("included_in_evidence", True)
                    and not (source.get("doi") and source.get("year") and source.get("venue"))]
    if missing_meta:
        uncertainty.append({
            "type": "missing_metadata",
            "detail": "%d 个来源缺少 DOI/年份/venue 中的至少一项；可靠性等级相应下调。" % len(missing_meta),
            "source_ids": missing_meta[:20],
        })
    if duplicates:
        uncertainty.append({
            "type": "duplicate_sources",
            "detail": "%d 个重复来源已被标记，未重复计数。" % len(duplicates),
        })
    if unreadable:
        uncertainty.append({
            "type": "unreadable_material",
            "detail": "%d 个材料无法读取或解析，详见 errors 与 input_manifest。" % len(unreadable),
        })
    if derived:
        uncertainty.append({
            "type": "sub_questions_derived",
            "detail": "子问题由流程按过程维度生成，可能与案例真实分析维度存在偏差。",
        })
    if not criteria_declared:
        uncertainty.append({
            "type": "criteria_not_supplied",
            "detail": "未提供纳排/范围标准；未做外部检索与外部筛选。",
        })
    if status == "partial":
        uncertainty.append({"type": "partial_run", "detail": "部分输入不可用或来源过少，结果只覆盖可用部分。"})
    if status == "insufficient_input":
        uncertainty.append({"type": "insufficient_input", "detail": "研究问题、来源或证据不足，未形成可复核综述。"})
    if status == "failed":
        uncertainty.append({"type": "failed_run", "detail": "输入损坏或流程异常；已写出结构化失败结果与限制说明。"})
    return uncertainty
