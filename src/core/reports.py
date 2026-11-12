"""Revenue and activity reports, plus an Excel export."""

import io
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from core.jalali import to_jalali
from core.models import (
    ClinicVisitDB,
    LabOrderDB,
    OwnerDB,
    PatientDB,
    VaccinationDB,
)


def _orders(session: Session, start: date, end: date) -> list[LabOrderDB]:
    return list(session.scalars(
        select(LabOrderDB)
        .options(selectinload(LabOrderDB.owner), selectinload(LabOrderDB.items))
        .where(LabOrderDB.date_admission >= start, LabOrderDB.date_admission <= end)
        .order_by(LabOrderDB.date_admission, LabOrderDB.id)
    ))


def _visits(session: Session, start: date, end: date) -> list[ClinicVisitDB]:
    return list(session.scalars(
        select(ClinicVisitDB)
        .options(
            selectinload(ClinicVisitDB.patient).selectinload(PatientDB.owner),
            selectinload(ClinicVisitDB.costs),
        )
        .where(ClinicVisitDB.visit_date >= start, ClinicVisitDB.visit_date <= end)
        .order_by(ClinicVisitDB.visit_date, ClinicVisitDB.id)
    ))


def summary(session: Session, start: date, end: date) -> dict:
    if start > end:
        raise ValueError("The start date is after the end date. (تاریخ شروع بعد از تاریخ پایان است)")
    orders, visits = _orders(session, start, end), _visits(session, start, end)

    daily = defaultdict(lambda: {"lab": 0, "clinic": 0})
    day = start
    while day <= end:
        daily[day]  # every day appears, even with no revenue
        day += timedelta(days=1)
    for o in orders:
        daily[o.date_admission]["lab"] += o.total
    for v in visits:
        daily[v.visit_date]["clinic"] += v.total_cost
    daily_df = pd.DataFrame(
        [{"date": d, "jalali": to_jalali(d), "lab": x["lab"], "clinic": x["clinic"]} for d, x in sorted(daily.items())]
    )

    tests = defaultdict(lambda: {"count": 0, "revenue": 0})
    for o in orders:
        for i in o.items:
            tests[i.test_name]["count"] += i.quantity
            tests[i.test_name]["revenue"] += i.price
    for v in visits:
        for c in v.costs:
            if c.test_id:
                tests[c.description]["count"] += c.quantity
                tests[c.description]["revenue"] += c.total
    top_tests = pd.DataFrame(
        [{"test": name, **x} for name, x in tests.items()], columns=["test", "count", "revenue"]
    ).sort_values(["count", "revenue"], ascending=False, ignore_index=True)

    new_clients = session.scalar(
        select(func.count()).select_from(OwnerDB).where(
            func.date(OwnerDB.created_at) >= start, func.date(OwnerDB.created_at) <= end
        )
    )
    vaccinations = session.scalar(
        select(func.count()).select_from(VaccinationDB).where(
            VaccinationDB.administered.is_(True), VaccinationDB.date >= start, VaccinationDB.date <= end
        )
    )
    lab_total = sum(o.total for o in orders)
    clinic_total = sum(v.total_cost for v in visits)
    return {
        "start": start,
        "end": end,
        "lab_total": lab_total,
        "clinic_total": clinic_total,
        "total": lab_total + clinic_total,
        "lab_orders": len(orders),
        "clinic_visits": len(visits),
        "new_clients": new_clients or 0,
        "vaccinations_given": vaccinations or 0,
        "daily": daily_df,
        "top_tests": top_tests,
        "orders": orders,
        "visits": visits,
    }


def to_excel(report: dict) -> bytes:
    """Excel workbook with summary, daily revenue, lab orders, lab items, clinic visits and test counts."""
    summary_rows = [
        ("From (از)", to_jalali(report["start"])),
        ("To (تا)", to_jalali(report["end"])),
        ("Lab revenue (درآمد آزمایشگاه)", report["lab_total"]),
        ("Clinic revenue (درآمد مطب)", report["clinic_total"]),
        ("Total revenue (جمع کل)", report["total"]),
        ("Lab admissions (پذیرش آزمایشگاه)", report["lab_orders"]),
        ("Clinic visits (ویزیت مطب)", report["clinic_visits"]),
        ("New clients (مشتری جدید)", report["new_clients"]),
        ("Vaccinations given (واکسن تزریق شده)", report["vaccinations_given"]),
    ]
    orders = pd.DataFrame([{
        "order": o.id, "date": to_jalali(o.date_admission), "client": o.owner.full_name,
        "phone": o.owner.telephone, "sample": o.sample_type, "status": o.status,
        "total": o.total,
    } for o in report["orders"]])
    items = pd.DataFrame([{
        "order": o.id, "date": to_jalali(o.date_admission), "code": i.code, "test": i.test_name,
        "fee": i.fee, "quantity": i.quantity, "price": i.price, "result": i.result,
    } for o in report["orders"] for i in o.items])
    visits = pd.DataFrame([{
        "visit": v.id, "date": to_jalali(v.visit_date), "file": v.patient.file_number,
        "animal": v.patient.name, "owner": v.patient.owner.full_name, "diagnosis": v.diagnosis,
        "total": v.total_cost,
    } for v in report["visits"]])
    daily = report["daily"].drop(columns=["date"]).assign(total=lambda d: d["lab"] + d["clinic"])

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows, columns=["item", "value"]).to_excel(writer, sheet_name="Summary", index=False)
        daily.to_excel(writer, sheet_name="Daily", index=False)
        orders.to_excel(writer, sheet_name="Lab orders", index=False)
        items.to_excel(writer, sheet_name="Lab tests", index=False)
        visits.to_excel(writer, sheet_name="Clinic visits", index=False)
        report["top_tests"].to_excel(writer, sheet_name="Test counts", index=False)
        for sheet in writer.sheets.values():
            for column in sheet.columns:
                width = max((len(str(c.value)) for c in column if c.value is not None), default=8)
                sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 50)
    return buffer.getvalue()
