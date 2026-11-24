from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Lightweight additive migration for databases created by earlier prototype versions.
    columns = {column["name"] for column in inspect(engine).get_columns("calls")}
    if "provider_started" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE calls ADD COLUMN provider_started BOOLEAN NOT NULL DEFAULT FALSE")
            )
