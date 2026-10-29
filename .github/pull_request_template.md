## What / why
<!-- one or two sentences -->

## BO and module
- [ ] BO1  [ ] BO2  [ ] BO3  [ ] BO4  [ ] BO5  [ ] BO6

## Checklist
- [ ] Contract tests green (`make test SERVICE=...`)
- [ ] mock/*.json still matches the real output shape
- [ ] Every transformation returns `lineage_events`
- [ ] No LLM step without a no-LLM fallback; numbers computed by code, not by the LLM
- [ ] Prompt added/changed under `prompts/` with before/after metric (if any)
- [ ] Contract change? Issue opened, `CONTRACT_VERSION` bumped, all owners approved
