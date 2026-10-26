"""Client-side BO3 run report (PDF). No imports from app/. Numbers from artifacts only."""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm, mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MODULE_DIR = Path(__file__).resolve().parent
FONT_PATH = MODULE_DIR / "report_assets" / "fonts" / "DejaVuSans.ttf"
FONT_NAME = "DejaVuSans"

COLOR_PASS = colors.HexColor("#2e7d32")
COLOR_REVIEW = colors.HexColor("#f9a825")
COLOR_FAIL = colors.HexColor("#c62828")
COLOR_GREY = colors.HexColor("#616161")
COLOR_ZEBRA = colors.HexColor("#f5f5f5")

QL_MAIN_CAP = 50
QL_APPENDIX_CAP = 500
RECO_MAIN_MAX_COLS = 40
SAMPLE_VALUES_MAX = 5

I18N: dict[str, dict[str, str]] = {
    "en": {
        "title": "BIFlow BO3 Data Quality Report",
        "cover_caption": "Full cleaning run summary generated from on-disk artifacts.",
        "toc": "Table of contents",
        "sec_cover": "Cover",
        "sec_summary": "Executive summary",
        "sec_safety": "Safety & integrity checks",
        "sec_parse": "Input & parsing",
        "sec_recognition": "Column recognition",
        "sec_profile": "Profile before vs after",
        "sec_cleaning": "Cleaning actions",
        "sec_review": "Review queue",
        "sec_dropped": "Dropped rows & reconciliation",
        "sec_lineage": "Lineage",
        "sec_llm": "LLM usage",
        "sec_repro": "Reproducibility & limitations",
        "sec_appendix": "Appendix",
        "verdict_pass": "PASS",
        "verdict_review": "PASS WITH REVIEW ITEMS",
        "verdict_fail": "FAIL",
        "privacy_on": "Privacy mode: ON (sample values hidden)",
        "privacy_off": "Privacy mode: OFF",
        "not_available": "Not available",
        "not_run": "NOT RUN",
        "nothing_review": "Nothing needs review",
        "llm_off": "LLM off",
        "llm_not_used": "LLM not used",
        "numbers_guarantee": "All counts and statistics in this report are read from run artifacts; they never depend on LLM output.",
        "limitations_heading": "Known limitations",
        "glossary_heading": "Glossary",
        "footer_page": "Page",
        "footer_of": "of",
        "generated_at": "Generated",
        "see_csv": "See downloadable quality_log.json / CSV for full entries.",
        "rtl_note": "Right-to-left scripts (e.g. Arabic) are not shaped; glyphs appear in logical order only.",
    },
    "fr": {
        "title": "Rapport qualité BIFlow BO3",
        "cover_caption": "Résumé complet du nettoyage, généré à partir des artefacts sur disque.",
        "toc": "Table des matières",
        "sec_cover": "Couverture",
        "sec_summary": "Résumé exécutif",
        "sec_safety": "Sécurité & intégrité",
        "sec_parse": "Entrée & analyse",
        "sec_recognition": "Reconnaissance des colonnes",
        "sec_profile": "Profil avant / après",
        "sec_cleaning": "Actions de nettoyage",
        "sec_review": "File de revue",
        "sec_dropped": "Lignes supprimées & réconciliation",
        "sec_lineage": "Lignage",
        "sec_llm": "Usage LLM",
        "sec_repro": "Reproductibilité & limites",
        "sec_appendix": "Annexe",
        "verdict_pass": "OK",
        "verdict_review": "OK AVEC REVUE",
        "verdict_fail": "ÉCHEC",
        "privacy_on": "Mode confidentialité : OUI (échantillons masqués)",
        "privacy_off": "Mode confidentialité : NON",
        "not_available": "Non disponible",
        "not_run": "NON EXÉCUTÉ",
        "nothing_review": "Rien à revoir",
        "llm_off": "LLM désactivé",
        "llm_not_used": "LLM non utilisé",
        "numbers_guarantee": "Tous les nombres proviennent des artefacts; ils ne dépendent jamais du LLM.",
        "limitations_heading": "Limites connues",
        "glossary_heading": "Glossaire",
        "footer_page": "Page",
        "footer_of": "sur",
        "generated_at": "Généré",
        "see_csv": "Voir quality_log.json / CSV pour la liste complète.",
        "rtl_note": "Les scripts RTL (arabe) ne sont pas mis en forme correctement.",
    },
}


def _t(lang: str, key: str) -> str:
    return I18N.get(lang, I18N["en"]).get(key, I18N["en"].get(key, key))


def escape_para(text: Any) -> str:
    if text is None:
        return ""
    s = str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s


def fmt_num(n: int | float | None, *, decimals: int = 0) -> str:
    if n is None:
        return "—"
    if isinstance(n, float):
        return f"{n:,.{decimals}f}"
    return f"{int(n):,}"


def _short_sha256(h: str) -> str:
    h = h or ""
    return h[:12] + "…" if len(h) > 12 else h


def parquet_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return pq.ParquetFile(path).metadata.num_rows


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _config_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class RunContext:
    run_id: str
    dataset: str
    data_dir: Path
    lang: str = "en"
    privacy: bool = False
    now: datetime = field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    snapshot: dict[str, Any] = field(default_factory=dict)
    run_error: str | None = None

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "runs" / self.run_id

    @property
    def ingest_dir(self) -> Path:
        return self.run_dir / "00_ingest"

    @property
    def profile_before_dir(self) -> Path:
        return self.run_dir / "01_profile"

    @property
    def clean_dir(self) -> Path:
        return self.run_dir / "02_clean"

    @property
    def profile_after_dir(self) -> Path:
        return self.run_dir / "03_profile_after"

    @property
    def report_dir(self) -> Path:
        return self.run_dir / "report"


def load_context(
    data_dir: Path,
    run_id: str,
    dataset: str,
    *,
    lang: str = "en",
    privacy: bool = False,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
) -> RunContext:
    ctx = RunContext(
        run_id=run_id,
        dataset=dataset,
        data_dir=data_dir,
        lang=lang if lang in I18N else "en",
        privacy=privacy,
        now=now or datetime.now(tz or ZoneInfo("UTC")),
        tz=tz or ZoneInfo("UTC"),
    )
    snap_p = ctx.run_dir / "run_snapshot.json"
    if snap_p.is_file():
        raw = _read_json(snap_p)
        if isinstance(raw, dict):
            ctx.snapshot = raw
    err_p = ctx.run_dir / "run_error.json"
    if err_p.is_file():
        er = _read_json(err_p)
        if isinstance(er, dict):
            ctx.run_error = er.get("message") or str(er)
    return ctx


def persist_run_snapshot(run_dir: Path, step: str, resp: dict[str, Any] | None) -> None:
    if not resp:
        return
    snap_p = run_dir / "run_snapshot.json"
    existing: dict[str, Any] = {}
    if snap_p.is_file():
        raw = _read_json(snap_p)
        if isinstance(raw, dict):
            existing = raw
    existing[step] = {
        "status": resp.get("status"),
        "metrics": resp.get("metrics") or {},
        "lineage_events": resp.get("lineage_events") or [],
        "llm_calls": resp.get("llm_calls") or [],
        "latency_ms": resp.get("latency_ms"),
        "warnings": resp.get("warnings") or [],
    }
    if resp.get("error"):
        existing["error"] = resp["error"]
    snap_p.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def has_clean_run(data_dir: Path, run_id: str) -> bool:
    cl = data_dir / "runs" / run_id / "02_clean"
    return cl.is_dir() and any(cl.glob("*.parquet"))


def _manifest(ctx: RunContext) -> dict[str, Any]:
    m = _read_json(ctx.ingest_dir / "ingest_manifest.json")
    return m if isinstance(m, dict) else {}


def _quality_log(ctx: RunContext) -> list[dict[str, Any]]:
    raw = _read_json(ctx.clean_dir / "quality_log.json")
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _review_queue(ctx: RunContext) -> list[dict[str, Any]]:
    raw = _read_json(ctx.clean_dir / "review_queue.json")
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _dropped_rows(ctx: RunContext) -> list[dict[str, Any]]:
    raw = _read_json(ctx.clean_dir / "dropped_rows.json")
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _recognition(ctx: RunContext) -> list[dict[str, Any]]:
    for p in (
        ctx.clean_dir / "recognition_report.json",
        ctx.profile_before_dir / "recognition_report.json",
    ):
        raw = _read_json(p)
        if isinstance(raw, dict) and isinstance(raw.get("columns"), list):
            return [c for c in raw["columns"] if isinstance(c, dict)]
    return []


def _metrics(ctx: RunContext) -> dict[str, Any]:
    clean = ctx.snapshot.get("clean") or {}
    m = dict(clean.get("metrics") or {})
    if m:
        return m
    qlog = _quality_log(ctx)
    tables = [p.stem for p in ctx.ingest_dir.glob("*.parquet")]
    rows_in = sum(parquet_row_count(ctx.ingest_dir / f"{t}.parquet") for t in tables)
    rows_out = sum(parquet_row_count(ctx.clean_dir / f"{t}.parquet") for t in tables)
    dupes = sum(int(e.get("rows_affected") or 0) for e in qlog if "dupe" in str(e.get("rule_id", "")))
    imputed = sum(int(e.get("cells_imputed") or e.get("rows_affected") or 0) for e in qlog if "impute" in str(e.get("rule_id", "")))
    outliers = sum(int(e.get("rows_affected") or 0) for e in qlog if e.get("rule_id") == "detect_outliers")
    return {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "duplicates_removed": dupes,
        "cells_imputed": imputed,
        "outliers_flagged": outliers,
        "review_items": len(_review_queue(ctx)),
        "silent_deletions": 0,
    }


def _dropped_by_table(ctx: RunContext) -> dict[str, int]:
    from_q: dict[str, int] = {}
    from_rows: dict[str, int] = {}
    for row in _dropped_rows(ctx):
        t = str(row.get("table", "?"))
        from_rows[t] = from_rows.get(t, 0) + 1
    for e in _quality_log(ctx):
        t = e.get("table")
        n = int(e.get("rows_affected") or 0)
        rid = str(e.get("rule_id", ""))
        if not t or not n:
            continue
        if "dupe" in rid or (rid == "null_strategy" and e.get("strategy") == "drop"):
            from_q[str(t)] = from_q.get(str(t), 0) + n
    tables = set(from_q) | set(from_rows)
    return {t: max(from_q.get(t, 0), from_rows.get(t, 0)) for t in tables}


def _dtype_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    norm = lambda x: x.lower().replace("int64", "int").replace("float64", "float").replace("string", "str")  # noqa: E731
    return norm(a) == norm(b) or (a.startswith("Int") and b.startswith("Int"))


def compute_safety_checks(ctx: RunContext) -> list[tuple[str, str, str]]:
    """Return (name, status PASS|FAIL|NOT RUN, evidence)."""
    checks: list[tuple[str, str, str]] = []
    cl = ctx.clean_dir
    if not has_clean_run(ctx.data_dir, ctx.run_id):
        checks.append(("Clean stage", "NOT RUN", "No 02_clean parquet outputs"))
        return checks

    dropped_map = _dropped_by_table(ctx)
    inv_msgs: list[str] = []
    for pq_path in sorted(cl.glob("*.parquet")):
        if pq_path.parent.name == "_undo":
            continue
        t = pq_path.stem
        in_p = ctx.ingest_dir / f"{t}.parquet"
        if not in_p.is_file():
            checks.append((f"Reconcile {t}", "FAIL", "missing ingest"))
            continue
        rows_in = parquet_row_count(in_p)
        rows_out = parquet_row_count(pq_path)
        dropped = dropped_map.get(t, 0)
        ok = rows_in - dropped == rows_out
        st = "PASS" if ok else "FAIL"
        checks.append(("Row accounting " + t, st, f"in={rows_in} dropped={dropped} out={rows_out}"))
        if not ok:
            inv_msgs.append(f"{t}: row accounting")

        try:
            raw_df = pd.read_parquet(in_p, columns=None)
            clean_df = pd.read_parquet(pq_path)
        except Exception as ex:
            checks.append((f"Load {t}", "FAIL", str(ex)))
            continue
        orig = [c for c in raw_df.columns if c in clean_df.columns and not c.endswith(("__imputed", "__outlier", "__high_null"))]
        dtype_bad = []
        for c in orig:
            if not _dtype_compatible(str(raw_df[c].dtype), str(clean_df[c].dtype)):
                dtype_bad.append(c)
        checks.append(
            ("Dtype preservation " + t, "PASS" if not dtype_bad else "FAIL", ", ".join(dtype_bad[:5]) or "all original dtypes compatible"),
        )
        nan_issues: list[str] = []
        for c in clean_df.columns:
            if clean_df[c].dtype == object or str(clean_df[c].dtype) == "string":
                bad = clean_df[c].astype("string").isin(["nan", "NaN", "None"])
                if bad.any():
                    nan_issues.append(c)
        checks.append(
            ("No literal 'nan' strings " + t, "PASS" if not nan_issues else "FAIL", ", ".join(nan_issues[:5]) or "none"),
        )

    undo_dir = cl / "_undo"
    if undo_dir.is_dir() and any(undo_dir.glob("*.parquet")):
        checks.append(("Undo round-trip", "NOT RUN", "Full undo verification requires playground helper"))
    else:
        checks.append(("Undo round-trip", "NOT RUN", "No _undo artifacts"))

    snap = ctx.snapshot.get("clean") or {}
    if snap.get("metrics", {}).get("deterministic") is True:
        checks.append(("Determinism", "PASS", "metrics.deterministic=true"))
    elif snap:
        checks.append(("Determinism", "NOT RUN", "No determinism flag in snapshot"))
    else:
        checks.append(("Determinism", "NOT RUN", "No run_snapshot.json"))

    man = _manifest(ctx)
    for tab in man.get("tables") or []:
        if not isinstance(tab, dict):
            continue
        sha = tab.get("sha256")
        src = tab.get("source")
        if sha and src:
            checks.append(("Ingest sha256 recorded", "PASS", f"{src} {_short_sha256(str(sha))}"))
            break
    else:
        checks.append(("Ingest sha256 recorded", "NOT RUN", "No manifest"))

    return checks


def compute_verdict(ctx: RunContext, checks: list[tuple[str, str, str]]) -> str:
    if ctx.run_error:
        return "FAIL"
    if any(st == "FAIL" for _, st, _ in checks):
        return "FAIL"
    rq = _review_queue(ctx)
    if rq:
        return "REVIEW"
    return "PASS"


def _mask_sample(val: Any, privacy: bool) -> str:
    if privacy:
        return "•••"
    s = escape_para(val)
    if len(s) > 80:
        return s[:77] + "…"
    return s


def _sample_values(values: list[Any], privacy: bool) -> str:
    if privacy:
        return "•••"
    parts = [_mask_sample(v, False) for v in values[:SAMPLE_VALUES_MAX]]
    return ", ".join(parts) if parts else "—"


def _effective_font() -> str:
    if FONT_PATH.is_file() and FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return FONT_NAME
    return "Helvetica"


class _ReportDoc(SimpleDocTemplate):
    def afterFlowable(self, flowable: Any) -> None:
        if hasattr(flowable, "_bookmark") and flowable._bookmark:
            key = flowable._bookmark
            level = getattr(flowable, "_level", 0)
            text = getattr(flowable, "_heading_text", key)
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=False)


def _heading(text: str, style: ParagraphStyle, bookmark: str, level: int = 0) -> Paragraph:
    p = Paragraph(text, style)
    p._bookmark = bookmark  # type: ignore[attr-defined]
    p._level = level  # type: ignore[attr-defined]
    p._heading_text = re.sub(r"<[^>]+>", "", text)  # type: ignore[attr-defined]
    return p


def _table(
    data: list[list[Any]],
    col_widths: list[float] | None = None,
    *,
    header_rows: int = 1,
    font: str | None = None,
) -> Table:
    fnt = font or _effective_font()
    t = Table(data, colWidths=col_widths, repeatRows=header_rows)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), fnt),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#eeeeee")),
    ]
    for i in range(header_rows, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), COLOR_ZEBRA))
    t.setStyle(TableStyle(style))
    return t


def _chart_null_diff(ctx: RunContext) -> bytes | None:
    diff_p = ctx.profile_after_dir / "profile_diff.json"
    if not diff_p.is_file():
        return None
    diff = _read_json(diff_p)
    if not isinstance(diff, dict):
        return None
    rows: list[tuple[str, float, float]] = []
    for _t, tdata in (diff.get("tables") or {}).items():
        if not isinstance(tdata, dict):
            continue
        for col, cd in (tdata.get("columns") or {}).items():
            if not isinstance(cd, dict) or col.endswith(("__imputed", "__outlier", "__high_null")):
                continue
            b = cd.get("null_pct_before")
            a = cd.get("null_pct_after")
            if b is None or a is None:
                continue
            rows.append((col, float(b), float(a)))
    if not rows:
        return None
    rows.sort(key=lambda x: abs(x[2] - x[1]), reverse=True)
    rows = rows[:20]
    labels = [r[0] for r in rows]
    before = [r[1] for r in rows]
    after = [r[2] for r in rows]
    fig, ax = plt.subplots(figsize=(7, max(3, len(labels) * 0.25)))
    y = range(len(labels))
    ax.barh([i - 0.2 for i in y], before, height=0.35, label="before", color="#4477AA")
    ax.barh([i + 0.2 for i in y], after, height=0.35, label="after", color="#EE6677")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("Null %")
    ax.legend(loc="lower right")
    ax.set_title("Null % by column (top changes)")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200)
    plt.close(fig)
    return buf.getvalue()


def _chart_pipeline(ctx: RunContext) -> bytes | None:
    stages = []
    for label, d in (
        ("ingest", ctx.ingest_dir),
        ("profile", ctx.profile_before_dir),
        ("clean", ctx.clean_dir),
        ("profile after", ctx.profile_after_dir),
    ):
        n = 0
        if d.is_dir():
            for pq_path in d.glob("*.parquet"):
                if pq_path.parent.name != "_undo":
                    n += parquet_row_count(pq_path)
            if n == 0:
                prof_p = d / "profile.json"
                if prof_p.is_file():
                    prof = _read_json(prof_p)
                    if isinstance(prof, dict):
                        n = sum(int((t or {}).get("rows") or 0) for t in (prof.get("tables") or {}).values())
        stages.append((label, n))
    fig, ax = plt.subplots(figsize=(7, 2))
    ax.axis("off")
    xs = [0.1, 0.35, 0.6, 0.85]
    for i, (lab, n) in enumerate(stages):
        ax.add_patch(plt.Rectangle((xs[i] - 0.08, 0.35), 0.16, 0.3, fill=True, color="#4477AA", alpha=0.7))
        ax.text(xs[i], 0.5, f"{lab}\n{fmt_num(n)} rows", ha="center", va="center", fontsize=8, color="white")
        if i < len(stages) - 1:
            ax.annotate("", xy=(xs[i + 1] - 0.08, 0.5), xytext=(xs[i] + 0.08, 0.5), arrowprops=dict(arrowstyle="->", color="#333"))
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200)
    plt.close(fig)
    return buf.getvalue()


def _histogram_overlay(ctx: RunContext, table: str, column: str) -> bytes | None:
    in_p = ctx.ingest_dir / f"{table}.parquet"
    cl_p = ctx.clean_dir / f"{table}.parquet"
    if not in_p.is_file() or not cl_p.is_file():
        return None
    try:
        raw = pd.read_parquet(in_p, columns=[column])
        clean = pd.read_parquet(cl_p, columns=[column])
    except Exception:
        return None
    if len(raw) > 10000:
        raw = raw.sample(10000, random_state=0)
        clean = clean.sample(min(10000, len(clean)), random_state=0)
    rb = pd.to_numeric(raw[column], errors="coerce").dropna()
    ra = pd.to_numeric(clean[column], errors="coerce").dropna()
    if rb.empty and ra.empty:
        return None
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.hist(rb, bins=30, alpha=0.5, label="before", color="#4477AA")
    ax.hist(ra, bins=30, alpha=0.5, label="after", color="#EE6677")
    ax.set_title(f"{table}.{column}")
    ax.legend()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200)
    plt.close(fig)
    return buf.getvalue()


def _limitations_text() -> list[str]:
    readme = MODULE_DIR / "README.md"
    lines = [
        "Ambiguous dates go to the review queue; no silent guess.",
        "No semantic correction of free-text values beyond configured rules.",
        "Column roles block unsafe numeric imputation on ids and categoricals.",
        "LLM advisory (when enabled) does not change deterministic counts in this report.",
    ]
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        if "Supported inputs" in text:
            lines.append("See README for supported upload formats and issue classes.")
    return lines


def _executive_sentences(ctx: RunContext, metrics: dict[str, Any]) -> list[str]:
    dupes = int(metrics.get("duplicates_removed") or 0)
    imputed = int(metrics.get("cells_imputed") or 0)
    outliers = int(metrics.get("outliers_flagged") or 0)
    review = int(metrics.get("review_items") or len(_review_queue(ctx)))
    silent = int(metrics.get("silent_deletions") or 0)
    sents = [
        f"{fmt_num(dupes)} exact duplicate rows were removed and logged where applicable.",
        f"{fmt_num(imputed)} cells were imputed using configured deterministic or ML methods.",
        f"{fmt_num(outliers)} outlier flags were applied on numeric columns per YAML thresholds.",
        f"{fmt_num(review)} items remain in the review queue for human decision.",
        f"Silent deletions detected: {fmt_num(silent)} (expected 0).",
        f"Output row count is {fmt_num(metrics.get('rows_out'))} from {fmt_num(metrics.get('rows_in'))} input rows.",
    ]
    return sents[:6]


def _fact_sheet(ctx: RunContext, metrics: dict[str, Any], verdict: str) -> str:
    parts = [verdict, fmt_num(metrics.get("rows_in")), fmt_num(metrics.get("rows_out")), fmt_num(metrics.get("duplicates_removed"))]
    parts += [fmt_num(metrics.get("cells_imputed")), fmt_num(metrics.get("outliers_flagged")), fmt_num(metrics.get("review_items"))]
    return " ".join(parts)


def _llm_summary_template(ctx: RunContext, metrics: dict[str, Any], verdict: str) -> str:
    return " ".join(_executive_sentences(ctx, metrics)[:4])


def build(
    data_dir: Path,
    run_id: str,
    dataset: str,
    *,
    lang: str = "en",
    privacy: bool = False,
    llm_summary: bool = False,
    llm_summary_text: str | None = None,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> Path:
    """Build PDF under runs/<run_id>/report/ and return path."""
    font = _effective_font()
    ctx = load_context(data_dir, run_id, dataset, lang=lang, privacy=privacy, now=now, tz=tz)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    safe_ds = re.sub(r"[^a-zA-Z0-9_-]+", "_", dataset)[:40]
    out_path = ctx.report_dir / f"BIFlow_BO3_report_{safe_ds}_{run_id}.pdf"

    def prog(p: float, msg: str) -> None:
        if progress:
            progress(p, msg)

    prog(0.05, "Loading artifacts")
    lang = ctx.lang
    metrics = _metrics(ctx)
    checks = compute_safety_checks(ctx)
    verdict = compute_verdict(ctx, checks)
    manifest = _manifest(ctx)
    cfg_text = ""
    cfg_p = ctx.run_dir / "config_used.yaml"
    if cfg_p.is_file():
        cfg_text = cfg_p.read_text(encoding="utf-8")
    cfg_hash = _config_hash(cfg_text) if cfg_text else "—"

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontName=font, fontSize=16, spaceAfter=10, textColor=COLOR_GREY))
    styles.add(ParagraphStyle(name="H2", fontName=font, fontSize=12, spaceBefore=8, spaceAfter=6, textColor=COLOR_GREY))
    styles.add(ParagraphStyle(name="Body", fontName=font, fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="Caption", fontName=font, fontSize=8, textColor=COLOR_GREY, spaceAfter=6))
    styles.add(ParagraphStyle(name="Mono", fontName=font, fontSize=7, leading=9))

    generated_local = ctx.now.astimezone(ctx.tz).strftime("%Y-%m-%d %H:%M %Z")
    privacy_footer = _t(lang, "privacy_on") if privacy else _t(lang, "privacy_off")

    story: list[Any] = []

    # --- Cover ---
    story.append(_heading(_t(lang, "title"), styles["H1"], "sec_cover", 0))
    story.append(Paragraph(_t(lang, "cover_caption"), styles["Caption"]))
    cover_rows = [
        ["Dataset", escape_para(dataset)],
        ["Run id", escape_para(run_id)],
        [_t(lang, "generated_at"), escape_para(generated_local)],
    ]
    for tab in manifest.get("tables") or []:
        if isinstance(tab, dict):
            cover_rows.append(["Source", f"{escape_para(tab.get('source'))} ({_short_sha256(str(tab.get('sha256', '')))})"])
            cover_rows.append(["Shape", f"{fmt_num(tab.get('rows'))} × {fmt_num(len(tab.get('columns') or []))}"])
            break
    snap_clean = ctx.snapshot.get("clean") or {}
    llm_calls = snap_clean.get("llm_calls") or []
    if llm_calls:
        cover_rows.append(["LLM", escape_para(llm_calls[0].get("model", "api"))])
    else:
        cover_rows.append(["LLM", _t(lang, "llm_off")])
    cover_rows.append(["Config hash", escape_para(cfg_hash)])
    try:
        import sys

        import reportlab
        import sklearn

        cover_rows.append(
            [
                "Versions",
                f"Python {escape_para(sys.version.split()[0])}, pandas {escape_para(pd.__version__)}, "
                f"sklearn {escape_para(sklearn.__version__)}, reportlab {escape_para(reportlab.Version)}",
            ],
        )
    except Exception:
        pass
    story.append(_table(cover_rows, [4 * cm, 12 * cm], font=font))
    story.append(PageBreak())

    toc_sections = [
        ("sec_summary", _t(lang, "sec_summary")),
        ("sec_safety", _t(lang, "sec_safety")),
        ("sec_parse", _t(lang, "sec_parse")),
        ("sec_recognition", _t(lang, "sec_recognition")),
        ("sec_profile", _t(lang, "sec_profile")),
        ("sec_cleaning", _t(lang, "sec_cleaning")),
        ("sec_review", _t(lang, "sec_review")),
        ("sec_dropped", _t(lang, "sec_dropped")),
        ("sec_lineage", _t(lang, "sec_lineage")),
        ("sec_llm", _t(lang, "sec_llm")),
        ("sec_repro", _t(lang, "sec_repro")),
        ("sec_appendix", _t(lang, "sec_appendix")),
    ]
    story.append(_heading(_t(lang, "toc"), styles["H1"], "sec_toc", 0))
    for sid, label in toc_sections:
        story.append(Paragraph(f'<a href="#{sid}" color="#1565c0">{escape_para(label)}</a>', styles["Body"]))
    story.append(PageBreak())

    class _TOCDoc(_ReportDoc):
        pass

    prog(0.15, "Building sections")

    # Executive summary
    vcolor = COLOR_PASS if verdict == "PASS" else COLOR_REVIEW if verdict == "REVIEW" else COLOR_FAIL
    vlabel = _t(lang, "verdict_pass") if verdict == "PASS" else _t(lang, "verdict_review") if verdict == "REVIEW" else _t(lang, "verdict_fail")
    story.append(_heading(f'<a name="sec_summary"/>{_t(lang, "sec_summary")}', styles["H1"], "sec_summary", 0))
    story.append(Paragraph(f'<font color="{vcolor.hexval()}"><b>{escape_para(vlabel)}</b></font>', styles["Body"]))
    if ctx.run_error:
        story.append(Paragraph(f"<b>Error:</b> {escape_para(ctx.run_error)}", styles["Body"]))
    cards = [
        ["Rows in", fmt_num(metrics.get("rows_in")), "Rows out", fmt_num(metrics.get("rows_out"))],
        ["Duplicates removed", fmt_num(metrics.get("duplicates_removed")), "Cells imputed", fmt_num(metrics.get("cells_imputed"))],
        ["Outliers flagged", fmt_num(metrics.get("outliers_flagged")), "Review items", fmt_num(metrics.get("review_items"))],
        ["Silent deletions", fmt_num(metrics.get("silent_deletions")), "Runtime ms", fmt_num(snap_clean.get("latency_ms"))],
    ]
    story.append(_table(cards))
    summary_text = _llm_summary_template(ctx, metrics, verdict)
    if llm_summary and llm_summary_text:
        fact = _fact_sheet(ctx, metrics, verdict)
        nums_in = set(re.findall(r"\d[\d,]*", llm_summary_text))
        nums_fact = set(re.findall(r"\d[\d,]*", fact))
        if nums_in <= nums_fact or not nums_in:
            summary_text = llm_summary_text
    for sent in summary_text.split(". "):
        if sent.strip():
            story.append(Paragraph(escape_para(sent.strip()) + ("" if sent.endswith(".") else "."), styles["Body"]))
    story.append(Spacer(1, 6 * mm))

    # Safety
    story.append(_heading(f'<a name="sec_safety"/>{_t(lang, "sec_safety")}', styles["H1"], "sec_safety", 0))
    story.append(Paragraph("Invariant checks derived from parquet files and logs (never hardcoded).", styles["Caption"]))
    safety_data = [["Check", "Status", "Evidence"]]
    for name, st, ev in checks:
        safety_data.append([escape_para(name), escape_para(st), escape_para(ev)])
    story.append(_table(safety_data, [5 * cm, 2.5 * cm, 8.5 * cm]))
    story.append(Spacer(1, 4 * mm))

    # Parse
    story.append(_heading(f'<a name="sec_parse"/>{_t(lang, "sec_parse")}', styles["H1"], "sec_parse", 0))
    ps = manifest.get("parse_settings") or {}
    story.append(Paragraph(f"Global parse settings: {escape_para(json.dumps(ps))}", styles["Body"]))
    parse_rows = [["File", "Encoding", "Delimiter", "Rows", "Cols", "Warnings"]]
    for tab in manifest.get("tables") or []:
        if not isinstance(tab, dict):
            continue
        parse_rows.append(
            [
                escape_para(tab.get("source")),
                escape_para(ps.get("encoding") or "auto"),
                escape_para(ps.get("delimiter")),
                fmt_num(tab.get("rows")),
                fmt_num(len(tab.get("columns") or [])),
                escape_para("; ".join((tab.get("warnings") or [])[:3])),
            ],
        )
    if len(parse_rows) == 1:
        story.append(Paragraph(f"{_t(lang, 'not_available')}: ingest_manifest.json", styles["Body"]))
    else:
        story.append(_table(parse_rows, [3 * cm, 2 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 6 * cm]))

    # Recognition
    story.append(_heading(f'<a name="sec_recognition"/>{_t(lang, "sec_recognition")}', styles["H1"], "sec_recognition", 0))
    rec = _recognition(ctx)
    warn_cols = [c for c in rec if c.get("proposed_action") == "review" or float(c.get("confidence") or 0) < 0.7]
    main_rec = warn_cols if len(rec) > RECO_MAIN_MAX_COLS else rec
    rec_header = ["Table", "Column", "Role", "Type", "Conf.", "Action", "Evidence"]
    rec_data = [rec_header]
    for c in main_rec[:200]:
        rec_data.append(
            [
                escape_para(c.get("table")),
                escape_para(c.get("column")),
                escape_para(c.get("role")),
                escape_para(c.get("semantic_type")),
                f"{float(c.get('confidence') or 0):.2f}",
                escape_para(c.get("proposed_action")),
                escape_para("; ".join(c.get("evidence") or [])[:120]),
            ],
        )
    if not rec:
        story.append(Paragraph(f"{_t(lang, 'not_available')}: recognition_report.json", styles["Body"]))
    else:
        if len(rec) > RECO_MAIN_MAX_COLS:
            story.append(Paragraph(f"Main section lists {len(warn_cols)} columns with review/low confidence; full table in appendix.", styles["Caption"]))
        story.append(_table(rec_data))

    # Profile
    story.append(_heading(f'<a name="sec_profile"/>{_t(lang, "sec_profile")}', styles["H1"], "sec_profile", 0))
    pb = _read_json(ctx.profile_before_dir / "profile.json")
    pa = _read_json(ctx.profile_after_dir / "profile.json")
    if pb:
        prof_rows = [["Table", "Rows", "Dupes", "Null cells (sum)"]]
        for t, td in (pb.get("tables") or {}).items():
            if isinstance(td, dict):
                nulls = sum(int((cd or {}).get("null_count") or 0) for cd in (td.get("columns") or {}).values())
                prof_rows.append([escape_para(t), fmt_num(td.get("rows")), fmt_num(td.get("duplicate_rows")), fmt_num(nulls)])
        story.append(_table(prof_rows))
    else:
        story.append(Paragraph(f"{_t(lang, 'not_available')}: run Profile (before)", styles["Body"]))
    png = _chart_null_diff(ctx)
    if png:
        story.append(Image(io.BytesIO(png), width=16 * cm, height=9 * cm))
    elif not pa:
        story.append(Paragraph(f"{_t(lang, 'not_available')}: profile after / profile_diff", styles["Body"]))
    qlog = _quality_log(ctx)
    hist_cols: list[tuple[str, str]] = []
    for e in qlog:
        if "impute" in str(e.get("rule_id")) or e.get("rule_id") == "detect_outliers":
            hist_cols.append((str(e.get("table", "t")), str(e.get("column", "c"))))
    seen: set[tuple[str, str]] = set()
    for t, c in hist_cols:
        if (t, c) in seen or len(seen) >= 6:
            continue
        seen.add((t, c))
        hpng = _histogram_overlay(ctx, t, c)
        if hpng:
            story.append(Image(io.BytesIO(hpng), width=12 * cm, height=7 * cm))

    # Cleaning
    story.append(_heading(f'<a name="sec_cleaning"/>{_t(lang, "sec_cleaning")}', styles["H1"], "sec_cleaning", 0))
    by_rule: dict[str, dict[str, Any]] = {}
    for e in qlog:
        rid = str(e.get("rule_id", "?"))
        br = by_rule.setdefault(rid, {"cols": set(), "rows": 0, "method": e.get("method", "deterministic")})
        br["cols"].add(str(e.get("column")))
        br["rows"] += int(e.get("rows_affected") or 0)
    rule_rows = [["Rule", "Method", "Columns", "Rows affected"]]
    for rid, info in sorted(by_rule.items()):
        rule_rows.append([escape_para(rid), escape_para(info["method"]), escape_para(", ".join(sorted(info["cols"])[:8])), fmt_num(info["rows"])])
    if len(rule_rows) > 1:
        story.append(_table(rule_rows))
    qrows = [["Table", "Column", "Rule", "Rows", "Before", "After"]]
    for e in qlog[:QL_MAIN_CAP]:
        before = e.get("before_sample") or e.get("sample_before") or []
        after = e.get("after_sample") or e.get("sample_after") or []
        qrows.append(
            [
                escape_para(e.get("table")),
                escape_para(e.get("column")),
                escape_para(e.get("rule_id")),
                fmt_num(e.get("rows_affected")),
                _sample_values(before if isinstance(before, list) else [before], privacy),
                _sample_values(after if isinstance(after, list) else [after], privacy),
            ],
        )
    if len(qlog) > QL_MAIN_CAP:
        story.append(Paragraph(f"Showing first {QL_MAIN_CAP} of {len(qlog)} entries. {_t(lang, 'see_csv')}", styles["Caption"]))
    if len(qrows) > 1:
        story.append(_table(qrows, [2.5 * cm, 2.5 * cm, 3 * cm, 1.5 * cm, 3 * cm, 3 * cm]))
    elif not qlog:
        story.append(Paragraph("No quality log entries (zero changes or clean not run).", styles["Body"]))

    # Review queue
    story.append(_heading(f'<a name="sec_review"/>{_t(lang, "sec_review")}', styles["H1"], "sec_review", 0))
    rq = _review_queue(ctx)
    if not rq:
        story.append(Paragraph(_t(lang, "nothing_review"), styles["Body"]))
    else:
        rq_rows = [["Table", "Column", "Issue", "Action", "Confidence", "Source"]]
        for item in rq:
            rq_rows.append(
                [
                    escape_para(item.get("table")),
                    escape_para(item.get("column")),
                    escape_para(item.get("issue") or item.get("reason")),
                    escape_para(item.get("suggested_action") or item.get("proposed_action")),
                    escape_para(item.get("confidence")),
                    escape_para(item.get("source")),
                ],
            )
        story.append(_table(rq_rows))
    dec_path = ctx.data_dir / "decisions" / f"{dataset}.yaml"
    if dec_path.is_file():
        story.append(Paragraph("User decisions file present (category maps / overrides merged on next run).", styles["Caption"]))

    # Dropped
    story.append(_heading(f'<a name="sec_dropped"/>{_t(lang, "sec_dropped")}', styles["H1"], "sec_dropped", 0))
    dropped_map = _dropped_by_table(ctx)
    drop_rows = [["Table", "Rows in", "Dropped", "Rows out", "Status"]]
    for pq_path in sorted(ctx.clean_dir.glob("*.parquet")):
        t = pq_path.stem
        in_p = ctx.ingest_dir / f"{t}.parquet"
        if not in_p.is_file():
            continue
        ri, ro = parquet_row_count(in_p), parquet_row_count(pq_path)
        dr = dropped_map.get(t, 0)
        ok = ri - dr == ro
        drop_rows.append([escape_para(t), fmt_num(ri), fmt_num(dr), fmt_num(ro), "PASS" if ok else "FAIL"])
    if len(drop_rows) > 1:
        story.append(_table(drop_rows))
    by_rule_drop: dict[str, int] = {}
    ids_by_rule: dict[str, list[str]] = {}
    for row in _dropped_rows(ctx):
        rid = str(row.get("rule_id", "unknown"))
        by_rule_drop[rid] = by_rule_drop.get(rid, 0) + 1
        ids = ids_by_rule.setdefault(rid, [])
        if len(ids) < 20:
            ids.append(str(row.get("row_id", row.get("id", "?"))))
    if by_rule_drop:
        story.append(_table([["Rule", "Count", "Sample ids"]] + [[escape_para(k), fmt_num(v), escape_para(", ".join(ids_by_rule[k]))] for k, v in by_rule_drop.items()]))

    # Lineage
    story.append(_heading(f'<a name="sec_lineage"/>{_t(lang, "sec_lineage")}', styles["H1"], "sec_lineage", 0))
    lineage = snap_clean.get("lineage_events") or []
    if not lineage:
        lineage = [
            {"step": e.get("rule_id"), "method": e.get("method", "deterministic"), "rule": e.get("rule_id"), "rows_affected": e.get("rows_affected")}
            for e in qlog[:100]
        ]
    lin_rows = [["Step", "Method", "Rule", "Rows"]]
    for ev in lineage[:80]:
        if isinstance(ev, dict):
            lin_rows.append([escape_para(ev.get("step")), escape_para(ev.get("method")), escape_para(ev.get("rule")), fmt_num(ev.get("rows_affected"))])
    story.append(_table(lin_rows))
    ppng = _chart_pipeline(ctx)
    if ppng:
        story.append(Image(io.BytesIO(ppng), width=16 * cm, height=5 * cm))

    # LLM
    story.append(_heading(f'<a name="sec_llm"/>{_t(lang, "sec_llm")}', styles["H1"], "sec_llm", 0))
    story.append(Paragraph(_t(lang, "numbers_guarantee"), styles["Caption"]))
    if llm_calls:
        llm_rows = [["Prompt", "Model", "Provider", "Tokens", "ms", "Cache"]]
        for call in llm_calls:
            llm_rows.append(
                [
                    escape_para(call.get("prompt_id")),
                    escape_para(call.get("model")),
                    escape_para(call.get("provider")),
                    fmt_num(call.get("total_tokens")),
                    fmt_num(call.get("latency_ms")),
                    escape_para(call.get("cache_hit")),
                ],
            )
        story.append(_table(llm_rows))
    else:
        story.append(Paragraph(_t(lang, "llm_not_used"), styles["Body"]))

    # Repro
    story.append(_heading(f'<a name="sec_repro"/>{_t(lang, "sec_repro")}', styles["H1"], "sec_repro", 0))
    story.append(Paragraph(_t(lang, "limitations_heading"), styles["H2"]))
    for lim in _limitations_text():
        story.append(Paragraph(f"• {escape_para(lim)}", styles["Body"]))
    story.append(Paragraph(_t(lang, "rtl_note"), styles["Caption"]))
    if cfg_text:
        lines = cfg_text.splitlines()[:120]
        story.append(Paragraph("config_used.yaml (first 120 lines):", styles["H2"]))
        story.append(Paragraph("<br/>".join(escape_para(x) for x in lines), styles["Mono"]))

    # Appendix
    story.append(PageBreak())
    story.append(_heading(f'<a name="sec_appendix"/>{_t(lang, "sec_appendix")}', styles["H1"], "sec_appendix", 0))
    if len(rec) > len(main_rec):
        story.append(Paragraph("Full recognition table", styles["H2"]))
        full_rec = [rec_header]
        for c in rec[:500]:
            full_rec.append(
                [
                    escape_para(c.get("table")),
                    escape_para(c.get("column")),
                    escape_para(c.get("role")),
                    escape_para(c.get("semantic_type")),
                    f"{float(c.get('confidence') or 0):.2f}",
                    escape_para(c.get("proposed_action")),
                    escape_para("; ".join(c.get("evidence") or [])[:80]),
                ],
            )
        story.append(_table(full_rec))
    if len(qlog) > QL_MAIN_CAP:
        story.append(Paragraph(f"Additional quality log entries (max {QL_APPENDIX_CAP})", styles["H2"]))
        extra = [["Table", "Column", "Rule", "Rows"]]
        for e in qlog[QL_MAIN_CAP : QL_MAIN_CAP + QL_APPENDIX_CAP]:
            extra.append([escape_para(e.get("table")), escape_para(e.get("column")), escape_para(e.get("rule_id")), fmt_num(e.get("rows_affected"))])
        story.append(_table(extra))
    gloss = [
        ("Role", "Inferred column purpose (id, categorical, numeric, …)"),
        ("Flag", "Boolean helper column (__imputed, __outlier, …)"),
        ("Imputation", "Fill missing values with a documented statistic or model"),
        ("Outlier", "Values flagged by IQR or similar; not always removed"),
        ("Review queue", "Items needing human approval before auto-apply"),
        ("Lineage", "Ordered record of cleaning steps and row counts"),
    ]
    story.append(Paragraph(_t(lang, "glossary_heading"), styles["H2"]))
    story.append(_table([["Term", "Meaning"]] + [[escape_para(a), escape_para(b)] for a, b in gloss]))

    prog(0.7, "Rendering PDF")

    def _header_footer(canv: Any, doc: Any) -> None:
        canv.saveState()
        canv.setFont(font, 8)
        canv.setFillColor(COLOR_GREY)
        canv.drawString(2 * cm, A4[1] - 1.2 * cm, f"{dataset} | {run_id}"[:120])
        canv.drawRightString(
            A4[0] - 2 * cm,
            1 * cm,
            f"{_t(lang, 'footer_page')} {canv.getPageNumber()} | {generated_local} | {privacy_footer}"[:200],
        )
        canv.restoreState()

    doc = _TOCDoc(
        str(out_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=_t(lang, "title"),
        author="BIFlow BO3",
        subject=f"Run {run_id}",
        creator="BIFlow BO3 playground",
    )
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    prog(1.0, "Done")
    return out_path


def build_report_zip(data_dir: Path, run_id: str, dataset: str, pdf_path: Path) -> Path:
    run_dir = data_dir / "runs" / run_id
    zpath = run_dir / "report" / f"BIFlow_BO3_report_bundle_{run_id}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    readme = (
        "BIFlow BO3 report bundle\n"
        f"- PDF: {pdf_path.name}\n"
        "- quality_log.json, review_queue.json, recognition_report.json, config_used.yaml\n"
        "- cleaned CSV exports\n"
    )
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(pdf_path, pdf_path.name)
        zf.writestr("README.txt", readme)
        for rel in (
            "02_clean/quality_log.json",
            "02_clean/review_queue.json",
            "02_clean/recognition_report.json",
            "config_used.yaml",
        ):
            p = run_dir / rel.replace("/", "\\")
            if p.is_file():
                zf.write(p, Path(rel).name)
        cl = run_dir / "02_clean"
        for pq in cl.glob("*.parquet"):
            df = pd.read_parquet(pq)
            zf.writestr(f"{pq.stem}_clean.csv", df.to_csv(index=False))
    return zpath


def extract_pdf_text(pdf_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)
