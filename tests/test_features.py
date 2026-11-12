from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from core import appointments, backup, reports, services, vaccines
from core.database import Base, add_missing_columns
from core.models import ReminderContactDB, VaccinationDB
from core.sci import plain
from core.receipts import clinic_visit_html, lab_order_html, lab_results_html

OWNER = {"name": "Ali", "surname": "Rezaei", "telephone": "09120000000"}
TODAY = date.today()


@pytest.fixture
def types(session):
    vaccines.seed_vaccine_types(session)
    return {vt.code: vt for vt in vaccines.list_vaccine_types(session)}


def make_patient(session, name="Pishi", animal_type="Cat"):
    owner = services.save_owner(session, OWNER)
    return services.save_patient(session, owner, {"name": name, "animal_type": animal_type})


# ---------------------------------------------------------------- vaccines

def test_seed_is_idempotent(session, types):
    vaccines.seed_vaccine_types(session)
    assert len(vaccines.list_vaccine_types(session)) == 3
    assert types["deworming"].interval_days == 90


def test_due_reminders_overdue_soon_and_ok(session, types):
    overdue = make_patient(session, "Overdue")
    soon = make_patient(session, "Soon")
    fine = make_patient(session, "Fine")
    vaccines.record_vaccination(session, overdue.id, types["rabies"].id, TODAY - timedelta(days=400))
    vaccines.record_vaccination(session, soon.id, types["rabies"].id, TODAY - timedelta(days=355))
    vaccines.record_vaccination(session, fine.id, types["rabies"].id, TODAY - timedelta(days=10))

    reminders = vaccines.due_reminders(session)
    assert [(r.patient.name, r.status) for r in reminders] == [("Overdue", "overdue"), ("Soon", "due_soon")]
    assert reminders[0].days_left == -35
    assert reminders[1].due_date == TODAY + timedelta(days=10)


def test_latest_dose_wins_and_inactive_patients_are_skipped(session, types):
    p = make_patient(session)
    vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY - timedelta(days=400))
    vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY - timedelta(days=5))
    assert vaccines.due_reminders(session) == []

    q = make_patient(session, "Gone")
    vaccines.record_vaccination(session, q.id, types["deworming"].id, TODAY - timedelta(days=100))
    assert len(vaccines.due_reminders(session)) == 1
    services.save_patient(session, q.owner, {"active": False}, q.id)
    assert vaccines.due_reminders(session) == []


def test_changing_interval_changes_due_date(session, types):
    p = make_patient(session)
    vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY - timedelta(days=200))
    assert vaccines.due_reminders(session) == []
    vaccines.update_vaccine_type(session, types["rabies"].id, interval_days=180)
    assert vaccines.due_reminders(session)[0].days_left == -20


def test_contacted_reminders(session, types):
    p = make_patient(session)
    vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY - timedelta(days=370))
    reminder = vaccines.due_reminders(session)[0]
    vaccines.mark_contacted(session, p.id, types["rabies"].id, reminder.due_date, "will come Saturday")
    reminder = vaccines.due_reminders(session)[0]
    assert reminder.contact is not None and reminder.contact.note == "will come Saturday"
    assert vaccines.due_reminders(session, include_contacted=False) == []
    vaccines.unmark_contacted(session, p.id, types["rabies"].id, reminder.due_date)
    assert vaccines.due_reminders(session)[0].contact is None


def test_new_dose_clears_old_contact(session, types):
    p = make_patient(session)
    vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY - timedelta(days=370))
    vaccines.mark_contacted(session, p.id, types["rabies"].id, vaccines.due_reminders(session)[0].due_date)
    vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY - timedelta(days=360))
    assert vaccines.due_reminders(session)[0].contact is None  # a new due date needs a new call


def test_patient_status_and_species_filter(session, types):
    vaccines.add_vaccine_type(session, "Kennel cough", 365, species="dog, سگ")
    cat = make_patient(session, "Pishi", "Cat")
    dog = make_patient(session, "Rex", "سگ")
    vaccines.record_vaccination(session, cat.id, types["rabies"].id, TODAY - timedelta(days=1))
    cat_status = {s.vaccine_type.name: s.status for s in vaccines.patient_vaccine_status(session, cat)}
    dog_status = {s.vaccine_type.name for s in vaccines.patient_vaccine_status(session, dog)}
    assert cat_status["Rabies (هاری)"] == "ok"
    assert cat_status["Deworming (انگل زدایی)"] == "no_record"
    assert "Kennel cough" not in cat_status
    assert "Kennel cough" in dog_status


def test_vaccination_validation(session, types):
    p = make_patient(session)
    with pytest.raises(ValueError):
        vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY + timedelta(days=1))
    with pytest.raises(ValueError):
        vaccines.add_vaccine_type(session, "X", 0)
    first = vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY)
    again = vaccines.record_vaccination(session, p.id, types["rabies"].id, TODAY, administered=True)
    assert first is again and again.administered


def test_clinic_visit_records_vaccinations(session, types):
    visit = services.create_clinic_visit(
        session, OWNER, {"name": "Pishi"}, {"visit_date": TODAY},
        vaccinations=[
            {"vaccine_type_id": types["rabies"].id, "administered": True},
            {"vaccine_type_id": types["deworming"].id, "date": TODAY - timedelta(days=30)},
            {"vaccine_type_id": types["polyvalent"].id, "date": None},
        ],
    )
    recorded = {v.vaccine_type.code: v for v in visit.patient.vaccinations}
    assert set(recorded) == {"rabies", "deworming"}
    assert recorded["rabies"].administered and recorded["rabies"].date == TODAY
    assert visit.rabies_vaccine_date == TODAY  # legacy column kept in sync
    assert "تزریق در کلینیک" in clinic_visit_html(services.get_clinic_visit(session, visit.id))
    services.delete_clinic_visit(session, visit.id)
    assert session.query(VaccinationDB).count() == 0


def test_backfill_from_legacy_columns(session, types):
    services.create_clinic_visit(session, OWNER, {"name": "P"}, {"rabies_vaccine_date": TODAY - timedelta(days=5)})
    assert vaccines.backfill_from_visits(session) == 1
    assert vaccines.backfill_from_visits(session) == 0


# ---------------------------------------------------------------- lab result templates

def test_result_template_values_and_flags(session):
    cbc = services.add_test(session, "CBC", "Complete blood count", 500_000)
    services.set_test_parameters(session, cbc.id, [
        {"name": "WBC", "unit": "10^3/µL", "ref_low": 6, "ref_high": 17},
        {"name": "HCT", "unit": "%", "ref_low": "37", "ref_high": "55"},
        {"name": "", "unit": "ignored"},
    ])
    order = services.create_lab_order(session, OWNER, {}, [{"test_id": cbc.id}])
    values = {v.name: v for v in order.items[0].values}
    assert set(values) == {"WBC", "HCT"}
    services.update_lab_results(session, order.id, {}, values={values["WBC"].id: "20", values["HCT"].id: "40"})
    assert values["WBC"].flag == "H" and values["HCT"].flag == "" and values["WBC"].reference == "6 – 17"
    html = lab_results_html(services.get_lab_order(session, order.id))
    assert "WBC" in html and "6 – 17" in html
    assert "▲" not in html and "وضعیت" not in html  # H / L flags are shown in the app only, not printed


def test_reference_standard_and_permitted_limit_on_results(session):
    culture = services.add_test(session, "CUL", "Culture", 1)
    services.set_test_parameters(session, culture.id, [
        {"name": "Count", "unit": "CFU/g", "ref_high": "1x10^5", "standard": " ISO 4833-1 "},
        {"name": "pH", "ref_low": 5},
    ])
    assert culture.parameters[0].standard == "ISO 4833-1" and culture.parameters[1].standard is None
    order = services.create_lab_order(session, OWNER, {}, [{"test_id": culture.id}])
    count, ph = order.items[0].values
    assert count.standard == "ISO 4833-1"                      # copied from the template
    assert plain(count.reference) == "≤ 1 × 10⁵" and ph.reference == "≥ 5"   # one-sided limits
    # the standard can be changed for this admission only; the template keeps its own
    services.update_lab_results(session, order.id, {}, standards={ph.id: "استاندارد ملی ۲۹۴۶", count.id: float("nan")})
    assert ph.standard == "استاندارد ملی ۲۹۴۶" and count.standard is None
    assert culture.parameters[1].standard is None
    html = lab_results_html(order, print_button=False)
    assert "<th>حد مجاز</th><th>استاندارد مرجع</th>" in html and "محدوده مرجع" not in html
    assert "استاندارد ملی ۲۹۴۶" in html
    assert "<div>انجام دهنده آزمایش</div><div>مهر و امضای مسئول آزمایشگاه</div>" in html
    assert "<div>تاریخ</div>" not in html
    assert "#999" not in html                                   # dark lines that survive scanning


def test_template_edits_keep_history(session):
    cbc = services.add_test(session, "CBC", "Complete blood count", 1)
    params = services.set_test_parameters(session, cbc.id, [{"name": "WBC", "ref_low": 6, "ref_high": 17}])
    order = services.create_lab_order(session, OWNER, {}, [{"test_id": cbc.id}])
    # rename one parameter, drop nothing, add one
    services.set_test_parameters(session, cbc.id, [
        {"id": params[0].id, "name": "WBC count", "ref_low": 5, "ref_high": 15}, {"name": "RBC"},
    ])
    assert [p.name for p in cbc.parameters] == ["WBC count", "RBC"]
    assert order.items[0].values[0].name == "WBC"  # the old order keeps its copy
    services.set_test_parameters(session, cbc.id, [])
    assert cbc.parameters == [] and order.items[0].values[0].parameter_id is None
    with pytest.raises(ValueError):
        services.set_test_parameters(session, cbc.id, [{"name": "X", "ref_low": 10, "ref_high": 1}])
    with pytest.raises(ValueError):
        services.set_test_parameters(session, cbc.id, [{"name": "X", "ref_low": "abc"}])


def test_ensure_result_values_for_template_added_later(session):
    test = services.add_test(session, "UA", "Urinalysis", 1)
    order = services.create_lab_order(session, OWNER, {}, [{"test_id": test.id}])
    assert order.items[0].values == []
    services.set_test_parameters(session, test.id, [{"name": "pH"}])
    assert services.ensure_result_values(session, order.id) == 1
    assert services.ensure_result_values(session, order.id) == 0


def test_non_numeric_value_has_no_flag(session):
    test = services.add_test(session, "X", "X", 1)
    services.set_test_parameters(session, test.id, [{"name": "Colour", "ref_low": 1, "ref_high": 2}])
    order = services.create_lab_order(session, OWNER, {}, [{"test_id": test.id}])
    value = order.items[0].values[0]
    services.update_lab_results(session, order.id, {}, values={value.id: "yellow"})
    assert value.flag == ""


# ---------------------------------------------------------------- drugs

def test_drug_catalog(session):
    amox = services.add_drug(session, "Amoxicillin", drug_form="Tablet", default_dosage="1 tab q12h")
    with pytest.raises(ValueError):
        services.add_drug(session, "amoxicillin")
    services.create_clinic_visit(session, OWNER, {"name": "P"}, {},
                                 medications=[{"drug_id": amox.id, "drug_name": "Amoxicillin"}])
    with pytest.raises(ValueError):
        services.delete_drug(session, amox.id)
    services.update_drug(session, amox.id, active=False)
    assert services.list_drugs(session, active_only=True) == []
    unused = services.add_drug(session, "Meloxicam")
    services.delete_drug(session, unused.id)
    assert [d.name for d in services.list_drugs(session)] == ["Amoxicillin"]


# ---------------------------------------------------------------- attachments

def test_attachments(session):
    visit = services.create_clinic_visit(
        session, OWNER, {"name": "P"}, {},
        attachments=[{"filename": "xray.png", "data": b"\x89PNG...", "content_type": "image/png"}],
    )
    att = services.get_clinic_visit(session, visit.id).attachments[0]
    assert att.is_image and att.size == 7
    assert services.get_attachment_data(session, att.id) == b"\x89PNG..."
    order = services.create_lab_order(session, OWNER, {}, [{"test_name": "A", "fee": 1}])
    services.add_attachment(session, "report.pdf", b"%PDF", "application/pdf", lab_order_id=order.id)
    assert len(services.get_lab_order(session, order.id).attachments) == 1
    with pytest.raises(ValueError):
        services.add_attachment(session, "empty.txt", b"", visit_id=visit.id)
    with pytest.raises(ValueError):
        services.add_attachment(session, "orphan.txt", b"x")
    services.delete_attachment(session, att.id)
    assert services.get_clinic_visit(session, visit.id).attachments == []


# ---------------------------------------------------------------- appointments

def test_appointments_and_conflicts(session):
    owner = services.save_owner(session, OWNER)
    nine = datetime.combine(TODAY, datetime.min.time()).replace(hour=9)
    a = appointments.create_appointment(session, nine, 30, "Vaccine", owner_id=owner.id)
    appointments.create_appointment(session, nine + timedelta(days=1), 30, contact_name="Walk-in")
    assert [x.id for x in appointments.list_appointments(session, TODAY)] == [a.id]
    assert len(appointments.list_appointments(session, TODAY, TODAY + timedelta(days=1))) == 2
    assert appointments.find_conflicts(session, nine + timedelta(minutes=15), 30) == [a]
    assert appointments.find_conflicts(session, nine + timedelta(minutes=30), 30) == []
    appointments.set_status(session, a.id, "cancelled")
    assert appointments.find_conflicts(session, nine, 30) == []
    assert appointments.display_name(a) == "Ali Rezaei"
    with pytest.raises(ValueError):
        appointments.create_appointment(session, nine, 30)  # no client and no name
    with pytest.raises(ValueError):
        appointments.set_status(session, a.id, "bogus")


def test_followup_appointment_from_visit(session):
    when = datetime.combine(TODAY + timedelta(days=7), datetime.min.time()).replace(hour=10)
    visit = services.create_clinic_visit(session, OWNER, {"name": "P"}, {}, appointment_at=when)
    appts = appointments.list_appointments(session, when.date())
    assert len(appts) == 1 and appts[0].patient_id == visit.patient_id


# ---------------------------------------------------------------- weight

def test_visit_weight_updates_patient(session):
    visit = services.create_clinic_visit(session, OWNER, {"name": "P", "weight": "4"}, {"weight": "4.5"})
    assert visit.weight == "4.5" and visit.patient.weight == "4.5"


# ---------------------------------------------------------------- reports

def test_report_summary_and_excel(session):
    cbc = services.add_test(session, "CBC", "Complete blood count", 500_000)
    services.create_lab_order(session, OWNER, {}, [{"test_id": cbc.id, "quantity": 2}])
    services.create_clinic_visit(session, OWNER, {"name": "P"}, {},
                                 costs=[{"test_id": cbc.id}, {"description": "Exam", "tariff": 200_000}])
    report = reports.summary(session, TODAY - timedelta(days=6), TODAY)
    assert report["lab_total"] == 1_000_000 and report["clinic_total"] == 700_000
    assert len(report["daily"]) == 7 and report["daily"]["lab"].sum() == 1_000_000
    assert report["top_tests"].iloc[0].to_dict() == {"test": "Complete blood count", "count": 3, "revenue": 1_500_000}
    assert report["new_clients"] == 2
    xlsx = reports.to_excel(report)
    assert xlsx[:2] == b"PK"
    with pytest.raises(ValueError):
        reports.summary(session, TODAY, TODAY - timedelta(days=1))


def test_empty_report(session):
    report = reports.summary(session, TODAY, TODAY)
    assert report["total"] == 0 and report["top_tests"].empty
    assert reports.to_excel(report)[:2] == b"PK"


# ---------------------------------------------------------------- backup

def test_backup_roundtrip(session, types, tmp_path):
    engine = session.get_bind()
    visit = services.create_clinic_visit(
        session, OWNER, {"name": "Pishi"}, {"vitals": {"T": "38"}, "followup_date": TODAY},
        attachments=[{"filename": "a.png", "data": b"\x00\x01binary", "content_type": "image/png"}],
        vaccinations=[{"vaccine_type_id": types["rabies"].id, "administered": True}],
    )
    session.commit()
    data = backup.export_backup(engine)
    assert backup.read_backup_info(data)["counts"]["clinic_visits"] == 1

    services.delete_clinic_visit(session, visit.id)
    services.save_owner(session, {"name": "Someone else"})
    session.commit()
    session.expunge_all()

    counts = backup.restore_backup(engine, data)
    assert counts["owners"] == 1 and counts["attachments"] == 1
    restored = services.get_clinic_visit(session, visit.id)
    assert restored.vitals == {"T": "38"} and restored.followup_date == TODAY
    assert services.get_attachment_data(session, restored.attachments[0].id) == b"\x00\x01binary"
    assert [o.full_name for o in services.search_owners(session, "")] == ["Ali Rezaei"]
    # new rows still get fresh ids after a restore
    assert services.save_owner(session, {"name": "New"}).id > restored.patient.owner_id
    with pytest.raises(ValueError):
        backup.restore_backup(engine, b"not a zip")


def test_auto_backup_once_per_day_and_pruning(session, tmp_path):
    engine = session.get_bind()
    assert backup.auto_backup(engine, tmp_path, keep=2, today=date(2026, 1, 1)) is not None
    assert backup.auto_backup(engine, tmp_path, keep=2, today=date(2026, 1, 1)) is None
    backup.auto_backup(engine, tmp_path, keep=2, today=date(2026, 1, 2))
    backup.auto_backup(engine, tmp_path, keep=2, today=date(2026, 1, 3))
    assert [p.name for p in backup.list_backups(tmp_path)] == ["vetclinic-2026-01-03.zip", "vetclinic-2026-01-02.zip"]


# ---------------------------------------------------------------- migration

def test_add_missing_columns_upgrades_old_tables():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:  # an "old" patients table without the new `active` column
        conn.execute(text("CREATE TABLE patients (id INTEGER PRIMARY KEY, owner_id INTEGER, file_number VARCHAR, "
                          "name VARCHAR, created_at DATETIME)"))
        conn.execute(text("INSERT INTO patients (id, owner_id, name, created_at) VALUES (1, 1, 'Old', '2026-01-01')"))
    added = add_missing_columns(engine)
    assert "patients.active" in added and "patients.weight" in added
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT active FROM patients WHERE id = 1")).scalar() == 1
    assert add_missing_columns(engine) == []
    assert "active" in {c["name"] for c in inspect(engine).get_columns("patients")}
    sessionmaker(bind=engine)().close()


def test_reminder_contact_model_exists(session):
    assert session.query(ReminderContactDB).count() == 0


def test_lab_sheets_print_landscape(session):
    test = services.add_test(session, "CUL", "Culture", 1)
    order = services.create_lab_order(session, OWNER, {}, [{"test_id": test.id}])
    assert "size: A4 landscape" in lab_results_html(order) and "size: A4 landscape" in lab_order_html(order)
    from core import receipts
    assert "landscape" not in receipts._page("Visit", "")    # other receipts stay portrait
