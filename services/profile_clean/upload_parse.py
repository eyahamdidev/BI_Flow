"""Robust CSV/TSV ingest for playground (no app imports)."""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_NA_TOKENS = {"", "NA", "N/A", "null", "None", "-", "?", "nan", "#N/A", "NaN", "NULL"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
BOOL_TRUE = {"true", "yes", "1", "oui", "y", "t"}
BOOL_FALSE = {"false", "no", "0", "non", "n", "f"}


@dataclass
class ParseSettings:
    encoding: str = "utf-8"
    delimiter: str = ","
    header: bool = True
    decimal: str = "."
    thousands: str | None = None
    dayfirst: bool = True
    na_tokens: tuple[str, ...] = tuple(DEFAULT_NA_TOKENS)


@dataclass
class ParseReport:
    table_name: str
    source_name: str
    encoding: str
    delimiter: str
    rows: int
    columns: list[str]
    skipped_lines: int = 0
    renamed_columns: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    inferred_schema: dict[str, str] = field(default_factory=dict)
    sha256: str = ""


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s or "table"


def sanitize_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\- ]", "_", base)
    return base[:200] or "upload.csv"


def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detect_delimiter(sample: str) -> str:
    counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
    return max(counts, key=counts.get) if max(counts.values()) > 0 else ","


def _dedupe_headers(cols: list[str]) -> tuple[list[str], dict[str, str]]:
    seen: dict[str, int] = {}
    out: list[str] = []
    renamed: dict[str, str] = {}
    for c in cols:
        base = (c or "").strip() or "unnamed"
        if base in seen:
            seen[base] += 1
            new = f"{base}__{seen[base]}"
            renamed[new] = base
            out.append(new)
        else:
            seen[base] = 0
            out.append(base)
    return out, renamed


def read_csv_robust(
    content: bytes,
    table_name: str,
    source_name: str,
    settings: ParseSettings | None = None,
) -> tuple[pd.DataFrame, ParseReport]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit")
    if len(content.strip()) == 0:
        raise ValueError("Empty file")
    settings = settings or ParseSettings()
    enc = settings.encoding or detect_encoding(content)
    text = content.decode(enc, errors="replace")
    if settings.delimiter == "auto":
        settings.delimiter = detect_delimiter(text[:8000])
    skipped = 0
    try:
        df = pd.read_csv(
            io.StringIO(text),
            sep=settings.delimiter,
            header=0 if settings.header else None,
            dtype=str,
            keep_default_na=False,
            na_values=list(settings.na_tokens),
            on_bad_lines="warn",
            engine="python",
        )
    except pd.errors.EmptyDataError as e:
        raise ValueError("No data rows (header-only?)") from e
    except Exception:
        df = pd.read_csv(
            io.StringIO(text),
            sep=settings.delimiter,
            header=0 if settings.header else None,
            dtype=str,
            keep_default_na=False,
            on_bad_lines="skip",
            engine="python",
        )
        skipped = 1
        # approximate: not always available from pandas
    if not settings.header:
        df.columns = [f"col_{i}" for i in range(len(df.columns))]
    cols, renamed = _dedupe_headers(list(df.columns))
    df.columns = cols
    df = df.dropna(how="all")
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed", na=False)]
    for c in df.columns:
        if isinstance(df[c], pd.DataFrame):
            continue
        df[c] = df[c].astype(str).str.strip()
        df[c] = df[c].replace({t: pd.NA for t in settings.na_tokens if t})
    report = ParseReport(
        table_name=table_name,
        source_name=source_name,
        encoding=enc,
        delimiter=settings.delimiter,
        rows=len(df),
        columns=list(df.columns),
        skipped_lines=skipped,
        renamed_columns=renamed,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    df, schema, warns = infer_types(df, settings)
    report.inferred_schema = schema
    report.warnings.extend(warns)
    if len(df) == 0:
        raise ValueError("No rows after parsing")
    return df, report


def infer_types(df: pd.DataFrame, settings: ParseSettings) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    from app.column_roles import apply_role_dtypes, infer_table_roles, parse_warning_for_role

    warnings: list[str] = []
    roles = infer_table_roles(df)
    out = apply_role_dtypes(df, roles)
    schema: dict[str, str] = {}
    for col, info in roles.items():
        schema[col] = info.storage_dtype if info.role != "datetime" else "datetime"
        msg = parse_warning_for_role(info, col)
        if msg:
            warnings.append(msg)
        if info.role == "datetime":
            parsed, amb = _try_dates(out[col].astype("string"), settings.dayfirst)
            out[col] = parsed
            if amb:
                warnings.append(f"Column '{col}': ambiguous day/month in dates (dayfirst={settings.dayfirst})")
    return out, schema, warnings


def _to_numeric_series(s: pd.Series, decimal: str, thousands: str | None) -> pd.Series:
    ss = s.astype(str).str.strip()
    if thousands:
        ss = ss.str.replace(thousands, "", regex=False)
    if decimal != ".":
        ss = ss.str.replace(decimal, ".", regex=False)
    ss = ss.str.replace(r"[^\d.\-eE]", "", regex=True)
    return pd.to_numeric(ss, errors="coerce")


def _try_dates(s: pd.Series, dayfirst: bool) -> tuple[pd.Series, bool]:
    amb = False
    iso = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    if iso.notna().mean() > 0.5:
        return iso, False
    dmy = pd.to_datetime(s, dayfirst=True, errors="coerce")
    mdy = pd.to_datetime(s, dayfirst=False, errors="coerce")
    if dayfirst and dmy.notna().mean() > 0.5:
        if (dmy.notna() & mdy.notna()).any() and not dmy.equals(mdy):
            amb = True
        return dmy, amb
    if mdy.notna().mean() > 0.5:
        return mdy, amb
    return pd.to_datetime(s, errors="coerce"), amb


def write_ingest(
    run_id: str,
    data_dir: Path,
    tables: dict[str, pd.DataFrame],
    reports: list[ParseReport],
    parse_settings: dict[str, Any],
) -> Path:
    dest = data_dir / "runs" / run_id / "00_ingest"
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "tables": [], "parse_settings": parse_settings}
    for rep in reports:
        df = tables[rep.table_name]
        pq = dest / f"{rep.table_name}.parquet"
        df.to_parquet(pq, index=False)
        manifest["tables"].append(
            {
                "table": rep.table_name,
                "source": rep.source_name,
                "sha256": rep.sha256,
                "rows": rep.rows,
                "columns": rep.columns,
                "inferred_schema": rep.inferred_schema,
                "warnings": rep.warnings,
            }
        )
    (dest / "ingest_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return dest


def read_upload_bytes(
    content: bytes,
    table_name: str,
    source_name: str,
    settings: ParseSettings | None = None,
) -> tuple[pd.DataFrame, ParseReport]:
    """CSV/TSV/TXT via read_csv_robust; parquet/json/xlsx when extension matches."""
    ext = Path(source_name).suffix.lower()
    if ext == ".parquet":
        df = pd.read_parquet(io.BytesIO(content))
        rep = ParseReport(
            table_name=table_name,
            source_name=source_name,
            encoding="n/a",
            delimiter="n/a",
            rows=len(df),
            columns=list(df.columns),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        df, schema, warns = infer_types(df, settings or ParseSettings())
        rep.inferred_schema = schema
        rep.warnings = warns
        return df, rep
    if ext in (".json", ".jsonl"):
        if ext == ".jsonl":
            lines = content.decode("utf-8", errors="replace").strip().splitlines()
            rows = [json.loads(x) for x in lines if x.strip()]
        else:
            rows = json.loads(content.decode("utf-8", errors="replace"))
            if isinstance(rows, dict):
                rows = [rows]
        df = pd.json_normalize(rows)
        rep = ParseReport(
            table_name=table_name,
            source_name=source_name,
            encoding="utf-8",
            delimiter="n/a",
            rows=len(df),
            columns=list(df.columns),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        return df, rep
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(io.BytesIO(content), sheet_name=0)
        rep = ParseReport(
            table_name=table_name,
            source_name=source_name,
            encoding="n/a",
            delimiter="n/a",
            rows=len(df),
            columns=list(df.columns),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        df, schema, warns = infer_types(df, settings or ParseSettings())
        rep.inferred_schema = schema
        rep.warnings = warns
        return df, rep
    return read_csv_robust(content, table_name, source_name, settings)


def csv_roundtrip_equal(df: pd.DataFrame, delimiter: str = ",") -> bool:
    buf = io.StringIO()
    export = df.copy()
    for c in export.columns:
        if pd.api.types.is_datetime64_any_dtype(export[c]):
            export[c] = export[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    export.to_csv(buf, index=False, sep=delimiter)
    buf.seek(0)
    back = pd.read_csv(buf, dtype=str, keep_default_na=False)
    orig = export.astype(str).fillna("")
    back = back.astype(str).fillna("")
    return orig.shape == back.shape and (orig.values == back.values).all()
