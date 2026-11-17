import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class shared by all database models."""


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./genai_reviewer.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Provide one database session per request and always close it afterward."""
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()


def create_tables() -> None:
    """Create local tables for development.

    Migrations will replace this startup helper when the schema begins evolving.
    """
    Base.metadata.create_all(bind=engine)
