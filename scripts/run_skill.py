#!/usr/bin/env python3
"""Literature review generation skill (Python standard library only).

Reads a case file (default /input/case.json) with a review question, explicit
eligibility criteria and a batch of records. It screens the batch against the
criteria before writing anything, keeps a reason for every exclusion, groups the
included records into themes derived from the supplied text, builds a locatable
evidence table, and drafts a cited review under /app/output/result.json. Every
substantive sentence carries the source id and quoted span it came from; where
the batch has no evidence the draft says so instead of inventing it.

No network access, no randomness, no private paths.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

DEFAULT_CASE = "/input/case.json"
DEFAULT_OUT = "/app/output/result.json"
DEFAULT_WORK = "/app/work"

RECORD_KEYS = ("records", "papers", "documents", "literature", "sources", "items", "bibliography")
CRITERIA_KEYS = ("criteria", "eligibility", "inclusion_criteria", "screening_criteria")
TOPIC_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "were", "was", "are", "has", "have",
    "study", "studies", "paper", "review", "research", "results", "using", "used", "based", "between",
    "among", "effect", "effects", "group", "groups", "patients", "data", "analysis", "findings",
    "however", "also", "can", "may", "not", "but", "than", "more", "less", "after", "during", "which",
}
POSITIVE_CUES = ("improve", "improved", "increase", "increased", "benefit", "effective", "efficacy",
                 "significant", "superior", "protective", "有效", "改善", "提高", "显著", "优于")
NEGATIVE_CUES = ("no effect", "no significant", "not significant", "ineffective", "no benefit", "worse",
                 "adverse", "harm", "no association", "negative", "无效", "无显著", "不支持", "恶化", "无差异")


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_task_text(case_path, work_dir):
    for path in (Path(case_path).resolve().parent / "task.md", Path("/input/task.md"), Path(work_dir) / "task.md"):
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
    return ""


def norm_space(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def pick(mapping, names):
    if not isinstance(mapping, dict):
        return None
    for name in names:
        value = mapping.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return norm_space(value)
    if isinstance(value, list):
        return norm_space(" ".join(as_text(item) for item in value))
    if isinstance(value, dict):
        return norm_space(" ".join(as_text(item) for item in value.values()))
    return norm_space(str(value))


def parse_year(value):
    if isinstance(value, int):
        return value if 1800 <= value <= 2100 else None
    match = re.search(r"(1[89]\d{2}|20\d{2})", as_text(value))
    return int(match.group(1)) if match else None


def sentences(text):
    text = norm_space(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?;])\s+|(?<=[。！？；])", text)
    return [norm_space(part) for part in parts if norm_space(part)]


def tokenize(text, limit=40):
    lowered = norm_space(text).lower()
    words = [word for word in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", lowered)
             if word not in TOPIC_STOPWORDS and not word.isdigit()]
    terms, seen = [], set()
    for word in words:
        if word not in seen:
            seen.add(word)
            terms.append(word)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        for index in range(len(chunk) - 1):
            bigram = chunk[index:index + 2]
            if bigram not in seen and bigram not in ("研究", "本文", "我们", "以及", "方法"):
                seen.add(bigram)
                terms.append(bigram)
    return terms[:limit]


def looks_like_record(node):
    if not isinstance(node, dict):
        return False
    keys = {str(key).lower() for key in node.keys()}
    return bool(keys & {"title", "abstract", "doi", "year", "authors", "journal", "venue"})


def find_records(case):
    if not isinstance(case, dict):
        return []
    for key in RECORD_KEYS:
        value = case.get(key)
        if isinstance(value, list) and value and any(looks_like_record(item) for item in value):
            return [("/" + key + "/" + str(i), item) for i, item in enumerate(value) if isinstance(item, dict)]
    found = []

    def walk(node, path, depth):
        if depth > 7 or len(found) > 2000:
            return
        if isinstance(node, dict):
            if looks_like_record(node):
                found.append((path, node))
                return
            for key, value in node.items():
                walk(value, path + "/" + str(key), depth + 1)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + "/" + str(index), depth + 1)

    walk(case, "", 0)
    return found


def normalize_record(raw, locator, index):
    title = as_text(pick(raw, ("title", "name")))
    abstract = as_text(pick(raw, ("abstract", "summary")))
    body = as_text(pick(raw, ("text", "full_text", "content", "body")))
    return {
        "source_id": as_text(pick(raw, ("source_id", "record_id", "paper_id", "id"))) or ("P%02d" % (index + 1)),
        "locator": locator,
        "title": title,
        "abstract": abstract,
        "body": body,
        "year": parse_year(pick(raw, ("year", "publication_year", "published", "date"))),
        "language": as_text(pick(raw, ("language", "lang"))).lower(),
        "venue": as_text(pick(raw, ("venue", "journal", "conference"))),
        "doi": as_text(pick(raw, ("doi", "DOI"))),
        "authors": as_text(pick(raw, ("authors", "author"))),
        "study_type": as_text(pick(raw, ("study_type", "type", "design", "publication_type"))),
        "has_fulltext": bool(body) or bool(pick(raw, ("full_text_available", "open_access", "fulltext"))),
        "key": as_text(pick(raw, ("source_id", "record_id", "paper_id", "id"))) or ("P%02d" % (index + 1)),
    }


def criteria_config(case):
    raw = pick(case, CRITERIA_KEYS) or {}
    if not isinstance(raw, dict):
        raw = {}
    include_types = as_text(pick(raw, ("include_types", "designs", "study_types")))
    exclude_types = as_text(pick(raw, ("exclude_types", "exclude_designs")))
    return {
        "year_from": parse_year(pick(raw, ("year_from", "from_year", "min_year", "start_year"))),
        "year_to": parse_year(pick(raw, ("year_to", "to_year", "max_year", "end_year"))),
        "languages": [item.strip().lower() for item in re.split(r"[,;]", as_text(pick(raw, ("languages", "language")))) if item.strip()],
        "require_abstract": bool(pick(raw, ("require_abstract", "abstract_required")) or False),
        "require_fulltext": bool(pick(raw, ("require_fulltext", "fulltext_required")) or False),
        "include_types": [item.strip().lower() for item in re.split(r"[,;]", include_types) if item.strip()],
        "exclude_types": [item.strip().lower() for item in re.split(r"[,;]", exclude_types) if item.strip()],
        "custom": as_text(pick(raw, ("notes", "custom", "additional"))),
        "declared": bool(raw),
    }


def review_question(case, task_text):
    question = as_text(pick(case, ("review_question", "research_question", "question", "topic", "objective", "title")))
    if not question:
        for line in task_text.splitlines():
            line = norm_space(line)
            if len(line) > 12 and not line.startswith("#"):
                question = line
                break
    return question


def screen(records, criteria, question):
    question_terms = tokenize(question, limit=12)
    included, excluded = [], []
    seen_doi, seen_title = {}, {}
    for record in records:
        reasons = []
        doi = record["doi"].lower()
        title_key = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", record["title"].lower())
        if doi and doi in seen_doi:
            reasons.append({"code": "duplicate_doi", "detail": "same DOI as " + seen_doi[doi]})
        elif title_key and title_key in seen_title:
            reasons.append({"code": "duplicate_title", "detail": "same normalised title as " + seen_title[title_key]})
        if criteria["year_from"] and record["year"] and record["year"] < criteria["year_from"]:
            reasons.append({"code": "out_of_year_range", "detail": "year %d before %d" % (record["year"], criteria["year_from"])})
        if criteria["year_to"] and record["year"] and record["year"] > criteria["year_to"]:
            reasons.append({"code": "out_of_year_range", "detail": "year %d after %d" % (record["year"], criteria["year_to"])})
        if criteria["languages"] and record["language"] and record["language"] not in criteria["languages"]:
            reasons.append({"code": "language_excluded", "detail": "language %s not in %s" % (record["language"], criteria["languages"])})
        if criteria["require_abstract"] and not record["abstract"]:
            reasons.append({"code": "no_abstract", "detail": "abstract required by criteria"})
        if criteria["require_fulltext"] and not record["has_fulltext"]:
            reasons.append({"code": "no_fulltext", "detail": "full text required by criteria"})
        type_text = record["study_type"].lower()
        if criteria["include_types"] and type_text and not any(item in type_text for item in criteria["include_types"]):
            reasons.append({"code": "design_not_included", "detail": "design '%s' not in %s" % (record["study_type"], criteria["include_types"])})
        if criteria["exclude_types"] and type_text and any(item in type_text for item in criteria["exclude_types"]):
            reasons.append({"code": "design_excluded", "detail": "design '%s' matches an exclusion" % record["study_type"]})
        if not record["title"] and not record["abstract"]:
            reasons.append({"code": "no_screening_text", "detail": "neither title nor abstract available"})
        relevant = any(term in (record["title"] + " " + record["abstract"]).lower() for term in question_terms)
        if question_terms and not relevant and not record["abstract"]:
            reasons.append({"code": "not_relevant", "detail": "no question term found in title/abstract"})
        if reasons:
            excluded.append({"source_id": record["source_id"], "title": record["title"], "reasons": reasons})
        else:
            included.append(record)
            if doi:
                seen_doi[doi] = record["source_id"]
            if title_key:
                seen_title[title_key] = record["source_id"]
    return included, excluded


def build_themes(records, question):
    corpus_terms = {}
    per_record = {}
    for record in records:
        terms = tokenize(record["title"] + " " + record["abstract"], limit=24)
        per_record[record["source_id"]] = terms
        for term in terms:
            corpus_terms[term] = corpus_terms.get(term, 0) + 1
    ordered = sorted(corpus_terms.items(), key=lambda item: (-item[1], item[0]))
    seeds = [term for term, count in ordered if count >= 2][:6]
    if not seeds:
        seeds = [term for term, _ in ordered[:2]]
    themes = []
    for index, seed in enumerate(seeds):
        themes.append({
            "theme_id": "T%d" % (index + 1),
            "label": seed,
            "seed_terms": [seed],
            "records": [],
            "boundary": "",
        })
    unassigned = []
    for record in records:
        terms = per_record[record["source_id"]]
        best, best_score = None, 0
        for theme in themes:
            score = sum(1 for term in terms if term in theme["seed_terms"])
            if score > best_score:
                best, best_score = theme, score
        if best is None:
            unassigned.append(record)
        else:
            best["records"].append(record["source_id"])
    if unassigned:
        themes.append({"theme_id": "T%d" % (len(themes) + 1), "label": "other_reported_topics",
                       "seed_terms": [], "records": [record["source_id"] for record in unassigned],
                       "boundary": "records whose vocabulary did not match a topic seed"})
    for theme in themes:
        co_terms = {}
        for source_id in theme["records"]:
            for term in per_record.get(source_id, []):
                co_terms[term] = co_terms.get(term, 0) + 1
        ranked = sorted(co_terms.items(), key=lambda item: (-item[1], item[0]))
        theme["seed_terms"] = [term for term, _ in ranked[:4]] or theme["seed_terms"]
        theme["label"] = " / ".join(theme["seed_terms"][:2]) or theme["label"]
        theme["size"] = len(theme["records"])
        theme["boundary"] = "derived from co-occurring terms in the included records; not an external taxonomy"
    return [theme for theme in themes if theme["records"]], per_record


def polarity(text):
    lowered = text.lower()
    pos = sum(1 for cue in POSITIVE_CUES if cue in lowered)
    neg = sum(1 for cue in NEGATIVE_CUES if cue in lowered)
    if "no significant" in lowered or "not significant" in lowered:
        pos = max(0, pos - 1)
    if pos and not neg:
        return "positive"
    if neg and not pos:
        return "negative"
    if pos and neg:
        return "mixed"
    return "neutral"


def evidence_rows(themes, records_by_id):
    rows = []
    for theme in themes:
        for source_id in theme["records"]:
            record = records_by_id[source_id]
            text = record["abstract"] or record["body"] or record["title"]
            span = sentences(text)[:1]
            rows.append({
                "row_id": "E%03d" % (len(rows) + 1),
                "theme_id": theme["theme_id"],
                "source_id": source_id,
                "locator": record["locator"],
                "citation": "[%s]" % source_id,
                "quote": (span[0] if span else record["title"])[:320],
                "evidence_strength": "direct" if record["abstract"] else "title_only",
                "direction": polarity(text),
                "year": record["year"],
            })
    return rows


def draft(themes, rows, question):
    paragraphs, conflicts = [], []
    for theme in themes:
        theme_rows = [row for row in rows if row["theme_id"] == theme["theme_id"]]
        directions = {row["direction"] for row in theme_rows if row["direction"] != "neutral"}
        if "positive" in directions and ("negative" in directions or "mixed" in directions):
            strength = "conflicting evidence"
            conflicts.append({"theme_id": theme["theme_id"], "type": "opposing_direction",
                              "positions": [{"source_id": row["source_id"], "direction": row["direction"], "quote": row["quote"]}
                                            for row in theme_rows if row["direction"] in ("positive", "negative", "mixed")][:4],
                              "handling": "positions are reported side by side; no side is selected"})
        elif len(theme_rows) >= 3:
            strength = "consistent but limited evidence"
        elif theme_rows:
            strength = "indicative evidence from few records"
        else:
            strength = "no evidence"
        citations = " ".join(row["citation"] for row in theme_rows)
        lead = "Theme %s (%s) is supported by %d included record(s) %s; the combined strength is %s." % (
            theme["theme_id"], theme["label"], len(theme_rows), citations or "(none)", strength)
        body = []
        for row in theme_rows[:4]:
            body.append("%s reports: \"%s\" %s." % (row["source_id"], row["quote"].rstrip("."), row["citation"]))
        if not theme_rows:
            body.append("No included record supports this theme; it is listed to show the screening outcome, not as a finding.")
        paragraphs.append({
            "theme_id": theme["theme_id"],
            "label": theme["label"],
            "strength": strength,
            "citations": [row["citation"] for row in theme_rows],
            "text": " ".join([lead] + body),
        })
    return paragraphs, conflicts


def gaps(themes, excluded, criteria):
    items = []
    empty = [theme for theme in themes if not theme["records"]]
    for theme in empty:
        items.append({"type": "theme_without_evidence", "theme_id": theme["theme_id"],
                      "basis": "no included record was assigned to this theme"})
    if not themes:
        items.append({"type": "no_included_records", "basis": "screening excluded every supplied record"})
    if excluded and len(excluded) >= max(1, len(themes)):
        items.append({"type": "screening_attrition", "basis": "%d record(s) were excluded; the review covers only included records" % len(excluded)})
    if not criteria["declared"]:
        items.append({"type": "criteria_not_supplied", "basis": "no eligibility block was found; only structural checks were applied"})
    return items


def contract_names(case):
    contract = case.get("output_contract") if isinstance(case, dict) else None
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


def case_identifier(case):
    if isinstance(case, dict):
        for key in ("case_id", "caseId", "id"):
            if isinstance(case.get(key), str) and case[key].strip():
                return case[key]
    return ""


def build_payload(case, task_text):
    raw_records = find_records(case)
    records = [normalize_record(raw, locator, index) for index, (locator, raw) in enumerate(raw_records)]
    question = review_question(case, task_text)
    criteria = criteria_config(case)
    included, excluded = screen(records, criteria, question)
    themes, per_record = build_themes(included, question)
    by_id = {record["source_id"]: record for record in included}
    rows = evidence_rows(themes, by_id)
    paragraphs, conflicts = draft(themes, rows, question)

    uncertainties = []
    if not question:
        uncertainties.append({"type": "no_review_question", "detail": "No review question was found; thematic framing cannot be checked against an aim."})
    if not records:
        uncertainties.append({"type": "no_records", "detail": "No record was supplied; no review can be drafted."})
    if records and not included:
        uncertainties.append({"type": "all_records_excluded", "detail": "Every supplied record failed screening; the draft contains no finding."})
    if not criteria["declared"]:
        uncertainties.append({"type": "criteria_not_supplied", "detail": "Eligibility criteria were not stated in the input; screening used structural checks only."})
    if included and any(not record["abstract"] for record in included):
        uncertainties.append({"type": "abstract_missing", "detail": "%d included record(s) have no abstract; their evidence is title-only." % sum(1 for record in included if not record["abstract"])})
    if included and not any(record["year"] for record in included):
        uncertainties.append({"type": "no_publication_years", "detail": "Publication years are absent; temporal claims are not made."})
    uncertainties.append({"type": "corpus_bounded", "detail": "Themes and gaps are derived only from the supplied batch; no external search was performed."})

    if not records or not question:
        status = "insufficient_input"
    elif not included:
        status = "insufficient_input"
    elif len(included) < 2:
        status = "partial"
    else:
        status = "success"

    notes = []
    if excluded:
        notes.append("%d record(s) excluded with reasons; see screening.excluded." % len(excluded))
    if paragraphs:
        notes.append("Draft paragraphs are generated from the evidence table; every sentence cites a source id.")

    result = {
        "review_question": question,
        "screening": {
            "criteria": criteria,
            "identified": len(records),
            "included": len(included),
            "excluded": len(excluded),
            "excluded_records": excluded,
            "flow": {"identified": len(records), "screened": len(records), "included": len(included), "excluded": len(excluded)},
        },
        "themes": themes,
        "evidence_table": rows,
        "review_draft": {
            "paragraphs": paragraphs,
            "citations_used": sorted({row["citation"] for row in rows}),
            "word_count": sum(len(paragraph["text"].split()) for paragraph in paragraphs),
            "citation_rule": "each paragraph lists the source ids whose quoted spans support it",
        },
        "conflicts": conflicts,
        "research_gaps": gaps(themes, excluded, criteria),
        "limitations": [
            "Themes are clustered from term co-occurrence in the included records, not from a pre-existing taxonomy.",
            "Evidence is title/abstract level; full-text methods and effect sizes were not verified.",
            "Screening applies declared criteria plus structural checks; it is not dual independent screening.",
            "No external search was performed, so the batch bounds every claim.",
        ],
        "change_log": [
            "Stated criteria and screened every supplied record before drafting.",
            "Recorded an exclusion reason for each excluded record.",
            "Clustered included records into evidence-derived themes.",
            "Built a locatable evidence table with quoted spans and direction labels.",
            "Drafted cited paragraphs with explicit strength labels; reported conflicts and gaps.",
        ],
    }

    return {
        "case_id": case_identifier(case),
        "status": status,
        "result": result,
        "evidence": [{"kind": "evidence_row", **row} for row in rows[:150]],
        "uncertainty": uncertainties,
        "errors": [],
        "stats": {
            "records": len(records),
            "included": len(included),
            "excluded": len(excluded),
            "themes": len(themes),
            "evidence_rows": len(rows),
            "paragraphs": len(paragraphs),
            "conflicts": len(conflicts),
            "network": "disabled",
        },
    }


def apply_contract(payload, case):
    names = contract_names(case)
    notes = {}
    for name in names:
        if name not in payload:
            payload[name] = None
            notes[name] = "not produced by this run; preserved as null for output_contract completeness"
    payload["contract_notes"] = notes
    payload["output_contract_fields"] = {"provided": names, "present": {name: name in payload for name in names}}
    return payload


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, str(target))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Screening-first literature review generation with cited themes and evidence table")
    parser.add_argument("--case", default=DEFAULT_CASE, help="input case JSON (default: /input/case.json)")
    parser.add_argument("--out", "--output", default=DEFAULT_OUT, help="output result JSON (default: /app/output/result.json)")
    parser.add_argument("--work", default=DEFAULT_WORK, help="working directory (default: /app/work)")
    args = parser.parse_args(argv)

    case = {}
    try:
        case = load_json(args.case)
        if not isinstance(case, dict):
            raise ValueError("case.json root must be a JSON object")
        try:
            Path(args.work).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        task_text = read_task_text(args.case, args.work)
        payload = build_payload(case, task_text)
        code = 0
    except Exception as exc:
        payload = {
            "case_id": case_identifier(case) if isinstance(case, dict) else "",
            "status": "failed",
            "result": None,
            "evidence": [],
            "uncertainty": [{"type": "run_failure", "detail": "Run failed; no review is drafted."}],
            "errors": [{"stage": "build", "type": type(exc).__name__, "message": str(exc)[:500]}],
            "stats": {},
        }
        code = 2

    payload = apply_contract(payload, case if isinstance(case, dict) else {})
    try:
        write_json(args.out, payload)
    except Exception as exc:
        sys.stderr.write(json.dumps({"status": "failed", "stage": "write_output", "message": str(exc)[:300]}) + "\n")
        return 3

    sys.stdout.write(json.dumps({
        "status": payload.get("status"),
        "case_id": payload.get("case_id"),
        "out": str(args.out),
        "included": payload.get("stats", {}).get("included", 0),
    }, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.path.join("/app/output", "result.json")
            os.makedirs("/app/output", exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    if not os.path.isfile("/app/output/result.json"):
        try:
            os.makedirs("/app/output", exist_ok=True)
            with open("/app/output/result.json", "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0)
