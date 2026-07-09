import streamlit as st
from datetime import datetime
import streamlit as st
import pandas as pd


st.title("submit")

choice = st.selectbox("Visit Type (نوع ویزیت)", ["Laboratory(آزمایشگاه)", "Clinic (مطب)"])

if choice == "Laboratory(آزمایشگاه)":

    # ---------- FORM 1: Patient / sample info (submitted once) ----------
    with st.form("Form Laboratory(آزمایشگاه)"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Name (نام)")
        surname = col2.text_input("Surname(نام خانوادگی)")
        address = col1.text_input("Address (آدرس)")
        telephone = col2.text_input("Telephone (تلفن)")
        sample_qty = col1.text_input("Sample Quantity (تعداد نمونه)")
        sample_type = col2.text_input("Sample Type (نوع نمونه)")
        date_sampling = col1.date_input("Date of Sampling (تاریخ نمونه برداری)")
        date_admission = col1.datetime_input("Date of Admission", value=datetime.now())
        date_response = col2.datetime_input("Date of Response (تاریخ جوابدهی)")
        other = col2.text_input("Other (غیره)")

        patient_submitted = st.form_submit_button("Save Patient Info")

    if patient_submitted:
        st.session_state.patient_info = {
            "name": name, "surname": surname, "address": address,
            "telephone": telephone, "sample_qty": sample_qty,
            "sample_type": sample_type, "date_sampling": date_sampling,
            "date_admission": date_admission, "date_response": date_response,
        }
        st.success("Patient info saved.")

    st.divider()

    # ---------- Storage for the unlimited test-row table ----------
    if "lab_rows" not in st.session_state:
        st.session_state.lab_rows = []

    # ---------- FORM 2: Add one test row at a time (submitted many times) ----------
    with st.form("add_lab_row_form", clear_on_submit=True):
        st.subheader("Add test (آفزودن آزمایش)")
        c1, c2, c3, c4 = st.columns([1, 3, 1, 1])
        code = c1.text_input("code (کد)")
        test_name = c2.text_input("test name (نام آزمایش)")
        price = c3.number_input("fee (هزینه)", min_value=0, step=1000)
        qty = c4.number_input("Quantity (تعداد)", min_value=1, step=1)

        row_submitted = st.form_submit_button("Add to table")

        if row_submitted:
            if test_name.strip():
                st.session_state.lab_rows.append({
                    "row": len(st.session_state.lab_rows) + 1,
                    "code": code,
                    "test_name": test_name,
                    "fee": price,
                    "quantity": qty,
                    "price": price * qty,
                })
            else:
                st.warning("نام آزمایش را وارد کنید.")

    # ---------- Display the growing table ----------
    if st.session_state.lab_rows:
        df = pd.DataFrame(st.session_state.lab_rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        total = df["price"].sum()
        st.markdown(f"**جمع کل: {total:,.0f} ریال**")
    else:
        st.info("هنوز آزمایشی اضافه نشده است.")

if choice == "Clinic (مطب)":
    col_date, col_file = st.columns(2)
    visit_date = col_date.text_input("Date (تاریخ)")
    file_number = col_file.text_input("File Number (شماره پرونده)")
    
    visit_type = st.radio(
        "Visit Type (نوع مراجعه)",
        [
            "First visit (بیمار نخستین بار مراجعه کرده است)",
            "Follow-up visit (مراجعه جهت پیگیری نتیجه درمانی)",
        ],
    )
    
    st.divider()
    
    # ---------------- FORM 1: main intake form (submitted once) ----------------
    with st.form("clinic_main_form"):
    
        # ---------- Owner info ----------
        st.subheader("مشخصات صاحب حیوان")
        st.caption("Owner Information")
    
        c1, c2 = st.columns(2)
        owner_name = c1.text_input("Owner Name (صاحب حیوان)")
        owner_phone = c2.text_input("Telephone (تلفن)")
        owner_address = st.text_input("Address (آدرس محل سکونت)")
    
        st.info(
            "The undersigned owner confirms the information entered in this form is accurate "
            "and agrees to pay all treatment and hospitalization costs according to the approved "
            "tariff of the Veterinary System Organization of Fars Province. "
            "(اینجانب صاحب حیوان با مشخصات ذکر شده، هرگونه اقدام درمانی اعلام کرده و کلیه مخارج درمان و "
            "بستری را طبق تعرفه مصوبه شورای نظام دامپزشکی استان فارس پرداخت می‌نمایم. صحت اطلاعات ثبت "
            "شده در این فرم را تایید می‌نمایم.)"
        )
    
        st.divider()
    
        # ---------- Patient (animal) info ----------
        st.subheader("مشخصات بیمار")
        st.caption("Patient Information")
    
        p1, p2, p3 = st.columns(3)
        animal_type = p1.text_input("Animal Type (نوع حیوان)")
        gender = p2.text_input("Gender (جنسیت)")
        breed = p3.text_input("Breed (نژاد حیوان)")
    
        animal_name = p1.text_input("Animal Name (نام حیوان)")
        sterilized = p2.text_input("Sterilization (عقیم سازی)")
        keeping_location = p3.text_input("Keeping Location (محل نگهداری)")
    
        microchip = p1.text_input("Microchip (میکروچیپ)")
        animal_age = p2.text_input("Animal Age (سن حیوان)")
        animal_weight = p3.text_input("Animal Weight (وزن حیوان)")
    
        st.divider()
    
        # ---------- History ----------
        st.subheader("تاریخچه و علت مراجعه از نظر صاحب حیوان")
        st.caption("History and Reason for Visit (owner's account)")
    
        reason_for_visit = st.text_area("Reason for Visit (علت مراجعه)")
        history_narrative = st.text_area("History / Present Condition (شرح حال - تاریخچه بیمار)")
        previous_medications = st.text_area("Previously Received Medications (داروهایی که قبلا دریافت کرده است)")
    
        st.markdown("**Vaccination and Internal/External Deworming History**")
        st.caption("سابقه واکسیناسیون و انگل زدایی داخلی و خارجی")
        v1, v2, v3 = st.columns(3)
        rabies_vaccine_date = v1.text_input("Last Rabies Vaccine Date (تاریخ آخرین تزریق واکسن هاری)")
        polyvalent_vaccine_date = v2.text_input("Last Polyvalent Vaccine Date (تاریخ آخرین تزریق واکسن پلی والان)")
        deworming_date = v3.text_input("Last Deworming Treatment Date (تاریخ آخرین درمان ضدانگلی)")
    
        diet_info = st.text_area("Diet and Daily Feeding Frequency (رژیم غذایی و دفعات مصرف در یک شبانه روز)")
    
        st.caption("This section is completed by the veterinarian. (این بخش توسط دامپزشک تکمیل شود.)")
        vaccination_status = st.radio(
            "Vaccination / Deworming Status (سابقه واکسیناسیون و انگل زدایی داخلی و خارجی حیوان)",
            ["Complete (کامل)", "Incomplete (ناقص)"],
        )
    
        st.divider()
    
        # ---------- Clinical exam ----------
        st.subheader("معاینات بالینی")
        st.caption("Clinical Examination")
    
        vt1, vt2, vt3, vt4 = st.columns(4)
        temp_t = vt1.text_input("T:")
        hr = vt2.text_input("HR:")
        pr = vt3.text_input("PR:")
        rr = vt4.text_input("RR:")
    
        exam_general_health = st.text_area("1. General Health (سلامت عمومی)")
        exam_skin_hair_ear = st.text_area("2. Skin / Hair / Ear (پوست / مو / گوش)")
        exam_eye = st.text_area("3. Eye (چشم)")
        exam_respiratory = st.text_area("4. Respiratory System — nose, pharynx, larynx, trachea, lungs (سیستم تنفس (بینی، حنجره، نای، ریه))")
        exam_cardiovascular = st.text_area("5. Heart and Vessels (قلب و عروق)")
        exam_digestive = st.text_area("6. Digestive System — mouth, esophagus, stomach, intestines, anus (دستگاه گوارش (دهان، مری، معده، روده، مقعد))")
        exam_urinary = st.text_area("7. Kidney, Bladder and Urinary Tract (کلیه، مثانه و مجاری ادراری)")
        exam_reproductive = st.text_area("8. Reproductive System (دستگاه تناسلی، تولید مثل)")
        exam_musculoskeletal = st.text_area("9. Muscles, Nerves, Bones (عضلات، اعصاب، استخوان‌ها)")
    
        st.divider()
    
        # ---------- Paraclinical results ----------
        st.subheader("پاراکلینیک (نتایج پیوست گردد)")
        st.caption("Paraclinical Results (attach reports)")
    
        st.markdown("**1. Blood / Serum / Cytology (خون شناسی / سرم شناسی / سیتولوژی)**")
        pc1a, pc1b = st.columns(2)
        blood_normal = pc1a.checkbox("Results are normal (نتایج طبیعی است)")
        blood_abnormal = pc1b.checkbox("Results are abnormal (نتایج غیر طبیعی است)")
        blood_summary = st.text_area("Summary Report (خلاصه گزارش) - Blood", key="blood_summary")
    
        st.markdown("**2. Radiology / Sonography (رادیولوژی / سونوگرافی)**")
        radiology_summary = st.text_area("Summary Report (خلاصه گزارش) - Radiology / Sonography")
    
        st.markdown("**3. Mycology / Bacteriology / Parasitology (قارچ شناسی / باکتری شناسی / انگل شناسی)**")
        mycology_summary = st.text_area("Summary Report (خلاصه گزارش) - Mycology / Bacteriology / Parasitology")
    
        st.markdown("**4. Necropsy (کالبد گشایی)**")
        necropsy_summary = st.text_area("Summary Report (خلاصه گزارش) - Necropsy")
    
        st.markdown("**Follow-up on Pathology Results (پیگیری نتایج پاتولوژی)**")
        surgery_referral = st.text_area("5. Referral for Surgery and Type of Surgery Performed (ارجاع به جراحی و نوع جراحی انجام شده)")
    
        st.divider()
    
        # ---------- Diagnosis ----------
        st.subheader("تشخیص قطعی یا تشخیص‌های افتراقی")
        st.caption("Final Diagnosis or Differential Diagnoses")
        diagnosis = st.text_area("Diagnosis (تشخیص)", label_visibility="collapsed")
    
        st.divider()
    
        # ---------- Follow-up date ----------
        followup_date = st.text_input("Next Follow-up Visit Date for Treatment (تاریخ مراجعه بعدی جهت پیگیری درمان)")
    
        main_submitted = st.form_submit_button("Save Patient Record (ذخیره پرونده)")
    
    if main_submitted:
        st.session_state.clinic_record = {
            "visit_date": visit_date,
            "file_number": file_number,
            "visit_type": visit_type,
            "owner_name": owner_name,
            "owner_phone": owner_phone,
            "owner_address": owner_address,
            "animal_type": animal_type,
            "gender": gender,
            "breed": breed,
            "animal_name": animal_name,
            "sterilized": sterilized,
            "keeping_location": keeping_location,
            "microchip": microchip,
            "animal_age": animal_age,
            "animal_weight": animal_weight,
            "reason_for_visit": reason_for_visit,
            "history_narrative": history_narrative,
            "previous_medications": previous_medications,
            "rabies_vaccine_date": rabies_vaccine_date,
            "polyvalent_vaccine_date": polyvalent_vaccine_date,
            "deworming_date": deworming_date,
            "diet_info": diet_info,
            "vaccination_status": vaccination_status,
            "vitals": {"T": temp_t, "HR": hr, "PR": pr, "RR": rr},
            "exam": {
                "general_health": exam_general_health,
                "skin_hair_ear": exam_skin_hair_ear,
                "eye": exam_eye,
                "respiratory": exam_respiratory,
                "cardiovascular": exam_cardiovascular,
                "digestive": exam_digestive,
                "urinary": exam_urinary,
                "reproductive": exam_reproductive,
                "musculoskeletal": exam_musculoskeletal,
            },
            "paraclinic": {
                "blood_normal": blood_normal,
                "blood_abnormal": blood_abnormal,
                "blood_summary": blood_summary,
                "radiology_summary": radiology_summary,
                "mycology_summary": mycology_summary,
                "necropsy_summary": necropsy_summary,
                "surgery_referral": surgery_referral,
            },
            "diagnosis": diagnosis,
            "followup_date": followup_date,
        }
        st.success("Patient record saved. (پرونده بیمار ذخیره شد.)")
    
    st.divider()
    
    # ==========================================================
    # ---------- FORM 2: Medications table (repeatable) ----------
    # ==========================================================
    st.subheader("درمان / نسخه")
    st.caption("Treatment / Prescription")
    
    if "medication_rows" not in st.session_state:
        st.session_state.medication_rows = []
    
    with st.form("add_medication_form", clear_on_submit=True):
        m1, m2, m3, m4, m5 = st.columns([2, 2, 1, 1, 1])
        dosage_instructions = m1.text_input("Dosage Instructions (دستور مصرف)")
        drug_name_latin = m2.text_input("Drug Name - Latin (نام دارو (لاتین))")
        prescribed_form = m3.text_input("Prescribed Form (فرم تجویز دارو)")
        quantity = m4.text_input("Quantity (تعداد)")
        drug_form = m5.text_input("Drug Form (شکل دارویی)")
    
        add_med = st.form_submit_button("➕ Add Medication (افزودن دارو)")
    
        if add_med:
            if drug_name_latin.strip():
                st.session_state.medication_rows.append({
                    "دستور مصرف": dosage_instructions,
                    "نام دارو (لاتین)": drug_name_latin,
                    "فرم تجویز دارو": prescribed_form,
                    "تعداد": quantity,
                    "شکل دارویی": drug_form,
                })
            else:
                st.warning("Please enter a drug name. (لطفا نام دارو را وارد کنید)")
    
    if st.session_state.medication_rows:
        med_df = pd.DataFrame(st.session_state.medication_rows)
        st.dataframe(med_df, use_container_width=True, hide_index=True)
    else:
        st.info("No medications added yet. (هنوز دارویی اضافه نشده است)")
    
    st.divider()
    
    # ==========================================================
    # ---------- FORM 3: Cost table (repeatable) ----------
    # ==========================================================
    st.subheader("هزینه و مخارج درمان")
    st.caption(
        "Treatment Costs and Expenses — all costs are according to the current tariff of the "
        "Veterinary System Organization of Fars Province. "
        "(کلیه هزینه ها طبق تعرفه سال جاری شورای صنفی نظام دامپزشکی استان فارس می‌باشد.)"
    )
    
    if "cost_rows" not in st.session_state:
        st.session_state.cost_rows = []
    
    with st.form("add_cost_form", clear_on_submit=True):
        cst1, cst2, cst3 = st.columns([3, 1, 1])
        service_description = cst1.text_input("Service Description (شرح خدمات)")
        approved_tariff = cst2.number_input("Approved Tariff (تعرفه مصوبه)", min_value=0, step=1000)
        cost_quantity = cst3.number_input("Quantity (تعداد)", min_value=1, step=1)
    
        add_cost = st.form_submit_button("➕ Add Cost Item (افزودن هزینه)")
    
        if add_cost:
            if service_description.strip():
                st.session_state.cost_rows.append({
                    "شرح خدمات": service_description,
                    "تعداد": cost_quantity,
                    "تعرفه مصوبه": approved_tariff,
                    "جمع کل": approved_tariff * cost_quantity,
                })
            else:
                st.warning("Please enter a service description. (لطفا شرح خدمات را وارد کنید)")
    
    total_cost = 0
    if st.session_state.cost_rows:
        cost_df = pd.DataFrame(st.session_state.cost_rows)
        st.dataframe(cost_df, use_container_width=True, hide_index=True)
        total_cost = cost_df["جمع کل"].sum()
        st.markdown(f"**Total (جمع کل): {total_cost:,.0f} ریال**")
    else:
        st.info("No cost items added yet. (هنوز هزینه‌ای اضافه نشده است)")
    
    st.divider()
    
    # ==========================================================
    # ---------- Settlement ----------
    # ==========================================================
    st.subheader("تسویه حساب پذیرش")
    st.caption("Reception Account Settlement")
    
    st.markdown(f"**Total of all diagnostic and treatment costs (جمع کلیه هزینه های تشخیصی و درمانی): {total_cost:,.0f} ریال**")
    
    payment_type = st.radio("Payment Type (نوع پرداخت)", ["Cash (نقدی)", "Card Reader (کارت خوان)"])