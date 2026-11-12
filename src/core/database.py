import os
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

# Override with the VETCLINIC_DATABASE_URL environment variable, e.g.
#   postgresql://postgres:<password>@localhost:5432/vetclinic
#   sqlite:///vetclinic.db
DATABASE_URL = os.environ.get(
    "VETCLINIC_DATABASE_URL",
    "postgresql://postgres:mehrfar2@localhost:5432/vetclinic",
)

Base = declarative_base()

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _ensure_postgres_database(url: str) -> None:
    """Create the target Postgres database if it does not exist yet."""
    db_url = make_url(url)
    if not db_url.drivername.startswith("postgresql") or not db_url.database:
        return
    admin_engine = create_engine(
        db_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_url.database},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_url.database}"'))
    finally:
        admin_engine.dispose()


def _column_default_sql(column, dialect_name: str) -> str | None:
    default = column.default.arg if column.default is not None and column.default.is_scalar else None
    if default is None:
        return None
    if isinstance(default, bool):
        if dialect_name == "postgresql":
            return "TRUE" if default else "FALSE"
        return "1" if default else "0"
    if isinstance(default, (int, float)):
        return str(default)
    return "'" + str(default).replace("'", "''") + "'"


def add_missing_columns(bind) -> list[str]:
    """Tiny additive migration: add columns that exist in the models but not yet in the database.

    `create_all` only creates missing tables, so this keeps older databases working after an upgrade.
    """
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    added = []
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(dialect=bind.dialect)}'
                default = _column_default_sql(column, bind.dialect.name)
                if default is not None:
                    ddl += f" DEFAULT {default}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    return added


def init_db() -> None:
    """Create the database (Postgres only), all tables, missing columns and default data."""
    from core import models  # noqa: F401  (registers the tables on Base)
    from core import vaccines

    _ensure_postgres_database(DATABASE_URL)
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    with get_session() as session:
        vaccines.seed_vaccine_types(session)
        vaccines.backfill_from_visits(session)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
