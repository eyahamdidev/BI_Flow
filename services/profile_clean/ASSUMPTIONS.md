# profile_clean assumptions (BO3)

- **Contracts:** `biflow-contracts` is installed from `../../contracts` (no shim used in CI).
- **Data:** Raw Olist CSVs are not bundled; tests use synthetic `tests/fixtures/olist_mini/` (~120 rows/table).
- **LLM:** CI and default dev use `FAKE_LLM=1`; live Ollama/API benchmarks are documented in README (`make eval-live`).
- **Lang:** Human-readable diff MD is English; `lang=fr` not fully localized (TODO).
- **HTML profile:** `ydata-profiling` is optional; runs continue if import fails.
- **Second dataset:** `configs/datasets/tiny_shop.yaml` demonstrates YAML-only configuration.
- **Upload playground:** Draft YAML is generated in the playground (`draft_yaml.py`), not in `app/`. Generated configs live under `configs/datasets/uploaded_*.yaml` (gitignored). Original uploads go to `data/uploads/<dataset>/` (gitignored).
- **Upload LLM:** Default `llm_advisory.enabled: false` in generated YAML; API provider requires UI consent checkbox.
- **Parse:** Playground reads CSV as strings first, infers types locally, writes parquet to `runs/<run_id>/00_ingest/`. XLSX multi-sheet ingest is optional (openpyxl) and not required for MVP.
- **REPO_ROOT in playground:** `parents[2]` from `playground.py` → repo root (`BI_Flow`).
- **Column roles:** Shared inference in `app/column_roles.py`; YAML `expected_schema` may include `{dtype, role, why}` per column; service re-infers if role absent.
- **Type guard:** Unsafe imputation/outlier actions are skipped and logged to review queue + lineage `type_guard_block`.
- **Cross-dataset tests:** Synthetic Titanic/Iris/etc. under `tests/fixtures/datasets/` (offline); real Kaggle files not required in CI.
- **Recognition:** Deterministic `app/recognizer.py`; auto-apply threshold default 0.9; LLM never required. User decisions in `data/decisions/<slug>.yaml` (gitignored).
- **Universal eval:** Torture corpus under `eval/universal/corpus/` (generated, not committed); metrics in `eval/universal/results/report.md`.
- **Scale:** Tables >500k rows may use sampling warnings; 1M-row budget tested via `ds_scale_100k` in corpus (full 1M optional locally).
- **PDF report:** Built client-side in `report_pdf.py` (no `app/` imports). Deps in `requirements-dev.txt` only (`reportlab`, `matplotlib`, `pypdf`, `pypdfium2`). Font: bundled `report_assets/fonts/DejaVuSans.ttf` (copied from matplotlib mpl-data on setup). RTL scripts (Arabic) are not shaped. Numbers come from artifacts; optional LLM summary defaults off with regex fact-check against a fact sheet. `run_snapshot.json` is written by the playground after clean/profile-after HTTP responses for lineage/LLM/metrics. Deterministic PDF bytes when `build(..., now=fixed)` except reportlab internal IDs may differ — tests compare extracted text. Quality log truncated to 50 rows in body, 500 in appendix.
