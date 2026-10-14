"""Personal loan eligibility assessment tool."""

import json
from decimal import Decimal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from banking_agent.database import SessionLocal
from banking_agent.models import Customer
from banking_agent.tools.context import current_tool_context


class EligibilityInput(BaseModel):
    customer_id: str = Field(description="Customer identifier")
    salary: float = Field(gt=0, description="Monthly salary in INR provided by the customer")
    existing_emi: float = Field(ge=0, description="Existing monthly EMI in INR")
    new_emi: float = Field(gt=0, description="Proposed loan monthly EMI in INR")


def check_loan_eligibility(customer_id: str, salary: float, existing_emi: float, new_emi: float) -> str:
    """Assess income, credit score, and total monthly obligation ratio."""
    if salary <= 0 or existing_emi < 0 or new_emi <= 0:
        raise ValueError("Salary and proposed EMI must be positive; existing EMI cannot be negative.")
    with SessionLocal() as session:
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise ValueError(f"Customer {customer_id} was not found.")
        credit_score = customer.credit_score

    ratio = (existing_emi + new_emi) / salary
    reasons = []
    if salary < 30000:
        reasons.append("monthly salary is below ₹30,000")
    if credit_score < 700:
        reasons.append("credit score is below 700")
    if ratio > 0.5:
        reasons.append("monthly obligations exceed 50% of salary")
    result = {
        "eligible": not reasons,
        "reason": "Meets all eligibility criteria." if not reasons else "; ".join(reasons) + ".",
        "obligation_ratio": round(ratio, 4),
        "credit_score": credit_score,
    }
    context = current_tool_context.get()
    if context is not None:
        context.results["eligibility"] = {
            **result,
            "customer_id": customer_id,
            "salary": salary,
            "existing_emi": existing_emi,
            "new_emi": new_emi,
        }
    return json.dumps(result)


check_loan_eligibility_tool = StructuredTool.from_function(
    func=check_loan_eligibility,
    name="check_loan_eligibility",
    description="Check loan eligibility using salary >= ₹30,000, database credit score >= 700, and (existing EMI + new EMI) / salary <= 0.5.",
    args_schema=EligibilityInput,
)