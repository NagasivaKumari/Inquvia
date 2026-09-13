"""Deterministic full-document computation for structured text/log/CSV/JSON.

When the user's document question requires computation over the entire file
(counts, averages, sums, groupings, rankings, trends, anomalies, comparisons),
the source is parsed and aggregated DETERMINISTICALLY — never dumped into the
model context. The LLM only ever sees:

  - schema
  - computed aggregates (with full calculation trace)
  - relevant samples
  - calculation metadata

and then explains the result. Coverage is recorded honestly: the trace reports
exactly how many records were processed and how many lines could not be parsed,
so nothing claims "complete analysis" unless the full source was actually
processed.

The computation plan is generated per-question (the status groups the user
requests are interpreted literally, never hardcoded) and executed with a
bounded filter DSL — no code eval, no global "2xx/4xx" assumptions.
"""
import csv
import io
import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_RECORDS = 1_000_000  # ponytail: hard cap; stream the rest if files exceed it
SAMPLE_ROWS = 25
GROUP_TOP_N = 10
MAX_SAMPLE_VALUES = 100_000  # memory bound for median/metric value collection
MAX_FIELDS = 40
DEFAULT_PLAN_LIMIT = 20

# Aggregation/analysis intent words. The structure gate (records actually parse
# into ≥2 rows) is what decides — these just decide whether to try.
_COMPUTE_WORDS = (
    "count", "counts", "how many", "how much", "average", "averages", "avg",
    "mean", "median", "sum", "total", "totals", "min", "max", "maximum",
    "minimum", "distribution", "breakdown", "group", "grouped", "group by",
    "rank", "ranking", "top ", "trend", "trends", "compare", "comparison",
    "compared", "anomaly", "anomalies", "outlier", "outliers", "percentage",
    "percent", "ratio", "frequency", "aggregate", "aggregated", "sorted",
    "sort ", "per request", "per hour", "per day", "entire file", "entire log",
    "entire document", "whole file", "whole log",
)

_FILTER_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "range", "in", "match", "true"}

_KV_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s|,]+)')
_NUM_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:[.,\d]*\d)?)(ms|ms|s|sec|secs|min|hr|kb|mb|gb|bytes?)?\s*$",
    re.IGNORECASE,
)

_UNITS = {
    "ms": 1.0, "s": 1000.0, "sec": 1000.0, "secs": 1000.0, "min": 60000.0,
    "hr": 3600000.0, "kb": 1024.0, "mb": 1024.0 ** 2, "gb": 1024.0 ** 3,
    "byte": 1.0, "bytes": 1.0,
}


def requires_full_compute(question: str) -> bool:
    q = (question or "").lower()
    return any(w in q for w in _COMPUTE_WORDS)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _num(v):
    """Numeric coercion for comparisons/aggregation. Returns float/int/None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip().strip('"')
        m = _NUM_RE.match(s)
        if not m:
            return None
        num_s = m.group(1).replace(",", "").replace(" ", "")
        try:
            num = float(num_s) if "." in num_s else int(num_s)
        except ValueError:
            return None
        unit = (m.group(2) or "").lower()
        if unit:
            num = num * _UNITS.get(unit, 1.0)
        return num
    return None


def _unquote(v) -> str:
    s = (v or "").strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _fields_of(kv_line: str) -> dict | None:
    vals = {}
    for k, v in _KV_RE.findall(kv_line):
        vals[k] = _unquote(v)
    return vals if len(vals) >= 2 else None


def _looks_header(row: list[str]) -> bool:
    row = [c for c in row if c.strip()]
    if not row:
        return False
    return all(_num(c) is None for c in row)


def _pick_parser(text: str, mime: str | None, filename: str) -> str | None:
    mime = (mime or "").lower()
    fname = (filename or "").lower()
    stripped = text.lstrip()
    first_lines = [l for l in text.splitlines() if l.strip()][:3]

    if "json" in mime or fname.endswith(".json"):
        if stripped.startswith("["):
            return "json"
        try:
            if first_lines and json.loads(first_lines[0]):
                return "jsonl"
        except Exception:
            pass
    if "csv" in mime or fname.endswith(".csv"):
        return "csv"
    if "," in (first_lines[0] if first_lines else "") and len(first_lines) >= 2:
        return "csv"

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    kv_lines = sum(1 for l in lines[:500] if (_fields_of(l) is not None))
    if kv_lines / max(1, min(len(lines), 500)) >= 0.5:
        return "kv"
    split_counts = [len(l.split()) for l in lines[:500]]
    if len(lines) >= 2 and max(split_counts) >= 3 and split_counts.count(split_counts[0]) >= 0.6 * len(split_counts):
        return "cols"
    return None


def _iter_parsed(data: bytes, parser: str, header: bool):
    """Deterministic record iterator. Rows are dicts; '_line' holds the raw
    text when the parser is line-based."""
    text = _decode(data)
    if parser == "csv":
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return
        if header:
            names = [c.strip() or f"col{i}" for i, c in enumerate(rows[0])]
            for r in rows[1:]:
                row = {}
                for i, v in enumerate(r):
                    name = names[i] if i < len(names) else f"col{i}"
                    row[name] = v
                row["_line"] = ",".join(r)
                yield row
            return
        for i, r in enumerate(rows):
            row = {f"col{c}": v for c, v in enumerate(r)}
            row["_line"] = ",".join(r)
            yield row
        return
    if parser == "json":
        try:
            obj = json.loads(text)
        except Exception:
            return
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    yield {k: v for k, v in item.items()}
        elif isinstance(obj, dict):
            yield {k: v for k, v in obj.items()}
        return
    if parser == "jsonl":
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                row = {k: v for k, v in obj.items()}
                row["_line"] = line.strip()
                yield row
        return
    if parser == "kv":
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _fields_of(line)
            if row is None:
                continue
            row["_line"] = line.strip()
            yield row
        return
    if parser == "cols":
        for line in text.splitlines():
            if not line.strip():
                continue
            parts = line.split()
            row = {f"col{i}": v for i, v in enumerate(parts)}
            row["_line"] = line.strip()
            yield row


def _scan(data: bytes, mime: str | None, filename: str) -> dict | None:
    """One pass over the full source: pick parser, count rows, infer schema.

    Returns a profile dict (BSON-safe) or None when the content is not
    structured (no parser, or <2 data records).
    """
    text = _decode(data)
    parser = _pick_parser(text, mime, filename)
    if not parser:
        return None
    header = False
    if parser == "csv":
        reader = csv.reader(io.StringIO(text))
        try:
            first = next(reader, None)
        except Exception:
            return None
        header = bool(first is not None and _looks_header(first))

    fields: list[str] = []
    field_present: dict[str, int] = {}
    field_numeric: dict[str, int] = {}
    sample: list[dict] = []
    rows_total = 0
    lines_total = sum(1 for l in text.splitlines() if l.strip())

    for row in _iter_parsed(data, parser, header):
        rows_total += 1
        if len(sample) < SAMPLE_ROWS:
            sample.append(row)
        for k, v in row.items():
            if k == "_line":
                continue
            if k not in field_present:
                fields.append(k)
                field_present[k] = 0
                field_numeric[k] = 0
            field_present[k] += 1
            if _num(v) is not None:
                field_numeric[k] += 1

    if rows_total < 2:
        return None

    unparsed = max(0, lines_total - rows_total) if parser in ("kv", "jsonl") else 0
    fields = fields[:MAX_FIELDS]
    field_schema = {}
    for k in fields:
        present = field_present.get(k, 0)
        numeric = field_numeric.get(k, 0)
        numeric_share = numeric / present if present else 0.0
        if numeric_share >= 0.95 and present:
            integral = all(
                isinstance(_num(v), int) and not isinstance(_num(v), bool)
                for row in sample if row.get(k) is not None
                for v in [row[k]]
            )
            ftype = "int" if integral else "float"
        else:
            ftype = "str"
        field_schema[k] = {
            "type": ftype,
            "present": present,
            "rows": rows_total,
            "numericShare": round(numeric_share, 3),
        }
    if parser in ("kv", "cols"):
        field_schema["_line"] = {"type": "str", "present": rows_total, "rows": rows_total, "numericShare": 0.0}

    return {
        "parser": parser,
        "header": header,
        "fields": fields,
        "schema": field_schema,
        "sample": sample,
        "rowsTotal": rows_total,
        "linesTotal": lines_total,
        "unparsedLines": unparsed,
    }


def _validate_metric(m: dict, fields: set[str]):
    f = (m.get("filter") or {}).get("field")
    g = m.get("group_by")
    mf = m.get("field")
    missing = []
    for cand, label in ((f, "filter field"), (g, "group field"), (mf, "value field")):
        if cand and cand not in fields and cand != "_line":
            missing.append(f"{cand!r} ({label})")
    return missing


def _match(row: dict, filt: dict | None) -> bool:
    if not filt:
        return True
    op = filt.get("op") or "eq"
    if op == "true":
        return True
    field = filt.get("field")
    if not field:
        return True
    v = row.get(field)
    if v is None:
        return False
    if op == "match":
        try:
            return re.search(filt.get("pattern") or "", str(v)) is not None
        except Exception:
            return False
    if op == "range":
        num = _num(v)
        if num is None:
            return False
        lo = filt.get("min")
        hi = filt.get("max")
        if lo is not None and num < _num(lo):
            return False
        if hi is not None and num > _num(hi):
            return False
        return True
    if op == "in":
        values = filt.get("values") or []
        for cand in values:
            n = _num(cand)
            if n is not None and _num(v) is not None:
                if _num(v) == n:
                    return True
            elif str(v) == str(cand):
                return True
        return False
    target = filt.get("value")
    nv = _num(v)
    nt = _num(target)
    if nv is not None and nt is not None:
        a, b = nv, nt
    else:
        a, b = str(v), str(target)
    try:
        if op == "eq":
            return a == b
        if op == "ne":
            return a != b
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b
    except TypeError:
        return False
    return False


def _new_scalar(fn: str, field: str | None):
    state = {"fn": fn, "n": 0, "sum": 0.0, "min": None, "max": None,
             "values": [], "distinct": set()}

    def update(row):
        if fn == "count":
            state["n"] += 1
            return
        v = row.get(field)
        num = _num(v)
        if fn == "distinct":
            state["distinct"].add(_unquote(str(v)) if v is not None else None)
            state["n"] += 1
            return
        if num is None:
            return
        state["n"] += 1
        state["sum"] += num
        if state["min"] is None or num < state["min"]:
            state["min"] = num
        if state["max"] is None or num > state["max"]:
            state["max"] = num
        if fn in ("median",) and len(state["values"]) < MAX_SAMPLE_VALUES:
            state["values"].append(num)

    return update, state


def _finish_scalar(state) -> float | int | None:
    fn = state["fn"]
    if fn == "count":
        return state["n"]
    if fn == "distinct":
        return len(state["distinct"])
    if state["n"] == 0:
        return None
    if fn == "sum":
        return round(state["sum"], 6)
    if fn == "mean":
        return round(state["sum"] / state["n"], 6)
    if fn == "min":
        return state["min"]
    if fn == "max":
        return state["max"]
    if fn == "median":
        vals = sorted(state["values"])
        if not vals:
            return None
        mid = len(vals) // 2
        if len(vals) % 2:
            return vals[mid]
        return round((vals[mid - 1] + vals[mid]) / 2.0, 6)
    return None


def execute(data: bytes, profile: dict, plan: list[dict]) -> dict:
    """Run the plan over the ENTIRE source deterministically (single streaming
    pass). Returns the computation trace + per-metric results."""
    parser = profile["parser"]
    header = profile["header"]
    fields = set(profile["fields"]) | {"_line"}

    metrics = []
    invalid = []
    for m in plan:
        m = dict(m) if isinstance(m, dict) else {}
        missing = _validate_metric(m, fields)
        if missing:
            invalid.append({"name": m.get("name") or "?",
                            "description": m.get("description"),
                            "skipped": True,
                            "reason": "references field(s) not present in the source: " + ", ".join(missing)})
            continue
        metrics.append(m)
    if not metrics:
        metrics = default_plan(profile)

    accs = []
    for m in metrics:
        upd, state = _new_scalar(m.get("type") or "count", m.get("field"))
        if m.get("group_by"):
            groups: dict = {}
            accs.append((m, groups, None))
            continue
        accs.append((m, state, upd))

    rows_processed = 0
    unparsed = profile["unparsedLines"]
    matched_samples: dict[str, list[dict]] = {}
    for row in _iter_parsed(data, parser, header):
        rows_processed += 1
        for m, state, upd in accs:
            if not _match(row, m.get("filter")):
                continue
            if m.get("group_by"):
                gkey = _group_key(row.get(m["group_by"]))
                if gkey not in state:
                    gupd, gstate = _new_scalar(m.get("type") or "count", m.get("field"))
                    state[gkey] = (gupd, gstate)
                gupd, gstate = state[gkey]
                gupd(row)
            else:
                upd(row)
                if len(matched_samples.get(m.get("name") or "", [])) < 3 and m.get("filter"):
                    matched_samples.setdefault(m.get("name") or "", []).append(row)
        if rows_processed >= MAX_RECORDS:
            unparsed += max(0, profile["linesTotal"] - rows_processed)
            break

    complete = rows_processed == profile["rowsTotal"] and profile["unparsedLines"] == 0

    results = []
    for m, state, _ in accs:
        if m.get("group_by"):
            items = []
            for gkey, (_, gstate) in state.items():
                value = _finish_scalar(gstate)
                items.append({"group": gkey, "value": value})
            items.sort(key=lambda i: (i["value"] is None, -(i["value"] or 0)))
            result = {
                "name": m.get("name") or "",
                "description": m.get("description") or "",
                "function": m.get("type") or "count",
                "field": m.get("field"),
                "groupBy": m["group_by"],
                "population": _filter_desc(m.get("filter")),
                "filterDefinition": m.get("filter") or {},
                "result": items[:GROUP_TOP_N],
                "topGroups": GROUP_TOP_N,
                "totalGroups": len(state),
                "recordsIncluded": sum(1 for _, gs in state.values() if gs["n"]) or None,
            }
        else:
            result = {
                "name": m.get("name") or "",
                "description": m.get("description") or "",
                "function": m.get("type") or "count",
                "field": m.get("field"),
                "groupBy": None,
                "population": _filter_desc(m.get("filter")),
                "filterDefinition": m.get("filter") or {},
                "result": _round_res(_finish_scalar(state)),
                "recordsIncluded": state["n"],
            }
        results.append(result)

    return {
        "source": profile.get("source") or "",
        "parser": parser,
        "recordsAvailable": profile["rowsTotal"],
        "recordsProcessed": rows_processed,
        "unparsedLines": unparsed,
        "complete": complete,
        "metrics": results,
        "skippedMetrics": invalid,
        "matchedSamples": matched_samples,
    }


def _round_res(v):
    if isinstance(v, float):
        return round(v, 6)
    return v


def _group_key(v):
    if v is None:
        return "<none>"
    return _unquote(str(v))


def _filter_desc(filt: dict | None) -> str:
    if not filt:
        return "all records"
    op = filt.get("op") or "eq"
    f = filt.get("field")
    if op == "range":
        lo = filt.get("min")
        hi = filt.get("max")
        return f"{f} >= {lo} AND {f} <= {hi}" if lo is not None and hi is not None else f"filters on {f}"
    if op == "in":
        return f"{f} in {filt.get('values')}"
    return f"{f} {op} {filt.get('value')}"


def _schema_block(profile: dict) -> str:
    lines = []
    for f in profile["fields"]:
        s = profile["schema"].get(f) or {}
        lines.append(f"  {f}: {s.get('type') or 'str'} (present in {s.get('present', 0)}/{profile['rowsTotal']} records)")
    if "_line" in profile["schema"]:
        if profile["parser"] in ("kv", "cols"):
            lines.append("  _line: full raw text of each record (use with 'match' filters)")
        else:
            lines.append("  _line: raw csv row text")
    return "\n".join(lines)


def _sample_block(profile: dict) -> str:
    return json.dumps(profile["sample"][:SAMPLE_ROWS], indent=1)[:8000]


def build_plan_prompt(question: str, profile: dict) -> tuple[str, list[dict]]:
    system = (
        "You are Inquvia's data-computation planner. Your ONLY job is to translate the user's "
        "data question into a deterministic, executable computation plan over the fixed schema below. "
        "The plan is executed by a streaming engine over the ENTIRE uploaded file, so:\n"
        "1. Interpret the user's requested groups/categories LITERALLY as they worded them "
        "(e.g. if they say 'successful = 2xx', that is status in [200,299]; if they define their own "
        "groups, use exactly those boundaries). Do NOT assume standard status-code semantics on your own.\n"
        "2. Emit one metric per computed value the question needs. Multi-part questions → multiple metrics.\n"
        "3. Use ONLY fields listed in the schema. Never invent field names.\n"
        "4. Available functions: count, sum, mean, median, min, max, distinct.\n"
        "5. Optional per-metric 'filter' with ops: range {field,min,max}, in {field,values}, "
        "eq/ne/gt/gte/lt/lte {field,value}, match {field,pattern}.\n"
        "6. Optional per-metric 'group_by': a field to group by (produces per-group values).\n"
        "Return ONLY JSON: {\"metrics\": [{name, description, type, field, filter?, group_by?}]}."
    )
    user = (
        f"QUESTION: {question}\n\n"
        f"DOCUMENT: {profile.get('source') or 'uploaded file'}\n"
        f"PARSER: {profile['parser']}\n"
        f"RECORDS: {profile['rowsTotal']} data rows scanned\n\n"
        f"SCHEMA:\n{_schema_block(profile)}\n\n"
        f"SAMPLE_RECORDS (first {min(SAMPLE_ROWS, len(profile['sample']))} of {profile['rowsTotal']}):\n"
        f"{_sample_block(profile)}\n"
    )
    return system, [{"text": user}]


def default_plan(profile: dict) -> list[dict]:
    """Deterministic fallback when plan generation fails: full analytics profile
    over every numeric field plus totals."""
    metrics = [{
        "name": "total_records",
        "description": "total records in the file",
        "type": "count",
        "field": None,
        "filter": None,
    }]
    seen = 0
    for f in profile["fields"]:
        if f == "_line":
            continue
        s = profile["schema"].get(f) or {}
        if s.get("type") in ("int", "float") and seen < DEFAULT_PLAN_LIMIT // 2:
            for fn, label in (("count", f"count_non_null_{f}"),
                              ("mean", f"mean_{f}"), ("min", f"min_{f}"), ("max", f"max_{f}")):
                metrics.append({
                    "name": label,
                    "description": f"{fn} of {f}",
                    "type": fn,
                    "field": f,
                })
            seen += 4
    if not any(m.get("name") == "total_non_null_lines" for m in metrics):
        metrics.append({
            "name": "line_count",
            "description": "records with raw text present",
            "type": "count",
            "field": None,
            "filter": {"op": "true", "field": "_line"},
        })
    return metrics


def build_results_block(computation: dict) -> str:
    lines = []
    for m in computation.get("metrics", []):
        res = m.get("result")
        if isinstance(res, list):
            vals = ", ".join(f"{g['group']}={g['value']}" for g in res[:GROUP_TOP_N])
            lines.append(
                f"- metric: {m['name']}\n"
                f"    description: {m.get('description') or ''}\n"
                f"    function: {m.get('function')}\n"
                f"    field: {m.get('field')}\n"
                f"    group_by: {m.get('groupBy')}\n"
                f"    population: {m.get('population')}\n"
                f"    recordsIncluded: {m.get('recordsIncluded')}\n"
                f"    top {min(GROUP_TOP_N, len(res))} of {m.get('totalGroups')} groups: {vals}"
            )
        else:
            lines.append(
                f"- metric: {m['name']}\n"
                f"    description: {m.get('description') or ''}\n"
                f"    function: {m.get('function')}\n"
                f"    field: {m.get('field')}\n"
                f"    population: {m.get('population')}\n"
                f"    filter: {json.dumps(m.get('filterDefinition')) if m.get('filterDefinition') else 'none'}\n"
                f"    recordsIncluded: {m.get('recordsIncluded')}\n"
                f"    result: {res}"
            )
    for m in computation.get("skippedMetrics") or []:
        lines.append(f"- metric: {m.get('name')} — SKIPPED ({m.get('reason')})")
    return "\n".join(lines)


def build_coverage_block(computation: dict) -> str:
    if computation["complete"]:
        return (
            f"COVERAGE: complete — {computation['recordsProcessed']} of "
            f"{computation['recordsAvailable']} records in the uploaded file were processed "
            f"(0 lines unparsed). The full file was analyzed."
        )
    return (
        f"COVERAGE: PARTIAL — only {computation['recordsProcessed']} of "
        f"{computation['recordsAvailable']} records were processed; "
        f"{computation['unparsedLines']} lines could not be parsed. "
        f"Any whole-file claim would be unsupported."
    )


def _relevant_samples_block(computation: dict, profile: dict) -> str:
    seen = 0
    out = []
    for m in computation.get("metrics", []):
        for row in (computation.get("matchedSamples") or {}).get(m.get("name") or "", []):
            out.append(f"metric '{m['name']}' matched record: " + json.dumps(row, default=str))
            seen += 1
    if seen == 0:
        return "no additional matching records were captured"
    return "\n".join(out[:12])


def build_reasoning_prompt(question: str, profile: dict, computation: dict) -> tuple[str, list[dict]]:
    system = (
        "You are Inquvia's document analyst for a deterministically computed result. "
        "The uploaded document was parsed and computed over by a streaming aggregation engine; "
        "the COMPUTED_RESULTS below are authoritative facts produced from the source data. "
        "RULES:\n"
        "1. Your answer MUST use these exact computed values. Do not re-estimate, round differently, "
        "or infer numbers the computation did not produce.\n"
        "2. The COVERAGE line states exactly how much of the file was processed. If it says complete, "
        "your answer may (and when the question describes it, should) state something like "
        "'a complete analysis of all N records in <file>'. If it says PARTIAL, your answer MUST say "
        "'analysis of the first X of Y records' (or the unparsed lines) and confidence must reflect the gap. "
        "NEVER call a complete run a 'snippet', 'excerpt', 'sample', or 'partial time window'; "
        "conversely never claim the whole file was analyzed when COVERAGE says PARTIAL.\n"
        "3. If groups/categories were requested in the question (successful/unsuccessful, etc.), "
        "state the exact definition the computation used and quote each computed value.\n"
        "4. conclusion: 'answered' when the computed results directly answer the question, "
        "'inconclusive' when results are genuinely ambiguous, 'insufficient_evidence' only when the "
        "file does not contain the needed data.\n"
        "5. Assign confidence 80-95 for complete deterministic counts/averages, lower when COVERAGE "
        "is PARTIAL or metrics were skipped.\n"
        "6. Return 'evidenceSignals': [] with each computed metric listed in 'findings' "
        "as 'metric <name> = <value> (computed over N records of <file>)'.\n"
        'Return ONLY JSON: {"conclusion": "...", "confidence": number, "answer": string, '
        '"assessmentReasoning": string, "findings": string[], "limitations": string[], '
        '"contradictions": string[], "uncertainty": string, "sourcesUsed": string[], '
        '"risk": "low"|"moderate"|"high"|"unknown", "evidenceSignals": []}'
    )
    parts = [
        {"text": f"DOCUMENT: {computation.get('source') or 'uploaded file'} "
                 f"(parsed as {computation['parser']}; {computation['recordsAvailable']} records in file)"},
        {"text": build_coverage_block(computation)},
        {"text": f"SCHEMA:\n{_schema_block(profile)}"},
        {"text": f"SAMPLE_RECORDS (first {min(SAMPLE_ROWS, len(profile['sample']))} rows):\n{_sample_block(profile)}"},
        {"text": "COMPUTED_RESULTS (computed deterministically over the processed records):\n" + build_results_block(computation)},
        {"text": "RELEVANT_SAMPLES:\n" + _relevant_samples_block(computation, profile)},
        {"text": f"QUESTION: {question}"},
    ]
    return system, parts


def computation_evidence_records(computation: dict, filename: str) -> list[dict]:
    recs = []
    for i, m in enumerate(computation.get("metrics", [])):
        res = m.get("result")
        if isinstance(res, list):
            summary = "; ".join(f"{g['group']}={g['value']}" for g in res[:5])
        else:
            summary = str(res)
        recs.append({
            "finding": (
                f"Computation ({m['name']}) over {filename or 'uploaded file'}: "
                f"{m.get('function')} on {m.get('field') or 'records'} ({m.get('population')}) = {summary}; "
                f"{m.get('recordsIncluded')} records included; "
                f"{computation['recordsProcessed']}/{computation['recordsAvailable']} records processed."
            ),
            "signal": "supporting",
            "metadata": {
                "origin": "computation",
                "calculationId": f"calc_{i + 1}",
                "metricName": m["name"],
                "metricFunction": m.get("function"),
                "metricField": m.get("field"),
                "population": m.get("population"),
                "filterDefinition": m.get("filterDefinition") or {},
                "groupBy": m.get("groupBy"),
                "recordsIncluded": m.get("recordsIncluded"),
                "recordsProcessed": computation["recordsProcessed"],
                "recordsAvailable": computation["recordsAvailable"],
                "unparsedLines": computation["unparsedLines"],
                "complete": computation["complete"],
                "parser": computation["parser"],
                "source": computation.get("source") or filename,
                "result": res if not isinstance(res, list) else res[:GROUP_TOP_N],
            },
        })
    return recs


def parse_plan(raw: str | None) -> list[dict]:
    if not raw:
        return []
    obj = json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(obj, dict):
        obj = obj.get("metrics")
    if not isinstance(obj, list):
        return []
    out = []
    for m in obj:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        mtype = m.get("type") or "count"
        if mtype not in ("count", "sum", "mean", "median", "min", "max", "distinct"):
            continue
        filt = m.get("filter") or {}
        if isinstance(filt, dict) and filt.get("op") not in _FILTER_OPS:
            continue
        out.append({
            "name": str(m["name"])[:120],
            "description": (m.get("description") or "")[:300],
            "type": mtype,
            "field": m.get("field"),
            "filter": filt or None,
            "group_by": m.get("group_by"),
        })
    return out


def run_computation(data: bytes, mime: str | None, filename: str,
                    plan: list[dict] | None = None) -> dict | None:
    """Full pipeline for callers that already have a plan; returns the
    computation trace, or None when the file is not structured."""
    profile = _scan(data, mime, filename)
    if not profile:
        return None
    profile["source"] = filename or ""
    return execute(data, profile, plan or default_plan(profile))


if __name__ == "__main__":  # self-check: fails loudly if computation regresses
    lines = []
    for i in range(10_000):
        status = 200 if i % 2 == 0 else 404
        rt = 12 + (i % 7)
        lines.append(f"2026-01-01T00:00:{i % 60:02d}Z INFO method=GET path=/api status={status} rt_ms={rt}")
    data = ("\n".join(lines) + "\n").encode()
    comp = run_computation(data, "text/plain", "sample.log", [
        {"name": "successful", "description": "status 200-299", "type": "count",
         "field": None, "filter": {"field": "status", "op": "range", "min": 200, "max": 299}},
        {"name": "unsuccessful", "description": "status 400-599", "type": "count",
         "field": None, "filter": {"field": "status", "op": "range", "min": 400, "max": 599}},
        {"name": "avg_rt", "description": "avg response time", "type": "mean",
         "field": "rt_ms", "filter": None},
        {"name": "per_status", "description": "counts grouped by status", "type": "count",
         "field": None, "group_by": "status"},
    ])
    assert comp is not None and comp["complete"], comp
    assert comp["recordsAvailable"] == 10_000 and comp["recordsProcessed"] == 10_000
    by_name = {m["name"]: m for m in comp["metrics"]}
    assert by_name["successful"]["result"] == 5000
    assert by_name["unsuccessful"]["result"] == 5000
    assert by_name["avg_rt"]["result"] == sum(12 + i % 7 for i in range(10000)) / 10000
    groups = {g["group"]: g["value"] for g in by_name["per_status"]["result"]}
    assert groups == {"200": 5000, "404": 5000}

    # Field-unknown metrics are skipped with an honest reason, never silent.
    comp2 = run_computation(data, "text/plain", "sample.log", [
        {"name": "bogus", "description": "bad field", "type": "count",
         "field": None, "filter": {"field": "does_not_exist", "op": "gt", "value": 0}},
    ])
    assert comp2["skippedMetrics"] and comp2["skippedMetrics"][0]["name"] == "bogus"

    # No plan → deterministic default profile still computes.
    comp3 = run_computation(data, "text/plain", "sample.log")
    names = [m["name"] for m in comp3["metrics"]]
    assert "total_records" in names and "mean_rt_ms" in names

    # Unparseable prose → not structured → None (fall back to page analysis).
    assert run_computation(
        b"Roses are red.\nThe violets are quite blue and tall this morning.",
        "text/plain", "poem.txt",
    ) is None
    print("compute_structured self-check OK")