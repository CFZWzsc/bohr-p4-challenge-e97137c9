#!/usr/bin/env python3
"""Emit secondary review artifacts from fields already inside result.json.

Artifacts produced (all deterministic, standard library only):
  synthesis_matrix.csv, screening_log.csv, prisma_flow.svg,
  provenance.json, validation.json, research_report.docx

No fact is introduced here: every cell/box/block is a formatting of a field
that already exists in the result payload.
"""

import sys

sys.dont_write_bytecode = True

import csv
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

DOCX_DATE = (1980, 1, 1, 0, 0, 0)


def _csv_text(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["" if value is None else value for value in header])
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()


def _theme_map(payload):
    mapping = {}
    for theme in payload.get("themes") or []:
        theme_id = theme.get("theme_id")
        for claim_id in theme.get("supporting_claim_ids") or []:
            mapping.setdefault(claim_id, set()).add(theme_id)
    return {claim_id: sorted(ids) for claim_id, ids in mapping.items()}


def render_synthesis_matrix(payload):
    source_map = {source.get("source_id"): source for source in payload.get("sources") or []}
    theme_map = _theme_map(payload)
    header = ["claim_id", "sub_question_id", "support_level", "direction", "source_id",
              "source_title", "locator", "theme_ids", "quote", "claim_text"]
    rows = []
    for claim in payload.get("claims") or []:
        source = source_map.get(claim.get("source_id"), {})
        rows.append([
            claim.get("claim_id"),
            claim.get("sub_question_id"),
            claim.get("support_level"),
            claim.get("direction"),
            claim.get("source_id"),
            source.get("title"),
            claim.get("locator"),
            ";".join(theme_map.get(claim.get("claim_id"), [])),
            claim.get("quote"),
            claim.get("text"),
        ])
    return _csv_text(header, rows)


def render_screening_log(payload):
    source_map = {source.get("source_id"): source for source in payload.get("sources") or []}
    header = ["source_id", "title", "round", "decision", "criterion_code", "criterion_source",
              "criteria_text", "rule_source", "checked_fields", "reason"]
    rows = []
    for entry in payload.get("screening") or []:
        source = source_map.get(entry.get("source_id"), {})
        rows.append([
            entry.get("source_id"),
            source.get("title"),
            entry.get("round"),
            entry.get("decision"),
            entry.get("criterion_code"),
            entry.get("criterion_source"),
            entry.get("criteria_text"),
            entry.get("rule_source"),
            ";".join(entry.get("checked_fields") or []),
            entry.get("reason"),
        ])
    return _csv_text(header, rows)


def render_prisma_svg(payload):
    counts = payload.get("prisma") or {}
    steps = [
        ("Records identified", counts.get("n_identified", 0)),
        ("Duplicates removed", counts.get("n_duplicates", 0)),
        ("Records screened", counts.get("n_screened", 0)),
        ("Excluded by code", counts.get("n_excluded_by_code", 0)),
        ("Studies included", counts.get("n_included", 0)),
    ]
    width = 460
    box_w = 340
    box_h = 44
    gap = 60
    height = 30 + gap * len(steps) + 10
    boxes = []
    y = 20
    for index, (label, value) in enumerate(steps):
        boxes.append(
            '<rect x="40" y="%d" width="%d" height="%d" fill="#eef3fa" stroke="#3b6fb5"/>'
            '<text x="52" y="%d" font-size="13">%s: %s</text>' % (
                y, box_w, box_h, y + 27, escape(str(label)), escape(str(value))))
        if index:
            boxes.append(
                '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#333" marker-end="url(#a)"/>' % (
                    box_w // 2 + 40, y - 16, box_w // 2 + 40, y))
        y += gap
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
        '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">'
        '<path d="M0,0 L8,4 L0,8 z" fill="#333"/></marker></defs>'
        '<rect width="%d" height="%d" fill="white"/>%s</svg>' % (
            width, height, width, height, width, height, "".join(boxes)))


def build_provenance(payload):
    manifest = payload.get("input_manifest") or []
    sha_by_path = {}
    for item in manifest:
        sha_by_path[item.get("path")] = item.get("sha256") or ""
    theme_map = _theme_map(payload)
    claim_by_source = {}
    for claim in payload.get("claims") or []:
        claim_by_source.setdefault(claim.get("source_id"), []).append(claim.get("claim_id"))
    screened_by_source = {}
    for entry in payload.get("screening") or []:
        screened_by_source.setdefault(entry.get("source_id"), []).append(entry.get("criterion_code"))
    source_map = {}
    for source in payload.get("sources") or []:
        source_id = source.get("source_id")
        origin = source.get("origin") or ""
        source_map[source_id] = {
            "title": source.get("title"),
            "origin": origin,
            "locator_prefix": source.get("locator_prefix"),
            "sha256": sha_by_path.get(origin, ""),
            "included_in_evidence": bool(source.get("included_in_evidence", True)),
            "duplicate_of": source.get("duplicate_of"),
            "cited_by_claims": sorted(claim_by_source.get(source_id, [])),
            "screened_by_codes": screened_by_source.get(source_id, []),
        }
    claim_map = {}
    for claim in payload.get("claims") or []:
        claim_map[claim.get("claim_id")] = {
            "sub_question_id": claim.get("sub_question_id"),
            "source_id": claim.get("source_id"),
            "evidence_id": claim.get("evidence_id"),
            "support_level": claim.get("support_level"),
            "direction": claim.get("direction"),
            "locator": claim.get("locator"),
            "quote_verified": bool(claim.get("quote_verified")),
            "theme_ids": theme_map.get(claim.get("claim_id"), []),
        }
    method = payload.get("method") or {}
    return {
        "case_id": payload.get("case_id"),
        "status": payload.get("status"),
        "skill": {"name": method.get("name"), "version": method.get("version")},
        "input_manifest": [
            {"path": item.get("path"), "kind": item.get("kind"),
             "sha256": item.get("sha256"), "status": item.get("status")}
            for item in manifest
        ],
        "source_map": source_map,
        "claim_map": claim_map,
    }


def build_validation(payload):
    return {
        "case_id": payload.get("case_id"),
        "status": payload.get("status"),
        "validator_verdict": payload.get("validator_verdict"),
        "all_checks_passed": bool((payload.get("verification") or {}).get("all_checks_passed")),
        "gates": payload.get("gates") or [],
        "self_check": payload.get("self_check") or [],
        "quote_check_summary": payload.get("quote_check_summary") or {},
        "prisma": payload.get("prisma") or {},
        "boundary": payload.get("boundary") or {},
        "errors": payload.get("errors") or [],
    }


_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="34"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>
</w:styles>"""


def _docx_paragraph(text, style=None):
    ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ""
    return ('<w:p>%s<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (
        ppr, escape(str("" if text is None else text))))


def _docx_table(header, rows):
    borders = ("<w:tblBorders>" + "".join(
        '<w:%s w:val="single" w:sz="4" w:color="999999"/>' % side
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")) + "</w:tblBorders>")
    grid = "<w:tblGrid>" + '<w:gridCol w:w="1800"/>' * len(header) + "</w:tblGrid>"

    def cell(value, bold=False):
        rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
        return ('<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr><w:p><w:r>%s'
                '<w:t xml:space="preserve">%s</w:t></w:r></w:p></w:tc>' % (
                    rpr, escape(str("—" if value is None else value))))

    trs = ["<w:tr>" + "".join(cell(item, True) for item in header) + "</w:tr>"]
    for row in rows:
        trs.append("<w:tr>" + "".join(cell(item) for item in row) + "</w:tr>")
    return ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>%s</w:tblPr>%s%s</w:tbl>' % (
        borders, grid, "".join(trs)))


def _synthesis_sections(payload):
    report = payload.get("report")
    synthesis = report if isinstance(report, dict) else payload.get("synthesis")
    return (synthesis or {}).get("sections") or []


def build_docx_body(payload):
    body = []
    question = payload.get("question") or "（未提供研究问题）"
    body.append(_docx_paragraph("文献综述草稿：%s" % question, "Title"))
    body.append(_docx_paragraph("case_id：%s；status：%s；引用格式：%s" % (
        payload.get("case_id") or "unknown", payload.get("status") or "unknown",
        ((payload.get("synthesis") or {}).get("citation_format") or "")), None))
    for section in _synthesis_sections(payload):
        body.append(_docx_paragraph(str(section.get("heading") or ""), "Heading1"))
        text = str(section.get("text") or "")
        for paragraph in [line for line in text.split("\n") if line.strip()] or [text]:
            body.append(_docx_paragraph(paragraph))
    sources = payload.get("sources") or []
    if sources:
        body.append(_docx_paragraph("参考来源（输入批次）", "Heading1"))
        body.append(_docx_table(
            ["source_id", "title", "year", "study_type", "reliability", "included"],
            [[source.get("source_id"), source.get("title"), source.get("year"),
              source.get("study_type"), (source.get("reliability") or {}).get("level"),
              "yes" if source.get("included_in_evidence", True) else "no"]
             for source in sources]))
    screening = payload.get("screening") or []
    if screening:
        body.append(_docx_paragraph("筛选记录", "Heading1"))
        body.append(_docx_table(
            ["source_id", "round", "decision", "criterion_code", "reason"],
            [[entry.get("source_id"), entry.get("round"), entry.get("decision"),
              entry.get("criterion_code"), entry.get("reason")] for entry in screening]))
    counts = payload.get("prisma") or {}
    if counts:
        body.append(_docx_paragraph("PRISMA 计数", "Heading1"))
        body.append(_docx_paragraph(
            "identified %s；duplicates %s；screened %s；excluded_by_code %s；included %s。" % (
                counts.get("n_identified", 0), counts.get("n_duplicates", 0),
                counts.get("n_screened", 0), counts.get("n_excluded_by_code", 0),
                counts.get("n_included", 0))))
    return "".join(body)


def build_docx_bytes(payload):
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>%s<w:sectPr/></w:body></w:document>' % build_docx_body(payload))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in (("[Content_Types].xml", _CT), ("_rels/.rels", _RELS),
                           ("word/document.xml", document),
                           ("word/_rels/document.xml.rels", _DOC_RELS),
                           ("word/styles.xml", _STYLES)):
            info = zipfile.ZipInfo(name, date_time=DOCX_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def _atomic_write(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(tmp, str(target))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _atomic_write_text(path, text):
    _atomic_write(path, text.encode("utf-8"))


def write_all(payload, out_dir):
    out_dir = Path(out_dir)
    outputs = []

    def emit(name, data, binary=False):
        path = out_dir / name
        if binary:
            _atomic_write(path, data)
        else:
            _atomic_write_text(path, data)
        outputs.append({"name": name, "bytes": path.stat().st_size})

    emit("synthesis_matrix.csv", render_synthesis_matrix(payload))
    emit("screening_log.csv", render_screening_log(payload))
    emit("prisma_flow.svg", render_prisma_svg(payload))
    emit("provenance.json",
         json.dumps(build_provenance(payload), ensure_ascii=False, indent=2) + "\n")
    emit("validation.json",
         json.dumps(build_validation(payload), ensure_ascii=False, indent=2) + "\n")
    emit("research_report.docx", build_docx_bytes(payload), binary=True)
    return outputs
