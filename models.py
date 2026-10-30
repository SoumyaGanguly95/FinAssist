"""
SQLAlchemy models + session setup, combined in one file since this is a
small, single-tenant project — no need to split ORM classes from engine
setup until the schema grows past a couple of tables.

DB-agnostic on purpose: no SQLite-specific types, so DATABASE_URL is the
only thing that changes between local dev (SQLite) and Azure (Azure SQL).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy import create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    thread_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    transactions: Mapped[list["TransactionRecord"]] = relationship(back_populates="account")

class HoldingRecord(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_holding_content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    instrument_name: Mapped[str] = mapped_column(String(255))
    asset_class: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_file: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

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