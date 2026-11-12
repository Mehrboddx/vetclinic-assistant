"""Appointment book."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core.models import APPOINTMENT_STATUSES, AppointmentDB, OwnerDB, PatientDB


def create_appointment(
    session: Session,
    start_at: datetime,
    duration_minutes: int = 30,
    reason: str = "",
    owner_id: int | None = None,
    patient_id: int | None = None,
    contact_name: str = "",
    contact_phone: str = "",
) -> AppointmentDB:
    if start_at is None:
        raise ValueError("Appointment date and time are required. (تاریخ و ساعت نوبت الزامی است)")
    if not owner_id and not (contact_name or "").strip():
        raise ValueError("Choose a client or enter a name. (مشتری را انتخاب یا نام را وارد کنید)")
    if int(duration_minutes or 0) < 5:
        raise ValueError("Duration must be at least 5 minutes. (مدت نوبت حداقل ۵ دقیقه)")
    appointment = AppointmentDB(
        start_at=start_at,
        duration_minutes=int(duration_minutes),
        reason=(reason or "").strip() or None,
        owner_id=owner_id or None,
        patient_id=patient_id or None,
        contact_name=(contact_name or "").strip() or None,
        contact_phone=(contact_phone or "").strip() or None,
        status="scheduled",
    )
    session.add(appointment)
    session.flush()
    return appointment


def _with_people(stmt):
    return stmt.options(selectinload(AppointmentDB.owner), selectinload(AppointmentDB.patient))


def list_appointments(
    session: Session, start: date, end: date | None = None, include_cancelled: bool = True
) -> list[AppointmentDB]:
    """Appointments from `start` through `end` (inclusive; defaults to the same day)."""
    end = end or start
    stmt = _with_people(
        select(AppointmentDB)
        .where(
            AppointmentDB.start_at >= datetime.combine(start, time.min),
            AppointmentDB.start_at < datetime.combine(end + timedelta(days=1), time.min),
        )
        .order_by(AppointmentDB.start_at)
    )
    if not include_cancelled:
        stmt = stmt.where(AppointmentDB.status != "cancelled")
    return list(session.scalars(stmt))


def find_conflicts(
    session: Session, start_at: datetime, duration_minutes: int, ignore_id: int | None = None
) -> list[AppointmentDB]:
    """Scheduled appointments that overlap the given slot."""
    end_at = start_at + timedelta(minutes=int(duration_minutes))
    conflicts = []
    for appt in list_appointments(session, start_at.date(), include_cancelled=False):
        if appt.id == ignore_id or appt.status != "scheduled":
            continue
        appt_end = appt.start_at + timedelta(minutes=appt.duration_minutes)
        if appt.start_at < end_at and start_at < appt_end:
            conflicts.append(appt)
    return conflicts


def set_status(session: Session, appointment_id: int, status: str) -> AppointmentDB:
    if status not in APPOINTMENT_STATUSES:
        raise ValueError(f"Unknown status: {status}")
    appointment = session.get(AppointmentDB, appointment_id)
    if appointment is None:
        raise ValueError(f"Appointment {appointment_id} not found.")
    appointment.status = status
    session.flush()
    return appointment


def reschedule(session: Session, appointment_id: int, start_at: datetime, duration_minutes: int | None = None):
    appointment = session.get(AppointmentDB, appointment_id)
    if appointment is None:
        raise ValueError(f"Appointment {appointment_id} not found.")
    appointment.start_at = start_at
    if duration_minutes:
        appointment.duration_minutes = int(duration_minutes)
    appointment.status = "scheduled"
    session.flush()
    return appointment


def delete_appointment(session: Session, appointment_id: int) -> None:
    appointment = session.get(AppointmentDB, appointment_id)
    if appointment is not None:
        session.delete(appointment)
        session.flush()


def display_name(appt: AppointmentDB) -> str:
    owner: OwnerDB | None = appt.owner
    patient: PatientDB | None = appt.patient
    who = owner.full_name if owner else (appt.contact_name or "-")
    return f"{who} — {patient.name}" if patient and patient.name else who


def display_phone(appt: AppointmentDB) -> str:
    return (appt.owner.telephone if appt.owner else None) or appt.contact_phone or ""
