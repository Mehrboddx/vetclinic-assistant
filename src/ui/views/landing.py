from datetime import date

import pandas as pd
import streamlit as st

from core import appointments, services, vaccines
from core.database import get_session
from core.jalali import to_jalali
from ui.components import VACCINE_STATUS, day_label, page_header, rial, section_title, setup_page

setup_page()

with get_session() as s:
    stats = services.dashboard_stats(s)
    todays = [
        {"time": a.start_at.strftime("%H:%M"), "who": appointments.display_name(a),
         "phone": appointments.display_phone(a), "reason": a.reason or "", "status": a.status}
        for a in appointments.list_appointments(s, date.today(), include_cancelled=False)
    ]
    due = vaccines.due_reminders(s, within_days=7, overdue_days=60)
    due_rows = [
        {"status": VACCINE_STATUS[r.status], "due": to_jalali(r.due_date), "vaccine": r.vaccine_type.name,
         "animal": r.patient.name, "owner": r.owner.full_name, "phone": r.owner.telephone,
         "contacted": "📞" if r.contact else ""}
        for r in due
    ]
    pending = [
        {"#": o.id, "admitted": to_jalali(o.date_admission), "client": o.owner.full_name,
         "tests": ", ".join(i.test_name for i in o.items), "response due": to_jalali(o.date_response)}
        for o in services.list_lab_orders(s, status="pending", limit=20)
    ]
    followups = [
        {"date": to_jalali(v.followup_date), "file": v.patient.file_number, "animal": v.patient.name,
         "owner": v.patient.owner.full_name, "phone": v.patient.owner.telephone}
        for v in services.upcoming_followups(s, days=7)
    ]
    test_count = len(services.list_tests(s, active_only=True))

page_header("Dashboard", "داشبورد", f"{day_label(date.today())} — به نرم‌افزار سوپر اختصاصیتون خوش آمدید.")

if test_count == 0:
    st.warning("Start by defining your tests on the Tests page. (ابتدا آزمایش‌ها را در صفحه آزمایش‌ها تعریف کنید)")
    st.page_link("views/tests.py", label="Go to Tests page (رفتن به صفحه آزمایش‌ها)", icon="🧪")

# ---------------------------------------------------------------- quick actions
QUICK_ACTIONS = [
    ("views/submit.py", "New admission (پذیرش جدید)", ":material/add_circle:"),
    ("views/appointments.py", "Book appointment (ثبت نوبت)", ":material/event:"),
    ("views/search.py", "Find a record (جستجوی پرونده)", ":material/search:"),
    ("views/reminders.py", "Call list (یادآوری‌ها)", ":material/call:"),
]
for col, (page, label, icon) in zip(st.columns(len(QUICK_ACTIONS)), QUICK_ACTIONS):
    if col.button(label, icon=icon, width="stretch", type="primary" if page.endswith("submit.py") else "secondary"):
        st.switch_page(page)

# ---------------------------------------------------------------- today's numbers
section_title("Today", "امروز")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Appointments (نوبت)", len([a for a in todays if a["status"] == "scheduled"]), border=True)
m2.metric("Admissions (پذیرش)", stats["lab_today"] + stats["visits_today"], border=True)
m3.metric("Revenue, rial (درآمد)", f"{int(stats['revenue_today'] or 0):,}", border=True,
          help=rial(stats["revenue_today"]))
m4.metric("Pending lab (جواب)", stats["pending_lab"], border=True,
          help="Lab orders still waiting for results (در انتظار جواب)")
m5.metric("Vaccines due (واکسن)", len(due), border=True,
          help="Overdue or due within 7 days (سررسید تا ۷ روز آینده)")


def panel(title: str, title_fa: str, rows: list, empty: str, link: tuple | None = None, drop=()) -> None:
    with st.container(border=True, height="stretch"):
        section_title(f"{title} · {len(rows)}" if rows else title, title_fa)
        if rows:
            st.dataframe(pd.DataFrame(rows).drop(columns=list(drop)), hide_index=True, width="stretch")
        else:
            st.caption(empty)
        if link:
            st.page_link(link[0], label=link[1], icon=":material/arrow_forward:")


c1, c2 = st.columns(2)
with c1:
    panel("Today's appointments", "نوبت‌های امروز", todays, "No appointments today. (نوبتی نیست)",
          ("views/appointments.py", "Open appointment book"), drop=("status",))
with c2:
    panel("Vaccines due", "واکسن‌های سررسید", due_rows, "Nothing overdue or due this week. (موردی نیست)",
          ("views/reminders.py", "All reminders & mark contacted"))

c3, c4 = st.columns(2)
with c3:
    panel("Pending lab orders", "در انتظار جواب", pending, "Nothing pending. (موردی نیست)",
          ("views/search.py", "Enter results in Records → Lab orders") if pending else None)
with c4:
    panel("Follow-ups, next 7 days", "مراجعات پیگیری", followups, "No follow-ups scheduled. (موردی نیست)")

st.caption(f"{stats['owners']} clients · {stats['patients']} animals · {test_count} active tests")

with st.expander("How to use this app (راهنما)", icon=":material/help:"):
    st.markdown(
        """
1. **Catalogs (فهرست‌ها)** — tests with fees and result templates, the drug list, and vaccines with their repeat intervals.
2. **Admission (پذیرش)** — admit a lab sample or a clinic patient. Record vaccines (or tick "given today"),
   weight, prescriptions from the drug list and attachments, and book the follow-up appointment.
3. **Appointments (نوبت‌دهی)** — the day's schedule, the week ahead, and booking.
4. **Reminders (یادآوری)** — which animals need a vaccine now; mark owners as contacted or copy a message.
5. **Records (سوابق)** — full history per client and animal, vaccine status, weight and vital charts,
   lab results with normal ranges, attachments.
6. **Reports (گزارش‌ها)** — revenue and activity for any period, with Excel export.
7. **Backup (پشتیبان)** — automatic daily backups, download a copy, restore.
"""
    )
