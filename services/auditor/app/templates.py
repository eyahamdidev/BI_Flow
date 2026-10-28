"""Template prose. Every number it writes is copied from the fact sheet, so the fact-check passes."""

from __future__ import annotations

from typing import Any


def _join(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values if value)


def _phrase(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().rstrip(".!?")
    return text or fallback


def explain_template(sheet: dict[str, Any], lang: str = "en") -> str:
    if lang == "fr":
        return _explain_fr(sheet)
    return _explain_en(sheet)


def _explain_en(sheet: dict[str, Any]) -> str:
    definition = sheet.get("definition") or {}
    name = definition.get("name") or sheet.get("kpi_id")
    period = sheet.get("period")
    sentences = [f"{name} for {period} is logged as {_phrase(definition.get('description'), 'a KPI with no logged description')}."]
    lineage = sheet.get("lineage") or {}
    if lineage.get("found") and (lineage.get("raw_tables") or lineage.get("cleaning_rules") or lineage.get("dbt_models")):
        sentences.append(
            "The logged path starts at "
            f"{_join(lineage.get('raw_tables') or []) or 'a logged dataset'}, applies "
            f"{_join(lineage.get('cleaning_rules') or []) or 'no extra cleaning rule'}, and passes through "
            f"{_join(lineage.get('dbt_models') or []) or 'no logged warehouse model'}."
        )
    else:
        sentences.append("No lineage path was logged from the raw tables to this KPI.")
    drivers = sheet.get("drivers") or {}
    contributions = drivers.get("contributions") or []
    if drivers and drivers.get("total_delta") is not None and contributions:
        pieces = [f"{item.get('dimension_value')} at {item.get('delta')}" for item in contributions]
        compare = drivers.get("compare_to") or sheet.get("compare_to") or "the logged comparison period"
        sentences.append(
            f"Compared with {compare}, the logged change is {drivers.get('total_delta')} {definition.get('unit') or ''}. "
            f"The logged contributions are {_join(pieces)}."
        )
    elif drivers and drivers.get("total_delta") is not None:
        sentences.append(f"The logged change is {drivers.get('total_delta')} {definition.get('unit') or ''}.")
    else:
        sentences.append("No driver decomposition was logged for this KPI and period.")
    insights = sheet.get("insights") or []
    if insights:
        first = insights[0]
        sentences.append(f"A logged {first.get('type') or 'insight'} ({first.get('id')}) is tied to this KPI.")
    else:
        sentences.append("No insight facts were logged for this KPI and period.")
    return " ".join(_fit(sentences, "en"))


def _explain_fr(sheet: dict[str, Any]) -> str:
    definition = sheet.get("definition") or {}
    name = definition.get("name") or sheet.get("kpi_id")
    period = sheet.get("period")
    sentences = [
        f"{name} pour {period} est journalisé ainsi : {_phrase(definition.get('description'), 'un indicateur sans description journalisée')}."
    ]
    lineage = sheet.get("lineage") or {}
    if lineage.get("found") and (lineage.get("raw_tables") or lineage.get("cleaning_rules") or lineage.get("dbt_models")):
        sentences.append(
            "Le chemin journalisé part de "
            f"{_join(lineage.get('raw_tables') or []) or 'un jeu journalisé'}, applique "
            f"{_join(lineage.get('cleaning_rules') or []) or 'aucune règle de nettoyage supplémentaire'}, et passe par "
            f"{_join(lineage.get('dbt_models') or []) or 'aucun modèle journalisé'}."
        )
    else:
        sentences.append("Aucun chemin de lignage n'a été journalisé entre les tables sources et cet indicateur.")
    drivers = sheet.get("drivers") or {}
    contributions = drivers.get("contributions") or []
    if drivers and drivers.get("total_delta") is not None and contributions:
        pieces = [f"{item.get('dimension_value')} à {item.get('delta')}" for item in contributions]
        compare = drivers.get("compare_to") or sheet.get("compare_to") or "la période de comparaison journalisée"
        sentences.append(
            f"Par rapport à {compare}, la variation journalisée est {drivers.get('total_delta')} {definition.get('unit') or ''}. "
            f"Les contributions journalisées sont {_join(pieces)}."
        )
    elif drivers and drivers.get("total_delta") is not None:
        sentences.append(f"La variation journalisée est {drivers.get('total_delta')} {definition.get('unit') or ''}.")
    else:
        sentences.append("Aucune décomposition des contributions n'a été journalisée pour cet indicateur et cette période.")
    insights = sheet.get("insights") or []
    if insights:
        first = insights[0]
        sentences.append(f"Un insight journalisé de type {first.get('type') or 'insight'} ({first.get('id')}) est lié à cet indicateur.")
    else:
        sentences.append("Aucun fait d'insight n'a été journalisé pour cet indicateur et cette période.")
    return " ".join(_fit(sentences, "fr"))


def _fit(sentences: list[str], lang: str) -> list[str]:
    cleaned = [sentence.strip() for sentence in sentences if sentence.strip()]
    filler = (
        "Cette phrase utilise uniquement la fiche de faits journalisée."
        if lang == "fr"
        else "This statement uses the logged fact sheet only."
    )
    while len(cleaned) < 3:
        cleaned.append(filler)
    return cleaned[:5]


def section_template(sheet: dict[str, Any], lang: str = "en") -> str:
    title = sheet.get("title") or "This section"
    steps = sheet.get("steps") or []
    count = sheet.get("event_count", len(steps))
    if lang == "fr":
        lead = f"{title} a journalisé {count} étapes."
    else:
        lead = f"{title} logged {count} steps."
    if not steps:
        return lead
    parts = [lead]
    for step in steps:
        if lang == "fr":
            sentence = f"L'étape {step.get('step')} utilise la méthode {step.get('method')}"
        else:
            sentence = f"Step {step.get('step')} used method {step.get('method')}"
        if step.get("rule"):
            sentence += f" ({step.get('rule')})" if lang == "en" else f" ({step.get('rule')})"
        if step.get("rows_in") is not None and step.get("rows_out") is not None:
            if lang == "fr":
                sentence += f", avec {step['rows_in']} lignes en entrée et {step['rows_out']} lignes en sortie"
            else:
                sentence += f", with {step['rows_in']} rows in and {step['rows_out']} rows out"
        if step.get("rows_affected") is not None:
            sentence += f", affecting {step['rows_affected']} rows" if lang == "en" else f", affectant {step['rows_affected']} lignes"
        parts.append(sentence + ".")
    if sheet.get("duration_s") is not None:
        if lang == "fr":
            parts.append(f"La durée journalisée de la section est {sheet['duration_s']} secondes.")
        else:
            parts.append(f"The logged section duration is {sheet['duration_s']} seconds.")
    if sheet.get("fix_count") is not None:
        parts.append(
            f"The quality log lists {sheet['fix_count']} fixes."
            if lang == "en"
            else f"Le journal qualité liste {sheet['fix_count']} corrections."
        )
    return " ".join(parts)


def kpi_template(sheet: dict[str, Any], lang: str = "en") -> str:
    count = sheet.get("kpi_count", 0)
    if lang == "fr":
        parts = [f"Le catalogue journalisé contient {count} indicateurs."]
    else:
        parts = [f"The logged catalog contains {count} KPIs."]
    for item in sheet.get("kpis") or []:
        sources = _join(item.get("source_tables") or []) or "none logged"
        rules = _join(item.get("cleaning_steps") or []) or "none logged"
        models = _join(item.get("dbt_models") or []) or "none logged"
        if lang == "fr":
            parts.append(
                f"{item.get('name')} ({item.get('kpi_id')}) est décrit ainsi : {_phrase(item.get('description'), 'sans description')}. "
                f"Sources journalisées : {sources}. Règles de nettoyage : {rules}. Modèles : {models}."
            )
        else:
            parts.append(
                f"{item.get('name')} ({item.get('kpi_id')}) is described as {_phrase(item.get('description'), 'having no logged description')}. "
                f"Logged sources: {sources}. Cleaning steps: {rules}. Models: {models}."
            )
    return " ".join(parts)


def insight_template(sheet: dict[str, Any], lang: str = "en") -> str:
    count = sheet.get("insight_count", 0)
    if lang == "fr":
        parts = [f"{count} insights journalisés sont rattachés à des faits."]
    else:
        parts = [f"{count} logged insights are tied to facts."]
    for item in sheet.get("insights") or []:
        facts = item.get("facts") or {}
        fact_text = ", ".join(f"{key} {value}" for key, value in facts.items()) or "no numeric facts"
        if lang == "fr":
            parts.append(
                f"L'insight {item.get('id')} sur {item.get('kpi_id')} ({item.get('period')}) est de type {item.get('type')}. "
                f"Faits journalisés : {fact_text}."
            )
        else:
            parts.append(
                f"Insight {item.get('id')} on {item.get('kpi_id')} ({item.get('period')}) is a {item.get('type')}. "
                f"Logged facts: {fact_text}."
            )
    return " ".join(parts)


def completeness_template(sheet: dict[str, Any], lang: str = "en") -> str:
    pct = sheet.get("coverage_pct")
    registered = sheet.get("registered_count")
    observed = sheet.get("observed_count")
    missing = sheet.get("untracked_count")
    names = _join(sheet.get("untracked_transformations") or [])
    if lang == "fr":
        text = (
            f"La couverture du lignage est {pct} pour cent. "
            f"{observed} étapes sur {registered} étapes enregistrées ont au moins un événement. "
            f"Le nombre de transformations non suivies est {missing}."
        )
        if names:
            text += f" Transformations non suivies : {names}."
        return text
    text = (
        f"Lineage coverage is {pct} percent. "
        f"{observed} of {registered} registered steps have at least one event. "
        f"The untracked transformation count is {missing}."
    )
    if names:
        text += f" Untracked transformations: {names}."
    return text
