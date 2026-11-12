"""Printable HTML receipts for lab admissions and clinic visits."""

import os
import re
from html import escape

from core.jalali import to_jalali
from core.models import ClinicVisitDB, LabOrderDB

CLINIC_NAME = os.environ.get("VETCLINIC_NAME", "کلینیک دامپزشکی")

_STYLE = """
body { font-family: Tahoma, 'Vazirmatn', sans-serif; direction: rtl; margin: 24px; color: #111; }
h1 { font-size: 20px; margin: 0; } h2 { font-size: 15px; margin: 18px 0 6px; }
.head { display: flex; justify-content: space-between; border-bottom: 2px solid #000; padding-bottom: 8px; }
table { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 13px; }
/* Black lines: grey ones print faintly and disappear when the sheet is scanned or photocopied. */
th, td { border: 1px solid #000; padding: 4px 6px; text-align: right; vertical-align: top; }
th { background: #e6e6e6; font-weight: bold; } .meta td { border: none; padding: 2px 6px; }
.total { font-weight: bold; font-size: 15px; margin-top: 10px; }
.pre { white-space: pre-wrap; }
.params { margin: 4px 0 10px; }
.result-text { border: 1px solid #000; padding: 6px 8px; white-space: pre-wrap; font-size: 13px; }
.sign { margin-top: 48px; display: flex; justify-content: space-between; font-size: 13px; }
.sign div { min-width: 220px; border-top: 1px solid #000; padding-top: 4px; text-align: center; }
@page { size: A4; margin: 14mm; }
@media print { button { display: none; } body { margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; } h2 { break-after: avoid; } table { break-inside: avoid; } }
"""


# "5 × 10⁴" is made of numbers and neutral symbols, so inside right-to-left text the browser would print it
# as "10⁴ × 5". Isolating each such number as left-to-right keeps it in the order it was typed.
_SCI = re.compile(r"\d+(?:[.,]\d+)?\s×\s10[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+")


def _e(value) -> str:
    if value in (None, ""):
        return "-"
    return _SCI.sub(lambda m: f'<bdi dir="ltr">{m.group(0)}</bdi>', escape(str(value)))


def _ltr(value) -> str:
    """A cell that always reads left to right: units and limits such as "6 – 17" or "≤ 1 × 10⁵"."""
    return f'<bdi dir="ltr">{_e(value)}</bdi>'


# Lab sheets hold a few tests at most, so a landscape page fits them and gives the tables room.
_LANDSCAPE = """
@page { size: A4 landscape; margin: 10mm 12mm; }
.head { padding-bottom: 6px; } .meta { margin-top: 4px; }
h2 { margin: 10px 0 3px; } .params { margin: 2px 0 4px; } th, td { padding: 3px 6px; }
.sign { margin-top: 30px; break-inside: avoid; }
"""


def _page(title: str, body: str, print_button: bool = True, landscape: bool = False) -> str:
    button = '<button onclick="window.print()">چاپ / Print</button>' if print_button else ""
    style = _STYLE + (_LANDSCAPE if landscape else "")
    return (
        f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title><style>{style}</style></head><body>"
        f"{button}{body}</body></html>"
    )


def lab_results_html(order: LabOrderDB, print_button: bool = True) -> str:
    """The results report handed to the client: details and results only, no fees."""
    owner, patient = order.owner, order.patient
    animal = "-"
    if patient:
        kind = " / ".join(x for x in (patient.animal_type, patient.breed) if x)
        animal = f"{_e(patient.name)}{f' ({_e(kind)})' if kind else ''} — پرونده {_e(patient.file_number)}"
    sections = []
    for item in order.items:
        part = f"<h2>{_e(item.test_name)}{f' <small>({_e(item.code)})</small>' if item.code else ''}</h2>"
        if item.values:
            part += (
                "<table class='params'><tr><th>پارامتر</th><th>نتیجه</th><th>واحد</th>"
                "<th>حد مجاز</th><th>استاندارد مرجع</th></tr>"
                + "".join(
                    f"<tr><td>{_e(v.name)}</td><td><bdi>{_e(v.value)}</bdi></td><td>{_ltr(v.unit)}</td>"
                    f"<td>{_ltr(v.reference)}</td><td><bdi>{_e(v.standard)}</bdi></td></tr>"
                    for v in item.values
                )
                + "</table>"
            )
        if item.result or not item.values:
            label = "توضیح" if item.values else "نتیجه"
            part += f"<div><b>{label}:</b></div><div class='result-text'><bdi>{_e(item.result)}</bdi></div>"
        sections.append(part)
    body = f"""
    <div class="head"><h1>{escape(CLINIC_NAME)} — جواب آزمایش</h1>
      <div>شماره پذیرش: <b>{order.id}</b></div></div>
    <table class="meta">
      <tr><td>نام صاحب حیوان: {_e(owner.full_name)}</td><td>تلفن: {_e(owner.telephone)}</td>
          <td>حیوان: {animal}</td></tr>
      <tr><td>نوع نمونه: {_e(order.sample_type)}</td><td>تعداد نمونه: {_e(order.sample_qty)}</td>
          <td>تاریخ نمونه برداری: {_e(to_jalali(order.date_sampling))}</td></tr>
      <tr><td>تاریخ پذیرش: {_e(to_jalali(order.date_admission))}</td>
          <td>تاریخ جوابدهی: {_e(to_jalali(order.date_response))}</td><td></td></tr>
    </table>
    {"".join(sections)}
    <div class="sign"><div>انجام دهنده آزمایش</div><div>مهر و امضای مسئول آزمایشگاه</div></div>
    """
    return _page(f"Lab results {order.id}", body, print_button, landscape=True)


def lab_order_html(order: LabOrderDB) -> str:
    """The admission sheet printed when a sample is admitted: tests and fees only.
    Results are not out yet at that point; they are printed later with `lab_results_html`."""
    owner = order.owner
    rows = "".join(
        f"<tr><td>{n}</td><td>{_e(i.code)}</td><td>{_e(i.test_name)}</td><td>{i.fee:,}</td>"
        f"<td>{i.quantity}</td><td>{i.price:,}</td></tr>"
        for n, i in enumerate(order.items, 1)
    )
    animal = f"{_e(order.patient.name)} (پرونده {_e(order.patient.file_number)})" if order.patient else "-"
    body = f"""
    <div class="head"><h1>برگه پذیرش</h1>
      <div>شماره پذیرش: <b>{order.id}</b></div></div>
    <table class="meta">
      <tr><td>نام: {_e(owner.full_name)}</td><td>تلفن: {_e(owner.telephone)}</td><td>آدرس: {_e(owner.address)}</td></tr>
      <tr><td>حیوان: {animal}</td><td>نوع نمونه: {_e(order.sample_type)}</td><td>تعداد نمونه: {_e(order.sample_qty)}</td></tr>
      <tr><td>تاریخ نمونه برداری: {_e(to_jalali(order.date_sampling))}</td>
          <td>تاریخ پذیرش: {_e(to_jalali(order.date_admission))}</td>
          <td>تاریخ جوابدهی: {_e(to_jalali(order.date_response))}</td></tr>
      <tr><td colspan="3">غیره: {_e(order.other)}</td></tr>
    </table>
    <h2>آزمایش‌ها</h2>
    <table><tr><th>ردیف</th><th>کد</th><th>نام آزمایش</th><th>هزینه</th><th>تعداد</th><th>مبلغ</th></tr>{rows}</table>
    <div class="total">جمع کل: {order.total:,} ریال</div>
    """
    return _page("برگه پذیرش", body, landscape=True)


def clinic_visit_html(visit: ClinicVisitDB) -> str:
    patient, owner = visit.patient, visit.patient.owner
    meds = "".join(
        f"<tr><td>{_e(m.drug_name)}</td><td>{_e(m.prescribed_form)}</td><td>{_e(m.drug_form)}</td>"
        f"<td>{_e(m.quantity)}</td><td>{_e(m.dosage_instructions)}</td></tr>"
        for m in visit.medications
    ) or "<tr><td colspan='5'>-</td></tr>"
    costs = "".join(
        f"<tr><td>{_e(c.description)}</td><td>{c.tariff:,}</td><td>{c.quantity}</td><td>{c.total:,}</td></tr>"
        for c in visit.costs
    ) or "<tr><td colspan='4'>-</td></tr>"
    vitals = visit.vitals or {}
    vaccinations = ", ".join(
        f"{escape(v.vaccine_type.name)} ({to_jalali(v.date)}{' — تزریق در کلینیک' if v.administered else ''})"
        for v in visit.vaccinations
    ) or "-"
    body = f"""
    <div class="head"><h1>{escape(CLINIC_NAME)} — پرونده مطب</h1>
      <div>شماره پرونده: <b>{_e(patient.file_number)}</b> | تاریخ: {_e(to_jalali(visit.visit_date))}</div></div>
    <table class="meta">
      <tr><td>صاحب حیوان: {_e(owner.full_name)}</td><td>تلفن: {_e(owner.telephone)}</td><td>آدرس: {_e(owner.address)}</td></tr>
      <tr><td>نام حیوان: {_e(patient.name)}</td><td>نوع: {_e(patient.animal_type)} / {_e(patient.breed)}</td>
          <td>جنسیت: {_e(patient.gender)} | سن: {_e(patient.age)} | وزن: {_e(visit.weight or patient.weight)}</td></tr>
      <tr><td colspan="3">T: {_e(vitals.get('T'))} &nbsp; HR: {_e(vitals.get('HR'))} &nbsp;
          PR: {_e(vitals.get('PR'))} &nbsp; RR: {_e(vitals.get('RR'))}</td></tr>
    </table>
    <h2>علت مراجعه</h2><div class="pre">{_e(visit.reason_for_visit)}</div>
    <h2>واکسن و انگل زدایی</h2><div>{vaccinations}</div>
    <h2>تشخیص</h2><div class="pre">{_e(visit.diagnosis)}</div>
    <h2>نسخه</h2>
    <table><tr><th>نام دارو</th><th>فرم تجویز</th><th>شکل دارویی</th><th>تعداد</th><th>دستور مصرف</th></tr>{meds}</table>
    <h2>هزینه‌ها</h2>
    <table><tr><th>شرح خدمات</th><th>تعرفه</th><th>تعداد</th><th>جمع</th></tr>{costs}</table>
    <div class="total">جمع کل: {visit.total_cost:,} ریال</div>
    <div>تاریخ مراجعه بعدی: {_e(to_jalali(visit.followup_date))}</div>
    """
    return _page(f"Visit {visit.id}", body)
