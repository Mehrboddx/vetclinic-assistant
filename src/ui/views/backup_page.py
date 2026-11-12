from datetime import datetime

import streamlit as st

from core import backup
from core.database import engine
from core.jalali import to_jalali
from ui.components import flash, page_header, setup_page, show_flash

setup_page()

page_header("Backup", "پشتیبان‌گیری", "Daily automatic backups, downloads and restore.")
show_flash()

st.markdown(
    f"""
- An **automatic backup** is saved once a day, the first time the app is opened that day, and the last
  {backup.AUTO_BACKUP_KEEP} are kept in `{backup.BACKUP_DIR}`.
- Download a backup regularly and keep a copy **on another device** (USB drive or cloud), so a broken
  computer doesn't take the clinic's records with it.
- A backup contains everything: clients, animals, visits, lab results, attachments, catalogs and appointments.
"""
)

st.subheader("Download a backup now (دریافت نسخه پشتیبان)")
if st.button("📦 Create backup (ایجاد نسخه پشتیبان)", type="primary"):
    with st.spinner("Creating backup..."):
        st.session_state["backup_bytes"] = backup.export_backup(engine)
        st.session_state["backup_name"] = f"vetclinic-backup-{datetime.now():%Y-%m-%d-%H%M}.zip"
if st.session_state.get("backup_bytes"):
    data = st.session_state["backup_bytes"]
    st.download_button(
        f"⬇ Download {st.session_state['backup_name']} ({len(data) / 1024:,.0f} KB)",
        data, file_name=st.session_state["backup_name"], mime="application/zip",
    )

st.subheader("Automatic backups (پشتیبان‌های خودکار)")
saved = backup.list_backups()
if not saved:
    st.caption("None yet.")
for path in saved:
    c1, c2 = st.columns([3, 1])
    stamp = datetime.fromtimestamp(path.stat().st_mtime)
    c1.markdown(f"`{path.name}` — {to_jalali(stamp, with_time=True)} — {path.stat().st_size / 1024:,.0f} KB")
    c2.download_button("⬇ Download", path.read_bytes(), file_name=path.name, mime="application/zip", key=f"dl_{path.name}")

st.divider()
st.subheader("Restore from a backup (بازیابی)")
st.warning(
    "Restoring **replaces all current data** with the contents of the backup file. "
    "A safety backup of the current data is saved first. "
    "(بازیابی، تمام اطلاعات فعلی را با محتوای فایل پشتیبان جایگزین می‌کند)"
)
uploaded = st.file_uploader("Backup file (.zip)", type=["zip"], key="restore_file")
if uploaded is not None:
    try:
        info = backup.read_backup_info(uploaded.getvalue())
    except ValueError as exc:
        st.error(str(exc))
    else:
        counts = info["counts"]
        st.info(
            f"Backup from {to_jalali(info['created_at'], with_time=True)}: "
            f"{counts.get('owners', 0)} clients, {counts.get('patients', 0)} animals, "
            f"{counts.get('clinic_visits', 0)} visits, {counts.get('lab_orders', 0)} lab orders."
        )
        confirm = st.text_input("Type RESTORE to confirm (برای تایید RESTORE را تایپ کنید)", autocomplete="off")
        if st.button("♻ Restore (بازیابی)", disabled=confirm.strip() != "RESTORE"):
            safety = backup.BACKUP_DIR / f"before-restore-{datetime.now():%Y-%m-%d-%H%M%S}.zip"
            backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            safety.write_bytes(backup.export_backup(engine))
            try:
                backup.restore_backup(engine, uploaded.getvalue())
            except Exception as exc:  # noqa: BLE001 - the transaction rolled back; show why
                st.error(f"Restore failed and nothing was changed: {exc}")
            else:
                for key in list(st.session_state):
                    del st.session_state[key]
                flash(f"Data restored. The previous data was saved to {safety.name}. (بازیابی انجام شد)")
                st.rerun()
