"""Vaccine types, vaccination records, and the due-date reminders built from them."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from core.models import (
    ClinicVisitDB,
    OwnerDB,
    PatientDB,
    ReminderContactDB,
    VaccinationDB,
    VaccineTypeDB,
)

# Built-in types; `code` links them to the three date fields of the original clinic form.
DEFAULT_VACCINE_TYPES = [
    {"code": "rabies", "name": "Rabies (هاری)", "interval_days": 365, "sort_order": 1},
    {"code": "polyvalent", "name": "Polyvalent (پلی والان)", "interval_days": 365, "sort_order": 2},
    {"code": "deworming", "name": "Deworming (انگل زدایی)", "interval_days": 90, "sort_order": 3},
]
LEGACY_VISIT_FIELDS = {
    "rabies": "rabies_vaccine_date",
    "polyvalent": "polyvalent_vaccine_date",
    "deworming": "deworming_date",
}

DUE_SOON_DAYS = 30


# ---------------------------------------------------------------- vaccine types

def seed_vaccine_types(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(VaccineTypeDB)):
        return
    for data in DEFAULT_VACCINE_TYPES:
        session.add(VaccineTypeDB(**data, active=True))
    session.flush()


def list_vaccine_types(session: Session, active_only: bool = False) -> list[VaccineTypeDB]:
    stmt = select(VaccineTypeDB).order_by(VaccineTypeDB.sort_order, VaccineTypeDB.id)
    if active_only:
        stmt = stmt.where(VaccineTypeDB.active.is_(True))
    return list(session.scalars(stmt))


def _validate_type(name: str, interval_days) -> None:
    if not (name or "").strip():
        raise ValueError("Vaccine name is required. (نام واکسن الزامی است)")
    if interval_days is None or int(interval_days) < 1:
        raise ValueError("The interval must be at least 1 day. (فاصله تکرار باید حداقل ۱ روز باشد)")


def add_vaccine_type(session: Session, name: str, interval_days: int, species: str = "") -> VaccineTypeDB:
    _validate_type(name, interval_days)
    last = session.scalar(select(func.max(VaccineTypeDB.sort_order))) or 0
    vt = VaccineTypeDB(
        name=name.strip(), interval_days=int(interval_days), species=(species or "").strip() or None,
        active=True, sort_order=last + 1,
    )
    session.add(vt)
    session.flush()
    return vt


def update_vaccine_type(session: Session, type_id: int, **fields) -> VaccineTypeDB:
    vt = session.get(VaccineTypeDB, type_id)
    if vt is None:
        raise ValueError(f"Vaccine type {type_id} not found.")
    _validate_type(fields.get("name", vt.name), fields.get("interval_days", vt.interval_days))
    for key in ("name", "interval_days", "species", "active", "sort_order"):
        if key in fields:
            value = fields[key]
            if isinstance(value, str):
                value = value.strip() or (None if key == "species" else value)
            setattr(vt, key, value)
    vt.interval_days = int(vt.interval_days)
    session.flush()
    return vt


# ---------------------------------------------------------------- vaccinations

def record_vaccination(
    session: Session,
    patient_id: int,
    vaccine_type_id: int,
    when: date,
    administered: bool = False,
    visit: ClinicVisitDB | None = None,
    notes: str = "",
) -> VaccinationDB:
    """Record a vaccination. Re-recording the same type on the same date updates the existing entry."""
    if when is None:
        raise ValueError("Vaccination date is required. (تاریخ واکسن الزامی است)")
    if when > date.today():
        raise ValueError("Vaccination date cannot be in the future. (تاریخ واکسن نمی‌تواند در آینده باشد)")
    existing = session.scalar(
        select(VaccinationDB).where(
            VaccinationDB.patient_id == patient_id,
            VaccinationDB.vaccine_type_id == vaccine_type_id,
            VaccinationDB.date == when,
        )
    )
    if existing:
        existing.administered = existing.administered or administered
        if visit is not None and existing.visit is None:
            existing.visit = visit
        session.flush()
        return existing
    vaccination = VaccinationDB(
        patient_id=patient_id, vaccine_type_id=vaccine_type_id, date=when,
        administered=administered, notes=(notes or "").strip() or None,
    )
    session.add(vaccination)
    if visit is not None:
        vaccination.visit = visit
    session.flush()
    return vaccination


def delete_vaccination(session: Session, vaccination_id: int) -> None:
    vaccination = session.get(VaccinationDB, vaccination_id)
    if vaccination is not None:
        session.delete(vaccination)
        session.flush()


def backfill_from_visits(session: Session) -> int:
    """Create vaccination records from the legacy date columns of clinic visits (idempotent)."""
    types = {vt.code: vt for vt in list_vaccine_types(session) if vt.code in LEGACY_VISIT_FIELDS}
    created = 0
    visits = session.scalars(
        select(ClinicVisitDB).where(
            (ClinicVisitDB.rabies_vaccine_date.is_not(None))
            | (ClinicVisitDB.polyvalent_vaccine_date.is_not(None))
            | (ClinicVisitDB.deworming_date.is_not(None))
        )
    )
    for visit in visits:
        for code, field in LEGACY_VISIT_FIELDS.items():
            when = getattr(visit, field)
            if when is None or code not in types:
                continue
            exists = session.scalar(
                select(VaccinationDB.id).where(
                    VaccinationDB.patient_id == visit.patient_id,
                    VaccinationDB.vaccine_type_id == types[code].id,
                    VaccinationDB.date == when,
                )
            )
            if not exists:
                session.add(VaccinationDB(patient_id=visit.patient_id, vaccine_type_id=types[code].id,
                                          date=when, administered=False, visit=visit))
                created += 1
    session.flush()
    return created


# ---------------------------------------------------------------- due dates

@dataclass
class VaccineStatus:
    vaccine_type: VaccineTypeDB
    last_date: date | None
    due_date: date | None
    days_left: int | None  # negative = overdue

    @property
    def status(self) -> str:
        if self.due_date is None:
            return "no_record"
        if self.days_left < 0:
            return "overdue"
        if self.days_left <= DUE_SOON_DAYS:
            return "due_soon"
        return "ok"


def patient_vaccine_status(session: Session, patient: PatientDB, today: date | None = None) -> list[VaccineStatus]:
    today = today or date.today()
    last_dates = dict(
        session.execute(
            select(VaccinationDB.vaccine_type_id, func.max(VaccinationDB.date))
            .where(VaccinationDB.patient_id == patient.id)
            .group_by(VaccinationDB.vaccine_type_id)
        ).all()
    )
    result = []
    for vt in list_vaccine_types(session, active_only=True):
        last = last_dates.get(vt.id)
        if last is None and not vt.applies_to(patient.animal_type):
            continue
        due = last + timedelta(days=vt.interval_days) if last else None
        result.append(VaccineStatus(vt, last, due, (due - today).days if due else None))
    return result


@dataclass
class DueReminder:
    patient: PatientDB
    owner: OwnerDB
    vaccine_type: VaccineTypeDB
    last_date: date
    due_date: date
    days_left: int
    contact: ReminderContactDB | None

    @property
    def status(self) -> str:
        return "overdue" if self.days_left < 0 else "due_soon"


def due_reminders(
    session: Session,
    today: date | None = None,
    within_days: int = DUE_SOON_DAYS,
    overdue_days: int | None = 365,
    include_contacted: bool = True,
) -> list[DueReminder]:
    """Vaccines that are overdue (up to `overdue_days` ago) or due within `within_days`, most urgent first.

    Only animals with at least one recorded dose of that vaccine are included, and inactive animals are skipped.
    """
    today = today or date.today()
    types = {vt.id: vt for vt in list_vaccine_types(session, active_only=True)}
    if not types:
        return []
    latest = session.execute(
        select(VaccinationDB.patient_id, VaccinationDB.vaccine_type_id, func.max(VaccinationDB.date))
        .where(VaccinationDB.vaccine_type_id.in_(types))
        .group_by(VaccinationDB.patient_id, VaccinationDB.vaccine_type_id)
    ).all()

    candidates = []
    for patient_id, type_id, last in latest:
        due = last + timedelta(days=types[type_id].interval_days)
        days_left = (due - today).days
        if days_left > within_days:
            continue
        if overdue_days is not None and days_left < -overdue_days:
            continue
        candidates.append((patient_id, type_id, last, due, days_left))
    if not candidates:
        return []

    patients = {
        p.id: p
        for p in session.scalars(
            select(PatientDB)
            .options(selectinload(PatientDB.owner))
            .where(PatientDB.id.in_({c[0] for c in candidates}), PatientDB.active.is_(True))
        )
    }
    contacts = {}
    for contact in session.scalars(
        select(ReminderContactDB).where(ReminderContactDB.patient_id.in_(patients))
    ):
        key = (contact.patient_id, contact.vaccine_type_id, contact.due_date)
        if key not in contacts or contact.contacted_at > contacts[key].contacted_at:
            contacts[key] = contact

    reminders = []
    for patient_id, type_id, last, due, days_left in candidates:
        patient = patients.get(patient_id)
        if patient is None:
            continue
        contact = contacts.get((patient_id, type_id, due))
        if contact and not include_contacted:
            continue
        reminders.append(DueReminder(patient, patient.owner, types[type_id], last, due, days_left, contact))
    reminders.sort(key=lambda r: (r.days_left, r.owner.full_name))
    return reminders


def mark_contacted(session: Session, patient_id: int, vaccine_type_id: int, due_date: date, note: str = "") -> ReminderContactDB:
    contact = ReminderContactDB(
        patient_id=patient_id, vaccine_type_id=vaccine_type_id, due_date=due_date,
        note=(note or "").strip() or None,
    )
    session.add(contact)
    session.flush()
    return contact


def unmark_contacted(session: Session, patient_id: int, vaccine_type_id: int, due_date: date) -> None:
    for contact in session.scalars(
        select(ReminderContactDB).where(
            ReminderContactDB.patient_id == patient_id,
            ReminderContactDB.vaccine_type_id == vaccine_type_id,
            ReminderContactDB.due_date == due_date,
        )
    ):
        session.delete(contact)
    session.flush()
