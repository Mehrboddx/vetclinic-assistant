from datetime import datetime, time

import streamlit as st

from core import services, vaccines
from core.database import get_session
from core.jalali import to_jalali
from core.models import PatientDB
from core.receipts import clinic_visit_html, lab_order_html
from ui.components import (
    VACCINE_STATUS,
    client_lookup,
    duplicate_phone_hint,
    fkey,
    flash,
    jalali_date_input,
    load_owner_by_phone,
    quick_add_drug,
    page_header,
    reset_form,
    rial,
    row_table,
    section_title,
    setup_page,
    show_flash,
    test_picker,
    uploaded_files,
)

setup_page()

page_header("Admission", "پذیرش", "Admit a laboratory sample or a clinic patient.")
show_flash()


def last_receipt(state_key: str, loader, renderer, label: str, button: str) -> None:
    record_id = st.session_state.get(state_key)
    if not record_id:
        return
    with get_session() as s:
        record = loader(s, record_id)
        html = renderer(record) if record else None
    if html:
        st.download_button(
            f"🖨 {button} #{record_id}",
            html,
            file_name=f"{label.lower().replace(' ', '_')}_{record_id}.html",
            mime="text/html",
        )


VISIT_KINDS = {"lab": "Laboratory (آزمایشگاه)", "clinic": "Clinic (مطب)"}
choice = st.segmented_control(
    "Visit Type (نوع ویزیت)", list(VISIT_KINDS), format_func=VISIT_KINDS.get, default="lab", required=True,
    key="admission_kind",
)

# ======================================================================
# Laboratory
# ======================================================================
if choice == "lab":
    P = "lab"
    last_receipt("last_lab_order", services.get_lab_order, lab_order_html, "Lab order",
                 "Download admission sheet (دریافت برگه پذیرش) — lab order")

    with st.container(border=True):
        section_title("Client & sample", "مشخصات مشتری و نمونه", 1)
        owner_fields = {"name": "name", "surname": "surname", "address": "address", "telephone": "telephone"}
        owner_clear = ("patient_pick",)
        owner_id = client_lookup(P, owner_fields, clear_widgets=owner_clear)
        col1, col2 = st.columns(2)
        name = col1.text_input("Name (نام)", key=fkey(P, "name"), autocomplete="off")
        surname = col2.text_input("Surname(نام خانوادگی)", key=fkey(P, "surname"), autocomplete="off")
        address = col1.text_input("Address (آدرس)", key=fkey(P, "address"), autocomplete="off")
        telephone = col2.text_input("Telephone (تلفن)", key=fkey(P, "telephone"), autocomplete="off",
                                    on_change=load_owner_by_phone, args=(P, owner_fields, owner_clear))
        sample_qty = col1.text_input("Sample Quantity (تعداد نمونه)", key=fkey(P, "sample_qty"), autocomplete="off")
        sample_type = col2.text_input(
            "Sample Type (نوع نمونه)", key=fkey(P, "sample_type"), placeholder="e.g. Blood, Serum, Urine (خون، سرم، ادرار)",
            autocomplete="off",
        )
        other = col1.text_input("Other (غیره)", key=fkey(P, "other"), autocomplete="off")
        duplicate_phone_hint(P, owner_id, telephone, owner_fields, owner_clear)

        patient_id = None
        if owner_id:
            with get_session() as s:
                animals = {p.id: f"{p.name or '-'} ({p.animal_type or '-'}) — file {p.file_number}"
                           for p in services.get_owner(s, owner_id).patients}
            if animals:
                patient_id = col2.selectbox(
                    "Animal, optional (حیوان)",
                    [None] + list(animals),
                    format_func=lambda i: "— not linked —" if i is None else animals[i],
                    key=fkey(P, "patient_pick"),
                )

        with get_session() as s:
            tests = services.list_tests(s, active_only=True)
        by_id = {t.id: t for t in tests}

        col3, col4 = st.columns(2)
        with col3:
            date_sampling = jalali_date_input("Date of Sampling (تاریخ نمونه برداری)", key=fkey(P, "date_sampling"))
            date_admission = jalali_date_input("Date of Admission (تاریخ پذیرش)", key=fkey(P, "date_admission"))
        with col4:
            # Admission date + the longest "days to result" of the selected tests. The picker's key includes
            # that date, so it refreshes whenever the tests or the admission date change.
            picked = [by_id.get(r["test_id"]) for r in st.session_state.get(P + "_rows", [])]
            auto_response = services.response_date(date_admission, picked)
            date_response = jalali_date_input(
                "Date of Response (تاریخ جوابدهی)", key=fkey(P, f"date_response_{auto_response}"),
                default_value=auto_response, optional=True,
            )
            if auto_response:
                slowest = max((t for t in picked if t and t.turnaround_days is not None),
                              key=lambda t: t.turnaround_days)
                st.caption(
                    f"Auto: admission + {slowest.turnaround_days} day(s) for {slowest.name}. You can change it. "
                    f"(محاسبه خودکار: تاریخ پذیرش + {slowest.turnaround_days} روز)"
                )

    with st.container(border=True):
        section_title("Tests", "آزمایش‌ها", 2)
        test_picker(fkey(P, "tests"), P + "_rows", tests)
        total = row_table(
            P + "_rows",
            {"code": "کد", "name": "نام آزمایش", "fee": "هزینه", "quantity": "تعداد", "price": "مبلغ"},
            total_column="price",
        )

    with st.container(border=True):
        section_title("Attachments", "پیوست‌ها", 3)
        lab_files = st.file_uploader(
            "Attachments: referral sheet, images... (پیوست‌ها)", accept_multiple_files=True, key=fkey(P, "files")
        )

    if st.button("Save lab admission (ثبت پذیرش آزمایشگاه)", type="primary", icon=":material/save:",
                 width="stretch"):
        rows = st.session_state.get(P + "_rows", [])
        try:
            with get_session() as s:
                order = services.create_lab_order(
                    s,
                    owner_data={"name": name, "surname": surname, "address": address, "telephone": telephone},
                    order_data={
                        "sample_qty": sample_qty, "sample_type": sample_type, "other": other,
                        "date_sampling": date_sampling, "date_admission": date_admission,
                        "date_response": date_response,
                    },
                    items=[{"test_id": r["test_id"], "code": r["code"], "test_name": r["name"],
                            "fee": r["fee"], "quantity": r["quantity"]} for r in rows],
                    owner_id=owner_id,
                    patient_id=patient_id,
                    attachments=uploaded_files(lab_files),
                )
                order_id = order.id
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["last_lab_order"] = order_id
            reset_form(P)
            flash(f"Lab admission #{order_id} saved — total {rial(total)}. (پذیرش ثبت شد)")
            st.rerun()

# ======================================================================
# Clinic
# ======================================================================
if choice == "clinic":
    P = "clinic"
    PATIENT_WIDGETS = {
        "file_number": "file_number", "animal_type": "animal_type", "gender": "gender", "breed": "breed",
        "name": "animal_name", "sterilized": "sterilized", "keeping_location": "keeping_location",
        "microchip": "microchip", "age": "animal_age", "weight": "animal_weight",
    }
    VISIT_TYPES = {
        "first": "First visit (بیمار نخستین بار مراجعه کرده است)",
        "followup": "Follow-up visit (مراجعه جهت پیگیری نتیجه درمانی)",
    }
    VACCINATION = {"complete": "Complete (کامل)", "incomplete": "Incomplete (ناقص)"}

    def load_patient() -> None:
        patient_id = st.session_state.get(fkey(P, "patient_pick"))
        st.session_state[P + "_patient_id"] = patient_id
        with get_session() as s:
            patient = s.get(PatientDB, patient_id) if patient_id else None
            for field, widget in PATIENT_WIDGETS.items():
                st.session_state[fkey(P, widget)] = (getattr(patient, field) or "") if patient else ""
        if patient_id:
            st.session_state[fkey(P, "visit_type")] = "followup"

    last_receipt("last_clinic_visit", services.get_clinic_visit, clinic_visit_html, "Clinic visit",
                 "Download receipt (دریافت رسید) — clinic visit")

    with st.container(border=True):
        section_title("Visit", "مراجعه", 1)
        col_date, col_file = st.columns(2)
        with col_date:
            visit_date = jalali_date_input("Date (تاریخ)", key=fkey(P, "visit_date"))
        file_number = col_file.text_input(
            "File Number (شماره پرونده)", key=fkey(P, "file_number"),
            help="Leave blank for a new patient to assign the next number automatically. (خالی = خودکار)",
            autocomplete="off",
        )

        visit_type = st.radio(
            "Visit Type (نوع مراجعه)", list(VISIT_TYPES), format_func=VISIT_TYPES.get, key=fkey(P, "visit_type"),
            horizontal=True,
        )

    with st.container(border=True):
        section_title("Owner information", "مشخصات صاحب حیوان", 2)
        owner_fields = {"name": "owner_name", "surname": "owner_surname", "telephone": "owner_phone",
                        "address": "owner_address"}
        owner_clear = ("patient_pick", *PATIENT_WIDGETS.values())
        owner_id = client_lookup(P, owner_fields, clear_widgets=owner_clear)

        c1, c2, c3 = st.columns(3)
        owner_name = c1.text_input("Owner Name (نام صاحب حیوان)", key=fkey(P, "owner_name"), autocomplete="off")
        owner_surname = c2.text_input("Owner Surname (نام خانوادگی)", key=fkey(P, "owner_surname"), autocomplete="off")
        owner_phone = c3.text_input("Telephone (تلفن)", key=fkey(P, "owner_phone"), autocomplete="off",
                                    on_change=load_owner_by_phone, args=(P, owner_fields, owner_clear))
        owner_address = st.text_input("Address (آدرس محل سکونت)", key=fkey(P, "owner_address"), autocomplete="off")
        duplicate_phone_hint(P, owner_id, owner_phone, owner_fields, owner_clear)

        st.info(
            "The undersigned owner confirms the information entered in this form is accurate "
            "and agrees to pay all treatment and hospitalization costs according to the approved "
            "tariff of the Veterinary System Organization of Fars Province. "
            "(اینجانب صاحب حیوان با مشخصات ذکر شده، هرگونه اقدام درمانی اعلام کرده و کلیه مخارج درمان و "
            "بستری را طبق تعرفه مصوبه شورای نظام دامپزشکی استان فارس پرداخت می‌نمایم. صحت اطلاعات ثبت "
            "شده در این فرم را تایید می‌نمایم.)"
        )

    with st.container(border=True):
        section_title("Patient information", "مشخصات بیمار", 3)

        if owner_id:
            with get_session() as s:
                animals = {p.id: f"{p.name or '-'} ({p.animal_type or '-'}) — file {p.file_number}"
                           for p in services.get_owner(s, owner_id).patients}
            st.selectbox(
                "Patient (بیمار)",
                [None] + list(animals),
                format_func=lambda i: "➕ New animal (حیوان جدید)" if i is None else animals[i],
                key=fkey(P, "patient_pick"),
                on_change=load_patient,
            )
        patient_id = st.session_state.get(P + "_patient_id")

        p1, p2, p3 = st.columns(3)
        animal_type = p1.text_input("Animal Type (نوع حیوان)", key=fkey(P, "animal_type"), autocomplete="off")
        gender = p2.text_input("Gender (جنسیت)", key=fkey(P, "gender"), autocomplete="off")
        breed = p3.text_input("Breed (نژاد حیوان)", key=fkey(P, "breed"), autocomplete="off")

        animal_name = p1.text_input("Animal Name (نام حیوان)", key=fkey(P, "animal_name"), autocomplete="off")
        sterilized = p2.text_input("Sterilization (عقیم سازی)", key=fkey(P, "sterilized"), autocomplete="off")
        keeping_location = p3.text_input("Keeping Location (محل نگهداری)", key=fkey(P, "keeping_location"), autocomplete="off")

        microchip = p1.text_input("Microchip (میکروچیپ)", key=fkey(P, "microchip"), autocomplete="off")
        animal_age = p2.text_input("Animal Age (سن حیوان)", key=fkey(P, "animal_age"), autocomplete="off")
        animal_weight = p3.text_input(
            "Animal Weight, kg (وزن حیوان)", key=fkey(P, "animal_weight"),
            help="Recorded with this visit so weight can be charted over time. (وزن در هر ویزیت ثبت می‌شود)",
            autocomplete="off",
        )

    with st.container(border=True):
        section_title("History & reason for visit", "تاریخچه و علت مراجعه از نظر صاحب حیوان", 4)

        reason_for_visit = st.text_area("Reason for Visit (علت مراجعه)", key=fkey(P, "reason"))
        history_narrative = st.text_area("History / Present Condition (شرح حال - تاریخچه بیمار)", key=fkey(P, "history"))
        previous_medications = st.text_area(
            "Previously Received Medications (داروهایی که قبلا دریافت کرده است)", key=fkey(P, "prev_meds")
        )

        st.markdown("**Vaccination and Internal/External Deworming History**")
        st.caption(
            "سابقه واکسیناسیون و انگل زدایی — enter the last date the owner reports, or tick if it is given today. "
            "Leave empty if unknown. Vaccine types and intervals are managed on the Catalogs page."
        )
        with get_session() as s:
            vaccine_types = [vt for vt in vaccines.list_vaccine_types(s, active_only=True) if vt.applies_to(animal_type)]
            on_file = {}
            if patient_id:
                on_file = {
                    status.vaccine_type.id: status
                    for status in vaccines.patient_vaccine_status(s, s.get(PatientDB, patient_id))
                }
        vaccination_inputs = []
        for row_start in range(0, len(vaccine_types), 3):
            for col, vt in zip(st.columns(3), vaccine_types[row_start:row_start + 3]):
                with col:
                    reported = jalali_date_input(
                        f"Last {vt.name} (تاریخ آخرین)", key=fkey(P, f"vacc_{vt.id}"), optional=True
                    )
                    given = st.checkbox("💉 Given today in clinic (امروز تزریق شد)", key=fkey(P, f"vacc_{vt.id}_given"))
                    status = on_file.get(vt.id)
                    if status and status.last_date:
                        st.caption(
                            f"On file: {to_jalali(status.last_date)} · due {to_jalali(status.due_date)} · "
                            f"{VACCINE_STATUS[status.status]}"
                        )
                    vaccination_inputs.append({"vaccine_type_id": vt.id, "date": reported, "administered": given})

        diet_info = st.text_area(
            "Diet and Daily Feeding Frequency (رژیم غذایی و دفعات مصرف در یک شبانه روز)", key=fkey(P, "diet")
        )

        st.caption("This section is completed by the veterinarian. (این بخش توسط دامپزشک تکمیل شود.)")
        vaccination_status = st.radio(
            "Vaccination / Deworming Status (سابقه واکسیناسیون و انگل زدایی داخلی و خارجی حیوان)",
            list(VACCINATION), format_func=VACCINATION.get, key=fkey(P, "vacc_status"), horizontal=True,
        )

    with st.container(border=True):
        section_title("Clinical examination", "معاینات بالینی", 5)

        vt1, vt2, vt3, vt4 = st.columns(4)
        vitals = {
            "T": vt1.text_input("T — temperature (دما)", key=fkey(P, "T"), placeholder="°C", autocomplete="off"),
            "HR": vt2.text_input("HR — heart rate (ضربان قلب)", key=fkey(P, "HR"), placeholder="/min", autocomplete="off"),
            "PR": vt3.text_input("PR — pulse rate (نبض)", key=fkey(P, "PR"), placeholder="/min", autocomplete="off"),
            "RR": vt4.text_input("RR — respiratory rate (تنفس)", key=fkey(P, "RR"), placeholder="/min", autocomplete="off"),
        }

        EXAM_FIELDS = {
            "general_health": "1. General Health (سلامت عمومی)",
            "skin_hair_ear": "2. Skin / Hair / Ear (پوست / مو / گوش)",
            "eye": "3. Eye (چشم)",
            "respiratory": "4. Respiratory System — nose, pharynx, larynx, trachea, lungs (سیستم تنفس (بینی، حنجره، نای، ریه))",
            "cardiovascular": "5. Heart and Vessels (قلب و عروق)",
            "digestive": "6. Digestive System — mouth, esophagus, stomach, intestines, anus (دستگاه گوارش (دهان، مری، معده، روده، مقعد))",
            "urinary": "7. Kidney, Bladder and Urinary Tract (کلیه، مثانه و مجاری ادراری)",
            "reproductive": "8. Reproductive System (دستگاه تناسلی، تولید مثل)",
            "musculoskeletal": "9. Muscles, Nerves, Bones (عضلات، اعصاب، استخوان‌ها)",
        }
        exam_cols = st.columns(2)
        exam = {
            field: exam_cols[n % 2].text_area(label, key=fkey(P, "exam_" + field), height=90)
            for n, (field, label) in enumerate(EXAM_FIELDS.items())
        }

    with st.container(border=True):
        section_title("Paraclinical results", "پاراکلینیک (نتایج پیوست گردد)", 6)

        pc1, pc2 = st.columns(2)
        with pc1:
            st.markdown("**1. Blood / Serum / Cytology (خون شناسی / سرم شناسی / سیتولوژی)**")
            blood_result = st.radio(
                "Blood results (نتایج)",
                ["not_done", "normal", "abnormal"],
                format_func={"not_done": "Not done (انجام نشده)", "normal": "Normal (نتایج طبیعی است)",
                             "abnormal": "Abnormal (نتایج غیر طبیعی است)"}.get,
                horizontal=True, key=fkey(P, "blood_result"), label_visibility="collapsed",
            )
            paraclinic = {
                "blood_normal": blood_result == "normal",
                "blood_abnormal": blood_result == "abnormal",
                "blood_summary": st.text_area("Summary Report (خلاصه گزارش) - Blood", key=fkey(P, "blood_summary"),
                                              height=90),
            }
        with pc2:
            st.markdown("**2. Radiology / Sonography (رادیولوژی / سونوگرافی)**")
            paraclinic["radiology_summary"] = st.text_area(
                "Summary Report (خلاصه گزارش) - Radiology / Sonography", key=fkey(P, "radiology"), height=90
            )
        pc3, pc4 = st.columns(2)
        with pc3:
            st.markdown("**3. Mycology / Bacteriology / Parasitology (قارچ شناسی / باکتری شناسی / انگل شناسی)**")
            paraclinic["mycology_summary"] = st.text_area(
                "Summary Report (خلاصه گزارش) - Mycology / Bacteriology / Parasitology", key=fkey(P, "mycology"),
                height=90,
            )
        with pc4:
            st.markdown("**4. Necropsy (کالبد گشایی)**")
            paraclinic["necropsy_summary"] = st.text_area(
                "Summary Report (خلاصه گزارش) - Necropsy", key=fkey(P, "necropsy"), height=90
            )
        st.markdown("**Follow-up on Pathology Results (پیگیری نتایج پاتولوژی)**")
        paraclinic["surgery_referral"] = st.text_area(
            "5. Referral for Surgery and Type of Surgery Performed (ارجاع به جراحی و نوع جراحی انجام شده)",
            key=fkey(P, "surgery"), height=90,
        )

    with st.container(border=True):
        section_title("Diagnosis", "تشخیص قطعی یا تشخیص‌های افتراقی", 7)
        diagnosis = st.text_area("Diagnosis (تشخیص)", label_visibility="collapsed", key=fkey(P, "diagnosis"))

        followup_date = jalali_date_input(
            "Next Follow-up Visit Date for Treatment (تاریخ مراجعه بعدی جهت پیگیری درمان)",
            key=fkey(P, "followup"), optional=True,
        )
        appointment_at = None
        if followup_date:
            b1, b2 = st.columns([2, 1])
            book_followup = b1.checkbox(
                f"📅 Book an appointment on {to_jalali(followup_date)} (ثبت نوبت)", key=fkey(P, "book")
            )
            followup_time = b2.time_input(
                "Time (ساعت)", value=time(10, 0), step=900, key=fkey(P, "book_time"), disabled=not book_followup
            )
            if book_followup:
                appointment_at = datetime.combine(followup_date, followup_time)

    with st.container(border=True):
        section_title("Treatment / prescription", "درمان / نسخه", 8)

        quick_add_drug(P + "_quick_drug")
        with get_session() as s:
            drugs = services.list_drugs(s, active_only=True)
        drug_options = {0: "✏️ Custom drug (داروی دلخواه)"} | {d.id: d.name for d in drugs}
        with st.form(fkey(P, "add_med"), clear_on_submit=True):
            drug_pick = st.selectbox(
                "From drug list (انتخاب از فهرست داروها)", list(drug_options), format_func=drug_options.get,
                index=1 if drugs else 0,
            )
            st.caption("Empty fields are filled from the drug list defaults. (فیلدهای خالی از فهرست تکمیل می‌شوند)")
            m1, m2, m3, m4, m5 = st.columns([2, 2, 1, 1, 1])
            drug_name_latin = m1.text_input("Drug Name - Latin (نام دارو (لاتین)) — custom only", autocomplete="off")
            dosage_instructions = m2.text_input("Dosage Instructions (دستور مصرف)", autocomplete="off")
            prescribed_form = m3.text_input("Prescribed Form (فرم تجویز دارو)", autocomplete="off")
            quantity = m4.text_input("Quantity (تعداد)", autocomplete="off")
            drug_form = m5.text_input("Drug Form (شکل دارویی)", autocomplete="off")
            if st.form_submit_button("➕ Add Medication (افزودن دارو)"):
                drug = next((d for d in drugs if d.id == drug_pick), None)
                name = drug_name_latin.strip() or (drug.name if drug else "")
                if name:
                    st.session_state.setdefault(P + "_meds", []).append({
                        "drug_id": drug.id if drug and not drug_name_latin.strip() else None,
                        "drug_name": name,
                        "dosage_instructions": dosage_instructions or (drug.default_dosage if drug else "") or "",
                        "prescribed_form": prescribed_form or (drug.prescribed_form if drug else "") or "",
                        "quantity": quantity,
                        "drug_form": drug_form or (drug.drug_form if drug else "") or "",
                    })
                    st.rerun()
                else:
                    st.warning("Choose a drug or enter a name. (لطفا دارو را انتخاب یا نام را وارد کنید)")

        row_table(P + "_meds", {
            "drug_name": "نام دارو (لاتین)", "dosage_instructions": "دستور مصرف",
            "prescribed_form": "فرم تجویز دارو", "quantity": "تعداد", "drug_form": "شکل دارویی",
        })

    with st.container(border=True):
        section_title("Treatment costs", "هزینه و مخارج درمان", 9)
        st.caption(
            "All costs are according to the current tariff of the "
            "Veterinary System Organization of Fars Province. "
            "(کلیه هزینه ها طبق تعرفه سال جاری شورای صنفی نظام دامپزشکی استان فارس می‌باشد.)"
        )
        with get_session() as s:
            tests = services.list_tests(s, active_only=True)
        test_picker(fkey(P, "costs"), P + "_costs", tests)
        total_cost = row_table(
            P + "_costs",
            {"name": "شرح خدمات", "fee": "تعرفه مصوبه", "quantity": "تعداد", "price": "جمع کل"},
            total_column="price",
        )

    with st.container(border=True):
        section_title("Attachments", "پیوست‌ها", 10)
        st.caption("X-ray / sonography images, lab reports (PDF)...")
        clinic_files = st.file_uploader(
            "Upload files (بارگذاری فایل)", accept_multiple_files=True, key=fkey(P, "files"),
            label_visibility="collapsed",
        )

    with st.container(border=True):
        section_title("Settlement", "تسویه حساب پذیرش", 11)
        st.metric("Total (جمع کل)", rial(total_cost),
                  help="Total of all diagnostic and treatment costs (جمع کلیه هزینه های تشخیصی و درمانی)")

    if st.button("Save Patient Record (ذخیره پرونده)", type="primary", icon=":material/save:", width="stretch"):
        try:
            with get_session() as s:
                visit = services.create_clinic_visit(
                    s,
                    owner_data={"name": owner_name, "surname": owner_surname,
                                "telephone": owner_phone, "address": owner_address},
                    patient_data={
                        "file_number": file_number, "name": animal_name, "animal_type": animal_type,
                        "breed": breed, "gender": gender, "sterilized": sterilized,
                        "keeping_location": keeping_location, "microchip": microchip,
                        "age": animal_age, "weight": animal_weight,
                    },
                    visit_data={
                        "visit_date": visit_date, "visit_type": visit_type,
                        "reason_for_visit": reason_for_visit, "history_narrative": history_narrative,
                        "previous_medications": previous_medications,
                        "diet_info": diet_info, "weight": animal_weight,
                        "vaccination_status": vaccination_status, "vitals": vitals, "exam": exam,
                        "paraclinic": paraclinic, "diagnosis": diagnosis, "followup_date": followup_date,
                    },
                    medications=st.session_state.get(P + "_meds", []),
                    costs=[{"test_id": c["test_id"], "description": c["name"], "tariff": c["fee"],
                            "quantity": c["quantity"]} for c in st.session_state.get(P + "_costs", [])],
                    owner_id=owner_id,
                    patient_id=patient_id,
                    vaccinations=vaccination_inputs,
                    attachments=uploaded_files(clinic_files),
                    appointment_at=appointment_at,
                )
                visit_id, saved_file = visit.id, visit.patient.file_number
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["last_clinic_visit"] = visit_id
            reset_form(P)
            booked = f" Follow-up booked for {to_jalali(appointment_at, with_time=True)}." if appointment_at else ""
            flash(f"Patient record saved — file number {saved_file}.{booked} (پرونده بیمار ذخیره شد)")
            st.rerun()
