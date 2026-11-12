from datetime import date

import pandas as pd
import streamlit as st

from core import vaccines
from core.database import get_session
from core.jalali import to_jalali
from core.receipts import CLINIC_NAME
from ui.components import VACCINE_STATUS, flash, jalali_date_input, page_header, setup_page, show_flash

setup_page()

page_header("Vaccine reminders", "یادآوری واکسن", "Animals whose vaccine or deworming is overdue or due soon.")
st.caption(
    "Animals whose next vaccine or deworming is overdue or coming up, based on the last recorded dose and the "
    "intervals on the Catalogs page. (بر اساس آخرین تزریق ثبت شده و فاصله تکرار)"
)
show_flash()

WINDOWS = {7: "Next 7 days (۷ روز)", 14: "Next 14 days (۱۴ روز)", 30: "Next 30 days (۳۰ روز)", 60: "Next 60 days (۶۰ روز)"}
f1, f2, f3 = st.columns([1, 1, 2])
within = f1.selectbox("Due within (تا)", list(WINDOWS), index=2, format_func=WINDOWS.get)
show_contacted = f2.toggle("Show already contacted (نمایش تماس گرفته شده)", value=True)
search = f3.text_input("Search owner / animal / phone (جستجو)", autocomplete="off")

with get_session() as s:
    reminders = vaccines.due_reminders(s, within_days=within, overdue_days=365)
    type_names = sorted({r.vaccine_type.name for r in reminders})

type_filter = st.multiselect("Vaccines (واکسن‌ها)", type_names, default=type_names) if type_names else []

if search.strip():
    needle = search.strip().lower()
    reminders = [
        r for r in reminders
        if needle in f"{r.owner.full_name} {r.patient.name or ''} {r.owner.telephone or ''} {r.patient.file_number}".lower()
    ]
reminders = [r for r in reminders if r.vaccine_type.name in type_filter]

overdue = sum(r.status == "overdue" for r in reminders)
this_week = sum(0 <= r.days_left <= 7 for r in reminders)
contacted = sum(r.contact is not None for r in reminders)
m1, m2, m3 = st.columns(3)
m1.metric("🔴 Overdue (گذشته)", overdue)
m2.metric("🟠 Due in 7 days (۷ روز آینده)", this_week)
m3.metric("📞 Contacted (تماس گرفته شده)", contacted)

if not show_contacted:
    reminders = [r for r in reminders if r.contact is None]

if not reminders:
    st.success("No vaccines due in this window. (موردی نیست)")
    st.stop()


def days_text(days: int) -> str:
    if days < 0:
        return f"{-days} days overdue ({-days} روز گذشته)"
    if days == 0:
        return "today (امروز)"
    return f"in {days} days ({days} روز دیگر)"


df = pd.DataFrame([{
    "status": VACCINE_STATUS[r.status],
    "due": to_jalali(r.due_date),
    "when": days_text(r.days_left),
    "vaccine": r.vaccine_type.name,
    "animal": f"{r.patient.name or '-'} ({r.patient.animal_type or '-'})",
    "file": r.patient.file_number,
    "owner": r.owner.full_name,
    "phone": r.owner.telephone or "",
    "last dose": to_jalali(r.last_date),
    "contacted": (f"📞 {to_jalali(r.contact.contacted_at)}" + (f" — {r.contact.note}" if r.contact.note else ""))
    if r.contact else "",
} for r in reminders])

st.caption("Select rows to mark them as contacted, record the vaccine, or prepare a message. (ردیف‌ها را انتخاب کنید)")
event = st.dataframe(
    df, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key="reminders_table",
)
selected = [reminders[i] for i in (event.selection.rows if event else []) if i < len(reminders)]

st.download_button(
    "⬇ Download call list (CSV) (دریافت لیست تماس)",
    df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"vaccine_reminders_{date.today().isoformat()}.csv",
    mime="text/csv",
)

if selected:
    st.divider()
    st.subheader(f"{len(selected)} selected (انتخاب شده)")
    tab_contact, tab_given, tab_message = st.tabs(
        ["📞 Mark contacted (ثبت تماس)", "💉 Record vaccination (ثبت تزریق)", "✉️ Message text (متن پیام)"]
    )
    with tab_contact:
        note = st.text_input("Note, e.g. 'will come Saturday' (یادداشت)", key="contact_note", autocomplete="off")
        c1, c2 = st.columns(2)
        if c1.button("📞 Mark as contacted (تماس گرفته شد)", type="primary"):
            with get_session() as s:
                for r in selected:
                    vaccines.mark_contacted(s, r.patient.id, r.vaccine_type.id, r.due_date, note)
            st.session_state.pop("reminders_table", None)
            flash(f"{len(selected)} reminder(s) marked as contacted. (ثبت شد)")
            st.rerun()
        if c2.button("↩ Undo contacted (لغو تماس)"):
            with get_session() as s:
                for r in selected:
                    vaccines.unmark_contacted(s, r.patient.id, r.vaccine_type.id, r.due_date)
            st.session_state.pop("reminders_table", None)
            flash("Contact marks removed. (لغو شد)")
            st.rerun()
    with tab_given:
        given_on = jalali_date_input("Date given (تاریخ تزریق)", key="given_on", default_value=date.today())
        st.caption("Records the selected vaccines as given in the clinic on this date; the next due date moves forward.")
        if st.button("💉 Record as given (ثبت تزریق)", type="primary"):
            try:
                with get_session() as s:
                    for r in selected:
                        vaccines.record_vaccination(s, r.patient.id, r.vaccine_type.id, given_on, administered=True)
                st.session_state.pop("reminders_table", None)
                flash(f"{len(selected)} vaccination(s) recorded. (تزریق ثبت شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with tab_message:
        st.caption("Copy a message to send by SMS or WhatsApp. (متن را کپی کنید)")
        for r in selected:
            when = "گذشته است" if r.days_left < 0 else f"در تاریخ {to_jalali(r.due_date)} است"
            text = (
                f"{r.owner.full_name} عزیز، زمان {r.vaccine_type.name} برای {r.patient.name or 'حیوان شما'} "
                f"{when}. لطفا برای دریافت نوبت با {CLINIC_NAME} تماس بگیرید."
            )
            st.markdown(f"**{r.owner.full_name}** — {r.owner.telephone or '-'}")
            st.code(text, language=None, wrap_lines=True)
