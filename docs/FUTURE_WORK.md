# Future work

Known improvements, in rough order of value. Each item says what exists today and what is missing.

## Product (what users see)

1. **Act on the review queue from the dashboard.** Today the cleaning step's "needs a human decision" items are
   shown in Overview → Notes per step, read-only. The building blocks exist: BO3's cleaner applies approved
   decisions from `data/decisions/<dataset>.yaml`, and the gateway can re-run from one stage
   (`run --resume <run> --from clean`). Missing: approve / reject / set-value buttons in the dashboard, a gateway
   endpoint that writes the decision, and an automatic re-run from `clean`.
2. **Add a dataset with a new structure from the dashboard.** Today: same structure as an existing dataset
   (upload in the sidebar), or new structure via config files by hand. Missing: an "onboard" flow that drafts the
   four config files (BO5 `suggest_kpis` already drafts the KPI YAML) for a human to review.
3. **Manage runs:** delete a run from the dashboard; compare two runs side by side.
4. **Semantic KPI search.** BO5 retrieval uses a built-in character-trigram matcher (Recall@1 0.875 on 32 questions)
   because no embedding model could be downloaded on the development network. Set `EMBED_PROVIDER=ollama`
   (`nomic-embed-text`) or allow the ONNX MiniLM download; the index rebuilds itself when the embedder changes.

## Quality of the analysis and the explanations

5. **BO2 fact-checker on real events:** sections about pipeline stages often fall back to the template because the
   LLM writes ranking phrases ("the main step was ...") that cannot be checked; tune the section prompt (v4) so it
   does not make ranking claims there, and measure before/after.
6. **BO2 audit time:** ~90 s of a ~115 s run is LLM prose (13 calls to the 120B model). Use the fast model for
   section prose, or fewer retries.
7. **BO2 Explain wording:** rates are written as raw ratios ("went up by 0.048367 ratio" instead of "+4.8 points"),
   and the closing sentence lists every cleaning step (17 names). Format by unit (percent points for ratios) and
   summarise the lineage ("8 source tables, 12 cleaning rules: see the Lineage tab").
8. **BO2 false alarm:** "row continuity break" is reported for joins that read several tables.
9. **BO4 quality score sensitivity:** the score moves 99.0 -> 99.1 after cleaning on the sample; tune weights /
   dimensions so cleaning gains are visible (the eval shows it does react to heavy corruption: 100 -> 88.5).
10. **Lineage completeness semantics (contract change):** split `lineage_steps` into always-emitted vs optional in
   `MetaResponse`, so optional steps (SQL/API ingest...) no longer count as "untracked".

## Evidence still to produce

11. **Manual baseline** (BO1): a person times the same prep by hand, protocol in `docs/manual_baseline.md`; then
    `biflow bench` prints the manual / automated ratio.
12. **Full-dataset benchmark** with every module real (the sample benchmark is in `docs/results/`).

## Engineering

13. **CI:** run the smoke test against `docker compose` (the real images) instead of one shared interpreter;
    add the dashboard and new BO5/BO6 tests to the matrix.
14. **BO3:** the timeout wrapper only answers after the work finishes; `/health` calls the LLM provider on every
    request; `_load_tables` picks between same-named inputs by dict order.
