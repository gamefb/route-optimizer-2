import os

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./routeplanner.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns that earlier versions had and nothing reads any more. They are removed
# from an existing database because some were created as required ("NOT NULL"),
# which would refuse every new row now that the app no longer fills them in.
RETIRED_COLUMNS = {
    "drivers": ["default_working"],
    "plans": ["order_modes"],
    "plan_stops": ["candidate_address_id"],
}


def ensure_schema() -> None:
    """Bring an existing database up to date, keeping its data.

    Creates missing tables, adds columns that newer versions introduced (always
    optional, so adding them is safe) and removes the retired ones.
    """
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing:
                    kind = column.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {kind}'))
            retired = [name for name in RETIRED_COLUMNS.get(table.name, []) if name in existing]
            if "candidate_address_id" in retired:
                _keep_single_candidates(conn, table)
            for name in retired:
                conn.execute(text(f'ALTER TABLE {table.name} DROP COLUMN "{name}"'))


def _keep_single_candidates(conn, stops) -> None:
    """Rows from before a "possible match" could list several addresses named just one.

    Carry that one over into the list before its old column goes.
    """
    listed = {
        row.id for row in conn.execute(select(stops.c.id, stops.c.candidate_address_ids)) if row.candidate_address_ids
    }
    old = conn.execute(text("SELECT id, candidate_address_id FROM plan_stops WHERE candidate_address_id IS NOT NULL"))
    for stop_id, address_id in old.all():
        if stop_id not in listed:
            conn.execute(stops.update().where(stops.c.id == stop_id).values(candidate_address_ids=[address_id]))
