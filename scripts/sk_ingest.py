#!/usr/bin/env python3
"""Input ingestion, source normalisation and evidence selection (stdlib only).

This module never performs network access and never writes files. It reads the
case JSON, task text and any supplied materials (json/jsonl/xml/csv/txt/md/pdf),
normalises them into sources with locators, and selects locatable evidence
passages for each sub-question.
"""

import sys

sys.dont_write_bytecode = True

import csv
import hashlib
import io
import json
import math
import re
import unicodedata
import zlib
from collections import Counter
from pathlib import Path

try:
    import xml.etree.ElementTree as ET
except Exception:  # pragma: no cover - stdlib should always provide it
    ET = None

SUPPORTED_SUFFIXES = {
    ".json", ".jsonl", ".ndjson", ".xml", ".csv", ".tsv",
    ".txt", ".md", ".markdown", ".pdf",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".mypy_cache"}
RECORD_KEYS = (
    "records", "papers", "documents", "literature", "sources", "items",
    "bibliography", "corpus", "materials", "articles", "studies", "source_records",
)
METADATA_KEYS = {
    "id", "source_id", "record_id", "paper_id", "doi", "year", "publication_year",
    "published", "date", "language", "lang", "venue", "journal", "conference",
    "authors", "author", "study_type", "type", "design", "publication_type",
    "url", "link", "path", "file", "file_path", "pdf", "document", "source_path",
    "title", "name", "reliability", "peer_reviewed", "sample_size", "population",
    "duration", "pages", "publisher", "isbn", "pmid", "arxiv",
}
SKIP_SECTIONS = {
    "references", "bibliography", "acknowledgements", "acknowledgments",
    "funding", "conflict of interest", "conflicts of interest",
}
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "were",
    "was", "are", "has", "have", "had", "into", "than", "then", "there", "their",
    "study", "studies", "paper", "review", "research", "result", "results", "using",
    "used", "based", "between", "among", "effect", "effects", "group", "groups",
    "patient", "patients", "data", "analysis", "finding", "findings", "however",
    "also", "can", "may", "not", "but", "more", "less", "after", "during", "which",
    "does", "did", "how", "what", "why", "when", "whether", "who", "whom", "its",
    "our", "we", "you", "they", "them", "his", "her", "all", "any", "each", "other",
    "such", "some", "most", "many", "much", "very", "been", "being", "about", "over",
    "under", "only", "both", "same", "different", "compared", "comparison",
}
CJK_STOP_BIGRAMS = {
    "研究", "本文", "我们", "以及", "方法", "结果", "结论", "分析", "问题", "证据",
    "文献", "综述", "相关", "进行", "是否", "对于", "一个", "可以", "需要",
    "不同", "之间", "通过", "基于", "这些", "那些", "其中", "并且", "但是",
    "由于", "因此", "如果", "没有", "已经", "能够", "主要", "包括", "以及",
}
NEGATIVE_PHRASES = (
    "no significant", "not significant", "no statistically significant",
    "no difference", "no effect", "no benefit", "no association", "no improvement",
    "did not differ", "did not improve", "failed to", "ineffective", "not effective",
    "no advantage", "worse", "increased risk",
    "无显著", "无统计学显著", "无差异", "无效果", "无效", "不支持", "恶化",
    "没有显著", "未见显著", "未改善", "更差", "不良反应增加",
)
POSITIVE_WORDS = (
    "improve", "improved", "improvement", "reduce", "reduced", "reduction",
    "effective", "efficacy", "benefit", "beneficial", "significant", "superior",
    "protective", "lower", "increased", "increase", "better", "success",
    "改善", "降低", "减少", "有效", "显著", "优于", "提高", "支持", "获益",
)
TOKEN_RE = re.compile(r"[a-z][a-z0-9\-]{2,}")
CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

DEFAULT_POLICY = {
    "version": "1.0.0",
    "evidence": {
        "min_sentence_chars": 25,
        "max_quote_chars": 400,
        "max_passages_per_subquestion": 8,
        "max_passages_per_source_per_subquestion": 2,
        "max_passages_per_source": 80,
        "max_claims": 120,
        "skip_sections": sorted(SKIP_SECTIONS),
    },
    "sources": {
        "max_sources": 300,
        "max_materials": 500,
        "max_file_chars": 400000,
        "max_total_chars": 2000000,
        "max_record_chars": 200000,
    },
    "pdf": {
        "max_chars": 200000,
        "max_raw_bytes": 8388608,
        "low_confidence_min_letters": 40,
        "low_confidence_bad_ratio": 0.1,
    },
    "reliability": {
        "high_min_score": 2.5,
        "medium_min_score": 1.0,
        "doi_points": 1.5,
        "venue_points": 1.0,
        "year_points": 0.5,
        "peer_reviewed_points": 2.0,
        "study_design_points": 1.0,
    },
    "themes": {"similarity_threshold": 0.3, "max_themes": 6, "anchor_terms": 4,
               "synonyms": {}, "labels": {}},
    "screening": {"min_text_chars": 40, "non_empirical_designs": [],
                  "no_primary_outcome_patterns": [], "result_cue_patterns": []},
    "lexicon": {
        "间歇性禁食": ["intermittent fasting", "intermittent", "fasting"],
        "2型糖尿病": ["type 2 diabetes", "t2d", "type 2"],
        "糖尿病": ["diabetes", "diabetic"],
        "血糖": ["glycaemic", "glycemic", "glucose", "hba1c"],
        "依从性": ["adherence", "compliance"],
        "安全性": ["safety", "adverse event"],
        "低血糖": ["hypoglycaemia", "hypoglycemia"],
        "老年": ["older", "elderly", "aged"],
        "长期": ["long-term", "long term"],
        "心血管": ["cardiovascular", "cardiac"],
        "随机": ["randomised", "randomized"],
        "系统综述": ["systematic review"],
        "疗效": ["efficacy", "effectiveness"],
        "风险": ["risk"],
        "干预": ["intervention"],
        "儿童": ["children", "paediatric", "pediatric"],
        "孕妇": ["pregnant", "pregnancy"],
    },
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def norm_space(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return norm_space(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return norm_space(" ".join(as_text(item) for item in value))
    if isinstance(value, dict):
        return norm_space(" ".join(as_text(item) for item in value.values()))
    return norm_space(str(value))


def pick(mapping, names):
    if not isinstance(mapping, dict):
        return None
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        value = mapping.get(name)
        if value in (None, "", [], {}):
            value = lowered.get(str(name).lower())
        if value not in (None, "", [], {}):
            return value
    return None


def parse_year(value):
    if isinstance(value, int):
        return value if 1800 <= value <= 2100 else None
    match = re.search(r"(1[89]\d{2}|20\d{2})", as_text(value))
    return int(match.group(1)) if match else None


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override if override is not None else base
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_policy(root):
    policy = deep_merge({}, DEFAULT_POLICY)
    path = Path(root) / "assets" / "policy.json"
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            policy = deep_merge(policy, loaded)
    except (OSError, ValueError, TypeError):
        pass
    if not isinstance(policy.get("lexicon"), dict):
        policy["lexicon"] = dict(DEFAULT_POLICY["lexicon"])
    return policy


def read_text_file(path, max_chars=400000):
    data = b""
    try:
        with open(path, "rb") as handle:
            data = handle.read(max_chars * 4 + 1024)
    except OSError:
        return "", "unreadable", False
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            text = data.decode(encoding)
            truncated = len(data) > max_chars * 4
            return text[:max_chars], "", truncated
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", "replace")[:max_chars], "", True


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# tokenisation
# ---------------------------------------------------------------------------

def stem(word):
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _lexicon_entries(policy):
    lexicon = policy.get("lexicon") if isinstance(policy, dict) else None
    entries = []
    if not isinstance(lexicon, dict):
        return entries
    for zh, values in lexicon.items():
        if not isinstance(zh, str) or not zh:
            continue
        english = []
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            for item in values:
                if isinstance(item, str):
                    english.extend(TOKEN_RE.findall(item.lower()))
        bigrams = [zh[i:i + 2] for i in range(max(0, len(zh) - 1))]
        entries.append((zh, [word for word in english if word not in STOPWORDS], bigrams))
    return entries


def lexicon_english_set(policy):
    anchors = set()
    for _zh, english, _bigrams in _lexicon_entries(policy or DEFAULT_POLICY):
        anchors.update(english)
    return anchors


def _contains_phrase(lowered, phrase):
    if not phrase:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return re.search(pattern, lowered) is not None


def tokenize(text, policy=None, limit=None):
    """Language-bridged deterministic tokenisation.

    English words are stemmed; Chinese text is represented as bigrams. A small
    bilingual lexicon in assets/policy.json is used in both directions so that a
    Chinese question can match English source text and vice versa.
    """
    text = norm_space(text)
    if not text:
        return []
    lowered = text.lower()
    tokens = []
    for word in TOKEN_RE.findall(lowered):
        if word in STOPWORDS:
            continue
        tokens.append(stem(word))
    for chunk in CJK_RE.findall(text):
        for index in range(len(chunk) - 1):
            bigram = chunk[index:index + 2]
            if bigram not in CJK_STOP_BIGRAMS:
                tokens.append(bigram)
    entries = _lexicon_entries(policy or DEFAULT_POLICY)
    for zh, english, bigrams in entries:
        if zh in text:
            tokens.extend(stem(word) for word in english)
        else:
            hit = False
            for phrase in english:
                if _contains_phrase(lowered, phrase):
                    hit = True
                    break
            if hit:
                tokens.extend(bigrams)
    seen = set()
    ordered = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)
    if limit:
        return ordered[:limit]
    return ordered


def polarity(text):
    """Return (stance, cues). Negative phrases are removed before positives."""
    lowered = norm_space(text).lower()
    cleaned = lowered
    negative_hits = []
    for phrase in NEGATIVE_PHRASES:
        if phrase in cleaned:
            negative_hits.append(phrase)
            cleaned = cleaned.replace(phrase, " ")
    positive_hits = [word for word in POSITIVE_WORDS if word in cleaned]
    if negative_hits and positive_hits:
        stance = "mixed"
    elif negative_hits:
        stance = "refutes"
    elif positive_hits:
        stance = "supports"
    else:
        stance = "neutral"
    return stance, (negative_hits + positive_hits)[:6]


# ---------------------------------------------------------------------------
# sentence / passage splitting
# ---------------------------------------------------------------------------

def split_passages(text, min_chars=25, max_chars=600):
    """Split normalised text into exact-substring sentence passages."""
    text = norm_space(text)
    if not text:
        return []
    spans = []
    cursor = 0
    for match in re.finditer(r"[^。！？.!?;；]+[。！？.!?;；]?", text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        start = match.start() + raw.find(stripped)
        spans.append((start, start + len(stripped), stripped))
    if not spans:
        spans = [(0, len(text), text)]
    passages = []
    for start, end, piece in spans:
        piece = piece.strip()
        if len(piece) > max_chars:
            cut = piece[:max_chars]
            # keep an exact substring, preferably ending at a clause boundary
            boundary = max(cut.rfind(", "), cut.rfind("，"), cut.rfind("; "), cut.rfind("；"))
            if boundary > max_chars * 0.5:
                cut = cut[:boundary + 1]
            piece = cut.strip()
        if len(piece) < min_chars:
            continue
        offset = text.find(piece, start)
        if offset < 0:
            offset = start
        passages.append({"text": piece, "char_start": offset})
    return passages


# ---------------------------------------------------------------------------
# PDF extraction (incremental, heuristic, flagged when uncertain)
# ---------------------------------------------------------------------------

def _pdf_unescape(raw):
    out = bytearray()
    index = 0
    mapping = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12, 40: 40, 41: 41, 92: 92}
    while index < len(raw):
        char = raw[index]
        if char == 92 and index + 1 < len(raw):
            nxt = raw[index + 1]
            if nxt in mapping:
                out.append(mapping[nxt])
                index += 2
                continue
            if 48 <= nxt <= 55:
                digits = b""
                cursor = index + 1
                while cursor < len(raw) and len(digits) < 3 and 48 <= raw[cursor] <= 55:
                    digits += bytes([raw[cursor]])
                    cursor += 1
                try:
                    out.append(int(digits, 8) & 0xFF)
                except ValueError:
                    pass
                index = cursor
                continue
            if nxt in (10, 13):
                index += 2
                continue
            out.append(nxt)
            index += 2
            continue
        out.append(char)
        index += 1
    return bytes(out)


def _decode_pdf_string(raw):
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", "replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", "replace")
    return raw.decode("latin-1", "replace")


def _pdf_stream_strings(content):
    pieces = []
    index = 0
    length = len(content)
    while index < length:
        char = content[index]
        if char == "(":
            depth = 1
            cursor = index + 1
            buffer = []
            while cursor < length and depth > 0:
                current = content[cursor]
                if current == "\\":
                    buffer.append(current)
                    if cursor + 1 < length:
                        buffer.append(content[cursor + 1])
                        cursor += 2
                        continue
                if current == "(":
                    depth += 1
                elif current == ")":
                    depth -= 1
                    if depth == 0:
                        cursor += 1
                        break
                buffer.append(current)
                cursor += 1
            raw = "".join(buffer).encode("latin-1", "ignore")
            pieces.append(_decode_pdf_string(_pdf_unescape(raw)))
            index = cursor
        elif char == "<":
            end = content.find(">", index + 1)
            if end < 0:
                break
            hexstr = re.sub(r"\s+", "", content[index + 1:end])
            if len(hexstr) % 2:
                hexstr += "0"
            try:
                raw = bytes.fromhex(hexstr)
            except ValueError:
                raw = b""
            pieces.append(_decode_pdf_string(raw))
            index = end + 1
        else:
            index += 1
    return pieces


def extract_pdf(path, policy):
    settings = policy.get("pdf", {})
    max_chars = safe_int(settings.get("max_chars"), 200000)
    max_raw = safe_int(settings.get("max_raw_bytes"), 8388608)
    min_letters = safe_int(settings.get("low_confidence_min_letters"), 40)
    bad_ratio = float(settings.get("low_confidence_bad_ratio", 0.1) or 0.1)
    try:
        with open(path, "rb") as handle:
            data = handle.read(max_raw + 1)
    except OSError as exc:
        return {"sections": [], "text": "", "low_confidence": True,
                "notes": ["unreadable_pdf: %s" % type(exc).__name__], "pages": 0}
    truncated_raw = len(data) > max_raw
    if b"/Encrypt" in data[:200000]:
        return {"sections": [], "text": "", "low_confidence": True,
                "notes": ["encrypted_pdf"], "pages": 0}
    stream_pattern = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
    streams = []
    for match in stream_pattern.finditer(data):
        raw = match.group(1)
        header = data[max(0, match.start() - 400):match.start()]
        if b"FlateDecode" in header:
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                try:
                    raw = zlib.decompressobj().decompress(raw)
                except zlib.error:
                    continue
        streams.append(raw)
    page_count = len(re.findall(rb"/Type\s*/Page\b", data))
    sections = []
    total = 0
    for stream_index, stream in enumerate(streams):
        if total >= max_chars:
            break
        content = stream.decode("latin-1", "ignore")
        blocks = re.findall(r"BT(.*?)ET", content, re.S)
        chunks = []
        for block in blocks or [content]:
            pieces = _pdf_stream_strings(block)
            if pieces:
                chunks.append(" ".join(piece for piece in pieces if piece.strip()))
        text = norm_space(" ".join(chunks))
        if not text:
            continue
        text = text[:max(0, max_chars - total)]
        total += len(text)
        if page_count and len(streams) >= page_count:
            page = stream_index + 1
            base = "p%d" % page
        else:
            page = None
            base = "stream=%d" % (stream_index + 1)
        sections.append({"name": "pdf_text", "text": text, "page": page,
                         "locator_suffix": base})
    text_all = norm_space(" ".join(section["text"] for section in sections))
    letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", text_all))
    bad = len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]", text_all))
    notes = []
    low_confidence = False
    if letters < min_letters:
        low_confidence = True
        notes.append("too_few_letters")
    if letters and bad / float(max(1, letters + bad)) > bad_ratio:
        low_confidence = True
        notes.append("high_non_printable_ratio")
    if not sections:
        low_confidence = True
        notes.append("no_text_stream_decoded")
    if not page_count:
        notes.append("page_count_unknown")
    if truncated_raw or total >= max_chars:
        notes.append("truncated")
    return {"sections": sections, "text": text_all, "low_confidence": low_confidence,
            "notes": notes, "pages": page_count}


# ---------------------------------------------------------------------------
# source construction
# ---------------------------------------------------------------------------

def looks_like_record(node):
    if not isinstance(node, dict):
        return False
    keys = {str(key).lower() for key in node.keys()}
    if keys & {"abstract", "doi", "full_text", "abstract_text", "summary"}:
        return True
    if "title" in keys and keys & {"year", "authors", "venue", "journal", "url",
                                   "text", "content", "study_type", "design"}:
        return True
    if "text" in keys and len(as_text(node.get("text"))) > 120:
        return True
    return False


def find_record_nodes(root):
    """Yield (json-path, record-dict) pairs in deterministic document order."""
    if isinstance(root, list):
        for index, item in enumerate(root):
            if isinstance(item, dict):
                yield "/%d" % index, item
            elif isinstance(item, str) and item.strip():
                yield "/%d" % index, {"text": item}
        return
    if not isinstance(root, dict):
        return
    for key in RECORD_KEYS:
        value = root.get(key)
        if isinstance(value, list) and value:
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    yield "/%s/%d" % (key, index), item
                elif isinstance(item, str) and item.strip():
                    yield "/%s/%d" % (key, index), {"text": item}
            return
        if isinstance(value, dict) and value:
            for item_key, item in value.items():
                if isinstance(item, dict):
                    yield "/%s/%s" % (key, item_key), item
                elif isinstance(item, str) and item.strip():
                    yield "/%s/%s" % (key, item_key), {"text": item}
            return
    found = []

    def walk(node, path, depth):
        if depth > 6 or len(found) > 2000:
            return
        if isinstance(node, dict):
            if path and looks_like_record(node):
                found.append((path, node))
                return
            for key, value in node.items():
                if str(key).lower() in {"output_contract", "criteria", "protocol", "constraints"}:
                    continue
                walk(value, path + "/" + str(key), depth + 1)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + "/" + str(index), depth + 1)

    walk(root, "", 0)
    return iter(found)


def reliability_for(meta, policy):
    settings = policy.get("reliability", {})
    score = 0.0
    basis = []
    if as_text(meta.get("doi")):
        score += float(settings.get("doi_points", 1.5))
        basis.append("doi")
    if as_text(meta.get("venue") or meta.get("journal")):
        score += float(settings.get("venue_points", 1.0))
        basis.append("venue")
    if parse_year(meta.get("year")):
        score += float(settings.get("year_points", 0.5))
        basis.append("year")
    if meta.get("peer_reviewed") is True or str(meta.get("peer_reviewed")).lower() in {"true", "yes", "1"}:
        score += float(settings.get("peer_reviewed_points", 2.0))
        basis.append("peer_reviewed")
    design = (as_text(meta.get("study_type")) + " " + as_text(meta.get("design")) + " " +
              as_text(meta.get("type"))).lower()
    if any(word in design for word in ("trial", "cohort", "systematic review", "meta-analysis",
                                       "randomised", "randomized", "case-control", "实验", "队列", "系统综述")):
        score += float(settings.get("study_design_points", 1.0))
        basis.append("study_design")
    explicit = as_text(meta.get("reliability")).lower()
    if explicit in {"high", "medium", "low", "unknown"}:
        level = explicit
        basis.append("explicit_reliability")
    elif score >= float(settings.get("high_min_score", 2.5)):
        level = "high"
    elif score >= float(settings.get("medium_min_score", 1.0)):
        level = "medium"
    elif score > 0:
        level = "low"
    else:
        level = "unknown"
    return {"level": level, "score": round(score, 2), "basis": basis}


FIELD_ALIASES = (
    ("title", ("title", "name", "headline")),
    ("abstract", ("abstract", "abstract_text", "summary")),
    ("background", ("background", "introduction")),
    ("objective", ("objective", "aim", "purpose")),
    ("methods", ("methods", "method", "methodology", "design")),
    ("results", ("results", "result", "findings", "outcomes")),
    ("discussion", ("discussion", "interpretation")),
    ("conclusion", ("conclusion", "conclusions", "implications")),
    ("limitations", ("limitations", "limitation")),
    ("text", ("text", "body", "content", "full_text", "fulltext", "transcript")),
)


def record_to_source(raw, jsonpath, origin, policy, provisional_id=None):
    meta = {}
    for key, value in raw.items():
        if isinstance(value, (str, int, float, bool)) and str(key).lower() in METADATA_KEYS:
            meta[str(key).lower()] = value
    title = as_text(pick(raw, FIELD_ALIASES[0][1]))
    sections = []
    seen_text = set()
    for name, aliases in FIELD_ALIASES:
        value = as_text(pick(raw, aliases))
        if not value:
            continue
        key = norm_space(value).lower()
        if key in seen_text:
            continue
        seen_text.add(key)
        sections.append({
            "name": name,
            "text": value,
            "locator_suffix": name,
            "page": None,
        })
    if not title and sections:
        title = sections[0]["text"][:160]
    if not sections and not title:
        return None
    text_all = norm_space(" ".join(section["text"] for section in sections))
    max_record = safe_int(policy.get("sources", {}).get("max_record_chars"), 200000)
    if len(text_all) > max_record:
        for section in sections:
            section["text"] = section["text"][:max_record]
        text_all = text_all[:max_record]
    meta.update({"title": title, "origin": origin})
    source_id = as_text(pick(raw, ("source_id", "record_id", "paper_id", "id"))) or provisional_id
    path_ref = as_text(pick(raw, ("path", "file", "file_path", "pdf", "document", "source_path")))
    if not path_ref:
        only_text = as_text(raw.get("text")) if isinstance(raw, dict) else ""
        if only_text.lower().endswith(tuple(SUPPORTED_SUFFIXES)):
            path_ref = only_text
            if not title:
                title = Path(only_text).stem
    if jsonpath:
        path_prefix = jsonpath if jsonpath.startswith("#") else "#" + jsonpath
    else:
        path_prefix = "#"
    return {
        "source_id": source_id,
        "title": title or as_text(pick(raw, ("source_id", "id"))) or "untitled",
        "text": text_all,
        "sections": sections,
        "origin": origin,
        "locator_prefix": origin + path_prefix,
        "year": parse_year(pick(raw, ("year", "publication_year", "published", "date"))),
        "language": as_text(pick(raw, ("language", "lang"))).lower(),
        "venue": as_text(pick(raw, ("venue", "journal", "conference"))),
        "doi": as_text(pick(raw, ("doi", "DOI"))),
        "authors": as_text(pick(raw, ("authors", "author"))),
        "study_type": as_text(pick(raw, ("study_type", "type", "design", "publication_type"))),
        "meta": meta,
        "reliability": reliability_for(meta, policy),
        "low_confidence": False,
        "confidence": "high",
        "confidence_notes": [],
        "path_ref": path_ref,
        "duplicate_of": None,
        "included_in_evidence": True,
    }


def text_source(title, sections, origin, policy, low_confidence=False, notes=None,
                confidence="high", meta=None):
    text_all = norm_space(" ".join(section["text"] for section in sections))
    max_file = safe_int(policy.get("sources", {}).get("max_file_chars"), 400000)
    if len(text_all) > max_file:
        text_all = text_all[:max_file]
    meta = dict(meta or {})
    meta.update({"title": title, "origin": origin})
    return {
        "source_id": None,
        "title": title or origin,
        "text": text_all,
        "sections": sections,
        "origin": origin,
        "locator_prefix": origin,
        "year": parse_year(meta.get("year")),
        "language": as_text(meta.get("language")).lower(),
        "venue": as_text(meta.get("venue")),
        "doi": as_text(meta.get("doi")),
        "authors": as_text(meta.get("authors")),
        "study_type": as_text(meta.get("study_type")),
        "meta": meta,
        "reliability": reliability_for(meta, policy),
        "low_confidence": bool(low_confidence),
        "confidence": confidence,
        "confidence_notes": list(notes or []),
        "path_ref": "",
        "duplicate_of": None,
        "included_in_evidence": True,
    }


def _flatten_strings(node, limit=200000):
    parts = []

    def walk(value):
        if len(parts) > 2000:
            return
        if isinstance(value, str):
            text = norm_space(value)
            if len(text) >= 2:
                parts.append(text)
        elif isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"id", "doi", "url"}:
                    continue
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return norm_space(" ".join(parts))[:limit]


def _markdown_sections(text):
    lines = text.splitlines()
    sections = []
    heading = ""
    buffer = []
    index = 0

    def flush():
        body = norm_space("\n".join(buffer))
        if body:
            sections.append({"name": heading or "section_%d" % (index + 1), "text": body,
                             "locator_suffix": "sec=%d" % (index + 1), "page": None})

    for line in lines:
        if re.match(r"^\s{0,3}#{1,6}\s+\S", line):
            flush()
            buffer = []
            index += 1
            heading = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()[:120]
        else:
            buffer.append(line)
    flush()
    if not sections:
        paragraphs = [norm_space(part) for part in re.split(r"\n\s*\n", text) if norm_space(part)]
        for idx, paragraph in enumerate(paragraphs):
            sections.append({"name": "paragraph_%d" % (idx + 1), "text": paragraph,
                             "locator_suffix": "p=%d" % (idx + 1), "page": None})
    return sections


def sources_from_file(path, rel, policy):
    suffix = path.suffix.lower()
    max_file = safe_int(policy.get("sources", {}).get("max_file_chars"), 400000)
    text, error, truncated = read_text_file(path, max_file)
    notes = []
    if truncated:
        notes.append("truncated")
    if error:
        return [], ["unreadable_material: %s (%s)" % (rel, error)]
    if not text.strip():
        return [], ["empty_material: %s" % rel]
    if suffix == ".pdf":
        extracted = extract_pdf(path, policy)
        sections = []
        for index, section in enumerate(extracted["sections"]):
            sections.append({
                "name": section["name"],
                "text": section["text"],
                "locator_suffix": section["locator_suffix"],
                "page": section.get("page"),
            })
        if not sections:
            return [], ["pdf_no_text: %s" % rel]
        title = Path(rel).stem
        confidence = "low" if extracted["low_confidence"] else "high"
        return [text_source(title, sections, rel, policy,
                            low_confidence=extracted["low_confidence"],
                            notes=notes + extracted["notes"], confidence=confidence,
                            meta={"file": rel, "pages": extracted["pages"]})], []
    if suffix in (".md", ".markdown"):
        sections = _markdown_sections(text)
        title = sections[0]["name"] if sections else Path(rel).stem
        return [text_source(title, sections, rel, policy, notes=notes,
                            meta={"file": rel})], []
    if suffix in (".txt",):
        paragraphs = [norm_space(part) for part in re.split(r"\n\s*\n", text) if norm_space(part)]
        if len(paragraphs) <= 1:
            paragraphs = [text]
        sections = []
        for index, paragraph in enumerate(paragraphs):
            sections.append({"name": "paragraph_%d" % (index + 1), "text": paragraph,
                             "locator_suffix": "p=%d" % (index + 1), "page": None})
        title = paragraphs[0][:120] if paragraphs else Path(rel).stem
        return [text_source(title, sections, rel, policy, notes=notes,
                            meta={"file": rel})], []
    if suffix in (".json", ".jsonl", ".ndjson"):
        records = []
        if suffix == ".json":
            try:
                data = json.loads(text)
            except ValueError as exc:
                return [], ["json_parse_error: %s (%s)" % (rel, type(exc).__name__)]
            records = list(find_record_nodes(data))
            if not records:
                flattened = _flatten_strings(data)
                if not flattened:
                    return [], ["empty_material: %s" % rel]
                return [text_source(Path(rel).stem, [{
                    "name": "document", "text": flattened,
                    "locator_suffix": "document", "page": None,
                }], rel, policy, notes=notes, meta={"file": rel})], []
            built = []
            for jsonpath, raw in records:
                source = record_to_source(raw, jsonpath, rel, policy)
                if source:
                    built.append(source)
            return built, ([] if built else ["no_records_in_json: %s" % rel])
        built = []
        leftovers = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                leftovers.append(line)
                continue
            if isinstance(item, dict) and looks_like_record(item):
                source = record_to_source(item, "#line=%d" % line_no, rel, policy)
                if source:
                    built.append(source)
            else:
                leftovers.append(as_text(item))
        if built:
            return built, []
        joined = norm_space(" ".join(leftovers))
        if not joined:
            return [], ["empty_material: %s" % rel]
        return [text_source(Path(rel).stem, [{
            "name": "document", "text": joined,
            "locator_suffix": "document", "page": None,
        }], rel, policy, notes=notes, meta={"file": rel})], []
    if suffix in (".csv", ".tsv"):
        delimiter = "\t" if suffix == ".tsv" else ","
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
        except (csv.Error, ValueError) as exc:
            return [], ["csv_parse_error: %s (%s)" % (rel, type(exc).__name__)]
        if rows and reader.fieldnames:
            fields = {str(name).lower() for name in reader.fieldnames if name}
            if fields & {"title", "abstract", "text", "summary", "content"}:
                built = []
                for index, row in enumerate(rows, start=1):
                    source = record_to_source(row, "#row=%d" % index, rel, policy)
                    if source:
                        built.append(source)
                return built, []
        lines = [" | ".join(str(value or "") for value in row.values()) for row in rows]
        joined = norm_space(" ".join(lines))
        if not joined:
            return [], ["empty_material: %s" % rel]
        return [text_source(Path(rel).stem, [{
            "name": "table", "text": joined, "locator_suffix": "table", "page": None,
        }], rel, policy, notes=notes, meta={"file": rel})], []
    if suffix == ".xml":
        if ET is None:
            return [], ["xml_unavailable: %s" % rel]
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            return [], ["xml_parse_error: %s (%s)" % (rel, type(exc).__name__)]
        children = list(root)
        record_children = []
        if children:
            tags = Counter(child.tag for child in children)
            repeated = [tag for tag, count in tags.items() if count >= 2]
            for child in children:
                if child.tag in repeated or looks_like_record(
                        {sub.tag: (sub.text or "") for sub in child}):
                    record_children.append(child)
        built = []
        for index, child in enumerate(record_children, start=1):
            fields = {sub.tag: (sub.text or "") for sub in child}
            if fields:
                source = record_to_source(fields, "/%s[%d]" % (child.tag, index), rel, policy)
                if source:
                    built.append(source)
        if built:
            return built, []
        flattened = norm_space(" ".join(text.strip() for text in root.itertext() if text.strip()))
        if not flattened:
            return [], ["empty_material: %s" % rel]
        return [text_source(Path(rel).stem, [{
            "name": "xml_text", "text": flattened,
            "locator_suffix": "xml", "page": None,
        }], rel, policy, notes=notes, meta={"file": rel})], []
    return [], ["unsupported_material: %s" % rel]


def finalize_sources(sources, policy):
    max_sources = safe_int(policy.get("sources", {}).get("max_sources"), 300)
    sources = sources[:max_sources]
    seen_ids = {}
    seen_doi = {}
    seen_title = {}
    seen_text = {}
    duplicates = []
    for index, source in enumerate(sources):
        source.setdefault("sections", [])
        source.setdefault("meta", {})
        source.setdefault("reliability", {"level": "unknown", "score": 0.0, "basis": []})
        base_id = as_text(source.get("source_id"))
        if not base_id:
            base_id = "S%02d" % (index + 1)
        candidate = base_id
        counter = 2
        while candidate in seen_ids:
            candidate = "%s-%d" % (base_id, counter)
            counter += 1
        source["source_id"] = candidate
        seen_ids[candidate] = source
        source["order"] = index
        doi_key = as_text(source.get("doi")).lower()
        title_key = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", as_text(source.get("title")).lower())
        text_key = sha256_bytes(norm_space(source.get("text", "")).encode("utf-8")) if source.get("text") else ""
        duplicate_of = None
        if doi_key and doi_key in seen_doi:
            duplicate_of = seen_doi[doi_key]
        elif title_key and len(title_key) > 12 and title_key in seen_title:
            duplicate_of = seen_title[title_key]
        elif text_key and text_key in seen_text:
            duplicate_of = seen_text[text_key]
        if duplicate_of:
            source["duplicate_of"] = duplicate_of
            source["included_in_evidence"] = False
            duplicates.append({"source_id": candidate, "duplicate_of": duplicate_of,
                               "basis": "doi" if doi_key and doi_key in seen_doi else
                                        ("title" if title_key and title_key in seen_title else "text")})
        else:
            source["duplicate_of"] = None
            source["included_in_evidence"] = True
            if doi_key:
                seen_doi[doi_key] = candidate
            if title_key:
                seen_title[title_key] = candidate
            if text_key:
                seen_text[text_key] = candidate
    return sources, duplicates


def _with_file_reference(source, input_dir, policy):
    """Merge the content of a referenced local file into a record source."""
    path_ref = source.get("path_ref")
    if not path_ref:
        return source, None
    candidate = Path(path_ref)
    if not candidate.is_absolute():
        candidate = Path(input_dir) / path_ref
    try:
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
            return source, None
    except OSError:
        return source, None
    rel = os_relpath(candidate, input_dir)
    built, errors = sources_from_file(candidate, rel, policy)
    if errors or not built:
        return source, {"path": rel, "error": errors[0] if errors else "no_content"}
    merged_sections = []
    for item in built:
        for section in item.get("sections", []):
            merged_sections.append({
                "name": "%s:%s" % (item.get("source_id") or "file", section.get("name")),
                "text": section["text"],
                "locator_suffix": section.get("locator_suffix") or section.get("name"),
                "page": section.get("page"),
            })
    if merged_sections:
        for section in merged_sections:
            section["locator_base"] = "%s#%s" % (
                rel, section.get("locator_suffix") or section.get("name") or "text")
        source["sections"] = merged_sections + source.get("sections", [])
        source["text"] = norm_space(" ".join(section["text"] for section in source["sections"]))
        source["low_confidence"] = any(item.get("low_confidence") for item in built)
        source["confidence"] = "low" if source["low_confidence"] else "high"
        source["confidence_notes"] = list(source.get("confidence_notes") or [])
    return source, {"path": str(candidate), "used": True}


def os_relpath(path, base):
    try:
        return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).name


def build_sources(case, input_dir, case_path, task_path, files, policy):
    """Build, de-duplicate and limit sources from case records and materials."""
    sources = []
    errors = []
    material_notes = []
    claimed_paths = set()
    case_name = os_relpath(case_path, input_dir) if case_path else "case.json"
    for jsonpath, raw in find_record_nodes(case):
        source = record_to_source(raw, jsonpath, case_name, policy)
        if not source:
            continue
        source, file_info = _with_file_reference(source, input_dir, policy)
        if file_info and file_info.get("used"):
            claimed_paths.add(Path(file_info["path"]).resolve())
        elif file_info and file_info.get("error"):
            material_notes.append({"path": file_info["path"], "error": file_info["error"]})
        sources.append(source)
    if not sources and looks_like_record(case):
        source = record_to_source(case, "", case_name, policy)
        if source:
            sources.append(source)

    file_reports = []
    material_count = 0
    for item in files:
        if item["kind"] != "material":
            file_reports.append(item)
            continue
        resolved = Path(item["path"]).resolve()
        if task_path and resolved == Path(task_path).resolve():
            item = dict(item)
            item["status"] = "task_text"
            file_reports.append(item)
            continue
        if case_path and resolved == Path(case_path).resolve():
            item = dict(item)
            item["status"] = "case"
            item["source_count"] = sum(1 for source in sources
                                       if source.get("origin") == item["rel"])
            file_reports.append(item)
            continue
        if resolved in claimed_paths:
            item = dict(item)
            item["status"] = "referenced_by_case"
            file_reports.append(item)
            continue
        if material_count >= safe_int(policy.get("sources", {}).get("max_materials"), 500):
            item = dict(item)
            item["status"] = "material_limit_reached"
            file_reports.append(item)
            continue
        material_count += 1
        built, file_errors = sources_from_file(Path(item["path"]), item["rel"], policy)
        item = dict(item)
        item["status"] = "parsed" if built else ("unreadable" if file_errors else "empty")
        item["source_count"] = len(built)
        file_reports.append(item)
        if file_errors:
            errors.extend(file_errors)
        sources.extend(built)
    sources, duplicates = finalize_sources(sources, policy)
    if duplicates:
        material_notes.extend({"duplicate": entry} for entry in duplicates)
    return sources, duplicates, errors, material_notes, file_reports


# ---------------------------------------------------------------------------
# question / sub-question parsing
# ---------------------------------------------------------------------------

QUESTION_KEYS = (
    "research_question", "review_question", "question", "research question",
    "topic", "objective", "aim", "prompt", "task_question", "title",
)
SUBQUESTION_KEYS = (
    "sub_questions", "subquestions", "sub-questions", "questions",
    "research_questions", "decomposition", "sub_tasks", "objectives", "aspects",
)


def question_from_case(case, task_text):
    question = ""
    if isinstance(case, dict):
        for key in QUESTION_KEYS:
            value = pick(case, (key,))
            text = as_text(value)
            if text and text.lower() not in {"untitled", "challenge"}:
                if key == "title" and len(text) < 6:
                    continue
                question = text
                break
        if not question:
            for container in ("task", "case", "input", "metadata"):
                nested = case.get(container)
                if isinstance(nested, dict):
                    for key in QUESTION_KEYS:
                        text = as_text(pick(nested, (key,)))
                        if text:
                            question = text
                            break
                    if question:
                        break
    if not question:
        for line in (task_text or "").splitlines():
            clean = norm_space(re.sub(r"^[#>*\-\d.\s]+", "", line))
            if len(clean) >= 12:
                question = clean
                break
    return question


def _subquestion_items(value):
    items = []
    if isinstance(value, str):
        lines = [norm_space(re.sub(r"^[\-\*\d.)、\s]+", "", line)) for line in value.splitlines()]
        items = [line for line in lines if len(line) >= 4]
    elif isinstance(value, list):
        for entry in value:
            if isinstance(entry, str):
                if entry.strip():
                    items.append(entry.strip())
            elif isinstance(entry, dict):
                text = as_text(pick(entry, ("question", "text", "title", "prompt", "description")))
                ident = as_text(pick(entry, ("id", "qid", "sub_question_id", "key")))
                if text:
                    items.append({"id": ident, "question": text})
    elif isinstance(value, dict):
        for key, entry in value.items():
            if isinstance(entry, str) and entry.strip():
                items.append({"id": str(key), "question": entry.strip()})
            elif isinstance(entry, dict):
                text = as_text(pick(entry, ("question", "text", "title", "prompt")))
                if text:
                    items.append({"id": str(key), "question": text})
    return items


def decompose(case, question, policy):
    raw_items = []
    if isinstance(case, dict):
        for key in SUBQUESTION_KEYS:
            value = pick(case, (key,))
            if value:
                raw_items = _subquestion_items(value)
                if raw_items:
                    break
    if not raw_items and isinstance(case, dict):
        for container in ("task", "case", "input"):
            nested = case.get(container)
            if isinstance(nested, dict):
                for key in SUBQUESTION_KEYS:
                    value = pick(nested, (key,))
                    if value:
                        raw_items = _subquestion_items(value)
                        if raw_items:
                            break
                if raw_items:
                    break
    derived = False
    if not raw_items:
        if not question:
            return [], False
        derived = True
        base = question or "给定研究问题"
        raw_items = [
            {"id": "Q1", "dimension": "population",
             "question": "人群（population）：在“%s”中，证据覆盖的人群范围与关键特征（年龄、合并症、场景）是什么？" % base},
            {"id": "Q2", "dimension": "intervention",
             "question": "干预（intervention）：该问题中的干预如何定义、实施与量化（剂量、频次、时长），不同研究是否一致？"},
            {"id": "Q3", "dimension": "outcome",
             "question": "结局（outcome）：相对比较，干预对关键结局指标（方向与幅度）的证据是什么？"},
            {"id": "Q4", "dimension": "comparator",
             "question": "对照（comparator）：与何种对照或常规照护相比，结论是否一致，差异来自哪里？"},
        ]
    sub_questions = []
    seen_ids = set()
    for index, item in enumerate(raw_items[:8]):
        if isinstance(item, str):
            ident, text, dimension = "", item, ""
        else:
            ident, text = item.get("id", ""), item.get("question", "")
            dimension = item.get("dimension", "")
        text = norm_space(text)
        if len(text) < 4:
            continue
        ident = ident or ("Q%d" % (index + 1))
        candidate = ident
        counter = 2
        while candidate in seen_ids:
            candidate = "%s-%d" % (ident, counter)
            counter += 1
        seen_ids.add(candidate)
        sub_question = {
            "sub_question_id": candidate,
            "question": text,
            "source": "derived" if derived else "case",
        }
        if dimension:
            sub_question["dimension"] = dimension
        sub_questions.append(sub_question)
    return sub_questions, derived


# ---------------------------------------------------------------------------
# evidence selection
# ---------------------------------------------------------------------------

def prepare_passages(sources, policy):
    settings = policy.get("evidence", {})
    min_chars = safe_int(settings.get("min_sentence_chars"), 25)
    max_chars = safe_int(settings.get("max_quote_chars"), 400) + 200
    skip = {str(name).lower() for name in settings.get("skip_sections", [])}
    per_source_cap = safe_int(settings.get("max_passages_per_source"), 80)
    for source in sources:
        passages = []
        if not source.get("included_in_evidence", True):
            source["passages"] = []
            continue
        has_body = any(
            str(section.get("name", "")).lower() != "title" and norm_space(section.get("text", ""))
            for section in source.get("sections", []))
        for section in source.get("sections", []):
            name = str(section.get("name", "")).lower()
            if name in skip or name.startswith("reference") or name.startswith("acknowledg"):
                continue
            if name == "title" and has_body:
                continue
            section_text = norm_space(section.get("text", ""))
            if not section_text:
                continue
            base = (section.get("locator_base") or source.get("locator_prefix")
                    or source.get("origin", "source"))
            suffix = section.get("locator_suffix") or section.get("name") or "text"
            for index, passage in enumerate(split_passages(section_text, min_chars, max_chars), start=1):
                locator = "%s#%s#s%d" % (base, suffix, index)
                confidence = "high"
                if source.get("low_confidence"):
                    confidence = "low"
                elif name == "title":
                    confidence = "title_only"
                elif source.get("confidence") == "low":
                    confidence = "low"
                passages.append({
                    "section": section.get("name") or "text",
                    "text": passage["text"],
                    "char_start": passage["char_start"],
                    "locator": locator,
                    "index": index,
                    "confidence": confidence,
                    "terms": set(tokenize(passage["text"], policy)),
                })
        # If a source has only a title, keep the title as a title-only passage.
        if not passages and source.get("title"):
            base = source.get("locator_prefix", source.get("origin", "source"))
            passages.append({
                "section": "title",
                "text": norm_space(source["title"]),
                "char_start": 0,
                "locator": "%s#title#s1" % base,
                "index": 1,
                "confidence": "title_only",
                "terms": set(tokenize(source["title"], policy)),
            })
        source["passages"] = passages[:per_source_cap]
    return sources


def select_evidence(sources, sub_questions, policy, question=""):
    settings = policy.get("evidence", {})
    max_per_subq = safe_int(settings.get("max_passages_per_subquestion"), 8)
    max_per_source = safe_int(settings.get("max_passages_per_source_per_subquestion"), 2)
    usable = [source for source in sources if source.get("included_in_evidence", True)]
    doc_freq = Counter()
    source_terms = {}
    for source in usable:
        terms = set(tokenize((source.get("title") or "") + " " + (source.get("text") or ""), policy))
        source_terms[source["source_id"]] = terms
        doc_freq.update(terms)
    total_docs = max(1, len(usable))
    generic_threshold = max(1, int(round(total_docs * 0.7)))
    question_terms = set(tokenize(question, policy)) if question else set()
    evidence = []
    evidence_index = {}
    pairs = []
    for sub_question in sub_questions:
        q_terms = set(tokenize(sub_question["question"], policy))
        corpus_terms = {term: doc_freq.get(term, 0) for term in q_terms if doc_freq.get(term, 0) > 0}
        if not corpus_terms:
            continue
        # Concepts that are specific to this sub-question (not already present
        # in the overarching question) define what would count as coverage.
        specific_terms = q_terms - question_terms
        specific_in_corpus = {term: doc_freq.get(term, 0) for term in specific_terms
                              if doc_freq.get(term, 0) > 0}
        specific_mode = bool(specific_in_corpus)
        if specific_terms and not specific_in_corpus and sub_question.get("source") != "derived":
            # A case-declared sub-question whose distinctive anchors are absent
            # is a coverage gap. Derived (PICO) questions keep their generic
            # anchors so that a corpus without the dimension wording can still
            # be searched.
            continue
        specific_mode = bool(specific_in_corpus)
        distinctive = {term for term, count in corpus_terms.items() if count <= generic_threshold}
        if not distinctive:
            # Fall back to generic terms only when every meaningful anchor of the
            # sub-question exists in the corpus but happens to be ubiquitous.
            # If a distinctive anchor (e.g. "older adults", "cardiovascular") is
            # absent, the sub-question is a coverage gap rather than a generic hit.
            unmatched = [term for term in q_terms if doc_freq.get(term, 0) == 0]
            english_anchors = lexicon_english_set(policy)
            missing_anchors = [term for term in unmatched
                               if term in english_anchors or (term.isascii() and len(term) >= 4)]
            if missing_anchors:
                continue
            distinctive = set(corpus_terms)
        candidates = []
        for source in usable:
            per_source = 0
            for passage_index, passage in enumerate(source.get("passages", [])):
                matched = q_terms & passage["terms"]
                specific_matched = matched & specific_terms
                if specific_mode:
                    if not specific_matched:
                        continue
                elif not (matched & distinctive):
                    continue
                score = 0.0
                for term in matched:
                    score += math.log((total_docs + 1.0) / (doc_freq.get(term, 0) + 1.0)) + 1.0
                score += 2.0 * len(specific_matched if specific_mode else (matched & distinctive))
                if passage["confidence"] == "title_only":
                    score *= 0.8
                if score < 1.0:
                    continue
                candidates.append({
                    "source": source,
                    "passage": passage,
                    "passage_index": passage_index,
                    "score": round(score, 3),
                    "terms": sorted(matched)[:12],
                })
        candidates.sort(key=lambda item: (-item["score"], item["source"]["order"],
                                          item["passage_index"]))
        chosen = 0
        per_source_count = Counter()
        for candidate in candidates:
            if chosen >= max_per_subq:
                break
            source_id = candidate["source"]["source_id"]
            if per_source_count[source_id] >= max_per_source:
                continue
            passage = candidate["passage"]
            key = (source_id, passage["locator"])
            row = evidence_index.get(key)
            if row is None:
                row = {
                    "evidence_id": "E%03d" % (len(evidence) + 1),
                    "source_id": source_id,
                    "sub_question_ids": [],
                    "section": passage["section"],
                    "locator": passage["locator"],
                    "quote": passage["text"],
                    "text": passage["text"],
                    "char_start": passage["char_start"],
                    "confidence": passage["confidence"],
                    "evidence_strength": "direct" if passage["confidence"] == "high" else
                                          ("title_only" if passage["confidence"] == "title_only"
                                           else "low_confidence_text"),
                    "terms_matched": [],
                    "score": candidate["score"],
                    "stance": polarity(passage["text"])[0],
                }
                evidence.append(row)
                evidence_index[key] = row
            else:
                row["score"] = max(row["score"], candidate["score"])
            if sub_question["sub_question_id"] not in row["sub_question_ids"]:
                row["sub_question_ids"].append(sub_question["sub_question_id"])
            row["terms_matched"] = sorted(set(row["terms_matched"]) | set(candidate["terms"]))[:12]
            pairs.append({
                "sub_question_id": sub_question["sub_question_id"],
                "evidence_id": row["evidence_id"],
                "source_id": source_id,
                "score": candidate["score"],
            })
            per_source_count[source_id] += 1
            chosen += 1
    return evidence, pairs
