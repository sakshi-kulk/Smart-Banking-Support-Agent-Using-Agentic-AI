"""SQLAlchemy entities and API request/response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from banking_agent.database import Base


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    existing_emi: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    application_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)
    loan_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tenure_years: Mapped[int] = mapped_column(Integer, nullable=False)
    emi: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)
    pending_application: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    awaiting_confirmation: Mapped[bool] = mapped_column(default=False, nullable=False)
    chat_history: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)


class ChatRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


class ChatResponse(BaseModel):
    conversation_id: str
    response: str


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    name: str
    account_number: str
    salary: Decimal
    existing_emi: Decimal
    credit_score: int


class LoanApplyRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    loan_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    tenure_years: int = Field(gt=0, le=40)
    emi: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    confirmed: bool


class LoanApplicationResponse(BaseModel):
    application_id: str
    status: str