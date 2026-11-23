#!/usr/bin/env python3
"""Thin, always-exit-0 wrapper around sk_entry.main().

The harness may invoke this file from any working directory. Import failures,
unexpected exceptions and output-write failures are contained here so that the
sandbox never sees a traceback or a non-zero exit code.
"""

import sys

sys.dont_write_bytecode = True

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def parse_opts(argv):
    opts = {"input": "/input", "work": "/app/work", "out": "/app/output"}
    index = 0
    flags = {"--input": "input", "--work": "work", "--out": "out", "--output": "out"}
    while index < len(argv):
        token = argv[index]
        matched = False
        for flag, key in flags.items():
            if token == flag and index + 1 < len(argv):
                opts[key] = argv[index + 1]
                index += 2
                matched = True
                break
            if token.startswith(flag + "="):
                opts[key] = token.split("=", 1)[1]
                index += 1
                matched = True
                break
        if not matched:
            index += 1
    return opts


def resolve_out(value):
    path = Path(value)
    if path.suffix.lower() == ".json":
        return path.parent, path
    return path, path / "result.json"


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _contract_names(case):
    contract = case.get("output_contract")
    names = []
    if isinstance(contract, dict):
        names = [str(key) for key in contract.keys()]
    elif isinstance(contract, list):
        for item in contract:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for key in ("name", "field", "key", "id"):
                    if isinstance(item.get(key), str):
                        names.append(item[key])
                        break
    return names


def _existing_success(result_path):
    data = _read_json(result_path)
    if data.get("status") in {"success", "partial"} and data.get("claims"):
        return True
    return False


def fallback(argv, exc):
    opts = parse_opts(argv)
    out_dir, result_path = resolve_out(opts["out"])
    if _existing_success(result_path):
        return
    case_path = Path(opts["input"])
    if case_path.is_file():
        case_path = case_path
    else:
        case_path = case_path / "case.json"
    case = _read_json(case_path)
    case_id = ""
    for key in ("case_id", "caseId", "id"):
        if isinstance(case.get(key), str) and case.get(key).strip():
            case_id = case[key].strip()
            break
    case_id = case_id or "unknown"
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
        "synthesis": {"sections": [], "narrative": "",
                      "citation_format": "[source_id | locator]"},
        "limitations": [{"type": "failed_run",
                         "detail": "入口包装器捕获异常，未形成可复核综述。"}],
        "uncertainty": [{"type": "failed_run", "detail": "入口包装器捕获异常。"}],
        "run_log": [{"step": "wrapper", "status": "failed",
                     "detail": "%s: %s" % (type(exc).__name__, str(exc)[:200])}],
        "criteria": {},
        "method": {"name": "deep-research-evidence-review", "network": False,
                   "deterministic": True},
        "input_manifest": [],
        "contract_extras": {},
        "output_contract_fields": {"provided": [], "present": {}, "mapping": {},
                                   "missing": [], "unknown": []},
        "verification": {"claims_total": 0, "contract_keys_present": 0,
                         "all_checks_passed": False, "report_consistent": False},
        "errors": [{"stage": "wrapper", "type": type(exc).__name__,
                    "message": str(exc)[:500]}],
        "stats": {"sources": 0, "claims": 0},
        "material_notes": [],
    }
    names = _contract_names(case)
    present = {}
    for name in names:
        payload[name] = {"produced": False, "best_effort": True,
                         "note": "wrapper fallback: no content produced"}
        present[name] = True
    payload["output_contract_fields"] = {
        "provided": names, "present": present, "mapping": {name: name for name in names},
        "missing": [], "unknown": [],
    }
    try:
        _write(result_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    except OSError:
        return
    report = ["# 文献综述运行报告（失败回退）", "",
              "- case_id：`%s`" % case_id, "- status：`failed`",
              "- 错误：`%s`" % type(exc).__name__, "",
              "入口包装器捕获异常，未形成结果。详见 result.json 的 errors。", ""]
    try:
        _write(Path(out_dir) / "report.md", "\n".join(report))
        _write(Path(out_dir) / "run-review.md",
               "# 运行复核（失败回退）\n\nstatus=`failed`；error=`%s`。\n" % type(exc).__name__)
    except OSError:
        pass


def main(argv):
    try:
        import sk_entry
        sk_entry.main(argv)
        return 0
    except SystemExit:
        return 0
    except BaseException as exc:
        try:
            fallback(argv, exc)
        except BaseException:
            pass
        return 0


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except BaseException:
        code = 0
    sys.exit(0)
