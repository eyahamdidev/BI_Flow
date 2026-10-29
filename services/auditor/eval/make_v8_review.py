"""Write the friend-facing review HTML from eval/v8_sample.json. No API key is read."""

from __future__ import annotations

import html
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "v8_sample.json"
OUT = HERE / "v8_review.html"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def seconds(ms: float) -> str:
    return f"{ms / 1000:.1f} seconds"


def main() -> None:
    payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
    rows = payload["rows"]
    accepted = [row for row in rows if row["source"] == "llm"]
    first = [row for row in accepted if row["first_try"] is True]
    retried = [row for row in accepted if row["first_try"] is False]
    backup = [row for row in rows if row["source"] == "template"]
    issues = [row for row in rows if row["checker_issues"]]
    kept_largest = sum(
        1
        for row in rows
        if row["largest"] and all(label in " ".join(row["kept"]) for label in row["largest"])
    )
    same_five = sum(
        1
        for row in rows
        if set(row["kept"]) == {row["offered"][0], row["offered"][1], row["offered"][2], row["offered"][5], row["offered"][6]}
    )
    times = [row["latency_ms"] for row in rows]
    first_times = [row["latency_ms"] for row in first]
    retry_times = [row["latency_ms"] for row in retried]
    ex01 = next(row for row in rows if row["id"] == "ex01")
    by_id = {row["id"]: row for row in rows}

    summary = [
        ("Explanation sheets", "20"),
        ("Paragraph written by the model", f"{len(accepted)} / 20"),
        ("Accepted on the first answer", f"{len(first)} / 20"),
        ("Accepted after a rewrite", f"{len(retried)} / 20"),
        ("Python backup used", f"{len(backup)} / 20"),
        ("Published paragraph with a bad number, direction, or top state", f"{len(issues)} / 20"),
        ("Biggest state kept", f"{kept_largest} / 20"),
        ("Same five facts kept", f"{same_five} / 20"),
        ("Fastest sheet", seconds(min(times))),
        ("Typical sheet (median)", seconds(statistics.median(times))),
        ("Slowest sheet", seconds(max(times))),
        ("Typical first-try sheet", seconds(statistics.median(first_times))),
        ("Typical rewritten sheet", seconds(statistics.median(retry_times))),
    ]
    summary_html = "\n".join(
        f"<tr><td>{esc(label)}</td><td>{esc(value)}</td></tr>" for label, value in summary
    )
    offered = "\n".join(f"<li>{esc(item)}</li>" for item in ex01["offered"])
    kept = "\n".join(f"<li>{esc(item)}</li>" for item in ex01["kept"])
    dropped = "\n".join(f"<li>{esc(item)}</li>" for item in ex01["dropped"])
    retry_line = ", ".join(f"{row['id']} ({row['attempts']} answers)" for row in retried)
    case_rows = "\n".join(
        "<tr>"
        f"<td>{esc(row['id'])}</td>"
        f"<td>{esc(row['kpi_id'])}</td>"
        f"<td>{esc(row['period'])} vs {esc(row['compare_to'])}</td>"
        f"<td>{esc(row['attempts'])}</td>"
        f"<td>{'model' if row['source'] == 'llm' else esc(row['source'])}</td>"
        "</tr>"
        for row in rows
    )

    loose_notes = {
        "ex03": (
            "The definition was in the dropped list. The paragraph still says the KPI tracks "
            "the total payments received for delivered orders. The letters are lowercase, and the check "
            "looks for the exact phrase from the file, so it did not flag this."
        ),
        "ex04": (
            "The last sentence says the rest of the increase was contributed by other factors. "
            "The file does not say that. The cause check looks for words such as because and due to. "
            "Other factors is not in that list."
        ),
        "ex12": (
            "The KPI is average order value. The paragraph says the revenue went up. "
            "The number 12000 is the logged change. The checker does not flag the extra word revenue."
        ),
    }
    loose_html = []
    for case_id, note in loose_notes.items():
        row = by_id[case_id]
        loose_html.append(
            "<div class='case'>"
            f"<p class='label'>{esc(row['id'])} · {esc(row['kpi_id'])} · {esc(row['period'])} vs {esc(row['compare_to'])}</p>"
            f"<p class='quote'>{esc(row['text'])}</p>"
            f"<p>{esc(note)}</p>"
            "</div>"
        )

    details = []
    for row in rows:
        answers = "answer" if row["attempts"] == 1 else "answers"
        details.append(
            "<div class='case'>"
            f"<p class='label'>{esc(row['id'])} · {esc(row['kpi_id'])} · "
            f"{esc(row['period'])} vs {esc(row['compare_to'])} · {esc(row['attempts'])} {answers}</p>"
            f"<p><strong>Kept.</strong> {esc('; '.join(row['kept']))}</p>"
            f"<p><strong>Left out.</strong> {esc('; '.join(row['dropped']))}</p>"
            f"<p class='quote'>{esc(row['text'])}</p>"
            "</div>"
        )

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>How the KPI explanation works</title>
<style>
  @page {{
    size: A4;
    margin: 16mm 16mm 18mm 16mm;
    @bottom-center {{
      content: "BO2 explanations  |  29 October 2026  |  " counter(page);
      font-family: Arial, sans-serif;
      font-size: 9pt;
      color: #555;
    }}
  }}
  body {{ font-family: Arial, sans-serif; font-size: 11.5pt; line-height: 1.45; color: #1a1a1a; }}
  h1 {{ font-size: 20pt; line-height: 1.2; margin: 0 0 0.3em; }}
  h2 {{ font-size: 14pt; margin: 1.3em 0 0.4em; page-break-after: avoid; }}
  p {{ margin: 0.45em 0; }}
  ul {{ margin: 0.3em 0 0.6em 1.1em; }}
  li {{ margin: 0.12em 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.6em 0 1em; page-break-inside: avoid; }}
  th, td {{ border: 1px solid #c8c8c8; padding: 4px 8px; text-align: left; vertical-align: top; font-size: 10pt; }}
  th {{ background: #f0f0f0; }}
  .lede {{ color: #333; }}
  .quote {{ margin: 0.3em 0; padding: 8px 10px; background: #f6f6f6; }}
  .label {{ font-weight: bold; margin-bottom: 0.15em; }}
  .case {{ page-break-inside: avoid; margin: 0.8em 0 1em; }}
</style>
</head>
<body>
<h1>How the KPI explanation works</h1>
<p class="lede">A note for friends reviewing the auditor. 29 October 2026.</p>
<p>A KPI here is one business number, such as revenue or the number of orders. The auditor's job is to explain that number in a short paragraph. The model reads the logged facts, chooses which ones a reader needs, and writes the paragraph. A checker then reads that paragraph and rejects it when a number, a direction, or a named place does not match the file.</p>

<h2>1. Where the facts come from</h2>
<p>The facts are not invented by the model. They come from the project files for that KPI: the name, the two months being compared, the size of the change, each state's contribution, the written definition, the time grain, the source tables, and the cleaning steps. The model sees that list with the values filled in. The list stays in file order. Nothing is pre-ranked.</p>
<p>When the list has more than five facts, the model must keep exactly five and leave the rest out. It must also write the paragraph itself, in three to five sentences. Every fact has to be placed once: either kept or left out. A kept fact has to appear in the paragraph. A fact it left out must not appear.</p>

<h2>2. One explanation, end to end</h2>
<p>This is the first test sheet, Revenue for January 2017 compared with December 2016. The file offered ten facts:</p>
<ul>
{offered}
</ul>
<p>The model kept five:</p>
<ul>
{kept}
</ul>
<p>It left these out:</p>
<ul>
{dropped}
</ul>
<p>It wrote:</p>
<p class="quote">{esc(ex01["text"])}</p>
<p>That answer was accepted on the first try. The checker pulled the numbers 1000, 2016, 12, 2017, 01, and 600 out of the paragraph. Each one is in the file. "Went up" matches a positive change of 1000. "Largest contribution came from SP" matches the file, because SP at 600 is bigger than RJ at 400. RJ, the definition, the word month, the table names, and the cleaning steps do not appear. Revenue, both months, 1000, and SP do appear. There is no "because" and no word such as "important" or "strong".</p>
<p>The checker is an extractor. It pulls numbers, direction words, and names out of the paragraph with patterns and compares them with the file. It does not ask a second model whether the paragraph sounds true, and it does not parse the grammar of the sentence.</p>

<h2>3. When the checker rejects a draft</h2>
<p>The error is sent back to the model, and the model rewrites. It gets two rewrites. If the third answer is still wrong, Python writes a backup paragraph and the screen says the model was rejected. On this test the backup was never used.</p>
<p>Five sheets were rejected at least once, then accepted: {esc(retry_line)}. The rejected drafts were not saved. Only the accepted paragraph is in this note. ex14 needed two rewrites. The other four needed one.</p>

<h2>4. What was tested</h2>
<p>The test is one run of the 20 explanation sheets already in the project. There are five KPIs (revenue, orders, average order value, late-delivery rate, average review score) and four pairs of months. The model is {esc(payload["model"])}. The prompt is explain version 8. Calls were one at a time, with a 2 second pause between sheets. That pause is not included in the times below.</p>
<p>The amounts on these sheets are a test ladder: 1000, 2000, 3000, and so on, split 60/40 across two states. They use the same names, units, tables, and cleaning steps as the project KPIs. They are not a live reading from the warehouse. A late-delivery rate of 13000 in this file is a test number, not a real rate.</p>
<p>Every sheet offered the same ten kinds of facts, so the model had to leave five out. That is the choice this test measures.</p>

<h2>5. Results</h2>
<p>A pass means the checker accepted the paragraph and the screen would show the model's own words.</p>
<table>
<tr><th>What was counted</th><th>Result</th></tr>
{summary_html}
</table>
<p>On every sheet the model kept the same five facts: the KPI name, the two months, the total change, and the biggest state. On every sheet it left out the definition, the word month, the smaller state, the table names, and the cleaning steps. That pattern held on {same_five} of the 20 sheets.</p>
<p>The middle time for one sheet was {esc(seconds(statistics.median(times)))}. A first-try answer was typically {esc(seconds(statistics.median(first_times)))}. ex14, which was rewritten twice, took {esc(seconds(max(times)))}.</p>

<h2>6. How to read 15 / 20 and 20 / 20</h2>
<p>15 / 20 means the first draft already satisfied the checker. 20 / 20 means that after the allowed rewrites, every published paragraph was the model's writing, and none of those paragraphs contained a number, a direction, or a "largest" place that the file rejects.</p>
<p>This is one run of 20 sheets. The same model can choose different words on another day. A person has not yet marked whether leaving out the definition, or the smaller state, would mislead a reader. That judgement is still open. These figures are the checker's figures.</p>

<h2>7. Wording the checker let through</h2>
<p>The extractor catches a false number, a false direction, a false "largest" place, a forbidden word, and an exact copy of a fact the model said it dropped. A few accepted sentences still add wording the file does not contain. Three of them are worth seeing before a review.</p>
{"".join(loose_html)}
<p>One more small gap: the check requires the number on a kept change, and it does not require the unit word. On ex16 the model wrote 16000 and 9600 without the word ratio. The numbers are the logged ones.</p>

<h2>8. The 20 paragraphs</h2>
<p>Tries is the answer that was accepted. 1 means the first draft passed.</p>
<table>
<tr><th>Case</th><th>KPI</th><th>Months</th><th>Tries</th><th>Published by</th></tr>
{case_rows}
</table>
{"".join(details)}
</body>
</html>
"""
    OUT.write_text(document, encoding="utf-8")
    print(f"same_five {same_five}")
    print(f"kept_largest {kept_largest}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
