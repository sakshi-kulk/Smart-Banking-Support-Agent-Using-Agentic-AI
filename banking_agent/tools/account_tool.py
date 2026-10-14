"""Customer account lookup tool."""

import json

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

from banking_agent.database import SessionLocal
from banking_agent.models import Customer
from banking_agent.tools.context import current_tool_context


class AccountInput(BaseModel):
    customer_id: str = Field(description="Customer identifier")


def get_account_details(customer_id: str) -> str:
    """Retrieve the customer's basic account and credit information."""
    context = current_tool_context.get()
    eligibility = context.results.get("eligibility") if context is not None else None
    if context is not None and eligibility is None and context.candidate is not None:
        eligibility = context.candidate.get("eligibility")
    if (
        context is None
        or customer_id != context.customer_id
        or eligibility is None
        or not eligibility.get("eligible")
    ):
        raise ToolException("Account details are available only after this customer has passed loan eligibility checks.")
    with SessionLocal() as session:
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise ValueError(f"Customer {customer_id} was not found.")
        result = {
            "customer_id": customer.customer_id,
            "name": customer.name,
            "account_number": customer.account_number,
            "credit_score": customer.credit_score,
        }
    context.results["account"] = result
    return json.dumps(result)


get_account_details_tool = StructuredTool.from_function(
    func=get_account_details,
    name="get_account_details",
    description="Fetch the customer's name, masked account number, and credit score from SQLite. Call only after eligibility is approved.",
    args_schema=AccountInput,
)