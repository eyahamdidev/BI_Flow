"""Three cold v7 runs on gpt-oss-120b, then the 15 synthetic sheets.

Concurrency is 1. Calls are at least BIFLOW_MIN_INTERVAL seconds apart.
Every HTTP 429 is logged with the case id. A fallback caused by 429 or
timeout is labelled on its own line. The API key is never printed.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))
os.environ.pop("FAKE_LLM", None)

HERE = Path(__file__).resolve().parent
LOG = HERE / "bakeoff_v7_paced.log"
MODEL = "openai/gpt-oss-120b"
PROMPT = "auditor.explain_kpi@v7"
CONCURRENCY = 1
COLUMNS = [
    "section",
    "case",
    "frame",
    "rendered text",
    "fact-sheet values used",
    "supported (1/0)",
    "note",
    "misleading_by_omission (1/0)",
]


def say(message: str) -> None:
    print(message, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    return round(ordered[min(index, len(ordered) - 1)], 1)


def _use_groq() -> None:
    load_env()
    os.environ.pop("FAKE_LLM", None)
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["LLM_MODEL_MAIN"] = MODEL
    os.environ["LLM_MODEL_FAST"] = MODEL
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["BIFLOW_MIN_INTERVAL"] = os.environ.get("BIFLOW_MIN_INTERVAL") or "8"
    os.environ["explain_kpi_version"] = "v7"


def _run_items(tag: str, items: list[dict]) -> tuple[list[dict], int]:
    if CONCURRENCY != 1:
        raise RuntimeError("this bake-off refuses concurrency other than 1")
    import app.v7 as v7
    from app.gate import case_rates
    from app.prose import write_prose
    from app.templates import explain_template
    from app.v7 import fallback_cause_of, fixed_words, offered_frames, outside_frame
    from biflow_contracts.biflow_llm import drain_calls

    v7.HTTP_429 = 0
    v7.RATE_EVENTS.clear()
    v7._LAST_CALL_AT = 0.0
    rows = []
    for item in items:
        v7.CURRENT_CASE = item["id"]
        seen = len(v7.RATE_EVENTS)
        drain_calls()
        started = time.perf_counter()
        lang = item.get("lang") or "en"
        try:
            result = write_prose(
                prompt_id=PROMPT,
                fact_sheet=item["fact_sheet"],
                template=explain_template(item["fact_sheet"], lang),
                lang=lang,
                section=f"Explain {item.get('kpi_id') or item['id']} for {item.get('period') or ''}",
                min_sentences=3,
                max_sentences=5,
                temperature=0.0,
            )
        except Exception as exc:
            from app.redact import redact

            say(f"ERROR {item['id']} {redact(type(exc).__name__ + ': ' + str(exc))[:300]}")
            rows.append(
                {
                    "id": item["id"],
                    "kpi_id": item.get("kpi_id"),
                    "period": item.get("period"),
                    "compare_to": item.get("compare_to"),
                    "lang": lang,
                    "shape": item.get("shape"),
                    "source": "error",
                    "first_try_pass": None,
                    "attempts": 0,
                    "warning": redact(str(exc))[:300],
                    "fallback_cause": None,
                    "frames": [],
                    "offered": [],
                    "claims": [],
                    "answer": "",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "tokens": 0,
                    "http_429": len(v7.RATE_EVENTS) - seen,
                    "safety_ok": False,
                }
            )
            continue
        calls = drain_calls()
        for event in v7.RATE_EVENTS[seen:]:
            say(f"429 case={event.get('case')} retry_after={event.get('retry_after')}")
        frames = [claim.get("frame") for claim in (result.claims or []) if claim.get("frame")]
        offered = [frame.name for frame in offered_frames(item["fact_sheet"], lang)]
        cause = fallback_cause_of(result.source, result.warning)
        if result.source == "fallback":
            say(f"FALLBACK {item['id']} caused by {cause}")
        claims = []
        for claim in result.claims or []:
            if claim.get("frame"):
                claims.append({"frame": claim["frame"], "sentence": claim.get("sentence"), "fact_ids": claim.get("fact_ids") or []})
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        safety = _safety(item["fact_sheet"], lang, offered_frames, outside_frame, fixed_words)
        rows.append(
            {
                "id": item["id"],
                "kpi_id": item.get("kpi_id"),
                "period": item.get("period"),
                "compare_to": item.get("compare_to"),
                "lang": lang,
                "shape": item.get("shape"),
                "source": result.source,
                "first_try_pass": result.first_try_pass,
                "attempts": result.attempts,
                "warning": result.warning,
                "fallback_cause": cause,
                "frames": frames,
                "offered": offered,
                "claims": claims,
                "answer": result.text,
                "latency_ms": latency_ms,
                "tokens": sum(call.tokens or 0 for call in calls),
                "http_429": len(v7.RATE_EVENTS) - seen,
                "safety_ok": safety,
            }
        )
        say(f"{tag} {item['id']} {result.source} first_try={result.first_try_pass} frames={','.join(frames)} cause={cause}")
    say(f"{tag} http_429 {v7.HTTP_429}")
    say(f"{tag} rates {case_rates(rows)}")
    return rows, v7.HTTP_429


def _safety(sheet: dict, lang: str, offered_frames, outside_frame, fixed_words) -> bool:
    offered = offered_frames(sheet, lang)
    names = [frame.name for frame in offered]
    if not names:
        return True
    for mask in range(1, 2 ** len(names)):
        chosen_names = [names[index] for index in range(len(names)) if mask & (1 << index)]
        chosen = [frame for frame in offered if frame.name in chosen_names]
        from app.v7 import render_frames

        text, _claims = render_frames(chosen_names, sheet, lang)
        leftover, words = outside_frame(text, chosen, sheet, lang)
        if any(char.isdigit() for char in leftover) or not words <= fixed_words(chosen, lang):
            return False
    return True


def _summarize(rows: list[dict], http_429: int) -> dict:
    from app.gate import case_rates

    stats = case_rates(rows)
    relaxed = case_rates(rows, drop_transport=True)
    latencies = [row["latency_ms"] for row in rows]
    return {
        "n": stats["n"],
        "first_try_pass_rate": stats["first_try_pass_rate"],
        "fallback_rate": stats["fallback_rate"],
        "without_transport": relaxed,
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "tokens": sum(row["tokens"] for row in rows),
        "http_429": http_429,
    }


def _direction_ok(row: dict) -> bool | None:
    shape = row.get("shape")
    text = row.get("answer") or ""
    if shape != "decrease" and shape != "flat":
        return None
    if row.get("lang") == "fr":
        return ("en baisse" in text) if shape == "decrease" else ("inchangé" in text)
    return ("went down" in text) if shape == "decrease" else ("was unchanged" in text)


def _values_used(frame: str, sheet: dict, lang: str) -> str:
    from app.fields import format_field
    from app.v7 import _FRAMES, frame_values

    found = _FRAMES.get(frame)
    if found is None:
        return ""
    values = frame_values(sheet, lang)
    parts = []
    for name in found.requires:
        value = values.get(name)
        shown = str(value) if name == "drivers.direction" else format_field(value, name, sheet)
        parts.append(f"{name}={shown}")
    return "; ".join(parts)


def _blank() -> dict[str, str]:
    return {column: "" for column in COLUMNS}


def _export(explain_rows: list[dict], synthetic_rows: list[dict], explain_cases: list[dict], synthetic_items: list[dict]) -> None:
    sheets = {item["id"]: item for item in explain_cases}
    sheets.update({item["id"]: item for item in synthetic_items})
    out_rows: list[dict[str, str]] = []
    md = [
        "# Fact sheets for the v7 faithfulness labels",
        "",
        "Mark supported 1 only when every number, unit, label, period, and direction word matches this sheet and the sentence states nothing else. If unsure, mark 0 and write a note. Leave misleading_by_omission 1 when the published frames leave out a logged fact that changes the meaning.",
        "",
        "The supported and omission cells are blank on purpose. This file does not label them.",
        "",
    ]

    def add_case(section: str, row: dict) -> None:
        item = sheets[row["id"]]
        sheet = item["fact_sheet"]
        lang = row.get("lang") or "en"
        for claim in row.get("claims") or []:
            record = _blank()
            record["section"] = section
            record["case"] = row["id"]
            record["frame"] = str(claim.get("frame") or "")
            record["rendered text"] = str(claim.get("sentence") or "")
            record["fact-sheet values used"] = _values_used(record["frame"], sheet, lang)
            out_rows.append(record)
        if not row.get("claims"):
            record = _blank()
            record["section"] = section
            record["case"] = row["id"]
            record["frame"] = "(abstain)" if row.get("source") == "abstain" else "(fallback)"
            record["rendered text"] = row.get("answer") or ""
            out_rows.append(record)
        omission = _blank()
        omission["section"] = section
        omission["case"] = row["id"]
        omission["frame"] = "(omission)"
        omission["rendered text"] = row.get("answer") or ""
        omission["fact-sheet values used"] = "offered=" + ",".join(row.get("offered") or []) + "; chosen=" + ",".join(row.get("frames") or [])
        out_rows.append(omission)
        md.extend(
            [
                f"## {row['id']}",
                "",
                f"Language: {lang}. Source: {row.get('source')}. Frames chosen: {', '.join(row.get('frames') or []) or 'none'}. Offered: {', '.join(row.get('offered') or []) or 'none'}.",
                "",
                "Published text:",
                "",
                row.get("answer") or "",
                "",
                "Fact sheet:",
                "",
                "```json",
                json.dumps(sheet, indent=2, ensure_ascii=False),
                "```",
                "",
            ]
        )

    for row in explain_rows:
        add_case("explain", row)
    marker = _blank()
    marker["section"] = "synthetic"
    marker["case"] = "# synthetic"
    out_rows.append(marker)
    md.extend(["# synthetic", "", "These 15 sheets cover shapes. They are not a sample for a rate.", ""])
    for row in synthetic_rows:
        add_case("synthetic", row)
    with (HERE / "faithfulness_v7.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)
    (HERE / "faithfulness_v7_sheets.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def _import_store(rows: list[dict], items: list[dict]) -> int:
    os.environ["DATA_DIR"] = str(ROOT / "data")
    from app.explain_store import explanation_key, response_sha256, save_explanation

    by_id = {item["id"]: item for item in items}
    saved = 0
    for row in rows:
        if row.get("source") == "abstain" or not row.get("answer"):
            continue
        item = by_id[row["id"]]
        key = explanation_key(
            str(item.get("kpi_id") or ""),
            str(item.get("period") or ""),
            item.get("compare_to"),
            item["fact_sheet"],
            PROMPT,
            MODEL,
            row.get("lang") or "en",
        )
        citations = [
            {"sentence": claim["sentence"], "fact_ids": claim.get("fact_ids") or [], "frame": claim.get("frame")}
            for claim in row.get("claims") or []
            if claim.get("sentence")
        ]
        save_explanation(
            {
                "key": key,
                "response_sha256": response_sha256(row["answer"]),
                "text": row["answer"],
                "prose_source": row.get("source"),
                "attempts": row.get("attempts") or 0,
                "warning": row.get("warning"),
                "citations": citations,
                "citation_method": "declared_field_id",
                "prompt_version": PROMPT,
                "model": MODEL,
            }
        )
        saved += 1
    return saved


def _public_row(row: dict) -> dict:
    kept = dict(row)
    return kept


def main() -> None:
    from app.gate import gate_passes, identical_frame_sets

    LOG.write_text("", encoding="utf-8")
    _use_groq()
    say(f"concurrency {CONCURRENCY} min_interval_s {os.environ.get('BIFLOW_MIN_INTERVAL')} model {MODEL}")
    explain_cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    for case in explain_cases:
        case["lang"] = "en"
    synthetic = json.loads((HERE / "synthetic_sheets" / "sheets.json").read_text(encoding="utf-8"))["sheets"]
    runs: list[list[dict]] = []
    rate_limits: list[int] = []
    for index in range(3):
        cache = Path(tempfile.gettempdir()) / f"biflow-v7-paced-{index}.sqlite"
        if cache.exists():
            cache.unlink()
        os.environ["BIFLOW_CACHE"] = str(cache)
        rows, limited = _run_items(f"120b-run-{index + 1}", explain_cases)
        runs.append(rows)
        rate_limits.append(limited)
        partial = {"runs_complete": index + 1, "rate_limits": rate_limits, "run_rows": runs}
        (HERE / "bakeoff_v7_paced.partial.json").write_text(json.dumps(partial, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    strict = gate_passes(runs)
    relaxed = gate_passes(runs, drop_transport=True)
    sets = identical_frame_sets(runs)
    say(f"gate_strict passed={strict}")
    say(f"gate_without_429_or_timeout passed={relaxed}")
    say(f"identical_frame_sets {sets} of {len(explain_cases)}")

    cache = Path(tempfile.gettempdir()) / "biflow-v7-paced-synthetic.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    synthetic_rows, synthetic_429 = _run_items("synthetic", synthetic)
    say("synthetic table")
    for row in synthetic_rows:
        say(
            " | ".join(
                [
                    row["id"],
                    f"offered={','.join(row['offered']) or '-'}",
                    f"chosen={','.join(row['frames']) or '-'}",
                    f"first_try={row['first_try_pass']}",
                    f"source={row['source']}",
                    f"cause={row['fallback_cause']}",
                    f"direction={_direction_ok(row)}",
                    f"safety={row['safety_ok']}",
                    f"429={row['http_429']}",
                ]
            )
        )
    summaries = [_summarize(rows, limited) for rows, limited in zip(runs, rate_limits, strict=True)]
    payload = {
        "prompt_id": PROMPT,
        "model": MODEL,
        "temperature": 0,
        "seed": 7,
        "reasoning_effort": "low",
        "concurrency": CONCURRENCY,
        "min_interval_s": float(os.environ.get("BIFLOW_MIN_INTERVAL") or 8),
        "runs": summaries,
        "rate_limits": rate_limits,
        "gate": {
            "strict_passed": strict,
            "without_429_or_timeout_passed": relaxed,
            "api_default": "v7" if strict else "v6",
            "reason": (
                "All three cold 120B runs had first-try 1.00 and fallback 0.00."
                if strict
                else "The three cold 120B runs did not all have first-try 1.00 and fallback 0.00, so the api profile stays on v6."
            ),
        },
        "identical_frame_sets": sets,
        "n_cases": len(explain_cases),
        "exported_run": 1,
        "rows_run_1": [_public_row(row) for row in runs[0]],
        "rows_run_2": [_public_row(row) for row in runs[1]],
        "rows_run_3": [_public_row(row) for row in runs[2]],
        "synthetic": {
            "n": len(synthetic_rows),
            "http_429": synthetic_429,
            "note": "Shape coverage only. No rate is claimed from these 15 sheets.",
            "rows": synthetic_rows,
        },
    }
    (HERE / "bakeoff_v7_paced.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _export(runs[0], synthetic_rows, explain_cases, synthetic)
    saved = _import_store(runs[0] + [row for row in synthetic_rows if row.get("source") != "abstain"], explain_cases + synthetic)
    say(f"store_imported {saved}")
    say(f"gate api_default {payload['gate']['api_default']}")


if __name__ == "__main__":
    main()
