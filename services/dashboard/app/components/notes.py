"""Turn the pipeline's technical notes (stage warnings) into plain sentences for the Overview tab."""
from __future__ import annotations

import re

_UNIQUE = re.compile(r"^data check \(warn\) unique_stg_(\w+?)__(\w+?)_?: (\d+) rows$")
_REL = re.compile(r"^data check \(warn\) relationships_stg_(\w+?)_(\w+?)__(\w+?)__ref_stg_(\w+?)_?: (\d+) rows$")
_FACT = re.compile(r"^(.+?): fact-check failed after 2 retries; template text used\. Unsupported claims: (.+?)(\. Template text also failed the fact-check)?$")
_NOLLM = re.compile(r"^(.+?): language model unavailable; template text used$")


def plain(note: str) -> str:
    """One technical note -> one plain sentence. Unknown notes are returned as they are."""
    n = note.strip()
    if m := _UNIQUE.match(n):
        return (f"Data check (warning, not an error): {int(m[3]):,} rows in {m[1]} share the same {m[2]}, which is "
                f"expected to be unique. They are kept, and the analysis tables handle them.")
    if m := _REL.match(n):
        return (f"Data check (warning, not an error): {int(m[5]):,} rows of {m[1]} have a {m[2]} that is not found in "
                f"{m[4]} (e.g. a category with no English translation). They are kept.")
    if n.startswith("optional HTML profile skipped"):
        return "The optional HTML profile report was not produced (its library is not installed). The data scan itself ran normally."
    if n.startswith("embedder unavailable"):
        return "KPI search uses the built-in text matcher, because no embedding model is configured."
    if n.startswith("untracked transformations:"):
        steps = n.split(":", 1)[1].strip()
        return ("Some registered step types did not occur in this run. That is normal for optional steps "
                f"(e.g. SQL or API ingest when the source is CSV): {steps}.")
    if m := _FACT.match(n):
        return (f"Audit report, section '{m[1]}': the LLM's wording did not pass the fact-check, so the plain template "
                f"text was published instead. The facts in the report are correct.")
    if m := _NOLLM.match(n):
        return f"Audit report, section '{m[1]}': written from the template (the LLM was not available or not configured)."
    if n.startswith("LLM budget of") and "section calls reached" in n:
        return "The audit report reached its LLM budget: the remaining sections use template text."
    if n.startswith("LLM advisory skipped"):
        return "Cleaning ran without the optional LLM suggestions (LLM not available). All rule-based cleaning ran."
    if n.startswith("reconciliation failed"):
        return f"Row reconciliation FAILED: the fact table does not have one row per order. {n}"
    if n.startswith("TEST FAILED"):
        return f"A data test FAILED (error level): {n[len('TEST FAILED '):]}"
    return n


def stage_notes(manifest: dict) -> dict[str, list[str]]:
    """Notes per stage. New runs store them per stage; older runs only have the combined list (de-duplicated here)."""
    out: dict[str, list[str]] = {}
    for name, st in (manifest.get("stages") or {}).items():
        if "warnings" in st:
            out[name] = list(dict.fromkeys(st["warnings"]))
    if not out:
        for w in manifest.get("warnings", []):
            name, _, text = w.partition(": ")
            out.setdefault(name, [])
            if text not in out[name]:
                out[name].append(text)
    return {k: v for k, v in out.items() if v}


REVIEW_ISSUES = {
    "hidden_missing": "values that may mean 'missing' (e.g. '-', 'n/a')",
    "protected_key": "a suggestion touched a key column",
    "not_in_allow_list": "a suggested fix is not allowed for this column",
    "drop_column_needs_review": "a suggestion to drop the column",
}
