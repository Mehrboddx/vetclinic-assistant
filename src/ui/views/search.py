import re
import time
from datetime import date

import pandas as pd
import streamlit as st

from core import services, vaccines
from core.database import get_session
from core.jalali import to_jalali
from core.models import OwnerDB, PatientDB
from core.pdf import find_browser, html_to_pdf
from core.receipts import clinic_visit_html, lab_order_html, lab_results_html
from ui.charts import trend_chart
from ui.components import (
    notation_help,
    STATUS_OPTIONS,
    VACCINE_STATUS,
    add_attachments_form,
    attachments_view,
    chart_ring,
    flash,
    jalali_date_input,
    page_header,
    rial,
    setup_page,
    show_flash,
)

setup_page()

page_header("Records", "سوابق و جستجو", "Clients, animals, lab orders and clinic visits.")
show_flash()

FLAG_LABELS = {"H": "▲ High (بالا)", "L": "▼ Low (پایین)", "": ""}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")


def to_number(text) -> float | None:
    """First number in a free-text field; understands Persian digits ('۴٫۵ kg' -> 4.5)."""
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(text or "").translate(_DIGITS))
    return float(match.group().replace(",", ".")) if match else None


def selected_row(df: pd.DataFrame, key: str):
    """Show a single-select table and return the selected row's `id` (or None)."""
    event = st.dataframe(
        df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=key,
        column_config={"id": st.column_config.NumberColumn("#", format="%d")},
    )
    rows = [r for r in (event.selection.rows if event else []) if r < len(df)]
    return int(df.iloc[rows[0]]["id"]) if rows else None


def confirm_delete(key: str, label: str) -> bool:
    with st.popover(f"🗑 Delete {label} (حذف)"):
        sure = st.checkbox("I am sure — this cannot be undone (مطمئن هستم)", key=key + "_sure")
        return st.button("Delete permanently (حذف دائمی)", key=key + "_btn", disabled=not sure)


# ---------------------------------------------------------------- lab order detail

def print_now(html: str) -> None:
    """Open the browser's print dialog for `html` (printed from a hidden frame, so only the report prints)."""
    script = (
        f"<script>/* {time.time_ns()} */"  # a new value each time, so the frame reloads and prints again
        "window.addEventListener('load', () => setTimeout(() => window.print(), 300));</script>"
    )
    st.iframe(html.replace("</body>", script + "</body>"), height=1)


def lab_order_detail(order_id: int, key: str) -> None:
    with get_session() as s:
        services.ensure_result_values(s, order_id)
    with get_session() as s:
        order = services.get_lab_order(s, order_id)
        if order is None:
            st.warning("This lab order no longer exists.")
            return
        html = lab_order_html(order)
        results_html = lab_results_html(order, print_button=False)
    if st.session_state.get("print_order") == order_id:  # set by "Save & print"
        st.session_state.pop("print_order")
        print_now(results_html)

    st.markdown(f"### Lab order #{order.id} — {order.owner.full_name}")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"**Phone:** {order.owner.telephone or '-'}")
    c2.markdown(f"**Sample:** {order.sample_type or '-'} × {order.sample_qty or '-'}")
    c3.markdown(f"**Admitted:** {to_jalali(order.date_admission)}")
    c4.markdown(f"**Sampled:** {to_jalali(order.date_sampling) or '-'}")
    if order.patient:
        st.markdown(f"**Animal:** {order.patient.name or '-'} (file {order.patient.file_number})")
    if order.other:
        st.markdown(f"**Other:** {order.other}")

    items = pd.DataFrame([
        {"id": i.id, "code": i.code, "test": i.test_name, "fee": i.fee, "qty": i.quantity,
         "price": i.price, "result": i.result or ""}
        for i in order.items
    ])
    edited = st.data_editor(
        items,
        hide_index=True,
        width="stretch",
        disabled=["id", "code", "test", "fee", "qty", "price"],
        column_config={
            "id": None,
            "code": "کد", "test": "آزمایش", "fee": "هزینه", "qty": "تعداد", "price": "مبلغ",
            "result": st.column_config.TextColumn("Result / comment (نتیجه / توضیح)", width="large"),
        },
        key=f"{key}_items",
    )

    notation_help()

    value_edits, standard_edits = {}, {}
    for item in order.items:
        if not item.values:
            continue
        st.markdown(f"**{item.test_name}** — result values (مقادیر)")
        values_df = pd.DataFrame([{
            "id": v.id, "parameter": v.name, "value": v.value or "", "unit": v.unit or "",
            "limit": v.reference, "flag": FLAG_LABELS[v.flag], "standard": v.standard or "",
        } for v in item.values])
        edited_values = st.data_editor(
            values_df,
            hide_index=True,
            width="stretch",
            disabled=["id", "parameter", "unit", "limit", "flag"],
            column_config={
                "id": None,
                "parameter": "Parameter (پارامتر)",
                "value": st.column_config.TextColumn("Value (مقدار)", width="medium"),
                "unit": "Unit (واحد)",
                "limit": "Permitted limit (حد مجاز)",
                "flag": "Flag (H / L)",
                "standard": st.column_config.TextColumn(
                    "Reference standard (استاندارد مرجع)", width="medium",
                    help="Filled from the test's template; change it here for this admission only."),
            },
            key=f"{key}_values_{item.id}",
        )
        value_edits.update({int(r["id"]): r["value"] for _, r in edited_values.iterrows()})
        standard_edits.update({int(r["id"]): r["standard"] for _, r in edited_values.iterrows()})
    if any(i.values for i in order.items):
        st.caption("Flags update after saving; they are shown here only, not on the printed results. "
                   "(علامت H / L بعد از ذخیره به‌روز می‌شود و فقط اینجا نمایش داده می‌شود)")

    st.markdown(f"**Total (جمع کل): {rial(order.total)}**")

    c1, c2 = st.columns(2)
    status = c1.selectbox(
        "Status (وضعیت)", list(STATUS_OPTIONS), format_func=STATUS_OPTIONS.get,
        index=list(STATUS_OPTIONS).index(order.status), key=f"{key}_status",
    )
    with c2:
        date_response = jalali_date_input(
            "Date of Response (تاریخ جوابدهی)", key=f"{key}_response",
            default_value=order.date_response, optional=order.date_response is None,
        )

    b1, b2 = st.columns(2)
    save = b1.button("💾 Save results (ذخیره نتایج)", key=f"{key}_save", type="primary", width="stretch")
    save_print = b2.button("💾🖨 Save & print results (ذخیره و چاپ جواب)", key=f"{key}_save_print",
                           type="primary", width="stretch")
    if save or save_print:
        results = {int(r["id"]): r["result"] for _, r in edited.iterrows()}
        with get_session() as s:
            services.update_lab_results(s, order_id, results, status=status, date_response=date_response,
                                        values=value_edits, standards=standard_edits)
        st.session_state.pop(f"results_pdf_{order_id}", None)  # results changed: an old PDF is out of date
        if save_print:
            st.session_state["print_order"] = order_id
        flash(f"Lab order #{order_id} updated. (نتایج ذخیره شد)")
        st.rerun()

    p1, p2, p3, p4 = st.columns(4)
    if p1.button("🖨 Print results (چاپ جواب)", key=f"{key}_print", width="stretch",
                 help="Prints the saved results. To include changes you just made, use 'Save & print'. "
                      "(جواب ذخیره‌شده چاپ می‌شود)"):
        print_now(results_html)
    with p2:
        pdf_key = f"results_pdf_{order_id}"
        has_browser = find_browser() is not None
        if st.button("📄 Results PDF (فایل PDF جواب)", key=f"{key}_pdf", width="stretch", disabled=not has_browser,
                     help="Makes a PDF of the saved results. (ساخت فایل PDF از جواب ذخیره‌شده)" if has_browser else
                          "Microsoft Edge or Google Chrome is needed to make PDFs. (برای PDF مرورگر Edge یا Chrome لازم است)"):
            try:
                with st.spinner("Making the PDF… (در حال ساخت PDF)"):
                    st.session_state[pdf_key] = html_to_pdf(results_html)
            except RuntimeError as exc:
                st.error(str(exc))
        if st.session_state.get(pdf_key):
            st.download_button("⬇️ Download PDF (دانلود PDF)", st.session_state[pdf_key],
                               file_name=f"lab_results_{order_id}.pdf", mime="application/pdf",
                               key=f"{key}_pdf_download", width="stretch", type="primary")
    p3.download_button("🧾 Admission sheet (برگه پذیرش)", html, file_name=f"lab_order_{order_id}.html",
                       mime="text/html", key=f"{key}_receipt", width="stretch")
    with p4:
        if confirm_delete(f"{key}_delete", f"lab order #{order_id}"):
            with get_session() as s:
                services.delete_lab_order(s, order_id)
            flash(f"Lab order #{order_id} deleted.")
            st.rerun()

    st.markdown(f"**📎 Attachments (پیوست‌ها): {len(order.attachments)}**")
    attachments_view(order.attachments, f"{key}_att")
    add_attachments_form(f"{key}_att_form", lab_order_id=order_id)


# ---------------------------------------------------------------- visit detail

def visit_detail(visit_id: int, key: str) -> None:
    with get_session() as s:
        visit = services.get_clinic_visit(s, visit_id)
        if visit is None:
            st.warning("This visit no longer exists.")
            return
        html = clinic_visit_html(visit)
    patient, owner = visit.patient, visit.patient.owner

    st.markdown(
        f"### Visit {to_jalali(visit.visit_date)} — {patient.name or '-'} (file {patient.file_number})"
    )
    st.caption(f"Owner: {owner.full_name} — {owner.telephone or '-'}")

    vitals = visit.vitals or {}
    st.markdown(
        " | ".join(f"**{k}:** {vitals.get(k) or '-'}" for k in ("T", "HR", "PR", "RR"))
        + f" | **Weight (وزن):** {visit.weight or '-'}"
    )

    def block(title: str, text) -> None:
        if text:
            st.markdown(f"**{title}**")
            st.text(text)

    block("Reason for visit (علت مراجعه)", visit.reason_for_visit)
    block("History (شرح حال)", visit.history_narrative)
    block("Previous medications (داروهای قبلی)", visit.previous_medications)
    block("Diet (رژیم غذایی)", visit.diet_info)
    if visit.vaccinations:
        st.markdown("**Vaccinations recorded (واکسن‌ها):** " + ", ".join(
            f"{v.vaccine_type.name} {to_jalali(v.date)}" + (" 💉" if v.administered else "")
            for v in visit.vaccinations
        ))
    st.markdown(f"**Vaccination status (وضعیت واکسیناسیون):** {visit.vaccination_status or '-'}")
    with st.expander("Clinical exam & paraclinic (معاینات و پاراکلینیک)"):
        for field, text in (visit.exam or {}).items():
            block(field.replace("_", " ").title(), text)
        para = visit.paraclinic or {}
        if para.get("blood_normal") or para.get("blood_abnormal"):
            st.markdown(f"**Blood:** {'normal' if para.get('blood_normal') else 'abnormal'}")
        for field in ("blood_summary", "radiology_summary", "mycology_summary", "necropsy_summary", "surgery_referral"):
            block(field.replace("_", " ").title(), para.get(field))
    block("Diagnosis (تشخیص)", visit.diagnosis)
    if visit.followup_date:
        st.markdown(f"**Next follow-up (مراجعه بعدی):** {to_jalali(visit.followup_date)}")

    if visit.medications:
        st.markdown("**Prescription (نسخه)**")
        st.dataframe(pd.DataFrame([{
            "نام دارو": m.drug_name, "دستور مصرف": m.dosage_instructions, "فرم تجویز": m.prescribed_form,
            "تعداد": m.quantity, "شکل دارویی": m.drug_form,
        } for m in visit.medications]), hide_index=True, width="stretch")
    if visit.costs:
        st.markdown("**Costs (هزینه‌ها)**")
        st.dataframe(pd.DataFrame([{
            "شرح خدمات": c.description, "تعرفه": c.tariff, "تعداد": c.quantity, "جمع": c.total,
        } for c in visit.costs]), hide_index=True, width="stretch")
    st.markdown(f"**Total (جمع کل): {rial(visit.total_cost)}**")

    b1, b2 = st.columns(2)
    b1.download_button("🖨 Receipt / record (رسید)", html, file_name=f"visit_{visit_id}.html",
                       mime="text/html", key=f"{key}_receipt")
    with b2:
        if confirm_delete(f"{key}_delete", "this visit"):
            with get_session() as s:
                services.delete_clinic_visit(s, visit_id)
            flash("Visit deleted.")
            st.rerun()

    st.markdown(f"**📎 Attachments (پیوست‌ها): {len(visit.attachments)}**")
    attachments_view(visit.attachments, f"{key}_att")
    add_attachments_form(f"{key}_att_form", visit_id=visit_id)


# ---------------------------------------------------------------- tables

def lab_orders_table(orders, key: str):
    if not orders:
        st.info("No lab orders. (موردی یافت نشد)")
        return None
    df = pd.DataFrame([{
        "id": o.id,
        "admitted": to_jalali(o.date_admission),
        "client": o.owner.full_name,
        "phone": o.owner.telephone,
        "tests": ", ".join(i.test_name for i in o.items),
        "total": o.total,
        "status": STATUS_OPTIONS.get(o.status, o.status),
        "response": to_jalali(o.date_response),
    } for o in orders])
    return selected_row(df, key)


def visits_table(visits, key: str):
    if not visits:
        st.info("No visits. (موردی یافت نشد)")
        return None
    df = pd.DataFrame([{
        "id": v.id,
        "date": to_jalali(v.visit_date),
        "file": v.patient.file_number,
        "animal": v.patient.name,
        "owner": v.patient.owner.full_name,
        "diagnosis": (v.diagnosis or "")[:60],
        "total": v.total_cost,
        "follow-up": to_jalali(v.followup_date),
    } for v in visits])
    return selected_row(df, key)


# ---------------------------------------------------------------- patient panel

def patient_vaccines(patient_id: int) -> None:
    with get_session() as s:
        patient = s.get(PatientDB, patient_id)
        statuses = vaccines.patient_vaccine_status(s, patient)
        types = vaccines.list_vaccine_types(s, active_only=True)
        history = [(v.id, v.vaccine_type.name, v.date, v.administered) for v in patient.vaccinations]

    if statuses:
        st.dataframe(pd.DataFrame([{
            "vaccine": x.vaccine_type.name,
            "last dose": to_jalali(x.last_date),
            "next due": to_jalali(x.due_date),
            "status": VACCINE_STATUS[x.status],
        } for x in statuses]), hide_index=True, width="stretch")

    with st.form(f"vacc_form_{patient_id}", clear_on_submit=True):
        st.markdown("**Record a vaccination (ثبت واکسن)**")
        c1, c2, c3 = st.columns([2, 2, 1])
        type_names = {t.id: t.name for t in types}
        vaccine_type_id = c1.selectbox("Vaccine (واکسن)", list(type_names), format_func=type_names.get)
        with c2:
            when = jalali_date_input("Date (تاریخ)", key=f"vacc_date_{patient_id}", default_value=date.today())
        administered = c3.checkbox("Given in clinic (در کلینیک)", value=True)
        if st.form_submit_button("💉 Save (ثبت)") and vaccine_type_id:
            try:
                with get_session() as s:
                    vaccines.record_vaccination(s, patient_id, vaccine_type_id, when, administered=administered)
                flash("Vaccination recorded. (واکسن ثبت شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if history:
        with st.popover(f"History ({len(history)}) (سابقه)"):
            for vid, name, when, given in history:
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"{to_jalali(when)} — {name}" + (" 💉 in clinic" if given else " (reported)"))
                if c2.button("🗑", key=f"vacc_del_{vid}", help="Delete this entry"):
                    with get_session() as s:
                        vaccines.delete_vaccination(s, vid)
                    flash("Vaccination entry deleted.")
                    st.rerun()


def patient_charts(visits) -> None:
    rows = []
    for v in sorted(visits, key=lambda v: (v.visit_date or date.min, v.id)):
        vitals = v.vitals or {}
        rows.append({
            "date": pd.Timestamp(v.visit_date), "jalali": to_jalali(v.visit_date),
            "weight": to_number(v.weight),
            **{k: to_number(vitals.get(k)) for k in ("T", "HR", "PR", "RR")},
        })
    df = pd.DataFrame(rows)
    series = {
        "weight": ("Weight (وزن)", "kg"), "T": ("Temperature (دما)", "°C"), "HR": ("Heart rate (ضربان قلب)", "/min"),
        "PR": ("Pulse rate (نبض)", "/min"), "RR": ("Respiratory rate (تنفس)", "/min"),
    }
    available = [k for k in series if not df.empty and df[k].notna().sum() >= 2]
    if not available:
        st.caption("Charts appear once two or more visits have weight or vital signs recorded. "
                   "(نمودار پس از ثبت حداقل دو ویزیت نمایش داده می‌شود)")
        return
    ring = chart_ring()
    columns = st.columns(2)
    for n, k in enumerate(available):
        title, unit = series[k]
        with columns[n % 2]:
            st.markdown(f"**{title}**")
            st.altair_chart(trend_chart(df.dropna(subset=[k]), k, title, unit, height=180, ring=ring), width="stretch")


def patient_panel(patient: PatientDB, owner_id: int) -> None:
    if not patient.active:
        st.warning("Inactive — not included in reminders. (غیرفعال)")
    with st.expander("✏️ Edit animal details (ویرایش مشخصات)"):
        with st.form(f"edit_patient_{patient.id}"):
            p1, p2, p3 = st.columns(3)
            pdata = {
                "name": p1.text_input("Name (نام)", patient.name or "", autocomplete="off"),
                "animal_type": p2.text_input("Type (نوع)", patient.animal_type or "", autocomplete="off"),
                "breed": p3.text_input("Breed (نژاد)", patient.breed or "", autocomplete="off"),
                "gender": p1.text_input("Gender (جنسیت)", patient.gender or "", autocomplete="off"),
                "sterilized": p2.text_input("Sterilization (عقیم سازی)", patient.sterilized or "", autocomplete="off"),
                "keeping_location": p3.text_input("Keeping location (محل نگهداری)", patient.keeping_location or "", autocomplete="off"),
                "microchip": p1.text_input("Microchip (میکروچیپ)", patient.microchip or "", autocomplete="off"),
                "age": p2.text_input("Age (سن)", patient.age or "", autocomplete="off"),
                "weight": p3.text_input("Weight, kg (وزن)", patient.weight or "", autocomplete="off"),
                "file_number": p1.text_input("File number (شماره پرونده)", patient.file_number or "", autocomplete="off"),
            }
            pdata["active"] = p2.checkbox(
                "Active — uncheck if deceased or moved away (فعال)", value=bool(patient.active)
            )
            if st.form_submit_button("Save animal (ذخیره)"):
                try:
                    with get_session() as s:
                        services.save_patient(s, s.get(OwnerDB, owner_id), pdata, patient.id)
                    flash("Animal updated. (ذخیره شد)")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    vacc_col, chart_col = st.columns([1, 1], gap="large")
    with vacc_col:
        st.markdown("##### 💉 Vaccines (واکسن‌ها)")
        patient_vaccines(patient.id)
    with chart_col:
        st.markdown("##### 📈 Weight & vital signs (وزن و علائم حیاتی)")
        patient_charts(patient.visits)

    st.markdown("##### Visits (مراجعات)")
    visit_id = visits_table(patient.visits, f"visits_{patient.id}")
    if visit_id:
        visit_detail(visit_id, f"pv_{visit_id}")


# ---------------------------------------------------------------- tabs

tab_clients, tab_lab, tab_clinic = st.tabs(
    ["Clients (مشتریان)", "Lab orders (آزمایشگاه)", "Clinic visits (مطب)"], key="records_tab"  # stays put after a save
)

with tab_clients:
    query = st.text_input(
        "Search by name, phone, animal name, file number or microchip "
        "(جستجو با نام، تلفن، نام حیوان، شماره پرونده یا میکروچیپ)",
        key="search_query",
        autocomplete="off",
    )
    with get_session() as s:
        owners = services.search_owners(s, query)
        owner_rows = [{
            "id": o.id, "name": o.full_name, "phone": o.telephone, "address": o.address,
            "animals": ", ".join(p.name or "-" for p in o.patients), "lab orders": len(o.lab_orders),
        } for o in owners]

    if not owner_rows:
        st.info("No clients found. (مشتری یافت نشد)")
        owner_id = None
    else:
        if not query.strip():
            st.caption("Most recent clients (آخرین مشتریان)")
        owner_id = selected_row(pd.DataFrame(owner_rows), "owners_table")

    if owner_id:
        with get_session() as s:
            owner = services.get_owner(s, owner_id)
        st.divider()
        st.subheader(f"{owner.full_name} — {owner.telephone or '-'}")

        with st.expander("✏️ Edit client details (ویرایش مشخصات)"):
            with st.form(f"edit_owner_{owner_id}"):
                c1, c2 = st.columns(2)
                data = {
                    "name": c1.text_input("Name (نام)", owner.name, autocomplete="off"),
                    "surname": c2.text_input("Surname (نام خانوادگی)", owner.surname, autocomplete="off"),
                    "telephone": c1.text_input("Telephone (تلفن)", owner.telephone or "", autocomplete="off"),
                    "address": c2.text_input("Address (آدرس)", owner.address or "", autocomplete="off"),
                }
                if st.form_submit_button("Save (ذخیره)"):
                    try:
                        with get_session() as s:
                            services.save_owner(s, data, owner_id)
                        flash("Client updated. (مشخصات ذخیره شد)")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

        st.markdown("#### Animals (حیوانات)")
        if not owner.patients:
            st.caption("No animals registered. (حیوانی ثبت نشده است)")
        else:
            labels = [
                f"🐾 {p.name or '-'} · {p.file_number}" + ("" if p.active else " (inactive)") for p in owner.patients
            ]
            for tab, patient in zip(st.tabs(labels), owner.patients):
                with tab:
                    patient_panel(patient, owner_id)

        st.markdown("#### Lab orders (آزمایش‌ها)")
        order_id = lab_orders_table(
            sorted(owner.lab_orders, key=lambda o: o.created_at, reverse=True), f"owner_orders_{owner_id}"
        )
        if order_id:
            lab_order_detail(order_id, f"ol_{order_id}")

with tab_lab:
    st.caption("Work queue: pick an order to enter results. (برای ثبت نتیجه یک مورد را انتخاب کنید)")
    f1, f2, f3 = st.columns(3)
    status_filter = f1.selectbox(
        "Status (وضعیت)", [None, *STATUS_OPTIONS],
        format_func=lambda v: "All (همه)" if v is None else STATUS_OPTIONS[v], index=1, key="lab_status_filter",
    )
    with f2:
        lab_from = jalali_date_input("From (از تاریخ)", key="lab_from", optional=True)
    with f3:
        lab_to = jalali_date_input("To (تا تاریخ)", key="lab_to", optional=True)
    with get_session() as s:
        orders = services.list_lab_orders(s, start=lab_from, end=lab_to, status=status_filter)
    if orders:
        st.caption(f"{len(orders)} order(s), total {rial(sum(o.total for o in orders))}")
    order_id = lab_orders_table(orders, "lab_queue")
    if order_id:
        st.divider()
        lab_order_detail(order_id, f"q_{order_id}")

with tab_clinic:
    f1, f2 = st.columns(2)
    with f1:
        visit_from = jalali_date_input("From (از تاریخ)", key="visit_from", optional=True)
    with f2:
        visit_to = jalali_date_input("To (تا تاریخ)", key="visit_to", optional=True)
    with get_session() as s:
        visits = services.list_clinic_visits(s, start=visit_from, end=visit_to)
    if visits:
        st.caption(f"{len(visits)} visit(s), total {rial(sum(v.total_cost for v in visits))}")
    visit_id = visits_table(visits, "visits_all")
    if visit_id:
        st.divider()
        visit_detail(visit_id, f"v_{visit_id}")
