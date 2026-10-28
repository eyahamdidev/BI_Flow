"""Build a lineage graph from events.jsonl.

Datasets, warehouse models, KPIs, and insights are nodes. Transformations are edges.
`upstream(kpi_id)` walks that graph from the raw tables to the KPI.
"""

from __future__ import annotations

import re
from typing import Any

import networkx as nx

from .constants import AUDITOR_STEPS
from .models_graph import LineageEdge, LineageGraph, LineageNode, PyVisEdge, PyVisGraph, PyVisNode

_GENERIC_STEMS = {
    "quality_log",
    "profile",
    "manifest",
    "validation_report",
    "quality_score",
    "review_queue",
    "kpi_values",
    "kpi_definitions",
    "insights",
    "drivers",
    "dashboard_config",
    "profile_html",
    "lineage_graph",
    "trace_report",
    "explain_answer",
    "biflow",
}

# Product node used when an event has no input/output artifacts (the current mocks).
# (id, label, layer, kind, edge source or None)
_CANON = {
    "ingest_csv": ("raw.tables", "raw tables", 0, "dataset", None),
    "validate_schema": ("raw.tables", "raw tables", 0, "dataset", None),
    "score": ("quality.score", "quality score", 0, "dataset", "raw.tables"),
    "profile_tables": ("profile.tables", "profile", 1, "dataset", "raw.tables"),
    "translate_category_names": ("clean.products", "clean products", 1, "dataset", "raw.tables"),
    "impute_product_weight": ("clean.products", "clean products", 1, "dataset", "raw.tables"),
    "dbt_staging": ("dbt.staging", "staging models", 2, "model", "clean.products"),
    "dbt_marts": ("dbt.fact_orders", "fact_orders", 2, "model", "dbt.staging"),
    "compute_kpi": ("kpi.catalog", "KPI catalog", 3, "kpi", "dbt.fact_orders"),
    "detect_anomalies": ("ins.anomalies", "insights", 4, "insight", "kpi.catalog"),
}

_LAYER_KIND = {0: "dataset", 1: "dataset", 2: "model", 3: "kpi", 4: "insight"}
_PREFIX_LAYER = {"raw": 0, "clean": 1, "profile": 1, "quality": 0, "dbt": 2, "kpi": 3, "ins": 4}


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (name or "").strip()).strip("_")
    return slug or "artifact"


def _layer_of(path: str, agent: str, name: str) -> int:
    """Path wins over the producing agent, so a clean step can still read a raw table."""
    blob = f"{path} {name}".lower().replace("\\", "/")
    if name.lower().startswith("ins.") or "05_insights" in blob:
        return 4
    if name.lower().startswith("kpi.") or "04_kpi" in blob:
        return 3
    if "03_etl" in blob or blob.endswith(".duckdb") or "/dbt/" in blob:
        return 2
    if "02_clean" in blob or "01_profile" in blob:
        return 1
    if "00_ingest" in blob or "/raw/" in blob:
        return 0
    if agent == "analyst":
        return 4
    if agent == "semantic_kpi":
        return 3
    if agent == "etl":
        return 2
    if agent == "profile_clean":
        return 1
    return 0


def _label_for(layer: int, stem: str) -> str:
    if layer == 0:
        return f"raw {stem}"
    if layer == 1:
        return f"clean {stem}"
    if layer == 3:
        return f"KPI {stem}"
    if layer == 4:
        return f"insight {stem}"
    return stem


def _node_from_name(name: str) -> tuple[str, str, int, str]:
    if "." in name:
        prefix, stem = name.split(".", 1)
        layer = _PREFIX_LAYER.get(prefix, 2)
        kind = _LAYER_KIND[layer]
        label = stem if layer == 2 else _label_for(layer, stem)
        if prefix == "profile":
            label = "profile"
        if prefix == "quality":
            label = "quality score"
        return name, label, layer, kind
    if name.startswith(("fact_", "dim_", "stg_")):
        return f"dbt.{name}", name, 2, "model"
    return f"raw.{_slug(name)}", f"raw {name}", 0, "dataset"


def _artifact_node(ref: dict[str, Any], agent: str) -> tuple[str, str, int, str]:
    if ref.get("node_id"):
        node_id, label, layer, kind = _node_from_name(str(ref["node_id"]))
        return node_id, str(ref.get("label") or label), layer, kind
    kpi_id = ref.get("kpi_id")
    if kpi_id or str(ref.get("kind") or "") == "kpi" or str(ref.get("name") or "").startswith("kpi."):
        kid = str(kpi_id or str(ref.get("name")).removeprefix("kpi."))
        return f"kpi.{kid}", f"KPI {kid}", 3, "kpi"
    insight_id = ref.get("insight_id")
    if insight_id or str(ref.get("kind") or "") == "insight" or str(ref.get("name") or "").startswith("ins."):
        iid = str(insight_id or str(ref.get("name")).removeprefix("ins."))
        return f"ins.{iid}", f"insight {iid}", 4, "insight"
    path = str(ref.get("path") or "")
    name = str(ref.get("name") or "")
    stem = ""
    if path:
        stem = path.replace("\\", "/").rstrip("/").split("/")[-1]
        if "." in stem:
            stem = stem.rsplit(".", 1)[0]
    if stem.lower() in _GENERIC_STEMS:
        stem = ""
    stem = _slug(stem or name or "artifact")
    layer = _layer_of(path, agent, name)
    prefix = {0: "raw", 1: "clean", 2: "dbt", 3: "kpi", 4: "ins"}[layer]
    node_id = stem if "." in stem else f"{prefix}.{stem}"
    return node_id, _label_for(layer, stem.split(".", 1)[-1]), layer, _LAYER_KIND[layer]


def _rows(refs: list[dict[str, Any]]) -> int | None:
    values: list[int] = []
    for ref in refs:
        rows = ref.get("rows")
        if isinstance(rows, bool) or rows is None:
            return None
        if isinstance(rows, (int, float)):
            values.append(int(rows))
        else:
            return None
    if not values:
        return None
    return sum(values)


def _sql_of(event: dict[str, Any]) -> str | None:
    params = event.get("params") or {}
    sql = params.get("sql")
    if isinstance(sql, str) and sql.strip():
        return sql.strip()
    rule = event.get("rule")
    if isinstance(rule, str) and rule.strip().lower().startswith("select"):
        return rule.strip()
    return None


def _method(event: dict[str, Any]) -> str:
    method = event.get("method") or "deterministic"
    if method not in ("deterministic", "ml", "llm_assisted"):
        return "deterministic"
    return method


def _skip(event: dict[str, Any]) -> bool:
    return event.get("agent") == "auditor" or event.get("step") in AUDITOR_STEPS


class _Graph:
    def __init__(self) -> None:
        self.g: nx.MultiDiGraph = nx.MultiDiGraph()

    def add_node(self, node_id: str, label: str, layer: int, kind: str, metadata: dict[str, Any] | None = None) -> None:
        meta = {k: v for k, v in (metadata or {}).items() if v is not None}
        if self.g.has_node(node_id):
            current = self.g.nodes[node_id]
            merged = dict(current.get("metadata") or {})
            for key, value in meta.items():
                if key == "steps":
                    steps = list(merged.get("steps") or [])
                    for step in value:
                        if step not in steps:
                            steps.append(step)
                    merged["steps"] = steps
                else:
                    merged[key] = value
            current["metadata"] = merged
            return
        self.g.add_node(node_id, label=label, layer=int(layer), kind=kind, metadata=meta)

    def touch(self, node_id: str, step: str | None, rule: str | None = None) -> None:
        if not self.g.has_node(node_id):
            return
        meta = self.g.nodes[node_id]["metadata"]
        if step:
            steps = list(meta.get("steps") or [])
            if step not in steps:
                steps.append(step)
                meta["steps"] = steps
        if rule:
            rules = list(meta.get("rules") or [])
            if rule not in rules:
                rules.append(rule)
                meta["rules"] = rules

    def add_edge(self, src: str, dst: str, **attr: Any) -> None:
        if not src or not dst or src == dst:
            return
        if not self.g.has_node(src) or not self.g.has_node(dst):
            return
        key = (attr.get("step_name"), attr.get("rule"))
        if self.g.has_edge(src, dst, key=key):
            return
        self.g.add_edge(src, dst, key=key, **attr)


def _edge_attr(event: dict[str, Any], rows_in: int | None, rows_out: int | None) -> dict[str, Any]:
    step = str(event.get("step") or "transform")
    rule = event.get("rule")
    attr: dict[str, Any] = {
        "step": step,
        "step_name": step,
        "method": _method(event),
        "agent": event.get("agent"),
        "rows_in": rows_in,
        "rows_out": rows_out,
    }
    if isinstance(rule, str) and rule:
        attr["rule"] = rule
    sql = _sql_of(event)
    if sql:
        attr["sql"] = sql
    return {k: v for k, v in attr.items() if v is not None}


def _named_refs(values: Any) -> list[str]:
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        return [str(item) for item in values if item]
    return []


def build_lineage_graph(
    events: list[dict[str, Any]],
    definitions: list[dict[str, Any]] | None = None,
    insights: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the Streamlit/pyvis payload. Invalid graphs degrade to an empty payload."""
    graph = _Graph()
    definitions = [item for item in (definitions or []) if isinstance(item, dict) and item.get("id")]
    insights = [item for item in (insights or []) if isinstance(item, dict) and item.get("id")]
    saw_compute = False
    saw_anomalies = False

    for event in events:
        if not isinstance(event, dict) or _skip(event):
            continue
        step = str(event.get("step") or "")
        agent = str(event.get("agent") or "")
        params = event.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        inputs = [ref for ref in (event.get("inputs") or []) if isinstance(ref, dict)]
        outputs = [ref for ref in (event.get("outputs") or []) if isinstance(ref, dict)]
        if step == "compute_kpi":
            saw_compute = True
        if step == "detect_anomalies":
            saw_anomalies = True

        if inputs or outputs:
            in_nodes = [_artifact_node(ref, agent) for ref in inputs]
            out_nodes = [_artifact_node(ref, agent) for ref in outputs]
            if params.get("kpi_id") and (not outputs or all(_is_kpi_blob(ref) for ref in outputs)):
                kid = str(params["kpi_id"])
                out_nodes = [(f"kpi.{kid}", f"KPI {kid}", 3, "kpi")]
            for node_id, label, layer, kind in in_nodes + out_nodes:
                graph.add_node(node_id, label, layer, kind)
            rows_in = _rows(inputs)
            rows_out = _rows(outputs)
            attr = _edge_attr(event, rows_in, rows_out)
            sources = [node[0] for node in in_nodes]
            for name in _named_refs(params.get("sources") or params.get("source_tables")):
                node_id, label, layer, kind = _node_from_name(name)
                graph.add_node(node_id, label, layer, kind)
                if node_id not in sources:
                    sources.append(node_id)
            targets = [node[0] for node in out_nodes]
            if not targets and params.get("kpi_id"):
                kid = str(params["kpi_id"])
                graph.add_node(f"kpi.{kid}", f"KPI {kid}", 3, "kpi", {"sql": _sql_of(event), "kpi_id": kid})
                targets = [f"kpi.{kid}"]
            for src in sources:
                for dst in targets:
                    graph.add_edge(src, dst, **attr)
            for node_id, *_rest in [*in_nodes, *out_nodes]:
                graph.touch(node_id, step, event.get("rule") if isinstance(event.get("rule"), str) else None)
            if params.get("kpi_id") and targets == [f"kpi.{params['kpi_id']}"]:
                graph.add_node(
                    f"kpi.{params['kpi_id']}",
                    f"KPI {params['kpi_id']}",
                    3,
                    "kpi",
                    {"sql": _sql_of(event), "kpi_id": str(params["kpi_id"])},
                )
            continue

        sources = _named_refs(params.get("sources") or params.get("source_tables"))
        if params.get("kpi_id") or sources:
            saw_compute = saw_compute or bool(params.get("kpi_id"))
            target_id = f"kpi.{params['kpi_id']}" if params.get("kpi_id") else None
            if target_id:
                graph.add_node(target_id, f"KPI {params['kpi_id']}", 3, "kpi", {"sql": _sql_of(event), "kpi_id": str(params["kpi_id"])})
            attr = _edge_attr(event, None, None)
            for name in sources:
                node_id, label, layer, kind = _node_from_name(name)
                graph.add_node(node_id, label, layer, kind)
                if target_id:
                    graph.add_edge(node_id, target_id, **attr)
            if target_id:
                graph.touch(target_id, step, event.get("rule") if isinstance(event.get("rule"), str) else None)
            continue

        if step == "compute_kpi" and definitions:
            continue
        if step == "detect_anomalies" and insights:
            continue
        spec = _CANON.get(step)
        if spec is None:
            node_id = f"step.{_slug(step or 'event')}"
            graph.add_node(node_id, step or "event", _layer_of("", agent, step), _LAYER_KIND[_layer_of("", agent, step)])
            graph.touch(node_id, step, event.get("rule") if isinstance(event.get("rule"), str) else None)
            continue
        node_id, label, layer, kind, source = spec
        graph.add_node(node_id, label, layer, kind)
        graph.touch(node_id, step, event.get("rule") if isinstance(event.get("rule"), str) else None)
        if source and graph.g.has_node(source):
            graph.add_edge(source, node_id, **_edge_attr(event, None, None))

    if saw_compute and definitions:
        anchor = _existing(graph, "dbt.fact_orders", 2)
        for item in definitions:
            kid = str(item["id"])
            graph.add_node(
                f"kpi.{kid}",
                f"KPI {kid}",
                3,
                "kpi",
                {
                    "kpi_id": kid,
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "sql": item.get("sql"),
                    "unit": item.get("unit"),
                },
            )
            if anchor:
                graph.add_edge(
                    anchor,
                    f"kpi.{kid}",
                    step="compute_kpi",
                    step_name="compute_kpi",
                    method="deterministic",
                    agent="semantic_kpi",
                    sql=item.get("sql"),
                    rule=item.get("sql") if isinstance(item.get("sql"), str) else None,
                )
            graph.touch(f"kpi.{kid}", "compute_kpi")

    if saw_anomalies and insights:
        for item in insights:
            iid = str(item["id"])
            kpi_id = str(item.get("kpi_id") or "")
            graph.add_node(f"ins.{iid}", f"insight {iid}", 4, "insight", {"insight_id": iid, "kpi_id": kpi_id, "type": item.get("type")})
            source = f"kpi.{kpi_id}" if kpi_id and graph.g.has_node(f"kpi.{kpi_id}") else _existing(graph, "kpi.catalog", 3)
            if source:
                graph.add_edge(
                    source,
                    f"ins.{iid}",
                    step=str(item.get("type") or "detect_anomalies"),
                    step_name="detect_anomalies",
                    method="ml",
                    agent="analyst",
                    rule=item.get("rule_id"),
                )

    return _dump(graph)


def _is_kpi_blob(ref: dict[str, Any]) -> bool:
    name = str(ref.get("name") or "").lower()
    path = str(ref.get("path") or "").lower()
    return name in {"kpi_values", "kpi_definitions", "kpis"} or "04_kpi" in path


def _existing(graph: _Graph, preferred: str, layer: int) -> str | None:
    """A logged node to attach to. Never invents a dataset that no event produced."""
    if graph.g.has_node(preferred):
        return preferred
    found = [node for node, data in graph.g.nodes(data=True) if data.get("layer") == layer]
    return sorted(found)[0] if found else None


def _dump(graph: _Graph) -> dict[str, Any]:
    nodes: list[LineageNode] = []
    for node_id, data in graph.g.nodes(data=True):
        nodes.append(
            LineageNode(
                id=node_id,
                label=str(data.get("label") or node_id),
                layer=int(data.get("layer") or 0),
                kind=data.get("kind") or "dataset",
                metadata=dict(data.get("metadata") or {}),
            )
        )
    nodes.sort(key=lambda node: (node.layer, node.id))
    edges: list[LineageEdge] = []
    for src, dst, data in graph.g.edges(data=True):
        edges.append(LineageEdge.model_validate({"from": src, "to": dst, **data}))
    edges.sort(key=lambda edge: (edge.src, edge.to, edge.step, edge.rule or ""))
    pyvis_nodes = [
        PyVisNode(id=node.id, label=node.label, title=_hover(node), level=node.layer, group=node.kind) for node in nodes
    ]
    pyvis_edges = [
        PyVisEdge.model_validate(
            {
                "from": edge.src,
                "to": edge.to,
                "title": " | ".join(part for part in (edge.step, edge.rule) if part),
            }
        )
        for edge in edges
    ]
    try:
        return LineageGraph(nodes=nodes, edges=edges, pyvis=PyVisGraph(nodes=pyvis_nodes, edges=pyvis_edges)).dump()
    except ValueError:
        return LineageGraph(nodes=[], edges=[], pyvis=PyVisGraph(nodes=[], edges=[])).dump()


def _hover(node: LineageNode) -> str:
    meta = node.metadata
    bits = [node.label, node.kind, f"layer {node.layer}"]
    if meta.get("rows") is not None:
        bits.append(f"rows {meta['rows']}")
    steps = meta.get("steps") or []
    if steps:
        bits.append("steps " + ", ".join(str(step) for step in steps))
    return " | ".join(bits)


def upstream(graph: dict[str, Any], kpi_id: str) -> dict[str, Any]:
    """Full logged path from raw tables through cleaning rules and dbt models to the KPI SQL."""
    wanted = kpi_id if str(kpi_id).startswith("kpi.") else f"kpi.{kpi_id}"
    bare = wanted.removeprefix("kpi.")
    nodes = {node["id"]: node for node in graph.get("nodes") or []}
    target = wanted if wanted in nodes else next((node_id for node_id, node in nodes.items() if (node.get("metadata") or {}).get("kpi_id") == bare), None)
    empty = {
        "kpi_id": bare,
        "found": False,
        "paths": [],
        "raw_tables": [],
        "cleaning_rules": [],
        "dbt_models": [],
        "kpi_sql": None,
    }
    if target is None:
        return empty

    built = nx.MultiDiGraph()
    for node_id in nodes:
        built.add_node(node_id)
    for edge in graph.get("edges") or []:
        built.add_edge(edge["from"], edge["to"], **{k: v for k, v in edge.items() if k not in {"from", "to"}})

    node_paths: list[list[str]] = []
    sources = [node_id for node_id in built.nodes if built.in_degree(node_id) == 0 and node_id != target]
    for source in sorted(sources):
        if not nx.has_path(built, source, target):
            continue
        for path in nx.all_simple_paths(built, source, target, cutoff=12):
            node_paths.append(list(path))
            if len(node_paths) >= 30:
                break
        if len(node_paths) >= 30:
            break
    if not node_paths:
        node_paths = [[target]]

    paths = []
    raw: list[str] = []
    cleaning: list[str] = []
    models: list[str] = []
    sqls: list[str] = []
    for path in node_paths:
        steps = []
        for left, right in zip(path, path[1:], strict=False):
            bundle = built.get_edge_data(left, right) or {}
            for data in bundle.values():
                step = {key: data[key] for key in ("from", "to", "step", "rule", "method", "agent", "sql", "step_name") if key in data and data[key] is not None}
                step["from"] = left
                step["to"] = right
                steps.append(step)
                dest = nodes.get(right) or {}
                step_name = str(data.get("step_name") or data.get("step") or "")
                if step_name != "profile_tables" and dest.get("layer") == 1 and dest.get("kind") == "dataset":
                    cleaning.append(str(data.get("rule") or data.get("step")))
                if data.get("sql"):
                    sqls.append(str(data["sql"]))
        for node_id in path:
            node = nodes.get(node_id) or {}
            if node.get("layer") == 0 and node.get("kind") == "dataset":
                raw.append(node_id)
            if node.get("layer") == 2:
                models.append(node_id)
        paths.append({"nodes": path, "steps": steps})

    meta_sql = (nodes[target].get("metadata") or {}).get("sql")
    if meta_sql:
        sqls.append(str(meta_sql))
    return {
        "kpi_id": bare,
        "found": True,
        "paths": paths,
        "raw_tables": _unique(raw),
        "cleaning_rules": _unique(cleaning),
        "dbt_models": _unique(models),
        "kpi_sql": sqls[0] if sqls else None,
    }


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
