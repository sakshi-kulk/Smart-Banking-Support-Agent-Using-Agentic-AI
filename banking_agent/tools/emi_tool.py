"""Loan EMI calculation tool."""

import json
import math

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from banking_agent.tools.context import current_tool_context


class EmiInput(BaseModel):
    loan_amount: float = Field(gt=0, description="Principal loan amount in INR")
    tenure_months: int = Field(gt=0, le=480, description="Loan tenure in months")
    annual_interest_rate: float = Field(default=10.0, ge=0, le=100, description="Annual interest rate in percent")


def calculate_emi(loan_amount: float, tenure_months: int, annual_interest_rate: float = 10.0) -> str:
    """Calculate the fixed monthly installment for a reducing-balance loan."""
    if loan_amount <= 0 or tenure_months <= 0 or annual_interest_rate < 0:
        raise ValueError("Loan amount and tenure must be positive; interest rate cannot be negative.")
    monthly_rate = annual_interest_rate / 1200
    if monthly_rate == 0:
        emi = loan_amount / tenure_months
    else:
        growth = math.pow(1 + monthly_rate, tenure_months)
        emi = loan_amount * monthly_rate * growth / (growth - 1)
    result = {"emi": round(emi, 2)}
    context = current_tool_context.get()
    if context is not None:
        context.results["emi"] = {
            **result,
            "loan_amount": loan_amount,
            "tenure_months": tenure_months,
            "annual_interest_rate": annual_interest_rate,
        }
    return json.dumps(result)


calculate_emi_tool = StructuredTool.from_function(
    func=calculate_emi,
    name="calculate_emi",
    description="Calculate a personal-loan EMI. Default annual interest rate is 10%. Call with loan amount and tenure in months.",
    args_schema=EmiInput,
)