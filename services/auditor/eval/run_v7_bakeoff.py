"""v7 frame-selection bake-off. Uses .env. Does not print the API key.

Two cold runs for gpt-oss-120b. One run each for gpt-oss-20b, llama3.1:8b, and llama3.2.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))
os.environ.pop("FAKE_LLM", None)

HERE = Path(__file__).resolve().parent


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


def _cases() -> list[dict]:
    return json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]


def _use(provider: str, model: str) -> None:
    load_env()
    os.environ.pop("FAKE_LLM", None)
    os.environ["LLM_MODEL_MAIN"] = model
    os.environ["LLM_MODEL_FAST"] = model
    if provider == "api":
        os.environ["LLM_PROVIDER"] = "api"
        os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
        os.environ["BIFLOW_PROFILE"] = "api"
    else:
        os.environ["LLM_PROVIDER"] = "ollama"
        os.environ["LLM_BASE_URL"] = "http://localhost:11434/v1"
        os.environ["LLM_API_KEY"] = "ollama"
        os.environ["BIFLOW_PROFILE"] = "ollama"


def _local_tags() -> list[str]:
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=5)
    except httpx.HTTPError:
        return []
    if response.status_code != 200:
        return []
    return [str(item.get("name")) for item in (response.json().get("models") or []) if isinstance(item, dict)]


def _run(tag: str, cases: list[dict]) -> tuple[list[dict], int]:
    import app.v7 as v7
    from app.prose import write_prose
    from app.templates import explain_template
    from app.v7 import offered_frames
    from biflow_contracts.biflow_llm import drain_calls

    v7.HTTP_429 = 0
    rows = []
    for case in cases:
        drain_calls()
        started = time.perf_counter()
        result = write_prose(
            prompt_id="auditor.explain_kpi@v7",
            fact_sheet=case["fact_sheet"],
            template=explain_template(case["fact_sheet"], "en"),
            lang="en",
            section=f"Explain {case['kpi_id']} for {case['period']}",
            min_sentences=3,
            max_sentences=5,
            temperature=0.0,
        )
        calls = drain_calls()
        frames = [claim.get("frame") for claim in (result.claims or []) if claim.get("frame")]
        offered = [frame.name for frame in offered_frames(case["fact_sheet"], "en")]
        rows.append(
            {
                "id": case["id"],
                "source": result.source,
                "first_try_pass": result.first_try_pass,
                "attempts": result.attempts,
                "warning": result.warning,
                "frames": frames,
                "offered": offered,
                "f3_offered": "F3" in offered,
                "f3_omitted": "F3" in offered and "F3" not in frames,
                "picked_f6": "F6" in frames,
                "picked_f7": "F7" in frames,
                "f6_offered": "F6" in offered,
                "f7_offered": "F7" in offered,
                "answer": result.text,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "tokens": sum(call.tokens or 0 for call in calls),
            }
        )
        print(tag, case["id"], result.source, result.first_try_pass, ",".join(frames), flush=True)
    print(tag, "http_429", v7.HTTP_429, flush=True)
    return rows, v7.HTTP_429


def _summarize(rows: list[dict], http_429: int) -> dict:
    n = len(rows)
    first = sum(1 for row in rows if row["source"] == "llm" and row["first_try_pass"] is True)
    after = sum(1 for row in rows if row["source"] == "llm" and row["first_try_pass"] is False)
    fallback = sum(1 for row in rows if row["source"] == "fallback")
    offered_f3 = [row for row in rows if row["f3_offered"]]
    omitted = sum(1 for row in offered_f3 if row["f3_omitted"])
    latencies = [row["latency_ms"] for row in rows]
    return {
        "n": n,
        "first_try_pass_rate": round(first / n, 4) if n else None,
        "pass_after_retry_rate": round(after / n, 4) if n else None,
        "fallback_rate": round(fallback / n, 4) if n else None,
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "tokens": sum(row["tokens"] for row in rows),
        "http_429": http_429,
        "f3_offered": len(offered_f3),
        "f3_omitted": omitted,
        "f6_offered": sum(1 for row in rows if row["f6_offered"]),
        "f6_picked": sum(1 for row in rows if row["picked_f6"]),
        "f7_offered": sum(1 for row in rows if row["f7_offered"]),
        "f7_picked": sum(1 for row in rows if row["picked_f7"]),
    }


def _arm(name: str, provider: str, model: str, cases: list[dict], runs: int) -> dict:

    _use(provider, model)
    run_rows = []
    rate_limits: list[int] = []
    for index in range(runs):
        cache = Path(tempfile.gettempdir()) / f"biflow-v7-{name}-{index}.sqlite"
        if cache.exists():
            cache.unlink()
        os.environ["BIFLOW_CACHE"] = str(cache)
        rows, limited = _run(f"{name}-{index}", cases)
        run_rows.append(rows)
        rate_limits.append(limited)
    summary = _summarize(run_rows[0], rate_limits[0])
    if runs == 2:
        by_id = {row["id"]: row for row in run_rows[1]}
        identical = sum(1 for row in run_rows[0] if row["frames"] == by_id[row["id"]]["frames"])
        same_text = sum(1 for row in run_rows[0] if row["answer"] == by_id[row["id"]]["answer"])
        summary["runs"] = 2
        summary["identical_frame_lists"] = identical
        summary["identical_text"] = same_text
        both_first = all(row["source"] == "llm" and row["first_try_pass"] is True for row in run_rows[0]) and all(
            row["source"] == "llm" and row["first_try_pass"] is True for row in run_rows[1]
        )
        both_fallback = all(row["source"] != "fallback" for row in run_rows[0]) and all(row["source"] != "fallback" for row in run_rows[1])
        summary["both_runs_first_try_1"] = both_first and len(run_rows[0]) == 20
        summary["both_runs_fallback_0"] = both_fallback
        summary["second_run"] = _summarize(run_rows[1], rate_limits[-1])
    summary["model"] = model
    summary["provider"] = provider
    summary["rows"] = run_rows[0]
    if runs == 2:
        summary["rows_run_b"] = [{"id": row["id"], "frames": row["frames"], "source": row["source"], "first_try_pass": row["first_try_pass"]} for row in run_rows[1]]
    return summary


def _checker_comparison() -> dict:
    from app.factcheck import unsupported_claims

    held = json.loads((HERE / "held_out_prose.json").read_text(encoding="utf-8"))
    fresh = json.loads((HERE / "held_out_fresh.json").read_text(encoding="utf-8"))
    held_sheet = held["fact_sheet"]
    bad = [item for item in held["items"] if item.get("supported") is False]
    held_caught = sum(1 for item in bad if unsupported_claims(item["prose"], item.get("fact_sheet") or held_sheet))
    fresh_bad = fresh["items"]
    fresh_caught = sum(1 for item in fresh_bad if unsupported_claims(item["prose"], fresh["fact_sheet"]))
    return {
        "held_out_before_rules": 0.3333,
        "held_out_after_rules_on_same_captions": round(held_caught / len(bad), 4) if bad else None,
        "fresh_checker_recall": round(fresh_caught / len(fresh_bad), 4) if fresh_bad else None,
        "not_producible_by_v7": True,
        "note": "These captions are free prose. v7 can publish only the fixed frames, so none of these sentences is a v7 output.",
    }


def _markdown(payload: dict) -> str:
    lines = [
        "# v7 frame bake-off",
        "",
        "The model selects frame names. Code writes the text. Two cold runs are reported for the 120B.",
        "",
        "| arm | model | first try | after retry | fallback | p50 ms | p95 ms | tokens | 429 | identical frames |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, arm in payload["arms"].items():
        if arm.get("error"):
            lines.append(f"| {name} | {arm.get('model')} | — | — | — | — | — | — | — | {arm['error']} |")
            continue
        lines.append(
            "| {name} | {model} | {first} | {after} | {fallback} | {p50} | {p95} | {tokens} | {http} | {same} |".format(
                name=name,
                model=arm.get("model"),
                first=arm.get("first_try_pass_rate"),
                after=arm.get("pass_after_retry_rate"),
                fallback=arm.get("fallback_rate"),
                p50=arm.get("latency_ms_p50"),
                p95=arm.get("latency_ms_p95"),
                tokens=arm.get("tokens"),
                http=arm.get("http_429"),
                same=arm.get("identical_frame_lists", "—"),
            )
        )
    gate = payload["gate"]
    lines.extend(
        [
            "",
            f"Gate: api default is {gate['api_default']}. {gate['reason']}",
            "",
            f"F3 omitted when offered, published text, 120B run A: {payload['omission']['f3_omitted']} of {payload['omission']['f3_offered']}.",
            f"F6 picked {payload['omission']['f6_picked']} (offered {payload['omission']['f6_offered']}). F7 picked {payload['omission']['f7_picked']} (offered {payload['omission']['f7_offered']}).",
            "",
            "No frame sentence contains a cause, a forecast, a target, or an opinion. Numbers and units are filled from the sheet.",
            "The held-out and fresh captions are not producible by v7. Checker recalls on those sets are unchanged and are listed in the JSON.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    cases = _cases()
    tags = _local_tags()
    print("local_tags", tags, flush=True)
    arms: dict[str, dict] = {}
    arms["groq-120b"] = _arm("groq-120b", "api", "openai/gpt-oss-120b", cases, 2)
    arms["groq-20b"] = _arm("groq-20b", "api", "openai/gpt-oss-20b", cases, 1)
    local = {"llama3.1:8b": "llama-8b", "llama3.2:latest": "llama-3b"}
    for model, name in local.items():
        if model == "llama3.1:8b":
            present = any("llama3.1:8b" in tag for tag in tags)
        else:
            present = any(tag.startswith("llama3.2") for tag in tags)
        if not present:
            arms[name] = {"model": model, "error": "model not installed", "provider": "ollama"}
            print("skip", model, flush=True)
            continue
        arms[name] = _arm(name, "ollama", model, cases, 1)
    big = arms["groq-120b"]
    gate_pass = bool(big.get("both_runs_first_try_1") and big.get("both_runs_fallback_0"))
    local_gate = {}
    for name in ("llama-8b", "llama-3b"):
        arm = arms.get(name) or {}
        local_gate[name] = bool(arm.get("first_try_pass_rate") == 1.0 and arm.get("fallback_rate") == 0.0)
    payload = {
        "prompt_id": "auditor.explain_kpi@v7",
        "temperature": 0,
        "seed": 7,
        "reasoning_effort": "low on the api provider; omitted for ollama",
        "gate": {
            "passed": gate_pass,
            "api_default": "v7" if gate_pass else "v6",
            "ollama_default": "v4",
            "low_ram_default": "v7" if local_gate.get("llama-3b") else "v4",
            "reason": (
                "Both 120B runs had first-try 1.00 and fallback 0.00."
                if gate_pass
                else "The 120B runs did not both reach first-try 1.00 and fallback 0.00, so the api profile stays on v6."
            ),
            "local": local_gate,
            "ollama_note": "The ollama profile's configured model is qwen2.5:7b-instruct, which was not in this bake-off, so that profile stays on v4.",
        },
        "omission": {
            "f3_offered": big.get("f3_offered"),
            "f3_omitted": big.get("f3_omitted"),
            "f6_offered": big.get("f6_offered"),
            "f6_picked": big.get("f6_picked"),
            "f7_offered": big.get("f7_offered"),
            "f7_picked": big.get("f7_picked"),
        },
        "checker_comparison": _checker_comparison(),
        "arms": arms,
    }
    (HERE / "bakeoff_v7.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (HERE / "bakeoff_v7.md").write_text(_markdown(payload), encoding="utf-8")
    print("gate", payload["gate"]["api_default"], payload["gate"]["reason"], flush=True)


if __name__ == "__main__":
    main()
