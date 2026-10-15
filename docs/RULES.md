# The rules (short version, full text in BIFlow_Technical_Spec.md section 1)

1. One folder / venv / `requirements.in` per module. No shared virtualenv.
2. **Modules never call each other.** Only the gateway calls modules.
3. Contracts (`contracts/`) are frozen. A change needs an issue, a PR approved by all owners, and a `CONTRACT_VERSION` bump.
4. **Mock first.** `mock/<mode>.json` must exist for every mode and match the real output shape.
5. Data travels **by reference**: paths relative to `DATA_DIR`, never DataFrames in JSON.
6. LLM only through `biflow_contracts.biflow_llm` (plain httpx, Ollama or API key: same code).
7. **Code computes, the LLM explains.** Numbers/joins/KPIs/anomalies come from code. The LLM writes text or picks from a closed menu (validated JSON).
8. Every LLM step has a no-LLM fallback; a module degrades (`status: partial`), it never crashes.
9. Every transformation returns a `lineage_event`. Only the gateway writes `events.jsonl`.
10. Models are chosen in `config/models.yaml`, not in code.
11. CI never calls an LLM (`FAKE_LLM=1`). Temperature 0 + fixed seeds for benchmarks.
