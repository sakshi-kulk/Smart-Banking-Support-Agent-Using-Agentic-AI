"""SQLite engine, session management, and demo-data initialization."""

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("BANKING_DATABASE_URL", "sqlite:///./banking.db")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base for SQLAlchemy models."""


def get_db() -> Generator[Session, None, None]:
    """Provide a request-scoped database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def initialize_database() -> None:
    """Create tables and seed the demo customer once."""
    from banking_agent.models import Customer

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        if session.get(Customer, "CUST1001") is None:
            session.add(
                Customer(
                    customer_id="CUST1001",
                    name="Asha Mehta",
                    account_number="XXXXXX1001",
                    salary=60000,
                    existing_emi=5000,
                    credit_score=760,
                )
            )
            session.commit()