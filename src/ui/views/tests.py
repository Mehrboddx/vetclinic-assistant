import pandas as pd
import streamlit as st

from core import services
from core.database import get_session
from core.models import LabTestDB
from core.sci import format_number
from ui.components import (
    bump, changed_rows, editor_key, flash, notation_help, page_header, setup_page, show_flash,
)

setup_page()

page_header("Tests", "آزمایش‌ها", "Define tests, their fees and result templates.")
show_flash()

st.caption(
    "Tests defined here are the ones you can select on the Admission page, for lab samples and as clinic cost items. "
    "(آزمایش‌های تعریف شده در اینجا هنگام پذیرش قابل انتخاب هستند)"
)
with get_session() as s:
    categories = services.list_test_categories(s)

with st.form("catalog_add_test", clear_on_submit=True):
    st.subheader("Add new test (افزودن آزمایش جدید)")
    c1, c2, c3 = st.columns([1, 3, 1])
    code = c1.text_input("Code (کد)", autocomplete="off")
    name = c2.text_input("Test name (نام آزمایش)", autocomplete="off")
    fee = c3.number_input("Fee, rial (هزینه)", min_value=0, step=1000)
    c4, c5 = st.columns([3, 2])
    category = c4.selectbox(
        "Category (گروه)", categories, index=None, accept_new_options=True,
        placeholder="Choose a category or type a new one (انتخاب گروه یا نوشتن گروه جدید)",
        help="Categories you have used before appear in this list. (گروه‌های قبلی در این فهرست هستند)",
    )
    turnaround = c5.number_input(
        "Days to result (مدت زمان جوابدهی - روز)", min_value=0, step=1, value=None, placeholder="e.g. 3",
        help="Used to fill the response date on admission: admission date + this many days. "
             "(تاریخ جوابدهی = تاریخ پذیرش + این تعداد روز)",
    )
    description = st.text_area("Description / notes (توضیحات)", height=68)
    if st.form_submit_button("➕ Add test (افزودن)", type="primary"):
        try:
            with get_session() as s:
                services.add_test(s, code, name, fee, category or "", description=description,
                                  turnaround_days=turnaround)
            flash(f"Test '{name.strip()}' added. (آزمایش اضافه شد)")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

st.subheader("All tests (همه آزمایش‌ها)")
with get_session() as s:
    tests = services.list_tests(s)
    param_counts = {t.id: len(t.parameters) for t in tests}

if not tests:
    st.info("No tests yet. Add your first test above. (هنوز آزمایشی تعریف نشده است)")
else:
    f1, f2 = st.columns([3, 1])
    search = f1.text_input("Filter (جستجو)", placeholder="code, name or category", autocomplete="off")
    show_inactive = f2.toggle("Show inactive (نمایش غیرفعال)", value=True)

    COLUMNS = ["code", "name", "category", "default_fee", "turnaround_days", "active", "description"]
    df = pd.DataFrame([{"id": t.id, **{c: getattr(t, c) for c in COLUMNS}} for t in tests]).set_index("id")
    df["turnaround_days"] = df["turnaround_days"].astype("Int64")
    df["template"] = [f"{param_counts[i]} fields" if param_counts[i] else "—" for i in df.index]
    if search.strip():
        needle = search.strip().lower()
        mask = df[["code", "name", "category"]].fillna("").apply(lambda col: col.str.lower().str.contains(needle))
        df = df[mask.any(axis=1)]
    if not show_inactive:
        df = df[df["active"]]

    edited = st.data_editor(
        df,
        width="stretch",
        hide_index=True,
        disabled=["template"],
        column_config={
            "code": st.column_config.TextColumn("Code (کد)", required=True),
            "name": st.column_config.TextColumn("Name (نام)", required=True, width="large"),
            "category": st.column_config.SelectboxColumn("Category (گروه)", options=categories),
            "default_fee": st.column_config.NumberColumn("Fee (هزینه)", min_value=0, step=1000, format="%d"),
            "turnaround_days": st.column_config.NumberColumn(
                "Days to result (روز جوابدهی)", min_value=0, step=1, format="%d"
            ),
            "active": st.column_config.CheckboxColumn("Active (فعال)"),
            "description": st.column_config.TextColumn("Notes (توضیحات)"),
            "template": st.column_config.TextColumn("Result template (قالب جواب)"),
        },
        key=editor_key("tests_editor", search.strip(), show_inactive),
    )
    changes = changed_rows(df, edited, COLUMNS)
    if changes:
        st.warning(f"{len(changes)} test(s) changed but not saved yet. (تغییرات ذخیره نشده)")
    if st.button("💾 Save changes (ذخیره تغییرات)", disabled=not changes, type="primary", key="tests_save"):
        try:
            with get_session() as s:
                for test_id, diff in changes.items():
                    if "default_fee" in diff:
                        diff["default_fee"] = int(diff["default_fee"] or 0)
                    if "active" in diff:
                        diff["active"] = bool(diff["active"])
                    services.update_test(s, test_id, **diff)
            bump("tests_editor")
            flash(f"Saved {len(changes)} change(s). (تغییرات ذخیره شد)")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    st.caption(
        "Changing a fee only affects new admissions. Uncheck 'Active' to hide a test from admission forms. "
        "(تغییر هزینه فقط روی پذیرش‌های جدید اثر دارد)"
    )

    # ---------- Result template ----------
    st.divider()
    st.subheader("Result template (قالب جواب آزمایش)")
    st.caption(
        "Define the fields measured by a test, with units, permitted limits and the reference standard the "
        "test follows. Values outside the limits are flagged H / L when results are entered. "
        "(پارامترها، واحد، حد مجاز و استاندارد مرجع هر آزمایش)"
    )
    options = {t.id: f"{t.code} — {t.name}" for t in tests}
    template_test = st.selectbox("Test (آزمایش)", list(options), format_func=options.get, key="template_test")
    with get_session() as s:
        params_df = pd.DataFrame(
            [{"id": p.id, "name": p.name, "unit": p.unit,
              "ref_low": format_number(p.ref_low), "ref_high": format_number(p.ref_high), "standard": p.standard}
             for p in s.get(LabTestDB, template_test).parameters],
            columns=["id", "name", "unit", "ref_low", "ref_high", "standard"],
        ).astype({"id": "Int64", "name": "object", "unit": "object", "ref_low": "object", "ref_high": "object",
                  "standard": "object"})
    edited_params = st.data_editor(
        params_df,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "id": None,
            "name": st.column_config.TextColumn("Parameter (پارامتر)", required=True),
            "unit": st.column_config.TextColumn("Unit (واحد)"),
            "ref_low": st.column_config.TextColumn("Limit from (حد پایین)", help="e.g. 6, 0.5 or 1x10^5. "
                                                   "Leave empty when there is only a maximum."),
            "ref_high": st.column_config.TextColumn("Limit to (حد بالا)", help="e.g. 17, 2.5 or 5x10^6. "
                                                    "Leave empty when there is only a minimum."),
            "standard": st.column_config.TextColumn("Reference standard (استاندارد مرجع)", width="medium",
                                                    help="The standard this test follows, e.g. ISO 6579-1 "
                                                         "or استاندارد ملی ۲۹۴۶"),
        },
        key=editor_key("params_editor", template_test),
    )
    st.caption("Add rows at the bottom of the table; select a row and press Delete to remove it.")
    notation_help()
    if st.button("💾 Save template (ذخیره قالب)", key="params_save"):
        rows = [{k: None if pd.isna(v) else v for k, v in r.items()} for r in edited_params.to_dict("records")]
        try:
            with get_session() as s:
                services.set_test_parameters(s, template_test, rows)
            bump("params_editor")
            flash("Result template saved. (قالب جواب ذخیره شد)")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    with st.expander("🗑 Delete a test (حذف آزمایش)"):
        to_delete = st.selectbox("Test", list(options), format_func=options.get, key="test_delete_pick")
        st.caption("Only tests never used in an admission can be deleted; deactivate the others instead.")
        if st.button("Delete permanently (حذف دائمی)", key="test_delete"):
            try:
                with get_session() as s:
                    services.delete_test(s, to_delete)
                flash("Test deleted. (آزمایش حذف شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
