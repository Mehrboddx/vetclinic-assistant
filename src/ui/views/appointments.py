from datetime import date, datetime, time, timedelta

import jdatetime
import pandas as pd
import streamlit as st

from core import appointments, services
from core.database import get_session
from core.jalali import to_jalali
from core.models import APPOINTMENT_STATUSES
from ui.components import (
    client_lookup,
    day_label,
    fkey,
    flash,
    jalali_date_input,
    page_header,
    reset_form,
    section_title,
    setup_page,
    show_flash,
)

setup_page()

page_header("Appointments", "نوبت‌دهی", "Day schedule, the week ahead, and booking.")
show_flash()

STATUS_LABELS = {
    "scheduled": "🕒 Scheduled (نوبت)",
    "done": "✅ Done (انجام شد)",
    "cancelled": "✖ Cancelled (لغو)",
    "no_show": "⚠ No-show (نیامد)",
}
STATUS_TONES = {"scheduled": "teal", "done": "green", "cancelled": "gray", "no_show": "amber"}


def change_status(appointment_id: int, key: str) -> None:
    with get_session() as s:
        appointments.set_status(s, appointment_id, st.session_state[key])


# ---------------------------------------------------------------- day view
left, right = st.columns([3, 2], gap="large")

with left:
    day = jalali_date_input("Day (روز)", key="appt_day")
    with get_session() as s:
        day_appts = appointments.list_appointments(s, day)
        rows = [{
            "id": a.id, "time": a.start_at.strftime("%H:%M"),
            "end": (a.start_at + timedelta(minutes=a.duration_minutes)).strftime("%H:%M"),
            "who": appointments.display_name(a), "phone": appointments.display_phone(a),
            "reason": a.reason or "", "status": a.status,
        } for a in day_appts]
    active = sum(r["status"] == "scheduled" for r in rows)
    section_title(f"Schedule · {active} scheduled" if rows else "Schedule", day_label(day))

    if not rows:
        st.info("No appointments on this day. (نوبتی ثبت نشده است)")
    for row in rows:
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 3, 2], vertical_alignment="center")
            c1.markdown(f"#### {row['time']}")
            c1.caption(f"until {row['end']}")
            c2.markdown(f"**{row['who']}**  \n📞 {row['phone'] or '-'} · {row['reason'] or '-'}")
            key = f"appt_status_{row['id']}"
            c3.selectbox(
                "Status", APPOINTMENT_STATUSES, index=APPOINTMENT_STATUSES.index(row["status"]),
                format_func=STATUS_LABELS.get, key=key, label_visibility="collapsed",
                on_change=change_status, args=(row["id"], key),
            )
            with c3.popover("More (بیشتر)"):
                new_day = jalali_date_input("Move to (انتقال به)", key=f"appt_move_day_{row['id']}", default_value=day)
                new_time = st.time_input("Time (ساعت)", value=datetime.strptime(row["time"], "%H:%M").time(),
                                         step=900, key=f"appt_move_time_{row['id']}")
                if st.button("Reschedule (تغییر زمان)", key=f"appt_move_{row['id']}"):
                    with get_session() as s:
                        appointments.reschedule(s, row["id"], datetime.combine(new_day, new_time))
                    flash("Appointment moved. (نوبت جابجا شد)")
                    st.rerun()
                if st.button("🗑 Delete (حذف)", key=f"appt_del_{row['id']}"):
                    with get_session() as s:
                        appointments.delete_appointment(s, row["id"])
                    flash("Appointment deleted. (نوبت حذف شد)")
                    st.rerun()

    # ---------- week overview ----------
    st.divider()
    section_title("Next 7 days", "هفت روز آینده")
    today = date.today()
    with get_session() as s:
        week = appointments.list_appointments(s, today, today + timedelta(days=6), include_cancelled=False)
        week_rows = [{"date": a.start_at.date(), "time": a.start_at.strftime("%H:%M"),
                      "who": appointments.display_name(a), "status": a.status} for a in week]
    overview = []
    for offset in range(7):
        d = today + timedelta(days=offset)
        items = [r for r in week_rows if r["date"] == d]
        overview.append({
            "day": day_label(d),
            "appointments": len(items),
            "who": ", ".join(f"{r['time']} {r['who']}" for r in items),
        })
    st.dataframe(pd.DataFrame(overview), hide_index=True, width="stretch")

# ---------------------------------------------------------------- new appointment
with right:
    section_title("New appointment", "نوبت جدید")
    P = "appt"
    owner_id = client_lookup(P, {"full_name": "contact_name", "telephone": "contact_phone"},
                             clear_widgets=("patient_pick",))
    contact_name = st.text_input("Name (نام)", key=fkey(P, "contact_name"), disabled=bool(owner_id), autocomplete="off")
    contact_phone = st.text_input("Phone (تلفن)", key=fkey(P, "contact_phone"), disabled=bool(owner_id), autocomplete="off")
    patient_id = None
    if owner_id:
        with get_session() as s:
            animals = {p.id: f"{p.name or '-'} ({p.animal_type or '-'})" for p in services.get_owner(s, owner_id).patients}
        if animals:
            patient_id = st.selectbox(
                "Animal (حیوان)", [None, *animals], format_func=lambda i: "—" if i is None else animals[i],
                key=fkey(P, "patient_pick"),
            )
    appt_day = jalali_date_input("Date (تاریخ)", key=fkey(P, "date"), default_value=day)
    c1, c2 = st.columns(2)
    appt_time = c1.time_input("Time (ساعت)", value=time(10, 0), step=900, key=fkey(P, "time"))
    duration = c2.number_input("Minutes (مدت - دقیقه)", min_value=5, max_value=480, value=30, step=5,
                               key=fkey(P, "duration"))
    reason = st.text_input("Reason, e.g. vaccine, check-up (علت)", key=fkey(P, "reason"), autocomplete="off")

    start_at = datetime.combine(appt_day, appt_time)
    with get_session() as s:
        conflicts = [(a.start_at.strftime("%H:%M"), appointments.display_name(a))
                     for a in appointments.find_conflicts(s, start_at, duration)]
    if conflicts:
        st.warning("Overlaps with: " + "; ".join(f"{t} {who}" for t, who in conflicts) + " (تداخل نوبت)")
    if start_at < datetime.now():
        st.caption("⚠ This time is in the past. (این زمان گذشته است)")
    jdate = jdatetime.date.fromgregorian(date=appt_day)
    if st.button(f"📅 Book {jdate.strftime('%Y/%m/%d')} {appt_time.strftime('%H:%M')} (ثبت نوبت)", type="primary"):
        try:
            with get_session() as s:
                appointments.create_appointment(
                    s, start_at, duration, reason, owner_id=owner_id, patient_id=patient_id,
                    contact_name="" if owner_id else contact_name, contact_phone="" if owner_id else contact_phone,
                )
            reset_form(P)
            flash(f"Appointment booked for {to_jalali(start_at, with_time=True)}. (نوبت ثبت شد)")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
