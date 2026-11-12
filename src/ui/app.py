import sys
from datetime import date
from pathlib import Path

import streamlit as st

# Make `core` and `ui` importable when launched with `streamlit run src/ui/app.py`.
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.jalali import to_jalali  # noqa: E402
from core.receipts import CLINIC_NAME  # noqa: E402

LOGO = str(Path(__file__).parent / "static" / "logo.svg")

st.set_page_config(page_title="Vet Clinic Assistant", page_icon=LOGO, layout="wide")
st.logo(LOGO, size="large")
with st.sidebar:
    st.markdown(f"**{CLINIC_NAME}**")
    st.caption(f"📆 {to_jalali(date.today())} · {date.today():%Y-%m-%d}")

pg = st.navigation({
    "": [
        st.Page("views/landing.py", title="Dashboard (داشبورد)", icon="🏠", default=True),
        st.Page("views/submit.py", title="Admission (پذیرش)", icon="📝"),
        st.Page("views/tests.py", title="Tests (آزمایش‌ها)", icon="🧪"),
        st.Page("views/appointments.py", title="Appointments (نوبت‌دهی)", icon="📅"),
        st.Page("views/reminders.py", title="Reminders (یادآوری)", icon="💉"),
        st.Page("views/search.py", title="Records (سوابق)", icon="🔍"),
    ],
    "Management (مدیریت)": [
        st.Page("views/reports.py", title="Reports (گزارش‌ها)", icon="📊"),
        st.Page("views/catalog.py", title="Catalogs (فهرست‌ها)", icon="💊"),
        st.Page("views/backup_page.py", title="Backup (پشتیبان)", icon="💾"),
    ],
})
pg.run()
