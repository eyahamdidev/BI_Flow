# BO3 cross-dataset safety fix notes

## 1. Ticket coerced to float + imputed/outlier flags (Titanic)
**Layer:** (a) ingest inferred ≥85% numeric parse on ticket-like strings; (b) YAML assigned `median` imputation and IQR outliers to every numeric column; (c) service applied ML imputation without checking string/id semantics. **Fix:** Shared `column_roles` (id for alphanumeric labels), YAML only imputes/outliers on allowed roles, service `type_guard` blocks unsafe actions.

## 2. SibSp as string with "nan" tokens
**Layer:** (a) mixed constant/mode fill on mis-typed columns; (c) imputation wrote float/null as string literals. **Fix:** Restore dtypes after imputation (`Int64` for counts), `sanitize_string_nulls` on output, categorical vs numeric roles.

## 3. Survived 0/1 → boolean
**Layer:** (a) ingest mapped 0/1 to bool via BOOL_TRUE/FALSE rules. **Fix:** `binary_flag` role keeps integer storage; no bool coercion unless explicit `convert_to`.

## 4. Outlier flags on Pclass / Parch / Ticket
**Layer:** (b) YAML listed all numeric dtypes in `outliers.columns`; (c) service did not check role/cardinality. **Fix:** Outliers only for `continuous_numeric`; guard blocks categorical/id/binary; skip IQR when `nunique < 4`.

## 5. Embarked nulls not flagged/imputed
**Layer:** (b) YAML used `constant: unknown` for strings; (c) mode imputation only in ML path for `mode` strategy. **Fix:** Categorical nulls use `mode` + `Embarked__imputed`; flag-only high-null for Cabin.

## 6. Iris outliers_flagged = 0 despite lineage event
**Layer:** (c) IQR ran but metric counted only existing flag sums; columns with all-false flags or wrong dtype; discrete columns skipped. **Fix:** Ensure boolean `__outlier` columns written; metric sums flags; continuous numeric columns selected in YAML; `nunique >= 4` gate.

## 7. Iris "low cardinality / constant" warning on variety
**Layer:** (a) generic warning in old `infer_types`. **Fix:** Role-based parse warnings (`categorical, 3 values`).

## 8. Run id `upload_mydata_...`
**Layer:** UI default not tied to slug. **Fix:** Run id updates when dataset slug changes (playground).
