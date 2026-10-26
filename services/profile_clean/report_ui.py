"""Streamlit Report section for BO3 playground."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from report_pdf import build, build_report_zip, has_clean_run, persist_run_snapshot


def _llm_provider() -> str:
    import os

    return os.getenv("LLM_PROVIDER", "ollama")


def render_report_section(
    *,
    data_dir: Path,
    run_id: str,
    dataset_slug: str,
    on_clean_response: dict | None = None,
) -> None:
    """Report PDF UI at end of upload results."""
    st.subheader("Report")
    if on_clean_response:
        persist_run_snapshot(data_dir / "runs" / run_id, "clean", on_clean_response)

    if not has_clean_run(data_dir, run_id):
        st.caption("Generate PDF report is available after a **Clean** run completes (02_clean parquet outputs).")
        st.button("Generate PDF report", disabled=True, key="report_gen_disabled")
        return

    lang = st.selectbox("Report language", ["en", "fr"], index=0, key="report_lang")
    privacy = st.checkbox("Hide sample values (privacy mode)", value=False, key="report_privacy")
    llm_summary = st.checkbox("Optional LLM plain-language summary (default off)", value=False, key="report_llm_sum")
    llm_text: str | None = None
    if llm_summary:
        if _llm_provider() == "api":
            st.warning("API provider: a fact sheet derived from artifacts may be sent to a third-party LLM endpoint.")
            if not st.checkbox("I understand the privacy implications", value=False, key="report_llm_consent"):
                llm_summary = False
        # LLM call not wired by default — template summary used unless caller extends this hook.
        llm_text = None

    if st.button("Generate PDF report", key="report_generate"):
        prog = st.progress(0.0, text="Starting…")
        status = st.empty()

        def progress(p: float, msg: str) -> None:
            prog.progress(min(1.0, p), text=msg)
            status.caption(msg)

        try:
            tz = ZoneInfo("UTC")
            try:
                tz = datetime.now().astimezone().tzinfo or ZoneInfo("UTC")  # type: ignore[arg-type]
            except Exception:
                pass
            pdf_path = build(
                data_dir,
                run_id,
                dataset_slug,
                lang=lang,
                privacy=privacy,
                llm_summary=llm_summary,
                llm_summary_text=llm_text,
                tz=tz if isinstance(tz, ZoneInfo) else ZoneInfo("UTC"),
                progress=progress,
            )
            st.session_state[f"report_pdf_{run_id}"] = str(pdf_path)
            prog.progress(1.0, text="PDF ready")
            st.success(f"Saved to `{pdf_path}`")
        except Exception as ex:
            st.error(f"Report generation failed: {ex}")
            return

    pdf_key = st.session_state.get(f"report_pdf_{run_id}")
    report_dir = data_dir / "runs" / run_id / "report"
    if not pdf_key and report_dir.is_dir():
        pdfs = sorted(report_dir.glob("BIFlow_BO3_report_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if pdfs:
            pdf_key = str(pdfs[0])
    if pdf_key and Path(pdf_key).is_file():
        pdf_path = Path(pdf_key)
        st.download_button(
            "Download PDF",
            pdf_path.read_bytes(),
            pdf_path.name,
            "application/pdf",
            key="report_dl_pdf",
        )
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(pdf_path))
            cols = st.columns(2)
            for i in range(min(2, len(pdf))):
                page = pdf[i]
                pil = page.render(scale=1.5).to_pil()
                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                cols[i].image(buf.getvalue(), caption=f"Page {i + 1}")
        except Exception as ex:
            st.caption(f"Preview unavailable ({ex}). Use Download PDF.")

        if st.button("Build report bundle (zip)", key="report_zip"):
            zpath = build_report_zip(data_dir, run_id, dataset_slug, pdf_path)
            st.session_state[f"report_zip_{run_id}"] = str(zpath)
        zip_key = st.session_state.get(f"report_zip_{run_id}")
        if zip_key and Path(zip_key).is_file():
            zp = Path(zip_key)
            st.download_button("Download report bundle (zip)", zp.read_bytes(), zp.name, "application/zip", key="report_dl_zip")
