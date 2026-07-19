"""
SQLAlchemy models + session setup, combined in one file since this is a
small, single-tenant project — no need to split ORM classes from engine
setup until the schema grows past a couple of tables.

DB-agnostic on purpose: no SQLite-specific types, so DATABASE_URL is the
only thing that changes between local dev (SQLite) and Azure (Azure SQL).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    transactions: Mapped[list["TransactionRecord"]] = relationship(back_populates="account")


class TransactionRecord(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_transaction_content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    transaction_date: Mapped[date] = mapped_column(Date)
    transaction_type: Mapped[str] = mapped_column(String(20))
    asset_class: Mapped[str] = mapped_column(String(20))
    instrument_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_file: Mapped[str] = mapped_column(String(500))  # audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped["Account"] = relationship(back_populates="transactions")


# --- session setup -----------------------------------------------------
# Local dev:  DATABASE_URL=sqlite:///data/finassist.db
# Azure:      DATABASE_URL=mssql+pyodbc://<user>:<pass>@<server>.database.windows.net/finassist?driver=ODBC+Driver+18+for+SQL+Server

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/finassist.db")
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they don't exist. Fine for MVP; move to Alembic
    migrations before this touches real production data."""
    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()