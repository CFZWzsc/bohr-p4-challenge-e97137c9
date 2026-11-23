#!/usr/bin/env python3
"""CLI entrypoint for the deep-research evidence review skill.

Usage (harness):
    python /skills/weekly-skill/scripts/run_skill.py --input /input --work /app/work --out /app/output

The CLI always exits 0 and always attempts to write result.json, report.md and
run-review.md. It uses the Python standard library only, never accesses the
network, and is deterministic for a given input tree.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sk_analyze
import sk_ingest
import sk_render

DEFAULT_INPUT = "/input"
DEFAULT_WORK = "/app/work"
DEFAULT_OUT = "/app/output"
SKILL_NAME = "deep-research-evidence-review"
SKILL_VERSION = "1.0.0"

ALIASES = {
    "report": "synthesis", "summary": "synthesis", "narrative": "synthesis",
    "review": "synthesis", "draft": "synthesis", "answer": "synthesis",
    "findings": "claims", "finding": "claims", "claim_table": "claims",
    "assertions": "claims", "conclusions": "claims", "main_results": "claims",
    "references": "sources", "reference": "sources", "bibliography": "sources",
    "source_list": "sources", "records": "sources", "papers": "sources",
    "citations": "evidence", "citation": "evidence", "evidence_matrix": "evidence",
    "quotes": "evidence", "quote_table": "evidence",
    "gaps": "coverage", "gap": "coverage", "coverage": "coverage", "missing": "coverage",
    "notes": "uncertainty", "note": "uncertainty", "uncertainty": "uncertainty",
    "caveats": "uncertainty",
    "status": "status", "run_status": "status", "state": "status",
    "question": "question", "research_question": "question",
    "sub_questions": "sub_questions", "subquestions": "sub_questions",
    "conflicts": "conflicts", "conflict": "conflicts", "disagreements": "conflicts",
    "limitations": "limitations", "limitation": "limitations",
    "run_log": "run_log", "log": "run_log", "trace": "run_log",
    "method": "method", "protocol": "method", "procedure": "method",
    "criteria": "criteria", "screening": "criteria",
    "sources": "sources", "evidence": "evidence", "claims": "claims",
    "case_id": "case_id", "input_id": "input_id",
}


def norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def case_identifier(case):
    if isinstance(case, dict):
        for key in ("case_id", "caseId", "id", "case_key"):
            value = case.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def contract_specs(case):
    contract = case.get("output_contract") if isinstance(case, dict) else None
    specs = {}
    if isinstance(contract, dict):
        for key, value in contract.items():
            specs[str(key)] = value
    elif isinstance(contract, list):
        for item in contract:
            if isinstance(item, str):
                specs[item] = None
            elif isinstance(item, dict):
                name = None
                for key in ("name", "field", "key", "id"):
                    if isinstance(item.get(key), str):
                        name = item[key]
                        break
                if name:
                    specs[name] = item
    return specs


def heuristic_target(name):
    tokens = set(re.split(r"[^a-z0-9]+", norm_key(name)))
    if tokens & {"source", "sources", "reference", "references", "bibliography",
                 "record", "records", "paper", "papers"}:
        return "sources"
    if tokens & {"citation", "citations", "quote", "quotes", "evidence", "locator",
                 "matrix", "snippet", "snippets"}:
        return "evidence"
    if tokens & {"claim", "claims", "finding", "findings", "assertion", "assertions",
                 "conclusion", "conclusions", "result", "results"}:
        return "claims"
    if tokens & {"conflict", "conflicts", "disagreement", "disagreements",
                 "contradiction", "contradictions", "opposing"}:
        return "conflicts"
    if tokens & {"gap", "gaps", "coverage", "missing", "blank", "blanks"}:
        return "coverage"
    if tokens & {"limitation", "limitations", "bias", "biases", "risk", "risks"}:
        return "limitations"
    if tokens & {"uncertainty", "uncertainties", "note", "notes", "caveat", "caveats"}:
        return "uncertainty"
    if tokens & {"question", "questions", "query", "queries"}:
        return "question"
    if tokens & {"subquestion", "subquestions", "sub", "decomposition"}:
        return "sub_questions"
    if tokens & {"status", "state", "outcome"}:
        return "status"
    if tokens & {"log", "logs", "trace", "traces", "run"}:
        return "run_log"
    if tokens & {"method", "methods", "protocol", "procedure", "criteria", "screening"}:
        return "method"
    if tokens & {"report", "summary", "synthesis", "narrative", "review", "draft", "answer"}:
        return "synthesis"
    return None


def apply_contract(payload, case):
    specs = contract_specs(case)
    names = list(specs.keys())
    mapping = {}
    extras = {}
    present = {}
    for name in names:
        key = str(name)
        if key in payload:
            mapping[key] = key
            present[key] = True
            continue
        target = ALIASES.get(norm_key(key))
        if target not in payload:
            target = heuristic_target(key)
        if target and target in payload:
            payload[key] = payload[target]
            mapping[key] = target
            present[key] = True
            continue
        payload[key] = {
            "produced": False,
            "best_effort": True,
            "requested": specs.get(name),
            "note": "no direct producer for this field; preserved honestly and recorded in contract_extras",
            "available_top_level": sorted(k for k in payload.keys() if k != "contract_extras"),
        }
        mapping[key] = None
        present[key] = False
        extras[key] = {"requested": specs.get(name), "mapped_to": None,
                       "reason": "unknown_contract_field"}
    payload["contract_extras"] = extras
    payload["output_contract_fields"] = {
        "provided": names,
        "present": present,
        "mapping": mapping,
        "missing": [name for name in names if not present.get(name)],
        "unknown": sorted(extras.keys()),
    }
    return payload


def compute_verification(payload):
    claims = payload.get("claims") or []
    evidence = payload.get("evidence") or []
    conflicts = payload.get("conflicts") or []
    coverage = payload.get("coverage") or {}
    limitations = payload.get("limitations") or []
    uncertainty = payload.get("uncertainty") or []
    contract = payload.get("output_contract_fields") or {}
    evidence_map = {row.get("evidence_id"): row for row in evidence}
    claims_with_locator = 0
    claims_with_quote = 0
    verified = 0
    for claim in claims:
        locator = claim.get("locator") or (claim.get("locators") or [None])[0]
        if locator:
            claims_with_locator += 1
        if claim.get("quote"):
            claims_with_quote += 1
        row = evidence_map.get(claim.get("evidence_id"))
        if row and claim.get("quote") and claim["quote"] in (row.get("text") or ""):
            verified += 1
    gap_ids = [gap.get("sub_question_id") for gap in coverage.get("gaps") or []]
    gap_item_ids = {item.get("sub_question_id") for item in coverage.get("items") or []
                    if item.get("status") == "gap"}
    limitation_gap_ids = {item.get("sub_question_id") for item in limitations
                          if item.get("type") == "evidence_gap"}
    uncertainty_gap_ids = {item.get("sub_question_id") for item in uncertainty
                           if item.get("type") == "evidence_gap"}
    provided = contract.get("provided") or []
    present = contract.get("present") or {}
    checks = {
        "case_id_present": bool(payload.get("case_id") and payload.get("case_id") != "unknown"),
        "contract_keys_present": all(bool(present.get(name)) for name in provided),
        "claims_have_locator": claims_with_locator == len(claims),
        "claims_have_quote": claims_with_quote == len(claims),
        "quotes_verified_substring": verified == len(claims),
        "conflicts_unresolved": all(conflict.get("resolution") == "unresolved" for conflict in conflicts),
        "gaps_in_coverage": all(gap_id in gap_item_ids for gap_id in gap_ids),
        "gaps_in_limitations": all(gap_id in limitation_gap_ids for gap_id in gap_ids),
        "gaps_in_uncertainty": all(gap_id in uncertainty_gap_ids for gap_id in gap_ids),
    }
    verification = {
        "claims_total": len(claims),
        "claims_with_locator": claims_with_locator,
        "claims_with_quote": claims_with_quote,
        "quotes_verified_substring": verified,
        "conflicts_total": len(conflicts),
        "conflicts_unresolved": sum(1 for conflict in conflicts
                                    if conflict.get("resolution") == "unresolved"),
        "gaps_total": len(gap_ids),
        "gaps_in_coverage": len(gap_ids),
        "gaps_in_limitations": len([gap_id for gap_id in gap_ids if gap_id in limitation_gap_ids]),
        "gaps_in_uncertainty": len([gap_id for gap_id in gap_ids if gap_id in uncertainty_gap_ids]),
        "contract_keys_total": len(provided),
        "contract_keys_present": sum(1 for name in provided if present.get(name)),
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }
    return verification


def collect_files(input_dir, case_path, task_path):
    items = []
    root = Path(input_dir)
    if not root.is_dir():
        return items
    try:
        paths = sorted((path for path in root.rglob("*") if path.is_file()),
                       key=lambda path: path.as_posix().lower())
    except OSError:
        return items
    case_resolved = Path(case_path).resolve() if case_path else None
    task_resolved = Path(task_path).resolve() if task_path else None
    for path in paths[:2000]:
        parts = {part.lower() for part in path.parts}
        if parts & sk_ingest.SKIP_DIRS:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        rel = sk_ingest.os_relpath(path, root)
        suffix = path.suffix.lower()
        resolved = path.resolve()
        if case_resolved and resolved == case_resolved:
            kind = "case"
        elif task_resolved and resolved == task_resolved:
            kind = "task"
        elif suffix in sk_ingest.SUPPORTED_SUFFIXES:
            kind = "material"
        else:
            kind = "other"
        items.append({
            "path": str(path),
            "rel": rel,
            "name": path.name,
            "suffix": suffix,
            "bytes": size,
            "sha256": sk_ingest.sha256_file(path),
            "kind": kind,
            "status": "present",
            "source_count": 0,
        })
    return items


def read_task_text(input_dir, case_path, work_dir):
    candidates = []
    if case_path:
        candidates.append(Path(case_path).resolve().parent / "task.md")
    candidates.append(Path(input_dir) / "task.md")
    candidates.append(Path(work_dir) / "task.md")
    for path in candidates:
        try:
            if path.is_file():
                text, _, _ = sk_ingest.read_text_file(path, 200000)
                if text.strip():
                    return text
        except OSError:
            continue
    return ""


def load_case(case_path):
    errors = []
    if not case_path:
        return {}, errors
    path = Path(case_path)
    if not path.is_file():
        return {}, errors
    try:
        text, error, _ = sk_ingest.read_text_file(path, 4000000)
        if error:
            raise ValueError(error)
        data = json.loads(text)
    except (OSError, ValueError, TypeError) as exc:
        errors.append({
            "stage": "load_case",
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        })
        return {}, errors
    if isinstance(data, list):
        return {"records": data}, errors
    if isinstance(data, dict):
        return data, errors
    return {"text": sk_ingest.as_text(data)}, errors


def extract_criteria(case):
    if not isinstance(case, dict):
        return {}, False
    for key in ("criteria", "protocol", "screening", "inclusion_criteria",
                "exclusion_criteria", "research_scope", "scope", "constraints"):
        value = sk_ingest.pick(case, (key,))
        if value not in (None, "", [], {}):
            if isinstance(value, (dict, list)):
                return {key: value}, True
            return {key: sk_ingest.as_text(value)}, True
    return {}, False


def decide_status(case_errors, question, sources, claims, usable_sources,
                  low_confidence_sources):
    if case_errors and not sources:
        return "failed"
    if not question or not sources:
        return "insufficient_input"
    if not claims:
        return "insufficient_input"
    ratio = (len(low_confidence_sources) / float(max(1, len(usable_sources)))) if usable_sources else 0.0
    if len(usable_sources) < 2 or ratio >= 0.5:
        return "partial"
    if case_errors:
        return "partial"
    return "success"


def build_input_manifest(files, case_path, file_reports):
    report_map = {item.get("path"): item for item in file_reports}
    manifest = []
    for item in files:
        report = report_map.get(item.get("path"), {})
        manifest.append({
            "path": item["rel"],
            "kind": item["kind"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "status": report.get("status", item.get("status", "present")),
            "source_count": report.get("source_count", 0),
        })
    if case_path and not Path(case_path).is_file():
        manifest.insert(0, {
            "path": "case.json", "kind": "case", "bytes": 0, "sha256": "",
            "status": "missing", "source_count": 0,
        })
    return manifest


def build_payload(case, case_path, input_dir, task_text, files, policy, case_errors):
    sources, duplicates, material_errors, material_notes, file_reports = sk_ingest.build_sources(
        case, input_dir, case_path, Path(input_dir) / "task.md", files, policy)
    sk_ingest.prepare_passages(sources, policy)
    question = sk_ingest.question_from_case(case, task_text)
    sub_questions, derived = sk_ingest.decompose(case, question, policy)
    evidence, pairs = sk_ingest.select_evidence(sources, sub_questions, policy, question)
    claims, conflicts = sk_analyze.build_claims(evidence, pairs, sources, sub_questions, policy)
    coverage = sk_analyze.build_coverage(sub_questions, evidence, claims, conflicts, sources, policy)
    criteria, criteria_declared = extract_criteria(case)
    usable_sources = [source for source in sources if source.get("included_in_evidence", True)]
    low_confidence_sources = [source for source in usable_sources
                              if source.get("low_confidence") or source.get("confidence") == "low"]
    unreadable = [error for error in material_errors
                  if error.startswith(("unreadable_material", "json_parse_error",
                                       "xml_parse_error", "csv_parse_error", "pdf_no_text"))]
    status = decide_status(case_errors, question, sources, claims, usable_sources,
                           low_confidence_sources)
    limitations = sk_analyze.build_limitations(
        question, sources, evidence, conflicts, coverage, duplicates, unreadable,
        derived, criteria_declared, status, low_confidence_sources)
    uncertainty = sk_analyze.build_uncertainty(
        question, sources, conflicts, coverage, duplicates, unreadable, derived,
        criteria_declared, low_confidence_sources, status)
    synthesis = sk_analyze.build_synthesis(
        question, sub_questions, evidence, claims, conflicts, coverage, sources,
        uncertainty, status)
    case_id = case_identifier(case) or "unknown"
    input_id = case_id
    if input_id == "unknown" and case_path and Path(case_path).is_file():
        input_id = "sha256:" + sk_ingest.sha256_file(case_path)[:12]
    run_log = [
        {"step": "load_input", "status": "ok" if not case_errors else "degraded",
         "detail": "读取 case.json 与 task.md；输入文件 %d 个，解析错误 %d 个。" % (
             len(files), len(case_errors))},
        {"step": "collect_sources", "status": "ok" if sources else "degraded",
         "detail": "来源 %d 个（去重 %d 个，不可读材料 %d 个）。" % (
             len(sources), len(duplicates), len(unreadable))},
        {"step": "decompose_question", "status": "ok" if sub_questions else "degraded",
         "detail": "子问题 %d 个（%s）。" % (
             len(sub_questions), "由流程生成" if derived else "取自案例")},
        {"step": "extract_evidence", "status": "ok" if evidence else "degraded",
         "detail": "证据行 %d 条，覆盖 %d 个子问题。" % (
             len(evidence), len({subq_id for row in evidence for subq_id in row.get("sub_question_ids", [])}))},
        {"step": "bind_claims", "status": "ok" if claims else "degraded",
         "detail": "论断 %d 条；冲突 %d 组。" % (len(claims), len(conflicts))},
        {"step": "assess_coverage", "status": "ok",
         "detail": "covered %d、thin %d、gap %d。" % (
             coverage["summary"]["covered"], coverage["summary"]["thin"],
             coverage["summary"]["gap"])},
        {"step": "synthesize", "status": "ok",
         "detail": "综合章节 %d 个。" % len(synthesis.get("sections") or [])},
    ]
    errors = list(case_errors)
    for error in material_errors:
        errors.append({"stage": "materials", "type": "material_error", "message": error})
    stats = {
        "input_files": len(files),
        "sources": len(sources),
        "usable_sources": len(usable_sources),
        "duplicates": len(duplicates),
        "sub_questions": len(sub_questions),
        "evidence_rows": len(evidence),
        "claims": len(claims),
        "conflicts": len(conflicts),
        "covered": coverage["summary"]["covered"],
        "thin": coverage["summary"]["thin"],
        "gaps": coverage["summary"]["gap"],
        "low_confidence_sources": len(low_confidence_sources),
        "unreadable_materials": len(unreadable),
        "network": "disabled",
        "deterministic": True,
    }
    threshold_map = {
        "coverage": coverage.get("thresholds", {}),
        "support_levels": policy.get("support_levels", {}),
        "policy_version": policy.get("version", ""),
    }
    payload = {
        "case_id": case_id,
        "input_id": input_id,
        "status": status,
        "question": question,
        "sub_questions": sub_questions,
        "sources": [{
            "source_id": source["source_id"],
            "title": source.get("title"),
            "year": source.get("year"),
            "language": source.get("language"),
            "venue": source.get("venue"),
            "doi": source.get("doi"),
            "authors": source.get("authors"),
            "study_type": source.get("study_type"),
            "reliability": source.get("reliability"),
            "origin": source.get("origin"),
            "locator_prefix": source.get("locator_prefix"),
            "confidence": source.get("confidence"),
            "low_confidence": bool(source.get("low_confidence")),
            "confidence_notes": source.get("confidence_notes") or [],
            "sections": [section.get("name") for section in source.get("sections", [])],
            "duplicate_of": source.get("duplicate_of"),
            "included_in_evidence": source.get("included_in_evidence", True),
            "characters": len(source.get("text") or ""),
        } for source in sources],
        "evidence": evidence,
        "claims": claims,
        "conflicts": conflicts,
        "coverage": coverage,
        "synthesis": synthesis,
        "limitations": limitations,
        "uncertainty": uncertainty,
        "run_log": run_log,
        "criteria": criteria,
        "method": {
            "name": SKILL_NAME,
            "version": SKILL_VERSION,
            "policy_version": policy.get("version", ""),
            "runtime": "python3 stdlib",
            "network": False,
            "deterministic": True,
            "pipeline": [
                "question_decomposition",
                "source_collection",
                "evidence_extraction",
                "claim_binding",
                "conflict_resolution",
                "synthesis",
            ],
            "criteria": criteria,
            "criteria_declared": criteria_declared,
            "thresholds": threshold_map,
            "citation_format": "[source_id | locator]",
            "sub_questions_derived": derived,
        },
        "input_manifest": build_input_manifest(files, case_path, file_reports),
        "contract_extras": {},
        "output_contract_fields": {},
        "errors": errors,
        "stats": stats,
        "material_notes": material_notes[:50],
    }
    payload = apply_contract(payload, case)
    payload["verification"] = compute_verification(payload)
    return payload


def failure_payload(case, case_path, error, files):
    case_id = case_identifier(case) or "unknown"
    payload = {
        "case_id": case_id,
        "input_id": case_id,
        "status": "failed",
        "question": "",
        "sub_questions": [],
        "sources": [],
        "evidence": [],
        "claims": [],
        "conflicts": [],
        "coverage": {"items": [], "gaps": [], "summary": {
            "sub_questions": 0, "covered": 0, "thin": 0, "gap": 0,
            "sources": 0, "evidence_rows": 0, "claims": 0}, "thresholds": {}},
        "synthesis": {"sections": [], "narrative": "", "citation_format": "[source_id | locator]",
                      "claim_level": True, "status_note": "failed run"},
        "limitations": [{"type": "failed_run", "detail": "流程异常或输入损坏，未形成可复核综述。"}],
        "uncertainty": [{"type": "failed_run", "detail": "未完成证据绑定；详见 errors。"}],
        "run_log": [{"step": "run", "status": "failed",
                     "detail": "%s: %s" % (type(error).__name__, str(error)[:200])}],
        "criteria": {},
        "method": {"name": SKILL_NAME, "version": SKILL_VERSION, "network": False,
                   "deterministic": True},
        "input_manifest": build_input_manifest(files, case_path, []),
        "contract_extras": {},
        "output_contract_fields": {},
        "errors": [{"stage": "run", "type": type(error).__name__, "message": str(error)[:500]}],
        "stats": {"sources": 0, "claims": 0, "network": "disabled"},
        "material_notes": [],
    }
    payload = apply_contract(payload, case)
    payload["verification"] = compute_verification(payload)
    return payload


def atomic_write_text(path, text):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(tmp, str(target))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def write_json(path, payload):
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def write_outputs(payload, out_dir, work_dir):
    out_dir = Path(out_dir)
    work_dir = Path(work_dir)
    result_path = out_dir / "result.json"
    report_path = out_dir / "report.md"
    review_path = out_dir / "run-review.md"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        out_dir = work_dir
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            out_dir = Path.cwd()
        result_path = out_dir / "result.json"
        report_path = out_dir / "report.md"
        review_path = out_dir / "run-review.md"
    write_json(result_path, payload)
    report_text = sk_render.render_report(payload)
    atomic_write_text(report_path, report_text)
    consistent = False
    try:
        reloaded = json.loads(result_path.read_text(encoding="utf-8"))
        consistent = sk_render.render_report(reloaded) == report_path.read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError):
        consistent = False
    payload["verification"]["report_consistent"] = bool(consistent)
    payload["verification"]["all_checks_passed"] = bool(
        all(payload["verification"].get("checks", {}).values()) and consistent)
    write_json(result_path, payload)
    atomic_write_text(review_path, sk_render.render_review(payload))
    return {
        "result": str(result_path),
        "report": str(report_path),
        "review": str(review_path),
    }


def resolve_input(arg):
    path = Path(arg)
    try:
        if path.is_file():
            return path.resolve().parent, path.resolve()
        return path.resolve(), path.resolve() / "case.json"
    except OSError:
        return path, path / "case.json"


def resolve_out(arg):
    path = Path(arg)
    if path.suffix.lower() == ".json":
        return path.resolve().parent, path.resolve()
    return path.resolve(), path.resolve() / "result.json"


def run(input_arg, work_dir, out_arg):
    input_dir, case_path = resolve_input(input_arg)
    out_dir, result_path = resolve_out(out_arg)
    task_path = Path(input_dir) / "task.md"
    files = collect_files(input_dir, case_path, task_path)
    task_text = read_task_text(input_dir, case_path, work_dir)
    case, case_errors = load_case(case_path)
    policy = sk_ingest.load_policy(HERE.parent)
    payload = build_payload(case, case_path, input_dir, task_text, files, policy, case_errors)
    payload["output_paths"] = {
        "result": str(result_path),
        "report": str(out_dir / "report.md"),
        "review": str(out_dir / "run-review.md"),
        "work": str(work_dir),
    }
    return payload, out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Deep-research evidence review: sources, locators, claims, conflicts, coverage.")
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help="input directory or case.json (default: /input)")
    parser.add_argument("--work", default=DEFAULT_WORK,
                        help="working directory (default: /app/work)")
    parser.add_argument("--out", "--output", dest="out", default=DEFAULT_OUT,
                        help="output directory or result.json path (default: /app/output)")
    try:
        args, _unknown = parser.parse_known_args(argv)
    except SystemExit:
        return 0
    work_dir = Path(args.work)
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    files = []
    case = {}
    case_path = None
    try:
        input_dir, case_path = resolve_input(args.input)
        task_path = Path(input_dir) / "task.md"
        files = collect_files(input_dir, case_path, task_path)
        task_text = read_task_text(input_dir, case_path, work_dir)
        case, case_errors = load_case(case_path)
        policy = sk_ingest.load_policy(HERE.parent)
        payload = build_payload(case, case_path, input_dir, task_text, files, policy, case_errors)
        out_dir, result_path = resolve_out(args.out)
        payload["output_paths"] = {
            "result": str(result_path),
            "report": str(out_dir / "report.md"),
            "review": str(out_dir / "run-review.md"),
            "work": str(work_dir),
        }
    except Exception as exc:
        try:
            out_dir, _ = resolve_out(args.out)
        except Exception:
            out_dir = Path(args.out)
        payload = failure_payload(case, case_path, exc, files)
        payload["output_paths"] = {"result": str(out_dir / "result.json"),
                                   "report": str(out_dir / "report.md"),
                                   "review": str(out_dir / "run-review.md"),
                                   "work": str(work_dir)}
    try:
        written = write_outputs(payload, out_dir, work_dir)
    except Exception as exc:
        written = {}
        try:
            sys.stderr.write(json.dumps({
                "status": "failed", "stage": "write_outputs",
                "message": str(exc)[:300],
            }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    summary = {
        "status": payload.get("status"),
        "case_id": payload.get("case_id"),
        "sources": len(payload.get("sources") or []),
        "claims": len(payload.get("claims") or []),
        "conflicts": len(payload.get("conflicts") or []),
        "gaps": len((payload.get("coverage") or {}).get("gaps") or []),
        "written": written,
    }
    try:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        pass
    except BaseException:
        sys.exit(0)
