from datetime import date
from html import escape

import pandas as pd
import streamlit as st
from streamlit_nej_datepicker import Config, datepicker_component

from core import backup, services
from core.database import DATABASE_URL, engine, get_session, init_db
from core.jalali import to_gregorian, to_jalali

STATUS_OPTIONS = {
    "pending": "Pending (در انتظار جواب)",
    "completed": "Results ready (جواب آماده)",
    "delivered": "Delivered (تحویل داده شده)",
}
VACCINE_STATUS = {
    "overdue": "🔴 Overdue (گذشته)",
    "due_soon": "🟠 Due soon (نزدیک)",
    "ok": "🟢 Up to date (به‌روز)",
    "no_record": "⚪ No record (ثبت نشده)",
}

_CSS = """
<style>
[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1400px; }
.jalali-field-label { margin: 0 0 0.25rem 0; font-size: 0.875rem; line-height: 1.2; }

/* Persian paragraphs and typed text read right-to-left; English stays left-to-right. */
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stCaptionContainer"], textarea, input[type="text"] { unicode-bidi: plaintext; }

.vc-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem;
             flex-wrap: wrap; margin-bottom: 1.25rem; padding-bottom: 0.9rem;
             border-bottom: 1px solid rgba(128, 128, 128, 0.22); }
.vc-header h1 { margin: 0; padding: 0; font-size: 1.85rem; line-height: 1.25; }
.vc-header .vc-sub { margin-top: 0.2rem; opacity: 0.68; font-size: 0.95rem; }
.vc-header .vc-fa { font-size: 1.35rem; font-weight: 600; opacity: 0.55; direction: rtl; }

.vc-section { display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem;
              flex-wrap: wrap; margin: 0.1rem 0 0.6rem 0; }
.vc-section .vc-en { font-weight: 650; font-size: 1.08rem; }
.vc-section .vc-fa { direction: rtl; font-weight: 600; opacity: 0.6; }
.vc-section .vc-num { display: inline-flex; align-items: center; justify-content: center;
                      width: 1.6rem; height: 1.6rem; margin-right: 0.5rem; border-radius: 50%;
                      font-size: 0.82rem; font-weight: 700; color: #fff;
                      background: #0f766e; }
</style>
"""


@st.cache_resource(show_spinner="Connecting to database...")
def _init_db_once() -> bool:
    init_db()
    return True


# Browser autofill (Chrome / Edge) fills boxes on screen without telling Streamlit, so a form that looks
# filled in is saved as empty ("Owner name is required"). Text inputs get autocomplete="off" directly; this
# covers the inputs Streamlit gives no option for (test search, dropdowns, numbers), including ones added later.
_NO_AUTOFILL = """<script>
(() => {
  if (window.__vetclinicNoAutofill) return;
  window.__vetclinicNoAutofill = true;
  const off = () => document
    .querySelectorAll('input:not([autocomplete="off"]):not([type=file]):not([type=checkbox]):not([type=radio])')
    .forEach(input => input.setAttribute('autocomplete', 'off'));
  off();
  new MutationObserver(off).observe(document.body, {childList: true, subtree: true});
})();
</script>"""


def setup_page() -> None:
    """Shared page setup: CSS + make sure the database and tables exist."""
    st.markdown(_CSS, unsafe_allow_html=True)
    st.html(_NO_AUTOFILL, unsafe_allow_javascript=True)
    try:
        _init_db_once()
    except Exception as exc:  # noqa: BLE001 - show any connection problem to the user
        st.error(
            "Could not connect to the database. (اتصال به پایگاه داده برقرار نشد)\n\n"
            f"`{DATABASE_URL.split('@')[-1]}`\n\n{exc}"
        )
        st.info("Start PostgreSQL or set VETCLINIC_DATABASE_URL (see README).")
        st.stop()
    try:
        _auto_backup_for(date.today().isoformat())
    except Exception as exc:  # noqa: BLE001 - a failed backup must not block the clinic
        st.toast(f"Automatic backup failed: {exc}", icon="⚠️")


@st.cache_resource(show_spinner=False)
def _auto_backup_for(day: str):
    """Runs once per day per server process (the cache key is the date)."""
    return backup.auto_backup(engine)


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:  # noqa: BLE001
        return False


def chart_ring() -> str:
    """Marker ring color = the chart surface of the active theme (backgroundColor in .streamlit/config.toml)."""
    return "#0f1716" if is_dark() else "#f6f8f7"


# ---------------------------------------------------------------- headings and labels

def page_header(title: str, title_fa: str, subtitle: str = "") -> None:
    """Page title in English with the Persian title opposite it."""
    sub = f'<div class="vc-sub" dir="auto">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="vc-header"><div><h1>{escape(title)}</h1>{sub}</div>'
        f'<div class="vc-fa">{escape(title_fa)}</div></div>',
        unsafe_allow_html=True,
    )


def section_title(title: str, title_fa: str = "", number: int | None = None) -> None:
    """Heading for a block of the page, e.g. one part of the admission form."""
    num = f'<span class="vc-num">{number}</span>' if number is not None else ""
    fa = f'<span class="vc-fa">{escape(title_fa)}</span>' if title_fa else ""
    st.markdown(
        f'<div class="vc-section"><span class="vc-en">{num}{escape(title)}</span>{fa}</div>',
        unsafe_allow_html=True,
    )


WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


def day_label(d: date) -> str:
    """Persian weekday and Jalali date, e.g. 'شنبه 1405/07/12'."""
    return f"{WEEKDAYS_FA[d.weekday()]} {to_jalali(d)}"


def rial(amount) -> str:
    return f"{int(amount or 0):,} ریال"


# ---------------------------------------------------------------- per-form widget keys

def fkey(prefix: str, name: str) -> str:
    """Widget key that changes after each save, so the form starts blank again."""
    return f"{prefix}_{st.session_state.get(prefix + '_nonce', 0)}_{name}"


def reset_form(prefix: str) -> None:
    st.session_state[prefix + "_nonce"] = st.session_state.get(prefix + "_nonce", 0) + 1
    for suffix in ("_owner_id", "_patient_id", "_rows", "_meds", "_costs", "_found_by_phone"):
        st.session_state.pop(prefix + suffix, None)


def flash(message: str) -> None:
    """Show a success message on the next rerun."""
    st.session_state["_flash"] = message


def show_flash() -> None:
    message = st.session_state.pop("_flash", None)
    if message:
        st.success(message)


# ---------------------------------------------------------------- jalali date input

def jalali_date_input(
    label: str,
    key: str,
    default_value: date | None = None,
    optional: bool = False,
) -> date | None:
    """Jalali calendar picker. Returns a Gregorian `date` (None if optional and left empty)."""
    st.markdown(f'<div class="jalali-field-label">{label}</div>', unsafe_allow_html=True)
    default = default_value or (None if optional else date.today())
    selected = datepicker_component(
        key=key,
        closedViewProps={
            "style": {
                "width": "100%",
                "boxSizing": "border-box",
                "background": "inherit",
                "padding": "0.65em 1em",
                "fontFamily": "inherit",
                "textAlign": "left",
                "fontSize": "14px",
                "minHeight": "2.75rem",
            }
        },
        # Config rejects an explicit None, so only pass a default when there is one.
        config=Config(locale="fa", closed_view="input", **({"default_value": default} if default else {})),
    )
    return to_gregorian(selected) or default


# ---------------------------------------------------------------- client lookup

def _fill_owner(prefix: str, owner_id: int, owner_fields: dict, clear_widgets: tuple) -> None:
    """Put a client on file into the form: their details only, never the tests or sample of a past admission."""
    with get_session() as s:
        owner = services.get_owner(s, owner_id)
        st.session_state[prefix + "_owner_id"] = owner.id
        st.session_state.pop(prefix + "_patient_id", None)
        for field, widget in owner_fields.items():
            st.session_state[fkey(prefix, widget)] = getattr(owner, field) or ""
    for widget in clear_widgets:
        st.session_state.pop(fkey(prefix, widget), None)


def _load_owner(prefix: str, owner_fields: dict, clear_widgets: tuple) -> None:
    owner_id = st.session_state.get(prefix + "_pick")
    if owner_id:
        _fill_owner(prefix, owner_id, owner_fields, clear_widgets)


def load_owner_by_phone(prefix: str, owner_fields: dict, clear_widgets: tuple = ()) -> None:
    """`on_change` of the phone field: a number that belongs to one client on file fills in that client.

    Only while the name fields are still empty, so a family member sharing the phone can still be entered as a
    new client by typing their name first. (Browser autofill is switched off on every field, because it fills
    the boxes on screen without telling Streamlit, which then saves them as empty.)
    """
    if st.session_state.get(prefix + "_owner_id"):
        return
    typed = [st.session_state.get(fkey(prefix, owner_fields[f]), "") for f in ("name", "surname")]
    if any((v or "").strip() for v in typed):
        return
    phone = st.session_state.get(fkey(prefix, owner_fields["telephone"]), "")
    with get_session() as s:
        matches = [o.id for o in services.find_owners_by_phone(s, phone)]
    if len(matches) == 1:
        _fill_owner(prefix, matches[0], owner_fields, clear_widgets)
        st.session_state[prefix + "_found_by_phone"] = True


def client_lookup(prefix: str, owner_fields: dict, clear_widgets: tuple = ()) -> int | None:
    """Search box to load an existing client into the form. `owner_fields` maps model field -> widget name;
    `clear_widgets` are reset whenever another client is loaded.

    Returns the loaded owner id, or None for a new client.
    """
    with st.expander("🔍 Existing client? (جستجوی مشتری قبلی)", expanded=False):
        query = st.text_input(
            "Name, phone, animal name or file number (نام، تلفن، نام حیوان یا شماره پرونده)",
            key=prefix + "_query",
            autocomplete="off",
        )
        if query.strip():
            with get_session() as s:
                owners = services.search_owners(s, query, limit=20)
                options = {o.id: f"{o.full_name} — {o.telephone or '-'}" for o in owners}
            if options:
                c1, c2 = st.columns([4, 1])
                c1.selectbox(
                    "Matches (نتایج)",
                    list(options),
                    format_func=options.get,
                    key=prefix + "_pick",
                    label_visibility="collapsed",
                )
                c2.button("Load (انتخاب)", key=prefix + "_load", on_click=_load_owner,
                          args=(prefix, owner_fields, clear_widgets))
            else:
                st.caption("No match. A new client will be created. (موردی یافت نشد)")

    owner_id = st.session_state.get(prefix + "_owner_id")
    if owner_id:
        c1, c2 = st.columns([4, 1])
        if st.session_state.get(prefix + "_found_by_phone"):
            c1.info(f"Client #{owner_id} found by phone number; their details are filled in. Tests and sample "
                    "are for this new admission. (مشتری با این شماره پیدا شد و مشخصاتش وارد شد)")
        else:
            c1.info(f"Editing existing client #{owner_id}. Changes will update their record. (مشتری موجود)")
        c2.button("New client (مشتری جدید)", key=prefix + "_new", on_click=reset_form, args=(prefix,))
    return owner_id


# ---------------------------------------------------------------- editable row lists

def row_table(state_key: str, columns: dict, total_column: str | None = None) -> int:
    """Show rows stored in session_state[state_key] with the option to remove selected ones.

    `columns` maps row dict keys -> display headers. Returns the sum of `total_column`.
    """
    rows = st.session_state.get(state_key, [])
    if not rows:
        st.info("Nothing added yet. (هنوز موردی اضافه نشده است)")
        return 0
    df = pd.DataFrame(rows)[list(columns)].rename(columns=columns)
    df.insert(0, "#", range(1, len(df) + 1))
    event = st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="multi-row",
        key=state_key + "_view",
    )
    selected = event.selection.rows if event else []
    if selected and st.button(f"🗑 Remove {len(selected)} selected row(s) (حذف)", key=state_key + "_remove"):
        st.session_state[state_key] = [r for i, r in enumerate(rows) if i not in set(selected)]
        st.session_state.pop(state_key + "_view", None)
        st.rerun()
    total = int(sum(r.get(total_column) or 0 for r in rows)) if total_column else 0
    if total_column:
        st.markdown(f"**Total (جمع کل): {rial(total)}**")
    return total


# ---------------------------------------------------------------- result notation

def notation_help() -> None:
    """How to type powers of ten and symbols in result fields, plus the symbols ready to copy."""
    st.caption(
        "Scientific notation: type `5x10^4` or `5e4` and it is saved as `5 × 10⁴`. "
        "`^` makes a power anywhere (`10^3/uL` → `10³/uL`); `+/-` → `±`, `<=` → `≤`, `>=` → `≥`."
    )
    st.markdown(
        '<div dir="rtl" style="font-size:0.85rem;opacity:0.75;margin-top:-0.6rem">'
        'برای نوشتن توان، مثلاً <bdi dir="ltr"><code>5x10^4</code></bdi> یا <bdi dir="ltr"><code>5e4</code></bdi> '
        'بنویسید؛ هنگام ذخیره به <bdi dir="ltr"><code>5 × 10⁴</code></bdi> تبدیل می‌شود.</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Symbols to copy (نمادها برای کپی)", expanded=False):
        st.caption("Click the copy icon at the right of a line, then paste into the cell. (کپی و جای‌گذاری)")
        st.code("×  ±  µ  °  ≤  ≥  ½  ‰", language=None)
        st.code("⁰ ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹ ⁻ ⁺", language=None)
        st.code("CFU/g   CFU/mL   10³/µL   10⁶/µL   ×10⁹/L", language=None)


# ---------------------------------------------------------------- catalog editors

def none_if_nan(value):
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def changed_rows(original: pd.DataFrame, edited: pd.DataFrame, columns: list[str]) -> dict[int, dict]:
    """Return {row id: {column: new value}} for cells that differ between the two frames."""
    changes = {}
    for row_id, row in edited.iterrows():
        before = original.loc[row_id]
        diff = {
            c: none_if_nan(row[c]) for c in columns
            if not (pd.isna(row[c]) and pd.isna(before[c])) and row[c] != before[c]
        }
        if diff:
            changes[int(row_id)] = diff
    return changes


def editor_key(name: str, *parts) -> str:
    """Editors keep pending edits by row position, so the key changes with filters and after each save."""
    nonce = st.session_state.get(f"{name}_nonce", 0)
    return "_".join([name, str(nonce), *map(str, parts)])


def bump(name: str) -> None:
    st.session_state[f"{name}_nonce"] = st.session_state.get(f"{name}_nonce", 0) + 1


def _add_item_row(state_key: str, test_id: int | None, code: str, name: str, fee: int, qty: int) -> None:
    """Append a row to session_state[state_key]; the same catalog test at the same fee just raises the quantity."""
    rows = st.session_state.setdefault(state_key, [])
    for row in rows:
        if test_id is not None and row["test_id"] == test_id and row["fee"] == fee and row["name"] == name:
            row["quantity"] += qty
            row["price"] = row["fee"] * row["quantity"]
            return
    rows.append({"test_id": test_id, "code": code, "name": name, "fee": fee, "quantity": qty, "price": fee * qty})


def test_picker(key: str, state_key: str, tests: list) -> None:
    """Pick tests that are already defined on the Tests page and add them to session_state[state_key]."""
    if not tests:
        st.warning(
            "No tests are defined yet. Define them on the **Tests (آزمایش‌ها)** page first. "
            "(ابتدا آزمایش‌ها را در صفحه آزمایش‌ها تعریف کنید)"
        )
        st.page_link("views/tests.py", label="Go to Tests page (رفتن به صفحه آزمایش‌ها)", icon="🧪")
        return
    by_id = {t.id: t for t in tests}
    with st.form(key + "_pick", clear_on_submit=True):
        picked = st.multiselect(
            "Tests (آزمایش‌ها)", list(by_id), format_func=lambda i: by_id[i].label,
            placeholder="Type a code or name to search… (جستجوی کد یا نام)",
        )
        c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
        qty = c1.number_input("Quantity each (تعداد)", min_value=1, step=1, value=1)
        if c2.form_submit_button("➕ Add selected (افزودن)", type="primary"):
            if not picked:
                st.warning("Select at least one test. (حداقل یک آزمایش انتخاب کنید)")
            else:
                for test_id in picked:
                    t = by_id[test_id]
                    _add_item_row(state_key, t.id, t.code, t.name, int(t.default_fee or 0), int(qty))
                st.rerun()
    st.caption("Missing a test? Define it on the Tests page. (آزمایش جدید را در صفحه آزمایش‌ها تعریف کنید)")


def duplicate_phone_hint(prefix: str, owner_id: int | None, telephone: str, owner_fields: dict,
                         clear_widgets: tuple = ()) -> None:
    """Warn when a new client is about to be created with a phone number that is already on file,
    with a button to use the client on file instead."""
    if owner_id or not (telephone or "").strip():
        return
    with get_session() as s:
        matches = [(o.id, o.full_name) for o in services.find_owners_by_phone(s, telephone)]
    if matches:
        st.warning(
            f"A client with this phone already exists: {', '.join(n for _, n in matches)}. "
            "Use them instead of creating a duplicate, unless this is a different person. "
            "(مشتری با این شماره تلفن قبلا ثبت شده است)"
        )
        for match_id, match_name in matches:
            st.button(f"Use {match_name} (استفاده از این مشتری)", key=f"{prefix}_use_{match_id}",
                      on_click=_fill_owner, args=(prefix, match_id, owner_fields, clear_widgets))


def quick_add_drug(key: str) -> None:
    """Add a drug to the drug list without leaving the page."""
    with st.expander("➕ Add a new drug to the list (افزودن دارو به فهرست)"):
        with st.form(key, clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            name = c1.text_input("Drug name - Latin (نام دارو (لاتین))", autocomplete="off")
            drug_form = c2.text_input("Drug form (شکل دارویی)", autocomplete="off")
            prescribed_form = c3.text_input("Prescribed form (فرم تجویز)", autocomplete="off")
            dosage = st.text_input("Default dosage instructions (دستور مصرف پیش‌فرض)", autocomplete="off")
            if st.form_submit_button("Save drug (ذخیره دارو)"):
                try:
                    with get_session() as s:
                        services.add_drug(s, name, drug_form, prescribed_form, dosage)
                    flash(f"Drug '{name.strip()}' added to the list. (دارو اضافه شد)")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def uploaded_files(files) -> list[dict]:
    """Convert st.file_uploader results into dicts for the services layer."""
    return [{"filename": f.name, "data": f.getvalue(), "content_type": f.type} for f in files or []]


def attachments_view(attachments, key: str) -> None:
    """Show images inline and offer every file for download, with a delete option."""
    if not attachments:
        st.caption("No attachments. (پیوستی وجود ندارد)")
        return
    columns = st.columns(3)
    for n, att in enumerate(attachments):
        with columns[n % 3]:
            with get_session() as s:
                data = services.get_attachment_data(s, att.id)
            if att.is_image:
                st.image(data, caption=att.filename, width="stretch")
            else:
                st.markdown(f"📄 **{att.filename}**")
            st.caption(f"{att.size / 1024:,.0f} KB · {to_jalali(att.uploaded_at, with_time=True)}")
            c1, c2 = st.columns(2)
            c1.download_button("⬇ Download", data, file_name=att.filename, mime=att.content_type,
                               key=f"{key}_dl_{att.id}")
            if c2.button("🗑 Delete", key=f"{key}_del_{att.id}"):
                with get_session() as s:
                    services.delete_attachment(s, att.id)
                flash(f"Attachment '{att.filename}' deleted.")
                st.rerun()


def add_attachments_form(key: str, visit_id: int | None = None, lab_order_id: int | None = None) -> None:
    with st.form(key, clear_on_submit=True):
        files = st.file_uploader("Add files: images, PDF... (افزودن فایل)", accept_multiple_files=True)
        if st.form_submit_button("📎 Upload (بارگذاری)") and files:
            try:
                with get_session() as s:
                    for f in uploaded_files(files):
                        services.add_attachment(s, f["filename"], f["data"], f["content_type"],
                                                visit_id=visit_id, lab_order_id=lab_order_id)
                flash(f"{len(files)} file(s) attached. (فایل پیوست شد)")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
