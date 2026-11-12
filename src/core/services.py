"""Business logic. Every function takes an open SQLAlchemy session; the caller commits."""

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from core import vaccines
from core.sci import format_scientific, parse_number
from core.models import (
    LAB_ORDER_STATUSES,
    AppointmentDB,
    AttachmentDB,
    ClinicVisitDB,
    DrugDB,
    LabOrderDB,
    LabOrderItemDB,
    LabResultValueDB,
    LabTestDB,
    LabTestParameterDB,
    MedicationDB,
    OwnerDB,
    PatientDB,
    VaccinationDB,
    VaccineTypeDB,
    VisitCostDB,
)

FIRST_FILE_NUMBER = 1000
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024

OWNER_FIELDS = ("name", "surname", "telephone", "address")
PATIENT_FIELDS = (
    "file_number", "name", "animal_type", "breed", "gender", "sterilized",
    "keeping_location", "microchip", "age", "weight", "active",
)
LAB_ORDER_FIELDS = (
    "sample_qty", "sample_type", "other", "date_sampling", "date_admission",
    "date_response", "notes",
)
VISIT_FIELDS = (
    "visit_date", "visit_type", "reason_for_visit", "history_narrative",
    "previous_medications", "rabies_vaccine_date", "polyvalent_vaccine_date",
    "deworming_date", "diet_info", "vaccination_status", "weight", "vitals", "exam",
    "paraclinic", "diagnosis", "followup_date",
)


def _clean(value):
    return value.strip() if isinstance(value, str) else value


def _apply(obj, data: dict, fields) -> None:
    for field in fields:
        if field in data:
            setattr(obj, field, _clean(data[field]))


# ---------------------------------------------------------------- test catalog

def list_tests(session: Session, active_only: bool = False) -> list[LabTestDB]:
    stmt = select(LabTestDB).order_by(LabTestDB.category, LabTestDB.code)
    if active_only:
        stmt = stmt.where(LabTestDB.active.is_(True))
    return list(session.scalars(stmt))


def list_test_categories(session: Session) -> list[str]:
    """Distinct categories already used by tests, for the category dropdown."""
    rows = session.scalars(select(LabTestDB.category).where(LabTestDB.category.is_not(None)).distinct())
    return sorted({c.strip() for c in rows if c and c.strip()}, key=str.casefold)


def _clean_days(value) -> int | None:
    if value is None or value == "":
        return None
    days = int(value)
    if days < 0:
        raise ValueError("Days to result cannot be negative. (مدت زمان جوابدهی نمی‌تواند منفی باشد)")
    return days


def response_date(admission: date, tests: list) -> date | None:
    """Admission date plus the longest turnaround among `tests`; None when no test has a turnaround set."""
    days = [t.turnaround_days for t in tests if t is not None and t.turnaround_days is not None]
    return admission + timedelta(days=max(days)) if days and admission else None


def add_test(
    session: Session,
    code: str,
    name: str,
    default_fee: int,
    category: str = "",
    description: str = "",
    turnaround_days: int | None = None,
) -> LabTestDB:
    code, name = (code or "").strip(), (name or "").strip()
    if not code or not name:
        raise ValueError("Test code and name are required. (کد و نام آزمایش الزامی است)")
    if default_fee is None or default_fee < 0:
        raise ValueError("Fee cannot be negative. (هزینه نمی‌تواند منفی باشد)")
    if session.scalar(select(LabTestDB).where(LabTestDB.code == code)):
        raise ValueError(f"A test with code '{code}' already exists. (این کد قبلا ثبت شده است)")
    test = LabTestDB(
        code=code,
        name=name,
        default_fee=int(default_fee),
        turnaround_days=_clean_days(turnaround_days),
        category=_clean(category) or None,
        description=_clean(description) or None,
        active=True,
    )
    session.add(test)
    session.flush()
    return test


def update_test(session: Session, test_id: int, **fields) -> LabTestDB:
    test = session.get(LabTestDB, test_id)
    if test is None:
        raise ValueError(f"Test {test_id} not found.")
    if "code" in fields:
        code = (fields["code"] or "").strip()
        if not code:
            raise ValueError("Test code is required. (کد آزمایش الزامی است)")
        clash = session.scalar(select(LabTestDB).where(LabTestDB.code == code, LabTestDB.id != test_id))
        if clash:
            raise ValueError(f"A test with code '{code}' already exists. (این کد قبلا ثبت شده است)")
    if "name" in fields and not (fields["name"] or "").strip():
        raise ValueError("Test name is required. (نام آزمایش الزامی است)")
    if "default_fee" in fields:
        if fields["default_fee"] is None or fields["default_fee"] < 0:
            raise ValueError("Fee cannot be negative. (هزینه نمی‌تواند منفی باشد)")
        fields["default_fee"] = int(fields["default_fee"])
    if "turnaround_days" in fields:
        test.turnaround_days = _clean_days(fields.pop("turnaround_days"))
    for key in ("code", "name", "category", "description", "default_fee", "active"):
        if key in fields:
            setattr(test, key, _clean(fields[key]))
    session.flush()
    return test


def test_usage_count(session: Session, test_id: int) -> int:
    lab = session.scalar(select(func.count()).select_from(LabOrderItemDB).where(LabOrderItemDB.test_id == test_id))
    clinic = session.scalar(select(func.count()).select_from(VisitCostDB).where(VisitCostDB.test_id == test_id))
    return (lab or 0) + (clinic or 0)


def delete_test(session: Session, test_id: int) -> None:
    """Delete a test that has never been used; used tests should be deactivated instead."""
    test = session.get(LabTestDB, test_id)
    if test is None:
        return
    if test_usage_count(session, test_id):
        raise ValueError(
            "This test is used in existing admissions; deactivate it instead. "
            "(این آزمایش در پذیرش‌های قبلی استفاده شده است؛ آن را غیرفعال کنید)"
        )
    session.delete(test)
    session.flush()


def _optional_float(value):
    if value is None or (isinstance(value, float) and value != value):  # None or NaN
        return None
    if isinstance(value, str) and not value.strip():
        return None
    number = parse_number(value)
    if number is None:
        raise ValueError(f"'{value}' is not a number. (عدد نامعتبر)")
    return number


def set_test_parameters(session: Session, test_id: int, rows: list[dict]) -> list[LabTestParameterDB]:
    """Replace a test's result template. Rows with an `id` update that parameter; rows without one are added;
    parameters missing from `rows` are removed (past results keep their copied name/unit/range)."""
    test = session.get(LabTestDB, test_id)
    if test is None:
        raise ValueError(f"Test {test_id} not found.")
    existing = {p.id: p for p in test.parameters}
    keep = set()
    for order, row in enumerate(rows):
        name = _clean(row.get("name") or "")
        if not name:
            continue
        low, high = _optional_float(row.get("ref_low")), _optional_float(row.get("ref_high"))
        if low is not None and high is not None and low > high:
            raise ValueError(f"{name}: the low limit is above the high limit. (حد پایین بیشتر از حد بالا است)")
        row_id = row.get("id")
        row_id = int(row_id) if row_id is not None and row_id == row_id else None  # NaN check
        param = existing.get(row_id)
        if param is None:
            param = LabTestParameterDB()
            test.parameters.append(param)
        param.name, param.unit = name, format_scientific(_clean(row.get("unit") or "")) or None
        param.ref_low, param.ref_high, param.sort_order = low, high, order
        param.standard = _clean(row.get("standard") or "") or None
        if param.id:
            keep.add(param.id)
    for param_id, param in existing.items():
        if param_id not in keep:
            for value in session.scalars(select(LabResultValueDB).where(LabResultValueDB.parameter_id == param_id)):
                value.parameter_id = None
            test.parameters.remove(param)
    session.flush()
    return list(test.parameters)


# ---------------------------------------------------------------- drug catalog

def list_drugs(session: Session, active_only: bool = False) -> list[DrugDB]:
    stmt = select(DrugDB).order_by(DrugDB.name)
    if active_only:
        stmt = stmt.where(DrugDB.active.is_(True))
    return list(session.scalars(stmt))


def add_drug(session: Session, name: str, drug_form: str = "", prescribed_form: str = "",
             default_dosage: str = "", notes: str = "") -> DrugDB:
    name = (name or "").strip()
    if not name:
        raise ValueError("Drug name is required. (نام دارو الزامی است)")
    if session.scalar(select(DrugDB).where(func.lower(DrugDB.name) == name.lower())):
        raise ValueError(f"'{name}' is already in the drug list. (این دارو قبلا ثبت شده است)")
    drug = DrugDB(
        name=name, drug_form=_clean(drug_form) or None, prescribed_form=_clean(prescribed_form) or None,
        default_dosage=_clean(default_dosage) or None, notes=_clean(notes) or None, active=True,
    )
    session.add(drug)
    session.flush()
    return drug


def update_drug(session: Session, drug_id: int, **fields) -> DrugDB:
    drug = session.get(DrugDB, drug_id)
    if drug is None:
        raise ValueError(f"Drug {drug_id} not found.")
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise ValueError("Drug name is required. (نام دارو الزامی است)")
        clash = session.scalar(select(DrugDB).where(func.lower(DrugDB.name) == name.lower(), DrugDB.id != drug_id))
        if clash:
            raise ValueError(f"'{name}' is already in the drug list. (این دارو قبلا ثبت شده است)")
    for key in ("name", "drug_form", "prescribed_form", "default_dosage", "notes", "active"):
        if key in fields:
            setattr(drug, key, _clean(fields[key]))
    session.flush()
    return drug


def delete_drug(session: Session, drug_id: int) -> None:
    drug = session.get(DrugDB, drug_id)
    if drug is None:
        return
    if session.scalar(select(func.count()).select_from(MedicationDB).where(MedicationDB.drug_id == drug_id)):
        raise ValueError(
            "This drug is used in existing prescriptions; deactivate it instead. "
            "(این دارو در نسخه‌های قبلی استفاده شده است؛ آن را غیرفعال کنید)"
        )
    session.delete(drug)
    session.flush()


# ---------------------------------------------------------------- attachments

def add_attachment(
    session: Session,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    visit_id: int | None = None,
    lab_order_id: int | None = None,
    visit: ClinicVisitDB | None = None,
    lab_order: LabOrderDB | None = None,
) -> AttachmentDB:
    if not data:
        raise ValueError(f"'{filename}' is empty. (فایل خالی است)")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"'{filename}' is larger than 50 MB. (حجم فایل بیش از حد مجاز است)")
    visit = visit or (session.get(ClinicVisitDB, visit_id) if visit_id else None)
    lab_order = lab_order or (session.get(LabOrderDB, lab_order_id) if lab_order_id else None)
    if visit is None and lab_order is None:
        raise ValueError("An attachment must belong to a visit or a lab order.")
    attachment = AttachmentDB(filename=filename, data=data, content_type=content_type, size=len(data))
    if visit is not None:
        visit.attachments.append(attachment)
    if lab_order is not None:
        lab_order.attachments.append(attachment)
    session.flush()
    return attachment


def get_attachment_data(session: Session, attachment_id: int) -> bytes | None:
    return session.scalar(select(AttachmentDB.data).where(AttachmentDB.id == attachment_id))


def delete_attachment(session: Session, attachment_id: int) -> None:
    attachment = session.get(AttachmentDB, attachment_id)
    if attachment is None:
        return
    for parent in (attachment.visit, attachment.lab_order):
        if parent is not None:
            parent.attachments.remove(attachment)  # delete-orphan cascade deletes the row
    session.delete(attachment)
    session.flush()


# ---------------------------------------------------------------- owners & patients

def search_owners(session: Session, query: str, limit: int = 50) -> list[OwnerDB]:
    query = (query or "").strip()
    stmt = select(OwnerDB).order_by(OwnerDB.created_at.desc()).limit(limit)
    if query:
        like = f"%{query}%"
        full_name = func.coalesce(OwnerDB.name, "") + " " + func.coalesce(OwnerDB.surname, "")
        stmt = stmt.where(
            or_(
                OwnerDB.name.ilike(like),
                OwnerDB.surname.ilike(like),
                full_name.ilike(like),
                OwnerDB.telephone.ilike(like),
                OwnerDB.patients.any(
                    or_(
                        PatientDB.name.ilike(like),
                        PatientDB.file_number.ilike(like),
                        PatientDB.microchip.ilike(like),
                    )
                ),
            )
        )
    return list(session.scalars(stmt))


def get_owner(session: Session, owner_id: int) -> OwnerDB | None:
    return session.get(
        OwnerDB,
        owner_id,
        options=[
            selectinload(OwnerDB.patients)
            .selectinload(PatientDB.visits)
            .selectinload(ClinicVisitDB.patient)
            .selectinload(PatientDB.owner),
            selectinload(OwnerDB.lab_orders).selectinload(LabOrderDB.items),
            selectinload(OwnerDB.lab_orders).selectinload(LabOrderDB.owner),
            selectinload(OwnerDB.lab_orders).selectinload(LabOrderDB.patient),
        ],
    )


def save_owner(session: Session, data: dict, owner_id: int | None = None) -> OwnerDB:
    """Create a new owner, or update the existing one when owner_id is given."""
    if not (_clean(data.get("name")) or _clean(data.get("surname"))):
        raise ValueError("Owner name is required. (نام صاحب حیوان الزامی است)")
    owner = session.get(OwnerDB, owner_id) if owner_id else None
    if owner is None:
        owner = OwnerDB()
        session.add(owner)
    _apply(owner, data, OWNER_FIELDS)
    owner.name = owner.name or ""
    owner.surname = owner.surname or ""
    session.flush()
    return owner


def find_owners_by_phone(session: Session, telephone: str) -> list[OwnerDB]:
    telephone = (telephone or "").strip()
    if not telephone:
        return []
    return list(session.scalars(select(OwnerDB).where(OwnerDB.telephone == telephone)))


def next_file_number(session: Session) -> str:
    numbers = [int(n) for n in session.scalars(select(PatientDB.file_number)) if n and n.isdigit()]
    return str(max(numbers, default=FIRST_FILE_NUMBER - 1) + 1)


def save_patient(session: Session, owner: OwnerDB, data: dict, patient_id: int | None = None) -> PatientDB:
    """Create or update an animal belonging to `owner`. A blank file number is auto-assigned."""
    patient = session.get(PatientDB, patient_id) if patient_id else None
    if patient is None:
        patient = PatientDB()
        session.add(patient)
    with session.no_autoflush:
        patient.owner = owner
        _apply(patient, data, PATIENT_FIELDS)
        if not patient.file_number:
            patient.file_number = next_file_number(session)
        stmt = select(PatientDB.id).where(PatientDB.file_number == patient.file_number)
        if patient.id:
            stmt = stmt.where(PatientDB.id != patient.id)
        clash = session.scalar(stmt)
    if clash is not None:
        raise ValueError(
            f"File number {patient.file_number} belongs to another patient. "
            f"(شماره پرونده {patient.file_number} متعلق به بیمار دیگری است)"
        )
    session.flush()
    return patient


# ---------------------------------------------------------------- lab orders

def _template_values(test: LabTestDB | None) -> list[LabResultValueDB]:
    if test is None:
        return []
    return [
        LabResultValueDB(parameter_id=p.id, name=p.name, unit=p.unit, ref_low=p.ref_low,
                         ref_high=p.ref_high, standard=p.standard, sort_order=p.sort_order)
        for p in test.parameters
    ]


def _build_lab_items(session: Session, items: list[dict]) -> list[LabOrderItemDB]:
    built = []
    for item in items:
        quantity = int(item.get("quantity") or 1)
        if quantity < 1:
            raise ValueError("Quantity must be at least 1. (تعداد باید حداقل ۱ باشد)")
        test = session.get(LabTestDB, item["test_id"]) if item.get("test_id") else None
        name = _clean(item.get("test_name")) or (test.name if test else "")
        if not name:
            raise ValueError("Every test needs a name. (نام آزمایش الزامی است)")
        fee = item.get("fee")
        fee = int(test.default_fee if fee is None and test else fee or 0)
        if fee < 0:
            raise ValueError("Fee cannot be negative. (هزینه نمی‌تواند منفی باشد)")
        built.append(
            LabOrderItemDB(
                test=test,
                code=_clean(item.get("code")) or (test.code if test else None),
                test_name=name,
                fee=fee,
                quantity=quantity,
                price=fee * quantity,
                values=_template_values(test),
            )
        )
    return built


def create_lab_order(
    session: Session,
    owner_data: dict,
    order_data: dict,
    items: list[dict],
    owner_id: int | None = None,
    patient_id: int | None = None,
    attachments: list[dict] | None = None,
) -> LabOrderDB:
    """Admit a lab sample. `items` are dicts with test_id (catalog) and/or code, test_name, fee, quantity.
    `attachments` are dicts with filename, data, content_type."""
    if not items:
        raise ValueError("Add at least one test. (حداقل یک آزمایش انتخاب کنید)")
    owner = save_owner(session, owner_data, owner_id)
    order = LabOrderDB(owner=owner, status="pending")
    session.add(order)
    if patient_id:
        order.patient = session.get(PatientDB, patient_id)
    _apply(order, order_data, LAB_ORDER_FIELDS)
    order.date_admission = order.date_admission or date.today()
    order.items = _build_lab_items(session, items)
    order.total = sum(i.price for i in order.items)
    for file in attachments or []:
        add_attachment(session, file["filename"], file["data"], file.get("content_type"), lab_order=order)
    session.flush()
    return order


def get_lab_order(session: Session, order_id: int) -> LabOrderDB | None:
    return session.get(
        LabOrderDB,
        order_id,
        options=[
            selectinload(LabOrderDB.items).selectinload(LabOrderItemDB.values),
            selectinload(LabOrderDB.owner),
            selectinload(LabOrderDB.patient),
            selectinload(LabOrderDB.attachments),
        ],
    )


def ensure_result_values(session: Session, order_id: int) -> int:
    """Add template rows to items that have none yet (e.g. a template was defined after admission)."""
    order = session.get(LabOrderDB, order_id)
    added = 0
    for item in order.items if order else []:
        if not item.values and item.test is not None and item.test.parameters:
            item.values = _template_values(item.test)
            added += len(item.values)
    session.flush()
    return added


def update_lab_results(
    session: Session,
    order_id: int,
    results: dict[int, str],
    status: str | None = None,
    date_response: date | None = None,
    values: dict[int, str] | None = None,
    standards: dict[int, str] | None = None,
) -> LabOrderDB:
    """Save free-text results per item (`results`), template values per value row (`values`) and,
    for this order only, the reference standard per value row (`standards`)."""
    order = session.get(LabOrderDB, order_id)
    if order is None:
        raise ValueError(f"Lab order {order_id} not found.")
    values, standards = values or {}, standards or {}
    for item in order.items:
        if item.id in results:
            item.result = format_scientific(_clean(results[item.id])) or None
        for value in item.values:
            if value.id in values:
                raw = values[value.id]
                value.value = format_scientific(_clean(str(raw))) if raw is not None and str(raw).strip() else None
            if value.id in standards:
                raw = standards[value.id]
                empty = raw is None or (isinstance(raw, float) and raw != raw)  # None or NaN from the grid
                value.standard = None if empty else (_clean(str(raw)) or None)
    if status:
        if status not in LAB_ORDER_STATUSES:
            raise ValueError(f"Unknown status: {status}")
        order.status = status
    if date_response:
        order.date_response = date_response
    session.flush()
    return order


def list_lab_orders(
    session: Session,
    start: date | None = None,
    end: date | None = None,
    status: str | None = None,
    limit: int | None = 200,
) -> list[LabOrderDB]:
    stmt = (
        select(LabOrderDB)
        .options(selectinload(LabOrderDB.owner), selectinload(LabOrderDB.items))
        .order_by(LabOrderDB.created_at.desc())
        .limit(limit)
    )
    if start:
        stmt = stmt.where(LabOrderDB.date_admission >= start)
    if end:
        stmt = stmt.where(LabOrderDB.date_admission <= end)
    if status:
        stmt = stmt.where(LabOrderDB.status == status)
    return list(session.scalars(stmt))


def delete_lab_order(session: Session, order_id: int) -> None:
    order = session.get(LabOrderDB, order_id)
    if order is not None:
        session.delete(order)
        session.flush()


# ---------------------------------------------------------------- clinic visits

def create_clinic_visit(
    session: Session,
    owner_data: dict,
    patient_data: dict,
    visit_data: dict,
    medications: list[dict] | None = None,
    costs: list[dict] | None = None,
    owner_id: int | None = None,
    patient_id: int | None = None,
    vaccinations: list[dict] | None = None,
    attachments: list[dict] | None = None,
    appointment_at: datetime | None = None,
) -> ClinicVisitDB:
    """Save a clinic visit.

    vaccinations: dicts with vaccine_type_id, date, administered (given in the clinic during this visit).
    attachments: dicts with filename, data, content_type.
    appointment_at: books a follow-up appointment at this date/time.
    """
    owner = save_owner(session, owner_data, owner_id)
    patient = save_patient(session, owner, patient_data, patient_id)
    visit = ClinicVisitDB(patient=patient)
    session.add(visit)
    _apply(visit, visit_data, VISIT_FIELDS)
    visit.visit_date = visit.visit_date or date.today()
    if _clean(visit_data.get("weight")):
        patient.weight = _clean(visit_data["weight"])

    for med in medications or []:
        if not _clean(med.get("drug_name")):
            raise ValueError("Every medication needs a drug name. (نام دارو الزامی است)")
        visit.medications.append(
            MedicationDB(
                drug_id=med.get("drug_id") or None,
                dosage_instructions=_clean(med.get("dosage_instructions")),
                drug_name=_clean(med["drug_name"]),
                prescribed_form=_clean(med.get("prescribed_form")),
                quantity=_clean(str(med.get("quantity") or "")),
                drug_form=_clean(med.get("drug_form")),
            )
        )

    for cost in costs or []:
        test = session.get(LabTestDB, cost["test_id"]) if cost.get("test_id") else None
        description = _clean(cost.get("description")) or (test.name if test else "")
        if not description:
            raise ValueError("Every cost item needs a description. (شرح خدمات الزامی است)")
        tariff = cost.get("tariff")
        tariff = int(test.default_fee if tariff is None and test else tariff or 0)
        quantity = int(cost.get("quantity") or 1)
        if tariff < 0 or quantity < 1:
            raise ValueError("Invalid tariff or quantity. (تعرفه یا تعداد نامعتبر است)")
        visit.costs.append(
            VisitCostDB(test=test, description=description, tariff=tariff, quantity=quantity, total=tariff * quantity)
        )
    visit.total_cost = sum(c.total for c in visit.costs)
    session.flush()

    for vacc in vaccinations or []:
        when = visit.visit_date if vacc.get("administered") else vacc.get("date")
        if when is None:
            continue
        vaccine_type = session.get(VaccineTypeDB, vacc["vaccine_type_id"])
        vaccines.record_vaccination(
            session, patient.id, vaccine_type.id, when, administered=bool(vacc.get("administered")), visit=visit,
        )
        legacy_field = vaccines.LEGACY_VISIT_FIELDS.get(vaccine_type.code)
        if legacy_field and (getattr(visit, legacy_field) is None or when > getattr(visit, legacy_field)):
            setattr(visit, legacy_field, when)

    for file in attachments or []:
        add_attachment(session, file["filename"], file["data"], file.get("content_type"), visit=visit)

    if appointment_at is not None:
        session.add(AppointmentDB(
            owner_id=owner.id, patient_id=patient.id, start_at=appointment_at, duration_minutes=30,
            reason="Follow-up (پیگیری درمان)", status="scheduled",
        ))
    session.flush()
    return visit


def get_clinic_visit(session: Session, visit_id: int) -> ClinicVisitDB | None:
    return session.get(
        ClinicVisitDB,
        visit_id,
        options=[
            selectinload(ClinicVisitDB.medications),
            selectinload(ClinicVisitDB.costs),
            selectinload(ClinicVisitDB.attachments),
            selectinload(ClinicVisitDB.vaccinations).selectinload(VaccinationDB.vaccine_type),
            selectinload(ClinicVisitDB.patient).selectinload(PatientDB.owner),
        ],
    )


def list_clinic_visits(
    session: Session, start: date | None = None, end: date | None = None, limit: int | None = 200
) -> list[ClinicVisitDB]:
    stmt = (
        select(ClinicVisitDB)
        .options(selectinload(ClinicVisitDB.patient).selectinload(PatientDB.owner))
        .order_by(ClinicVisitDB.visit_date.desc(), ClinicVisitDB.id.desc())
        .limit(limit)
    )
    if start:
        stmt = stmt.where(ClinicVisitDB.visit_date >= start)
    if end:
        stmt = stmt.where(ClinicVisitDB.visit_date <= end)
    return list(session.scalars(stmt))


def delete_clinic_visit(session: Session, visit_id: int) -> None:
    visit = session.get(ClinicVisitDB, visit_id)
    if visit is not None:
        session.delete(visit)
        session.flush()


def upcoming_followups(session: Session, today: date | None = None, days: int = 7) -> list[ClinicVisitDB]:
    today = today or date.today()
    stmt = (
        select(ClinicVisitDB)
        .options(selectinload(ClinicVisitDB.patient).selectinload(PatientDB.owner))
        .where(ClinicVisitDB.followup_date >= today, ClinicVisitDB.followup_date <= today + timedelta(days=days))
        .order_by(ClinicVisitDB.followup_date)
    )
    return list(session.scalars(stmt))


# ---------------------------------------------------------------- dashboard

def dashboard_stats(session: Session, today: date | None = None) -> dict:
    today = today or date.today()
    lab_today = session.scalar(
        select(func.count()).select_from(LabOrderDB).where(LabOrderDB.date_admission == today)
    )
    visits_today = session.scalar(
        select(func.count()).select_from(ClinicVisitDB).where(ClinicVisitDB.visit_date == today)
    )
    lab_revenue = session.scalar(
        select(func.coalesce(func.sum(LabOrderDB.total), 0)).where(LabOrderDB.date_admission == today)
    )
    clinic_revenue = session.scalar(
        select(func.coalesce(func.sum(ClinicVisitDB.total_cost), 0)).where(ClinicVisitDB.visit_date == today)
    )
    pending = session.scalar(
        select(func.count()).select_from(LabOrderDB).where(LabOrderDB.status == "pending")
    )
    return {
        "lab_today": lab_today or 0,
        "visits_today": visits_today or 0,
        "revenue_today": int(lab_revenue or 0) + int(clinic_revenue or 0),
        "pending_lab": pending or 0,
        "owners": session.scalar(select(func.count()).select_from(OwnerDB)) or 0,
        "patients": session.scalar(select(func.count()).select_from(PatientDB)) or 0,
        "generated_at": datetime.now(),
    }
