"""Whole-database backup and restore as a portable zip (works for PostgreSQL and SQLite)."""

import base64
import io
import json
import os
import zipfile
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, LargeBinary, delete, insert, select, text

from core.database import Base

FORMAT_VERSION = 1
BACKUP_DIR = Path(os.environ.get("VETCLINIC_BACKUP_DIR", Path(__file__).resolve().parents[1] / "data" / "backups"))
AUTO_BACKUP_KEEP = 14


def _encode(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _decode(column, value):
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return date.fromisoformat(value)
    if isinstance(column.type, LargeBinary) and isinstance(value, dict):
        return base64.b64decode(value["__b64__"])
    return value


def export_backup(engine) -> bytes:
    from core import models  # noqa: F401  (registers the tables)

    tables = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            rows = conn.execute(select(table)).mappings()
            tables[table.name] = [{k: _encode(v) for k, v in row.items()} for row in rows]
    payload = {"format": FORMAT_VERSION, "created_at": datetime.now().isoformat(), "tables": tables}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup.json", json.dumps(payload, ensure_ascii=False))
    return buffer.getvalue()


def read_backup_info(data: bytes) -> dict:
    payload = _load(data)
    return {
        "created_at": datetime.fromisoformat(payload["created_at"]),
        "counts": {name: len(rows) for name, rows in payload["tables"].items()},
    }


def _load(data: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            payload = json.loads(archive.read("backup.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("This is not a valid backup file. (فایل پشتیبان نامعتبر است)") from exc
    if payload.get("format") != FORMAT_VERSION or "tables" not in payload:
        raise ValueError("Unsupported backup format. (قالب فایل پشتیبان پشتیبانی نمی‌شود)")
    return payload


def restore_backup(engine, data: bytes) -> dict:
    """Replace ALL current data with the backup's contents, in a single transaction."""
    from core import models  # noqa: F401

    payload = _load(data)
    counts = {}
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))
        for table in Base.metadata.sorted_tables:
            rows = payload["tables"].get(table.name, [])
            columns = {c.name: c for c in table.columns}
            clean = [{k: _decode(columns[k], v) for k, v in row.items() if k in columns} for row in rows]
            if clean:
                conn.execute(insert(table), clean)
            counts[table.name] = len(clean)
        if engine.dialect.name == "postgresql":
            for table in Base.metadata.sorted_tables:
                if "id" in table.columns:
                    conn.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), "
                        f"(SELECT MAX(id) FROM \"{table.name}\") IS NOT NULL)"
                    ))
    return counts


def list_backups(directory: Path = BACKUP_DIR) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("vetclinic-*.zip"), reverse=True)


def auto_backup(engine, directory: Path = BACKUP_DIR, keep: int = AUTO_BACKUP_KEEP, today: date | None = None):
    """Write one backup per day (the first time the app starts that day) and keep the newest `keep` files."""
    today = today or date.today()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"vetclinic-{today.isoformat()}.zip"
    created = None
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(export_backup(engine))
        tmp.replace(path)
        created = path
    for old in list_backups(directory)[keep:]:
        old.unlink(missing_ok=True)
    return created
