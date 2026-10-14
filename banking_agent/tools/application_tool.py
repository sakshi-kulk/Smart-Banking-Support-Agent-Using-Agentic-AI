"""Confirmed personal loan application submission tool."""

import json
import uuid
from decimal import Decimal

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

from banking_agent.database import SessionLocal
from banking_agent.models import LoanApplication
from banking_agent.tools.context import current_tool_context


class ApplicationInput(BaseModel):
    customer_id: str = Field(description="Customer identifier")
    loan_amount: float = Field(gt=0, description="Approved loan principal in INR")
    tenure: int = Field(gt=0, le=40, description="Loan term in years")
    emi: float = Field(gt=0, description="Calculated monthly EMI in INR")


def submit_loan_application(customer_id: str, loan_amount: float, tenure: int, emi: float) -> str:
    """Insert an application only when this invocation has explicit authorization."""
    context = current_tool_context.get()
    candidate = context.candidate if context is not None else None
    eligibility = candidate.get("eligibility") if candidate is not None else None
    if (
        context is None
        or not context.confirmation_authorized
        or candidate is None
        or eligibility is None
        or not eligibility.get("eligible")
        or customer_id != context.customer_id
        or customer_id != candidate.get("customer_id")
        or abs(loan_amount - candidate.get("loan_amount", -1)) > 0.01
        or tenure != candidate.get("tenure_years")
        or abs(emi - candidate.get("emi", -1)) > 0.01
    ):
        if context is not None:
            context.results["submission_denied"] = True
        raise ToolException("Submission is blocked. An explicit customer confirmation for this exact eligible loan is required.")

    idempotency_key = context.idempotency_key or str(uuid.uuid4())
    with SessionLocal() as session:
        existing = session.query(LoanApplication).filter_by(idempotency_key=idempotency_key).one_or_none()
        if existing is not None:
            result = {"application_id": existing.application_id, "status": existing.status}
        else:
            application = LoanApplication(
                application_id=f"APP-{uuid.uuid4().hex[:12].upper()}",
                customer_id=customer_id,
                loan_amount=Decimal(str(loan_amount)).quantize(Decimal("0.01")),
                tenure_years=tenure,
                emi=Decimal(str(emi)).quantize(Decimal("0.01")),
                status="Submitted",
                idempotency_key=idempotency_key,
            )
            session.add(application)
            session.commit()
            result = {"application_id": application.application_id, "status": application.status}
    context.results["submission"] = result
    return json.dumps(result)


submit_loan_application_tool = StructuredTool.from_function(
    func=submit_loan_application,
    name="submit_loan_application",
    description="Submit the exact eligible loan only after the customer has explicitly confirmed it. The server enforces confirmation independently of this instruction.",
    args_schema=ApplicationInput,
)