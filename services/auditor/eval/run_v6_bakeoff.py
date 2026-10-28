"""Bake-off for explain v3, v4, and v6. One arm at a time. Temperature 0.

Reads the provider settings from .env. Does not print the API key.
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))

os.environ.pop("FAKE_LLM", None)

from app.factcheck import fact_check, unsupported_claims  # noqa: E402
from app.prose import render_prompt, write_prose  # noqa: E402
from app.redact import redact  # noqa: E402
from app.templates import explain_template  # noqa: E402
from biflow_contracts.biflow_llm import LLMUnavailable, chat_text, drain_calls  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "bakeoff_v6.json"
COUNTS = {"429": 0}


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


def _wrap_http() -> None:
    if getattr(httpx.post, "_biflow_counts", False):
        return
    original = httpx.post

    def counting_post(*args, **kwargs):
        response = original(*args, **kwargs)
        if getattr(response, "status_code", None) == 429:
            COUNTS["429"] += 1
        return response

    counting_post._biflow_counts = True  # type: ignore[attr-defined]
    httpx.post = counting_post


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    return round(ordered[index], 1)


def _summarize(rows: list[dict], kind: str) -> dict:
    finished = [row for row in rows if row.get("error") is None]
    n = len(finished)
    if kind == "template":
        first = sum(1 for row in finished if row.get("first_try_pass"))
        after = 0
        fallback = 0
    else:
        first = sum(1 for row in finished if row.get("source") == "llm" and row.get("first_try_pass") is True)
        after = sum(1 for row in finished if row.get("source") == "llm" and row.get("first_try_pass") is False)
        fallback = sum(1 for row in finished if row.get("source") == "template")
    flagged = [row for row in finished if row.get("unsupported") is True]
    known = [row for row in finished if "unsupported" in row]
    latencies = [row["latency_ms"] for row in finished if isinstance(row.get("latency_ms"), (int, float))]
    tokens = [row["tokens"] for row in finished if isinstance(row.get("tokens"), int)]
    return {
        "n": n,
        "errors": len(rows) - n,
        "first_try_pass_rate": round(first / n, 4) if n else None,
        "pass_after_retry_rate": round(after / n, 4) if n else None,
        "fallback_rate": round(fallback / n, 4) if n else None,
        "unsupported_statement_rate": round(len(flagged) / n, 4) if n and known else None,
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "tokens": sum(tokens) if tokens else None,
        "http_429": None if kind == "reused" else COUNTS["429"],
    }


def _cases() -> list[dict]:
    return json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]


def _template_rows(cases: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        started = time.perf_counter()
        answer = explain_template(case["fact_sheet"], "en")
        rows.append(
            {
                "id": case["id"],
                "source": "code",
                "first_try_pass": fact_check(answer, case["fact_sheet"]),
                "attempts": 1,
                "answer": answer,
                "unsupported": bool(unsupported_claims(answer, case["fact_sheet"])),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "tokens": 0,
                "error": None,
            }
        )
    return rows


def _use_api(model: str) -> None:
    load_env()
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["LLM_MODEL_MAIN"] = model
    os.environ["LLM_MODEL_FAST"] = "llama-3.1-8b-instant"
    os.environ.pop("FAKE_LLM", None)


def _use_local(model: str) -> None:
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_BASE_URL"] = "http://localhost:11434/v1"
    os.environ["LLM_API_KEY"] = "ollama"
    os.environ["BIFLOW_PROFILE"] = "ollama"
    os.environ["LLM_MODEL_MAIN"] = model
    os.environ["LLM_MODEL_FAST"] = model
    os.environ.pop("FAKE_LLM", None)


def _model_rows(cases: list[dict], prompt_id: str, on_row) -> list[dict]:
    rows: list[dict] = []
    for case in cases:
        started = time.perf_counter()
        drain_calls()
        try:
            result = write_prose(
                prompt_id=prompt_id,
                fact_sheet=case["fact_sheet"],
                template=explain_template(case["fact_sheet"], "en"),
                lang="en",
                section=f"Explain {case['kpi_id']} for {case['period']}",
                min_sentences=3,
                max_sentences=5,
                temperature=0.0,
            )
            calls = drain_calls()
            issues = unsupported_claims(result.text, case["fact_sheet"])
            rows.append(
                {
                    "id": case["id"],
                    "source": result.source,
                    "first_try_pass": result.first_try_pass,
                    "attempts": result.attempts,
                    "warning": redact(result.warning),
                    "answer": result.text,
                    "claims": result.claims,
                    "unsupported": bool(issues),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "tokens": sum(call.tokens or 0 for call in calls),
                    "error": None,
                }
            )
        except (LLMUnavailable, TimeoutError, OSError) as exc:
            rows.append(
                {
                    "id": case["id"],
                    "source": None,
                    "first_try_pass": None,
                    "attempts": 0,
                    "latency_ms": None,
                    "tokens": None,
                    "error": redact(str(exc)),
                }
            )
        print(case["id"], rows[-1].get("source"), rows[-1].get("first_try_pass"), rows[-1].get("latency_ms"), flush=True)
        on_row(rows)
    return rows


def _reused(path: Path, model_key: str, prompt_id: str, cases: list[dict]) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    block = document[model_key]
    by_id = {case["id"]: case for case in cases}
    rows = []
    for row in block.get("rows") or []:
        copied = dict(row)
        answer = copied.get("answer")
        case = by_id.get(copied.get("id"))
        if isinstance(answer, str) and case:
            copied["unsupported"] = bool(unsupported_claims(answer, case["fact_sheet"]))
        copied["warning"] = redact(copied.get("warning"))
        rows.append(copied)
    summary = _summarize(rows, "reused")
    summary.update(
        {
            "kind": "reused",
            "prompt_id": prompt_id,
            "model": model_key,
            "temperature": 0.2,
            "reused_from": path.name,
            "note": "Earlier live run at temperature 0.2. Tokens and HTTP 429 were not recorded.",
            "rows": rows,
        }
    )
    return summary


def verify_groq() -> str | None:
    """GET /models, then one chat completion. Returns the model to use, or None on failure."""
    load_env()
    _wrap_http()
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    if not base or not key or key == "ollama":
        print("chat_status=missing_env")
        return None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        listed = httpx.get(f"{base}/models", headers=headers, timeout=30)
    except httpx.HTTPError as exc:
        print("models_status=network")
        print(redact(str(exc))[:300])
        return None
    print(f"models_status={listed.status_code}")
    if listed.status_code != 200:
        print(redact(listed.text)[:300])
        return None
    names = [item.get("id") or item.get("name") for item in (listed.json().get("data") or [])]
    names = [name for name in names if isinstance(name, str)]
    wanted = os.environ.get("LLM_MODEL_MAIN") or "llama-3.3-70b-versatile"
    if wanted not in names:
        siblings = [name for name in names if "70b" in name.lower()]
        print("model_missing", wanted)
        if siblings:
            wanted = siblings[0]
        elif "openai/gpt-oss-120b" in names:
            wanted = "openai/gpt-oss-120b"
        else:
            print("no_70b_sibling")
            return None
        print("model_substituted", wanted)
    else:
        print("model_present", wanted)
    payload = {
        "model": wanted,
        "messages": [{"role": "user", "content": "Reply with the single word pong."}],
        "temperature": 0,
        "max_tokens": 8,
    }
    status = 0
    body = ""
    for attempt in range(4):
        try:
            chat = httpx.post(f"{base}/chat/completions", headers=headers, json=payload, timeout=60)
        except httpx.HTTPError as exc:
            print("chat_status=network")
            print(redact(str(exc))[:300])
            return None
        status = chat.status_code
        body = chat.text
        if status == 429:
            wait = float(chat.headers.get("Retry-After", 2 ** attempt))
            print("chat_status=429")
            time.sleep(min(wait, 30))
            continue
        break
    print(f"chat_status={status}")
    if status != 200:
        print(redact(body)[:300])
        return None
    content = ((chat.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    print("chat_ok", redact(str(content))[:40])
    return wanted


def _local_tags() -> list[str]:
    try:
        payload = httpx.get("http://localhost:11434/api/tags", timeout=5).json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return []
    return [item.get("name", "") for item in payload.get("models") or []]


def _load() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"temperature": 0, "arms": {}, "mlflow": None}


def _save(payload: dict) -> None:
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run_live(payload: dict, name: str, prompt_id: str, mode: str, model: str, cases: list[dict]) -> None:
    existing = payload["arms"].get(name) or {}
    done_rows = [row for row in existing.get("rows") or [] if row.get("error") is None and row.get("answer")]
    if len(done_rows) == len(cases) and existing.get("errors") == 0 and os.environ.get("FORCE") != "1":
        print("skip", name, flush=True)
        return
    print("arm", name, model, prompt_id, flush=True)
    if mode == "api":
        _use_api(model)
    else:
        _use_local(model)
    safe = name.replace(":", "-")
    cache = Path(tempfile.gettempdir()) / f"biflow-bakeoff-{safe}.sqlite"
    os.environ["BIFLOW_CACHE"] = str(cache)
    prior_429 = existing.get("http_429") if isinstance(existing.get("http_429"), int) else 0
    COUNTS["429"] = 0
    arm = {
        "kind": "live",
        "prompt_id": prompt_id,
        "model": model,
        "provider": os.environ.get("LLM_PROVIDER"),
        "temperature": 0,
        "rows": list(done_rows),
    }
    payload["arms"][name] = arm
    _save(payload)
    done_ids = {row["id"] for row in done_rows}
    pending = [case for case in cases if case["id"] not in done_ids]

    def checkpoint(rows: list[dict]) -> None:
        summary = _summarize(rows, "live")
        summary["http_429"] = prior_429 + COUNTS["429"]
        arm.update(summary)
        arm["rows"] = rows
        payload["arms"][name] = arm
        _save(payload)

    rows = list(done_rows)
    rows.extend(_model_rows(pending, prompt_id, lambda new_rows: checkpoint(done_rows + new_rows)))
    checkpoint(rows)


def _judge_held_out(judge_model: str, local: bool) -> dict:
    if local:
        _use_local(judge_model)
    else:
        _use_api(os.environ.get("LLM_MODEL_MAIN") or "openai/gpt-oss-120b")
    os.environ["LLM_MODEL_FAST"] = judge_model
    document = json.loads((HERE / "held_out_prose.json").read_text(encoding="utf-8"))
    default_sheet = document.get("fact_sheet") if isinstance(document.get("fact_sheet"), dict) else {}
    items = []
    for item in document.get("items") or []:
        sheet = item.get("fact_sheet") if isinstance(item.get("fact_sheet"), dict) else default_sheet
        items.append({**item, "fact_sheet": sheet})
    unsupported = [item for item in items if item.get("supported") is False]
    supported = [item for item in items if item.get("supported") is True]
    judge_caught = 0
    union_caught = 0
    union_false = 0
    details = []
    for item in unsupported:
        regex_hit = bool(unsupported_claims(item["prose"], item["fact_sheet"]))
        failed = _judge_one(item["prose"], item["fact_sheet"])
        judge_caught += int(failed)
        union_caught += int(regex_hit or failed)
        details.append({"id": item["id"], "checker": regex_hit, "judge_fail": failed, "supported": False})
        print("judge", item["id"], "checker" if regex_hit else "checker-miss", "FAIL" if failed else "PASS", flush=True)
    for item in supported:
        regex_hit = not fact_check(item["prose"], item["fact_sheet"])
        failed = _judge_one(item["prose"], item["fact_sheet"])
        union_false += int(regex_hit or failed)
        details.append({"id": item["id"], "checker": regex_hit, "judge_fail": failed, "supported": True})
    n_bad = len(unsupported) or 1
    n_good = len(supported) or 1
    return {
        "judge_model": judge_model,
        "writer_model": "llama3.2:latest",
        "writer_note": "Held-out captions were written by llama3.2. The judge is a different model.",
        "n_unsupported": len(unsupported),
        "n_supported": len(supported),
        "recall": round(judge_caught / n_bad, 4) if unsupported else None,
        "checker_recall": round(sum(1 for row in details if row["supported"] is False and row["checker"]) / n_bad, 4) if unsupported else None,
        "union_recall": round(union_caught / n_bad, 4) if unsupported else None,
        "union_false_reject_rate": round(union_false / n_good, 4) if supported else None,
        "items": details,
    }


def _judge_one(prose: str, sheet: dict) -> bool:
    user = render_prompt(
        "auditor.fact_judge@v1",
        section="held-out",
        language="English",
        facts=json.dumps(sheet, ensure_ascii=False),
        prose=prose,
    )
    raw = chat_text("auditor.fact_judge@v1", "You check a paragraph against a fact sheet.", user, role="llm_fast", temperature=0.0)
    verdict = (raw or "").strip().split()
    return bool(verdict) and verdict[0].upper().startswith("FAIL")


def _judge_arm(arm: dict, judge_model: str, local: bool) -> dict:
    """Flags on the large model's published text. Not a recall: those answers are not hand-labelled."""
    if local:
        _use_local(judge_model)
    else:
        _use_api(arm.get("model") or "")
    os.environ["LLM_MODEL_FAST"] = judge_model
    flagged = 0
    seen = 0
    for row in arm.get("rows") or []:
        if not row.get("answer"):
            continue
        seen += 1
        # The judge needs the fact sheet. Recover it from the case id when the caller passes it.
        sheet = row.get("fact_sheet")
        if not isinstance(sheet, dict):
            continue
        flagged += int(_judge_one(row["answer"], sheet))
        print("judge70", row["id"], flagged, flush=True)
    return {
        "judge_model": judge_model,
        "writer_model": arm.get("model"),
        "n": seen,
        "flag_rate": round(flagged / seen, 4) if seen else None,
        "note": "Flag rate is not recall. The published answers are not hand-labelled.",
    }


def _best_arm(payload: dict) -> tuple[str, dict] | None:
    best_name = None
    best = None
    for name, arm in (payload.get("arms") or {}).items():
        if arm.get("kind") == "template" or arm.get("first_try_pass_rate") is None:
            continue
        rows = arm.get("rows") or []
        if not any(row.get("answer") or row.get("claims") for row in rows):
            continue
        rank = (arm["first_try_pass_rate"], -(arm.get("fallback_rate") or 0))
        if best is None or rank > best:
            best = rank
            best_name = name
    if best_name is None:
        return None
    return best_name, payload["arms"][best_name]


def _export(payload: dict, cases: list[dict]) -> None:
    chosen = _best_arm(payload)
    if chosen is None:
        print("no_exportable_arm")
        return
    name, arm = chosen
    by_id = {case["id"]: case for case in cases}
    csv_path = HERE / "faithfulness_template.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case", "sentence", "rendered text", "ids", "supported (1/0)"])
        for row in arm.get("rows") or []:
            claims = row.get("claims") or []
            if claims:
                for claim in claims:
                    writer.writerow([row["id"], claim.get("sentence") or "", claim.get("rendered") or "", " ".join(claim.get("ids") or []), ""])
                continue
            answer = row.get("answer") or ""
            for sentence in [part.strip() for part in answer.split(".") if part.strip()]:
                writer.writerow([row["id"], sentence + ".", sentence + ".", "", ""])
    model_rows = [row for row in arm.get("rows") or [] if row.get("source") == "llm" and row.get("answer")]
    picked = model_rows[:5] if len(model_rows) >= 5 else (arm.get("rows") or [])[:5]
    form_rows = []
    for row in picked:
        case = by_id.get(row["id"])
        if not case:
            continue
        form_rows.append({"case": row["id"], "source": "template", "text": explain_template(case["fact_sheet"], "en")})
        form_rows.append({"case": row["id"], "source": "model", "text": row.get("answer") or ""})
    random.Random(6).shuffle(form_rows)
    letters = "ABCDEFGHIJ"
    key_rows = []
    lines = [
        "# Clarity form",
        "",
        "Score each explanation from 1 (unclear) to 5 (clear to a non-technical reader).",
        "The source is hidden. Do not open `readability_key.json` until the scores are written down.",
        "",
        "Write the scores into `eval/readability.json` under `form_scores`:",
        "",
        '`"form_scores": [{"item": "A", "clarity": 4}]`',
        "",
        "Leave `scores` empty. That list is the five-person panel, which is separate from this form.",
        "",
    ]
    for index, row in enumerate(form_rows):
        letter = letters[index]
        key_rows.append({"item": letter, "case": row["case"], "source": row["source"]})
        lines.append(f"## {letter}")
        lines.append("")
        lines.append(row["text"])
        lines.append("")
        lines.append("Clarity (1-5):")
        lines.append("")
    (HERE / "readability_form.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (HERE / "readability_key.json").write_text(json.dumps({"arm": name, "items": key_rows}, indent=2) + "\n", encoding="utf-8")
    readable = json.loads((HERE / "readability.json").read_text(encoding="utf-8"))
    readable["form_scores"] = []
    readable["form_arm"] = name
    (HERE / "readability.json").write_text(json.dumps(readable, indent=2) + "\n", encoding="utf-8")
    payload["faithfulness_export"] = {"arm": name, "file": "faithfulness_template.csv", "labelled": False}
    print("exported", name, flush=True)


def _markdown(payload: dict) -> str:
    header = "| arm | model | prompt | first try | after retry | fallback | unsupported | p50 ms | p95 ms | tokens | 429 |"
    rule = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, rule]
    for name, arm in (payload.get("arms") or {}).items():
        lines.append(
            "| {name} | {model} | {prompt} | {first} | {after} | {fallback} | {bad} | {p50} | {p95} | {tokens} | {limited} |".format(
                name=name,
                model=arm.get("model") or "",
                prompt=arm.get("prompt_id") or "",
                first=arm.get("first_try_pass_rate"),
                after=arm.get("pass_after_retry_rate"),
                fallback=arm.get("fallback_rate"),
                bad=arm.get("unsupported_statement_rate"),
                p50=arm.get("latency_ms_p50"),
                p95=arm.get("latency_ms_p95"),
                tokens=arm.get("tokens"),
                limited=arm.get("http_429"),
            )
        )
    decision = payload.get("default_decision") or {}
    lines.append("")
    lines.append(decision.get("reason") or "")
    return "\n".join(lines) + "\n"


def _decide(payload: dict) -> None:
    v4 = (payload.get("arms") or {}).get("groq-120b-v4") or {}
    v6 = (payload.get("arms") or {}).get("groq-120b-v6") or {}
    left = v4.get("first_try_pass_rate")
    right = v6.get("first_try_pass_rate")
    beats = left is not None and right is not None and right > left
    payload["default_decision"] = {
        "default": "v6" if beats else "v3",
        "beats_v4": beats,
        "groq_v4_first_try": left,
        "groq_v6_first_try": right,
        "reason": (
            "The large-model v6 first-try rate is higher than v4, so explain_kpi defaults to v6."
            if beats
            else "The large-model v6 first-try rate did not beat v4. The explain default stays v3."
        ),
    }


def _mlflow(payload: dict) -> dict:
    try:
        health = httpx.get("http://127.0.0.1:5000/health", timeout=2)
        up = health.status_code < 500
    except httpx.HTTPError:
        return {"logged": False, "reason": "MLflow is not running"}
    if not up:
        return {"logged": False, "reason": "MLflow is not running"}
    try:
        import mlflow
    except ImportError:
        return {"logged": False, "reason": "MLflow is running but the mlflow package is not installed"}
    mlflow.set_tracking_uri("http://127.0.0.1:5000")
    mlflow.set_experiment("auditor-explain-bakeoff")
    with mlflow.start_run(run_name="v6-bakeoff"):
        for name, arm in (payload.get("arms") or {}).items():
            for key in ("first_try_pass_rate", "pass_after_retry_rate", "fallback_rate", "unsupported_statement_rate"):
                if isinstance(arm.get(key), (int, float)):
                    mlflow.log_metric(f"{name}.{key}", arm[key])
    return {"logged": True}


def main() -> None:
    load_env()
    _wrap_http()
    cases = _cases()
    payload = _load()
    payload["temperature"] = 0
    selected = [item for item in os.environ.get("ARMS", "").split(",") if item]
    tags = _local_tags()
    groq_model = None
    needs_groq = not selected or any(name.startswith("groq") or name == "judge" for name in selected)
    if needs_groq:
        groq_model = verify_groq()
        if groq_model is None:
            payload["connection"] = {"requested_model": "llama-3.3-70b-versatile", "chat_status": "failed"}
            _save(payload)
            print("stopped_after_connection_failure")
            sys.exit(1)
        payload["connection"] = {
            "requested_model": "llama-3.3-70b-versatile",
            "requested_model_status": 404 if "70b" not in groq_model else 200,
            "model": groq_model,
            "chat_status": 200,
            "note": None
            if "70b" in groq_model
            else "llama-3.3-70b-versatile is not on this key (HTTP 404 model_not_found). No 70B id was listed. The large arm uses openai/gpt-oss-120b. llama-3.1-8b-instant is also 404, so the judge is local llama3.1:8b.",
        }
        os.environ["LLM_MODEL_MAIN"] = groq_model

    def want(name: str) -> bool:
        return not selected or name in selected

    if want("template") and "template" not in payload["arms"]:
        rows = _template_rows(cases)
        arm = _summarize(rows, "template")
        arm.update({"kind": "template", "prompt_id": "code", "model": "template", "temperature": 0, "rows": rows})
        payload["arms"]["template"] = arm
        _save(payload)
    if want("llama3.2-v3") and "llama3.2-v3" not in payload["arms"]:
        payload["arms"]["llama3.2-v3"] = _reused(HERE / "bakeoff_results.json", "llama3.2:latest", "auditor.explain_kpi@v3", cases)
        _save(payload)
    if want("llama3.2-v4") and "llama3.2-v4" not in payload["arms"]:
        payload["arms"]["llama3.2-v4"] = _reused(HERE / "bakeoff_v4.json", "llama3.2:latest", "auditor.explain_kpi@v4", cases)
        _save(payload)
    if want("groq-120b-v4"):
        _run_live(payload, "groq-120b-v4", "auditor.explain_kpi@v4", "api", groq_model or "", cases)
    if want("groq-120b-v6"):
        _run_live(payload, "groq-120b-v6", "auditor.explain_kpi@v6", "api", groq_model or "", cases)
    if want("llama3.2-v6") and "llama3.2:latest" in tags:
        _run_live(payload, "llama3.2-v6", "auditor.explain_kpi@v6", "local", "llama3.2:latest", cases)
    elif want("llama3.2-v6"):
        payload["arms"]["llama3.2-v6"] = {"kind": "missing", "model": "llama3.2:latest", "error": "tag not installed"}
        _save(payload)
    eight = next((tag for tag in tags if tag.startswith("llama3.1:8b")), None)
    for prompt, suffix in (("auditor.explain_kpi@v4", "v4"), ("auditor.explain_kpi@v6", "v6")):
        arm_name = f"llama3.1-8b-{suffix}"
        if not want(arm_name):
            continue
        if eight:
            _run_live(payload, arm_name, prompt, "local", eight, cases)
        else:
            payload["arms"][arm_name] = {"kind": "missing", "model": "llama3.1:8b", "error": "still not installed"}
            _save(payload)
    judge_local = "llama3.1:8b" in tags
    judge_model = "llama3.1:8b" if judge_local else "openai/gpt-oss-20b"
    if want("judge") and groq_model:
        judged = _judge_held_out(judge_model, judge_local)
        (HERE / "judge_held_out.json").write_text(json.dumps(judged, indent=2) + "\n", encoding="utf-8")
        bad_path = HERE / "bad_prose.json"
        planted = json.loads(bad_path.read_text(encoding="utf-8"))
        items = planted.get("items") if isinstance(planted, dict) else planted
        bad_path.write_text(
            json.dumps(
                {
                    "llm_judge_recall": judged.get("recall"),
                    "judge_model": judged.get("judge_model"),
                    "writer_model": judged.get("writer_model"),
                    "note": "Recall is on the labelled held-out captions, not on this development list. The judge model is not the writer.",
                    "items": items,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        groq_arm = payload["arms"].get("groq-120b-v6") or payload["arms"].get("groq-120b-v4")
        if groq_arm:
            for row in groq_arm.get("rows") or []:
                case = next((item for item in cases if item["id"] == row.get("id")), None)
                if case:
                    row["fact_sheet"] = case["fact_sheet"]
            payload["groq_judge_flags"] = _judge_arm(groq_arm, judge_model, judge_local)
            for row in groq_arm.get("rows") or []:
                row.pop("fact_sheet", None)
        payload["judge_held_out"] = {key: value for key, value in judged.items() if key != "items"}
        _save(payload)
    _decide(payload)
    _export(payload, cases)
    payload["mlflow"] = _mlflow(payload)
    _save(payload)
    table = _markdown(payload)
    (HERE / "bakeoff_v6.md").write_text(table, encoding="utf-8")
    print(table)


if __name__ == "__main__":
    main()
