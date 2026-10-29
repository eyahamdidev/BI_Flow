# Dashboard (Streamlit)

Owner **BO6**. Port `8501`. A client of the **gateway** (never of a module), read-only on `data/runs/<run_id>/`.

```
app/main.py          page + sidebar run picker + six tabs
app/data/loader.py   DATA LAYER: run artifacts, falls back to fixtures (demo mode)
app/api/gateway.py   API LAYER: /api/explain, /api/runs
app/tabs/*.py        one file per tab: overview, kpi_explorer, insights, data_quality, lineage, explain
app/components/      reusable tiles and charts (every chart shows a data-source label)
app/fixtures/        demo data so the UI works before the pipeline does
```

```bash
make run SERVICE=dashboard          # http://localhost:8501 (works on fixtures with no backend)
make test SERVICE=dashboard
```

## TODO (BO6)
- [ ] Drive tiles/charts from `dashboard_config.json` instead of looping over KPI definitions
- [ ] Filters: date range (done in explorer), category, state across tabs
- [ ] Lineage tab: use BO2's real graph JSON, click a KPI -> upstream path
- [ ] Insights tab: show rule_id + facts (done), link to KPI explorer
- [ ] Load time under 5 s from precomputed outputs
