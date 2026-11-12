from datetime import date, timedelta

import pytest

from core import services
from core.jalali import to_jalali
from core.receipts import clinic_visit_html, lab_order_html

OWNER = {"name": "Ali", "surname": "Rezaei", "telephone": "09120000000", "address": "Shiraz"}


def test_add_and_list_tests(session):
    services.add_test(session, "CBC", "Complete blood count", 500_000, category="Hematology")
    services.add_test(session, "UA", "Urinalysis", 300_000)
    assert {t.code for t in services.list_tests(session)} == {"CBC", "UA"}


def test_add_test_rejects_duplicate_code_and_blank_fields(session):
    services.add_test(session, "CBC", "Complete blood count", 500_000)
    with pytest.raises(ValueError):
        services.add_test(session, "CBC", "Other", 1)
    with pytest.raises(ValueError):
        services.add_test(session, "", "No code", 1)
    with pytest.raises(ValueError):
        services.add_test(session, "X", "Negative", -5)


def test_update_and_deactivate_test(session):
    test = services.add_test(session, "CBC", "Complete blood count", 500_000)
    services.update_test(session, test.id, default_fee=600_000, active=False)
    assert test.default_fee == 600_000
    assert services.list_tests(session, active_only=True) == []


def test_used_test_cannot_be_deleted(session):
    test = services.add_test(session, "CBC", "Complete blood count", 500_000)
    unused = services.add_test(session, "UA", "Urinalysis", 300_000)
    services.create_lab_order(session, OWNER, {}, [{"test_id": test.id, "quantity": 1}])
    with pytest.raises(ValueError):
        services.delete_test(session, test.id)
    services.delete_test(session, unused.id)
    assert [t.code for t in services.list_tests(session)] == ["CBC"]


def test_create_lab_order_uses_catalog_fee_and_snapshots(session):
    cbc = services.add_test(session, "CBC", "Complete blood count", 500_000)
    order = services.create_lab_order(
        session,
        OWNER,
        {"sample_type": "Blood", "date_sampling": date(2026, 10, 1)},
        [
            {"test_id": cbc.id, "quantity": 2},
            {"test_id": None, "test_name": "Custom culture", "fee": 250_000, "quantity": 1},
        ],
    )
    assert order.total == 1_250_000
    assert order.status == "pending"
    assert order.date_admission == date.today()
    # changing the catalog later must not rewrite the order
    services.update_test(session, cbc.id, name="Renamed", default_fee=1)
    assert order.items[0].test_name == "Complete blood count"
    assert order.items[0].price == 1_000_000


def test_lab_order_requires_items_and_owner(session):
    with pytest.raises(ValueError):
        services.create_lab_order(session, OWNER, {}, [])
    with pytest.raises(ValueError):
        services.create_lab_order(session, {"name": ""}, {}, [{"test_name": "x", "fee": 1}])


def test_existing_owner_is_reused_and_updated(session):
    first = services.create_lab_order(session, OWNER, {}, [{"test_name": "A", "fee": 1}])
    second = services.create_lab_order(
        session, {**OWNER, "address": "Tehran"}, {}, [{"test_name": "B", "fee": 1}], owner_id=first.owner.id
    )
    assert first.owner is second.owner
    assert second.owner.address == "Tehran"
    assert len(services.search_owners(session, "")) == 1


def test_update_lab_results(session):
    order = services.create_lab_order(session, OWNER, {}, [{"test_name": "A", "fee": 1}])
    item_id = order.items[0].id
    services.update_lab_results(session, order.id, {item_id: "Normal"}, status="completed", date_response=date(2026, 10, 3))
    assert order.items[0].result == "Normal"
    assert order.status == "completed"
    with pytest.raises(ValueError):
        services.update_lab_results(session, order.id, {}, status="bogus")


def test_clinic_visit_with_medications_and_costs(session):
    exam = services.add_test(session, "VIS", "Visit fee", 800_000)
    visit = services.create_clinic_visit(
        session,
        OWNER,
        {"name": "Pishi", "animal_type": "Cat"},
        {"visit_type": "first", "vitals": {"T": "38.5"}, "diagnosis": "Healthy",
         "followup_date": date.today() + timedelta(days=3)},
        medications=[{"drug_name": "Amoxicillin", "quantity": 1}],
        costs=[{"test_id": exam.id, "quantity": 1}, {"description": "Injection", "tariff": 100_000, "quantity": 2}],
    )
    assert visit.patient.file_number == str(services.FIRST_FILE_NUMBER)
    assert visit.total_cost == 1_000_000
    assert visit.vitals == {"T": "38.5"}
    assert services.upcoming_followups(session) == [visit]
    stats = services.dashboard_stats(session)
    assert stats["visits_today"] == 1 and stats["revenue_today"] == 1_000_000


def test_file_numbers_increment_and_must_be_unique(session):
    owner = services.save_owner(session, OWNER)
    p1 = services.save_patient(session, owner, {"name": "A"})
    p2 = services.save_patient(session, owner, {"name": "B"})
    assert int(p2.file_number) == int(p1.file_number) + 1
    with pytest.raises(ValueError):
        services.save_patient(session, owner, {"name": "C", "file_number": p1.file_number})


def test_search_by_phone_animal_name_and_full_name(session):
    services.create_clinic_visit(session, OWNER, {"name": "Pishi"}, {})
    assert len(services.search_owners(session, "0912")) == 1
    assert len(services.search_owners(session, "pishi")) == 1
    assert len(services.search_owners(session, "Ali Rezaei")) == 1
    assert services.search_owners(session, "nobody") == []


def test_receipts_render(session):
    order = services.create_lab_order(session, OWNER, {}, [{"test_name": "<b>A</b>", "fee": 1000}])
    html = lab_order_html(order)
    assert "&lt;b&gt;A&lt;/b&gt;" in html and "1,000" in html
    visit = services.create_clinic_visit(session, OWNER, {"name": "Pishi"}, {}, costs=[])
    assert "Pishi" in clinic_visit_html(visit)


def test_jalali_formatting():
    assert to_jalali(date(2026, 10, 2)) == "1405/07/10"
    assert to_jalali(None) == ""


def test_get_owner_is_usable_after_session_closes(session):
    visit = services.create_clinic_visit(session, OWNER, {"name": "Pishi"}, {})
    services.create_lab_order(session, OWNER, {}, [{"test_name": "A", "fee": 1}], owner_id=visit.patient.owner_id)
    session.commit()
    session.expunge_all()
    owner = services.get_owner(session, visit.patient.owner_id)
    session.close()  # the UI renders detached objects
    assert owner.patients[0].visits[0].patient.owner.full_name == "Ali Rezaei"
    assert owner.lab_orders[0].owner.full_name == "Ali Rezaei"
    assert owner.lab_orders[0].items[0].test_name == "A"


def test_turnaround_days_and_categories(session):
    cbc = services.add_test(session, "CBC", "Complete blood count", 1, category="Hematology", turnaround_days=1)
    culture = services.add_test(session, "CUL", "Culture", 1, category="Microbiology", turnaround_days=3)
    services.add_test(session, "GRAM", "Gram stain", 1, category=" Microbiology ")
    assert services.list_test_categories(session) == ["Hematology", "Microbiology"]
    assert culture.turnaround_days == 3
    services.update_test(session, cbc.id, turnaround_days=2.0)
    assert cbc.turnaround_days == 2
    services.update_test(session, cbc.id, turnaround_days=None)
    assert cbc.turnaround_days is None
    with pytest.raises(ValueError):
        services.add_test(session, "NEG", "Negative", 1, turnaround_days=-1)


def test_response_date_uses_longest_turnaround(session):
    from datetime import date
    quick = services.add_test(session, "A", "Quick", 1, turnaround_days=1)
    slow = services.add_test(session, "B", "Slow", 1, turnaround_days=3)
    unset = services.add_test(session, "C", "No turnaround", 1)
    admitted = date(2026, 10, 12)  # 1405/07/20
    assert services.response_date(admitted, [quick, slow, unset]) == date(2026, 10, 15)  # 1405/07/23
    assert services.response_date(admitted, [unset]) is None
    assert services.response_date(admitted, []) is None


def test_scientific_notation():
    from core.sci import LRI, PDI, format_number, format_scientific, parse_number, plain

    def f(text):
        return plain(format_scientific(text))

    assert f("5x10^4") == "5 × 10⁴"
    assert f("5 X 10^-3 CFU/g") == "5 × 10⁻³ CFU/g"
    assert f("2.5*10^+06") == "2.5 × 10⁶"
    assert f("5e4") == "5 × 10⁴"
    assert f("1.50E-3") == "1.5 × 10⁻³"
    assert f("10^3/uL") == "10³/uL"
    assert f("Growth of E. coli, 5x10^4 CFU/mL +/- 10%") == "Growth of E. coli, 5 × 10⁴ CFU/mL ± 10%"
    assert f("type 2e") == "type 2e"           # not a number in e-notation
    assert f("Negative") == "Negative"
    # kept left to right inside Persian text, and formatting twice changes nothing
    persian = format_scientific("رشد خالص 5x10^4 CFU/g")
    assert persian == f"رشد خالص {LRI}5 × 10⁴{PDI} CFU/g"
    assert format_scientific(persian) == persian
    assert parse_number("5 × 10⁴") == 50_000
    assert parse_number(format_scientific("5x10^4")) == 50_000
    assert parse_number("5x10^4") == 50_000
    assert parse_number("2,5") == 2.5
    assert parse_number("Negative") is None
    assert format_number(50_000) == "50000" and plain(format_number(1e6)) == "1 × 10⁶"
    assert format_number(12.5) == "12.5"


def test_scientific_results_are_saved_and_flagged(session):
    culture = services.add_test(session, "CUL", "Culture", 1)
    services.set_test_parameters(session, culture.id, [
        {"name": "Bacterial count", "unit": "CFU/g", "ref_low": None, "ref_high": "1x10^5"},
    ])
    assert culture.parameters[0].ref_high == 100_000
    order = services.create_lab_order(session, OWNER, {}, [{"test_id": culture.id}])
    item = order.items[0]
    services.update_lab_results(session, order.id, {item.id: "Pure growth, 5x10^4 CFU/g"},
                                values={item.values[0].id: "5x10^6"})
    from core.sci import plain
    assert plain(item.result) == "Pure growth, 5 × 10⁴ CFU/g"
    assert plain(item.values[0].value) == "5 × 10⁶" and item.values[0].flag == "H"
    assert plain(item.values[0].reference).endswith("1 × 10⁵")
    from core.receipts import lab_results_html
    assert "<bdi dir=\"ltr\">5 × 10⁶</bdi>" in lab_results_html(order)


def test_lab_results_report_and_pdf(session):
    from core.pdf import find_browser, html_to_pdf
    from core.receipts import lab_results_html
    culture = services.add_test(session, "CUL", "Culture", 900_000)
    services.set_test_parameters(session, culture.id, [{"name": "Count", "unit": "CFU/g", "ref_high": "1x10^5"}])
    urine = services.add_test(session, "UA", "Urinalysis", 300_000)
    order = services.create_lab_order(session, OWNER, {"sample_type": "Feces"},
                                      [{"test_id": culture.id}, {"test_id": urine.id}])
    c_item, u_item = order.items
    services.update_lab_results(session, order.id, {u_item.id: "No abnormality"}, values={c_item.values[0].id: "5x10^6"})
    html = lab_results_html(order, print_button=False)
    assert "جواب آزمایش" in html and "Culture" in html and "No abnormality" in html and "≤ " in html and "1 × 10⁵" in html
    assert "900,000" not in html and "window.print()" not in html   # results only: no fees, no print button
    if find_browser() is None:
        pytest.skip("no Edge/Chrome on this machine")
    assert html_to_pdf(html).startswith(b"%PDF")


def test_admission_sheet_has_no_results_or_status(session):
    from core.receipts import lab_results_html
    test = services.add_test(session, "CUL", "Culture", 900_000)
    services.set_test_parameters(session, test.id, [{"name": "Count", "unit": "CFU/g"}])
    order = services.create_lab_order(session, OWNER, {"sample_type": "Feces"}, [{"test_id": test.id}])
    item = order.items[0]
    services.update_lab_results(session, order.id, {item.id: "Pure growth"}, status="completed",
                                values={item.values[0].id: "5x10^4"})
    html = lab_order_html(order)
    assert "<h1>برگه پذیرش</h1>" in html and "<title>برگه پذیرش</title>" in html
    assert "Culture" in html and "900,000" in html and "Feces" in html          # tests, fees and sample stay
    assert "نتیجه" not in html and "Pure growth" not in html and "10⁴" not in html  # no results
    assert "وضعیت" not in html and "جواب آماده" not in html                     # no request status
    # the results themselves are still saved and printed on the results report
    assert item.result == "Pure growth" and "Pure growth" in lab_results_html(order)
