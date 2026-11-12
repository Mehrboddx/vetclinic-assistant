from datetime import date, timedelta

import jdatetime
import streamlit as st

from core import reports
from core.database import get_session
from core.jalali import to_jalali
from ui.charts import revenue_chart, top_tests_chart
from ui.components import chart_ring, jalali_date_input, page_header, rial, setup_page

setup_page()

page_header("Reports", "گزارش‌ها", "Revenue and activity for any period.")

today = date.today()
month_start = jdatetime.date.today().replace(day=1).togregorian()
PRESETS = {
    "today": ("Today (امروز)", today, today),
    "7": ("Last 7 days (۷ روز اخیر)", today - timedelta(days=6), today),
    "30": ("Last 30 days (۳۰ روز اخیر)", today - timedelta(days=29), today),
    "month": ("This Jalali month (ماه جاری)", month_start, today),
    "90": ("Last 90 days (۹۰ روز اخیر)", today - timedelta(days=89), today),
    "custom": ("Custom range (بازه دلخواه)", None, None),
}
preset = st.segmented_control(
    "Period (بازه)", list(PRESETS), format_func=lambda k: PRESETS[k][0], default="30", key="report_preset"
) or "30"
if preset == "custom":
    c1, c2 = st.columns(2)
    with c1:
        start = jalali_date_input("From (از)", key="report_from", default_value=today - timedelta(days=29))
    with c2:
        end = jalali_date_input("To (تا)", key="report_to")
else:
    _, start, end = PRESETS[preset]

try:
    with get_session() as s:
        report = reports.summary(s, start, end)
        excel = reports.to_excel(report)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

st.caption(f"{to_jalali(start)} — {to_jalali(end)}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total revenue (درآمد کل)", rial(report["total"]))
m2.metric("Laboratory (آزمایشگاه)", rial(report["lab_total"]), f"{report['lab_orders']} admissions", delta_color="off")
m3.metric("Clinic (مطب)", rial(report["clinic_total"]), f"{report['clinic_visits']} visits", delta_color="off")
m4.metric("New clients (مشتری جدید)", report["new_clients"])
m5.metric("Vaccinations given (واکسن تزریق شده)", report["vaccinations_given"])

st.download_button(
    "⬇ Export to Excel (خروجی اکسل)",
    excel,
    file_name=f"vetclinic_report_{start.isoformat()}_{end.isoformat()}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)

st.divider()
if report["total"] == 0:
    st.info("No revenue in this period. (در این بازه درآمدی ثبت نشده است)")
else:
    st.subheader("Daily revenue (درآمد روزانه)")
    if len(report["daily"]) > 1:
        st.altair_chart(revenue_chart(report["daily"], ring=chart_ring()), width="stretch")
    with st.expander("Table (جدول)"):
        table = report["daily"].drop(columns=["date"]).rename(columns={
            "jalali": "Date (تاریخ)", "lab": "Laboratory (آزمایشگاه)", "clinic": "Clinic (مطب)"
        })
        st.dataframe(table, hide_index=True, width="stretch")

st.subheader("Most ordered tests (پرتکرارترین آزمایش‌ها)")
top = report["top_tests"].head(12)
if top.empty:
    st.caption("No catalog tests ordered in this period. (موردی نیست)")
else:
    st.altair_chart(top_tests_chart(top), width="stretch")
    with st.expander("Table (جدول)"):
        st.dataframe(
            report["top_tests"].rename(columns={"test": "Test (آزمایش)", "count": "Count (تعداد)",
                                                "revenue": "Revenue (درآمد)"}),
            hide_index=True, width="stretch",
        )
