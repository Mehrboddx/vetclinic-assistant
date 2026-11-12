import pandas as pd
import streamlit as st

from core import services, vaccines
from core.database import get_session
from ui.components import bump, changed_rows, editor_key, flash, page_header, setup_page, show_flash

setup_page()

page_header("Catalogs", "فهرست‌ها", "Drugs and vaccines. Tests are defined on the Tests page.")
show_flash()


tab_drugs, tab_vaccines = st.tabs(["💊 Drugs (داروها)", "💉 Vaccines (واکسن‌ها)"])

# ======================================================================
# Drugs
# ======================================================================
with tab_drugs:
    st.caption("Drugs listed here can be picked when writing a prescription. (داروهای فهرست در نسخه قابل انتخاب هستند)")
    with st.form("catalog_add_drug", clear_on_submit=True):
        st.subheader("Add drug (افزودن دارو)")
        c1, c2, c3 = st.columns([2, 1, 1])
        drug_name = c1.text_input("Drug name - Latin (نام دارو (لاتین))", autocomplete="off")
        drug_form = c2.text_input("Drug form, e.g. Tablet (شکل دارویی)", autocomplete="off")
        prescribed_form = c3.text_input("Prescribed form (فرم تجویز)", autocomplete="off")
        default_dosage = st.text_input("Default dosage instructions (دستور مصرف پیش‌فرض)", autocomplete="off")
        notes = st.text_input("Notes (توضیحات)", autocomplete="off")
        if st.form_submit_button("➕ Add drug (افزودن)", type="primary"):
            try:
                with get_session() as s:
                    services.add_drug(s, drug_name, drug_form, prescribed_form, default_dosage, notes)
                flash(f"Drug '{drug_name.strip()}' added. (دارو اضافه شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with get_session() as s:
        drugs = services.list_drugs(s)
    if not drugs:
        st.info("No drugs yet. (هنوز دارویی ثبت نشده است)")
    else:
        DRUG_COLUMNS = ["name", "drug_form", "prescribed_form", "default_dosage", "notes", "active"]
        drugs_df = pd.DataFrame([{"id": d.id, **{c: getattr(d, c) for c in DRUG_COLUMNS}} for d in drugs]).set_index("id")
        edited_drugs = st.data_editor(
            drugs_df,
            width="stretch",
            hide_index=True,
            column_config={
                "name": st.column_config.TextColumn("Name (نام)", required=True, width="medium"),
                "drug_form": st.column_config.TextColumn("Form (شکل)"),
                "prescribed_form": st.column_config.TextColumn("Prescribed form (فرم تجویز)"),
                "default_dosage": st.column_config.TextColumn("Default dosage (دستور مصرف)", width="large"),
                "notes": st.column_config.TextColumn("Notes (توضیحات)"),
                "active": st.column_config.CheckboxColumn("Active (فعال)"),
            },
            key=editor_key("drugs_editor"),
        )
        drug_changes = changed_rows(drugs_df, edited_drugs, DRUG_COLUMNS)
        if drug_changes:
            st.warning(f"{len(drug_changes)} drug(s) changed but not saved yet. (تغییرات ذخیره نشده)")
        if st.button("💾 Save changes (ذخیره تغییرات)", disabled=not drug_changes, type="primary", key="drugs_save"):
            try:
                with get_session() as s:
                    for drug_id, diff in drug_changes.items():
                        if "active" in diff:
                            diff["active"] = bool(diff["active"])
                        services.update_drug(s, drug_id, **diff)
                bump("drugs_editor")
                flash(f"Saved {len(drug_changes)} change(s). (تغییرات ذخیره شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        with st.expander("🗑 Delete a drug (حذف دارو)"):
            drug_options = {d.id: d.name for d in drugs}
            drug_to_delete = st.selectbox("Drug", list(drug_options), format_func=drug_options.get, key="drug_delete_pick")
            st.caption("Only drugs never used in a prescription can be deleted; deactivate the others instead.")
            if st.button("Delete permanently (حذف دائمی)", key="drug_delete"):
                try:
                    with get_session() as s:
                        services.delete_drug(s, drug_to_delete)
                    flash("Drug deleted. (دارو حذف شد)")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

# ======================================================================
# Vaccines
# ======================================================================
with tab_vaccines:
    st.caption(
        "Each vaccine or preventive treatment has a repeat interval. The next due date is the last recorded dose "
        "plus this interval, and drives the Reminders page. "
        "(تاریخ نوبت بعدی = آخرین تزریق + فاصله تکرار)"
    )
    with st.form("catalog_add_vaccine", clear_on_submit=True):
        st.subheader("Add vaccine / treatment (افزودن واکسن)")
        c1, c2, c3 = st.columns([2, 1, 2])
        vaccine_name = c1.text_input("Name, e.g. Feline leukemia (نام)", autocomplete="off")
        interval = c2.number_input("Repeat every N days (فاصله تکرار - روز)", min_value=1, value=365, step=1)
        species = c3.text_input(
            "Only for animal types, comma-separated (فقط برای)", placeholder="e.g. cat, گربه — empty = all",
            autocomplete="off",
        )
        if st.form_submit_button("➕ Add (افزودن)", type="primary"):
            try:
                with get_session() as s:
                    vaccines.add_vaccine_type(s, vaccine_name, interval, species)
                flash(f"'{vaccine_name.strip()}' added. (اضافه شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with get_session() as s:
        vaccine_types = vaccines.list_vaccine_types(s)
    if vaccine_types:
        VT_COLUMNS = ["name", "interval_days", "species", "active", "sort_order"]
        vt_df = pd.DataFrame(
            [{"id": v.id, **{c: getattr(v, c) for c in VT_COLUMNS}} for v in vaccine_types]
        ).set_index("id")
        edited_vt = st.data_editor(
            vt_df,
            width="stretch",
            hide_index=True,
            column_config={
                "name": st.column_config.TextColumn("Name (نام)", required=True, width="medium"),
                "interval_days": st.column_config.NumberColumn(
                    "Every N days (فاصله - روز)", min_value=1, step=1, format="%d"
                ),
                "species": st.column_config.TextColumn("Only for (فقط برای)", help="Comma-separated; empty = all animals"),
                "active": st.column_config.CheckboxColumn("Active (فعال)"),
                "sort_order": st.column_config.NumberColumn("Order (ترتیب)", step=1, format="%d"),
            },
            key=editor_key("vaccines_editor"),
        )
        vt_changes = changed_rows(vt_df, edited_vt, VT_COLUMNS)
        if vt_changes:
            st.warning(f"{len(vt_changes)} row(s) changed but not saved yet. (تغییرات ذخیره نشده)")
        if st.button("💾 Save changes (ذخیره تغییرات)", disabled=not vt_changes, type="primary", key="vaccines_save"):
            try:
                with get_session() as s:
                    for type_id, diff in vt_changes.items():
                        for key in ("interval_days", "sort_order"):
                            if key in diff:
                                diff[key] = int(diff[key] or 0)
                        if "active" in diff:
                            diff["active"] = bool(diff["active"])
                        vaccines.update_vaccine_type(s, type_id, **diff)
                bump("vaccines_editor")
                flash(f"Saved {len(vt_changes)} change(s). (تغییرات ذخیره شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.caption(
        "Defaults: rabies and polyvalent every 365 days, deworming every 90 days. "
        "Uncheck 'Active' to stop reminders for a type."
    )
