"""Pydantic shape of lineage_graph.json. Streamlit reads id, label, layer, from, to, and step."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeKind = Literal["dataset", "model", "kpi", "insight"]


class LineageNode(BaseModel):
    id: str
    label: str
    layer: int = Field(ge=0, le=4)
    kind: NodeKind = "dataset"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LineageEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    src: str = Field(alias="from")
    to: str
    step: str
    rule: str | None = None
    method: str | None = None
    agent: str | None = None
    rows_in: int | None = None
    rows_out: int | None = None
    sql: str | None = None
    step_name: str | None = None


class PyVisNode(BaseModel):
    id: str
    label: str
    title: str
    level: int
    group: str


class PyVisEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    src: str = Field(alias="from")
    to: str
    title: str


class PyVisGraph(BaseModel):
    nodes: list[PyVisNode]
    edges: list[PyVisEdge]


class LineageGraph(BaseModel):
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    pyvis: PyVisGraph

    @model_validator(mode="after")
    def endpoints_exist(self) -> LineageGraph:
        ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.src not in ids or edge.to not in ids:
                raise ValueError(f"edge {edge.src} -> {edge.to} is missing an endpoint")
        return self

    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)
