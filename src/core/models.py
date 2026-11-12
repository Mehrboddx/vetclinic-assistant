from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import deferred, relationship

from core.database import Base
from core.sci import format_number, parse_number

LAB_ORDER_STATUSES = ["pending", "completed", "delivered"]
APPOINTMENT_STATUSES = ["scheduled", "done", "cancelled", "no_show"]


class OwnerDB(Base):
    """A client of the clinic (animal owner, or the sender of a lab sample)."""

    __tablename__ = "owners"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, default="")
    surname = Column(String, nullable=False, default="")
    telephone = Column(String, index=True)
    address = Column(String)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    patients = relationship("PatientDB", back_populates="owner", cascade="all, delete-orphan")
    lab_orders = relationship("LabOrderDB", back_populates="owner", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return f"{self.name or ''} {self.surname or ''}".strip()


class PatientDB(Base):
    """An animal."""

    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    file_number = Column(String, unique=True, index=True)
    name = Column(String)
    animal_type = Column(String)
    breed = Column(String)
    gender = Column(String)
    sterilized = Column(String)
    keeping_location = Column(String)
    microchip = Column(String, index=True)
    age = Column(String)
    weight = Column(String)
    # Unchecked for deceased / moved-away animals: they stop appearing in reminders.
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    owner = relationship("OwnerDB", back_populates="patients")
    visits = relationship(
        "ClinicVisitDB",
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="ClinicVisitDB.visit_date.desc()",
    )
    lab_orders = relationship("LabOrderDB", back_populates="patient")
    vaccinations = relationship(
        "VaccinationDB",
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="VaccinationDB.date.desc()",
    )


# ---------------------------------------------------------------- lab

class LabTestDB(Base):
    """Catalog of tests (experiments) the vet offers; managed from the Tests page."""

    __tablename__ = "lab_tests"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String)
    sample_type = Column(String)  # unused: the sample type is entered per admission; kept for older data
    default_fee = Column(BigInteger, nullable=False, default=0)
    turnaround_days = Column(Integer)  # days from admission until the result is ready; None = not set
    description = Column(Text)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    parameters = relationship(
        "LabTestParameterDB",
        back_populates="test",
        cascade="all, delete-orphan",
        order_by="(LabTestParameterDB.sort_order, LabTestParameterDB.id)",
    )

    @property
    def label(self) -> str:
        days = f" · {self.turnaround_days} روز" if self.turnaround_days is not None else ""
        return f"{self.code} — {self.name} ({self.default_fee:,} ریال{days})"


class LabTestParameterDB(Base):
    """One field of a test's result template, e.g. WBC (10^3/µL, 6–17)."""

    __tablename__ = "lab_test_parameters"
    id = Column(Integer, primary_key=True)
    test_id = Column(Integer, ForeignKey("lab_tests.id"), nullable=False)
    name = Column(String, nullable=False)
    unit = Column(String)
    ref_low = Column(Float)
    ref_high = Column(Float)
    standard = Column(String)  # reference standard (استاندارد مرجع) the test follows, e.g. ISO 6579
    sort_order = Column(Integer, default=0, nullable=False)

    test = relationship("LabTestDB", back_populates="parameters")


class LabOrderDB(Base):
    """A laboratory admission."""

    __tablename__ = "lab_orders"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    sample_qty = Column(String)
    sample_type = Column(String)
    other = Column(String)
    date_sampling = Column(Date)
    date_admission = Column(Date)
    date_response = Column(Date)
    status = Column(String, default="pending", nullable=False)
    payment_type = Column(String)  # no longer collected; kept so older records and backups still load
    notes = Column(Text)
    total = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    owner = relationship("OwnerDB", back_populates="lab_orders")
    patient = relationship("PatientDB", back_populates="lab_orders")
    items = relationship(
        "LabOrderItemDB",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="LabOrderItemDB.id",
    )
    attachments = relationship(
        "AttachmentDB", back_populates="lab_order", cascade="all, delete-orphan", order_by="AttachmentDB.id"
    )


class LabOrderItemDB(Base):
    """One test on a lab order. Code/name/fee are copied so later catalog edits don't rewrite history."""

    __tablename__ = "lab_order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("lab_orders.id"), nullable=False)
    test_id = Column(Integer, ForeignKey("lab_tests.id"))
    code = Column(String)
    test_name = Column(String, nullable=False)
    fee = Column(BigInteger, nullable=False, default=0)
    quantity = Column(Integer, nullable=False, default=1)
    price = Column(BigInteger, nullable=False, default=0)
    result = Column(Text)

    order = relationship("LabOrderDB", back_populates="items")
    test = relationship("LabTestDB")
    values = relationship(
        "LabResultValueDB",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="(LabResultValueDB.sort_order, LabResultValueDB.id)",
    )


class LabResultValueDB(Base):
    """A measured value for one template parameter; name/unit/range/standard are copied from the template."""

    __tablename__ = "lab_result_values"
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("lab_order_items.id"), nullable=False)
    parameter_id = Column(Integer, ForeignKey("lab_test_parameters.id", ondelete="SET NULL"))
    name = Column(String, nullable=False)
    unit = Column(String)
    ref_low = Column(Float)
    ref_high = Column(Float)
    standard = Column(String)
    sort_order = Column(Integer, default=0, nullable=False)
    value = Column(String)

    item = relationship("LabOrderItemDB", back_populates="values")

    @property
    def flag(self) -> str:
        """'L' below range, 'H' above range, '' otherwise (or when the value isn't numeric)."""
        number = parse_number(self.value)
        if number is None:
            return ""
        if self.ref_low is not None and number < self.ref_low:
            return "L"
        if self.ref_high is not None and number > self.ref_high:
            return "H"
        return ""

    @property
    def reference(self) -> str:
        if self.ref_low is None and self.ref_high is None:
            return ""
        low, high = format_number(self.ref_low), format_number(self.ref_high)
        if self.ref_low is None:
            return f"≤ {high}"
        if self.ref_high is None:
            return f"≥ {low}"
        return f"{low} – {high}"


# ---------------------------------------------------------------- clinic

class ClinicVisitDB(Base):
    """A clinic (مطب) visit, with the full intake form."""

    __tablename__ = "clinic_visits"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    visit_date = Column(Date)
    visit_type = Column(String)  # "first" | "followup"
    reason_for_visit = Column(Text)
    history_narrative = Column(Text)
    previous_medications = Column(Text)
    # Kept for the original form; vaccinations are tracked in VaccinationDB.
    rabies_vaccine_date = Column(Date)
    polyvalent_vaccine_date = Column(Date)
    deworming_date = Column(Date)
    diet_info = Column(Text)
    vaccination_status = Column(String)  # "complete" | "incomplete"
    weight = Column(String)
    vitals = Column(JSON, default=dict)
    exam = Column(JSON, default=dict)
    paraclinic = Column(JSON, default=dict)
    diagnosis = Column(Text)
    followup_date = Column(Date)
    payment_type = Column(String)  # no longer collected; kept so older records and backups still load
    total_cost = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    patient = relationship("PatientDB", back_populates="visits")
    medications = relationship(
        "MedicationDB", back_populates="visit", cascade="all, delete-orphan", order_by="MedicationDB.id"
    )
    costs = relationship(
        "VisitCostDB", back_populates="visit", cascade="all, delete-orphan", order_by="VisitCostDB.id"
    )
    attachments = relationship(
        "AttachmentDB", back_populates="visit", cascade="all, delete-orphan", order_by="AttachmentDB.id"
    )
    # Vaccinations recorded with a visit are removed if that visit is deleted.
    vaccinations = relationship("VaccinationDB", back_populates="visit", cascade="all, delete")


class DrugDB(Base):
    """Catalog of drugs for quick prescription entry."""

    __tablename__ = "drugs"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)  # Latin name
    drug_form = Column(String)  # e.g. tablet, injection
    prescribed_form = Column(String)
    default_dosage = Column(String)
    notes = Column(Text)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class MedicationDB(Base):
    __tablename__ = "visit_medications"
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey("clinic_visits.id"), nullable=False)
    drug_id = Column(Integer, ForeignKey("drugs.id"))
    dosage_instructions = Column(String)
    drug_name = Column(String, nullable=False)
    prescribed_form = Column(String)
    quantity = Column(String)
    drug_form = Column(String)

    visit = relationship("ClinicVisitDB", back_populates="medications")
    drug = relationship("DrugDB")


class VisitCostDB(Base):
    __tablename__ = "visit_costs"
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey("clinic_visits.id"), nullable=False)
    test_id = Column(Integer, ForeignKey("lab_tests.id"))
    description = Column(String, nullable=False)
    tariff = Column(BigInteger, nullable=False, default=0)
    quantity = Column(Integer, nullable=False, default=1)
    total = Column(BigInteger, nullable=False, default=0)

    visit = relationship("ClinicVisitDB", back_populates="costs")
    test = relationship("LabTestDB")


# ---------------------------------------------------------------- vaccines

class VaccineTypeDB(Base):
    """A vaccine or preventive treatment with its repeat interval (editable on the Catalogs page)."""

    __tablename__ = "vaccine_types"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True)  # set for the built-in types that map to the original form fields
    name = Column(String, nullable=False)
    interval_days = Column(Integer, nullable=False, default=365)
    # Comma-separated words matched against the animal type, e.g. "dog, سگ". Empty = all animals.
    species = Column(String)
    active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    def applies_to(self, animal_type: str | None) -> bool:
        words = [w.strip().lower() for w in (self.species or "").split(",") if w.strip()]
        if not words:
            return True
        animal = (animal_type or "").lower()
        return any(w in animal for w in words)


class VaccinationDB(Base):
    __tablename__ = "vaccinations"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    vaccine_type_id = Column(Integer, ForeignKey("vaccine_types.id"), nullable=False)
    date = Column(Date, nullable=False)
    administered = Column(Boolean, default=False, nullable=False)  # given here vs reported by the owner
    visit_id = Column(Integer, ForeignKey("clinic_visits.id", ondelete="SET NULL"))
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    patient = relationship("PatientDB", back_populates="vaccinations")
    vaccine_type = relationship("VaccineTypeDB")
    visit = relationship("ClinicVisitDB", back_populates="vaccinations")


class ReminderContactDB(Base):
    """Records that the owner was contacted about a specific due vaccine."""

    __tablename__ = "reminder_contacts"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    vaccine_type_id = Column(Integer, ForeignKey("vaccine_types.id", ondelete="CASCADE"), nullable=False)
    due_date = Column(Date, nullable=False)
    contacted_at = Column(DateTime, default=datetime.now, nullable=False)
    note = Column(String)


# ---------------------------------------------------------------- attachments & appointments

class AttachmentDB(Base):
    """An uploaded file (X-ray, sonography image, PDF report...) stored in the database."""

    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey("clinic_visits.id"))
    lab_order_id = Column(Integer, ForeignKey("lab_orders.id"))
    filename = Column(String, nullable=False)
    content_type = Column(String)
    size = Column(Integer, default=0, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))
    uploaded_at = Column(DateTime, default=datetime.now, nullable=False)

    visit = relationship("ClinicVisitDB", back_populates="attachments")
    lab_order = relationship("LabOrderDB", back_populates="attachments")

    @property
    def is_image(self) -> bool:
        return (self.content_type or "").startswith("image/")


class AppointmentDB(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"))
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"))
    contact_name = Column(String)
    contact_phone = Column(String)
    start_at = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer, default=30, nullable=False)
    reason = Column(String)
    status = Column(String, default="scheduled", nullable=False)
    visit_id = Column(Integer, ForeignKey("clinic_visits.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    owner = relationship("OwnerDB")
    patient = relationship("PatientDB")
