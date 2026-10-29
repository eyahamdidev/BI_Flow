"""Regenerate contracts/schemas/*.json from the pydantic models. CI fails if the committed files drift."""
import json
from pathlib import Path

from biflow_contracts import models as m

out = Path(__file__).resolve().parent.parent / "contracts" / "schemas"
out.mkdir(exist_ok=True)
for cls in (m.RunRequest, m.RunResponse, m.LineageEvent, m.Artifact, m.Insight, m.MetaResponse, m.EvalResponse):
    (out / f"{cls.__name__}.json").write_text(json.dumps(cls.model_json_schema(), indent=2, sort_keys=True) + "\n")
(out / "CONTRACT_VERSION").write_text(m.CONTRACT_VERSION + "\n")
print("schemas written for contract version", m.CONTRACT_VERSION)
