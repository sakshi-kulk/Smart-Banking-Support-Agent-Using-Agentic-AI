"""HTTP endpoints for chat, customer lookup, and direct loan applications."""

import json
import logging
import re
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from banking_agent.agent import create_banking_agent
from banking_agent.database import get_db
from banking_agent.models import (
    ChatRequest,
    ChatResponse,
    ChatSession,
    Customer,
    CustomerResponse,
    LoanApplyRequest,
    LoanApplicationResponse,
)
from banking_agent.tools.application_tool import submit_loan_application
from banking_agent.tools.context import ToolRunContext, current_tool_context
from banking_agent.tools.eligibility_tool import check_loan_eligibility
from banking_agent.tools.emi_tool import calculate_emi

logger = logging.getLogger(__name__)
router = APIRouter()


def is_explicit_confirmation(message: str) -> bool:
    """Accept only clear, standalone confirmation phrases."""
    normalized = re.sub(r"[.!?]+$", "", message.strip().lower())
    return normalized in {
        "yes",
        "yes please",
        "yes, submit it",
        "yes, submit the application",
        "yes please submit it",
        "yes please submit the application",
        "i confirm",
        "i confirm, submit the application",
        "proceed",
        "proceed with the application",
        "go ahead",
        "go ahead and submit",
        "go ahead and submit the application",
    }


def _money(amount: float | Decimal) -> str:
    return f"₹{float(amount):,.2f}"


def _loan_summary(candidate: dict, account: dict, eligibility: dict, application: dict | None = None) -> str:
    application_status = application["status"] if application else "Awaiting confirmation"
    lines = [
        "=======================",
        "Loan Summary",
        "=======================",
        f"Loan Amount: {_money(candidate['loan_amount'])}",
        f"Tenure: {candidate['tenure_years']} years",
        f"Monthly EMI: {_money(candidate['emi'])}",
        "",
        f"Eligibility: {'Approved' if eligibility['eligible'] else 'Not approved'}",
        f"Reason: {eligibility['reason']}",
        "",
        f"Customer: {account['name']}",
        f"Account Number: {account['account_number']}",
        f"Credit Score: {account['credit_score']}",
        f"Application Status: {application_status}",
    ]
    if application:
        lines.append(f"Application ID: {application['application_id']}")
    else:
        lines.extend(["", "Do you want me to submit the loan application?"])
    return "\n".join(lines)


def _eligibility_summary(eligibility: dict, emi: dict | None) -> str:
    lines = [
        "=======================",
        "Loan Summary",
        "=======================",
    ]
    if emi:
        lines.extend(
            [
                f"Loan Amount: {_money(emi['loan_amount'])}",
                f"Tenure: {emi['tenure_months'] // 12} years",
                f"Monthly EMI: {_money(emi['emi'])}",
            ]
        )
    lines.extend(
        [
            "",
            "Eligibility: Not approved",
            f"Reason: {eligibility['reason']}",
            "",
            "No account lookup or application submission was performed.",
        ]
    )
    return "\n".join(lines)


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Run one turn with the agent and persist its confirmation state."""
    if db.get(Customer, request.customer_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    conversation_id = request.conversation_id or str(uuid.uuid4())
    chat_session = db.get(ChatSession, conversation_id)
    if chat_session is None:
        chat_session = ChatSession(conversation_id=conversation_id, customer_id=request.customer_id)
        db.add(chat_session)
        db.flush()
    elif chat_session.customer_id != request.customer_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation belongs to another customer.")

    confirmation = (
        chat_session.awaiting_confirmation
        and chat_session.pending_application is not None
        and is_explicit_confirmation(request.message)
    )
    candidate = chat_session.pending_application if confirmation else None
    if not confirmation:
        chat_session.pending_application = None
        chat_session.awaiting_confirmation = False

    context = ToolRunContext(
        customer_id=request.customer_id,
        confirmation_authorized=confirmation,
        candidate=candidate,
        idempotency_key=candidate.get("idempotency_key") if candidate else None,
    )
    history = []
    for entry in (chat_session.chat_history or [])[-12:]:
        if entry.get("role") == "user":
            history.append(HumanMessage(content=entry["content"]))
        elif entry.get("role") == "assistant":
            history.append(AIMessage(content=entry["content"]))

    token = current_tool_context.set(context)
    try:
        executor = create_banking_agent(request.customer_id)
        result = executor.invoke(
            {"input": request.message, "customer_id": request.customer_id, "chat_history": history}
        )
        response_text = str(result.get("output", "I could not complete that request."))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent request failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The banking assistant could not complete this request. Please try again.",
        ) from exc
    finally:
        current_tool_context.reset(token)

    eligibility = context.results.get("eligibility")
    emi = context.results.get("emi")
    account = context.results.get("account")
    submitted = context.results.get("submission")

    if submitted and candidate:
        response_text = _loan_summary(
            candidate,
            candidate["account"],
            candidate["eligibility"],
            submitted,
        )
        chat_session.pending_application = None
        chat_session.awaiting_confirmation = False
    elif eligibility and not eligibility["eligible"]:
        response_text = _eligibility_summary(eligibility, emi)
        chat_session.pending_application = None
        chat_session.awaiting_confirmation = False
    elif eligibility and eligibility["eligible"] and emi and account:
        if abs(eligibility["new_emi"] - emi["emi"]) <= 0.01 and emi["tenure_months"] % 12 == 0:
            candidate = {
                "customer_id": request.customer_id,
                "loan_amount": emi["loan_amount"],
                "tenure_years": emi["tenure_months"] // 12,
                "emi": emi["emi"],
                "idempotency_key": str(uuid.uuid4()),
                "account": account,
                "eligibility": eligibility,
            }
            chat_session.pending_application = candidate
            chat_session.awaiting_confirmation = True
            response_text = _loan_summary(candidate, account, eligibility)
        elif context.results.get("submission_denied"):
            response_text = "I could not verify that the proposed EMI matches the calculated loan. No application was submitted."
    elif context.results.get("submission_denied"):
        response_text = "I can only submit an eligible application after presenting its details and receiving your explicit confirmation. No application was submitted."

    history_data = list(chat_session.chat_history or [])
    history_data.extend(
        [
            {"role": "user", "content": request.message},
            {"role": "assistant", "content": response_text},
        ]
    )
    chat_session.chat_history = history_data[-16:]
    db.commit()
    return ChatResponse(conversation_id=conversation_id, response=response_text)


@router.get("/customer/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: str, db: Session = Depends(get_db)) -> CustomerResponse:
    """Return the account profile for a customer ID."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    return CustomerResponse.model_validate(customer)


@router.post("/loan/apply", response_model=LoanApplicationResponse)
def apply_for_loan(request: LoanApplyRequest, db: Session = Depends(get_db)) -> LoanApplicationResponse:
    """Submit a loan after an explicit API confirmation and server-side eligibility checks."""
    if not request.confirmed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Explicit confirmation is required.")
    customer = db.get(Customer, request.customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    expected_emi = json.loads(calculate_emi(float(request.loan_amount), request.tenure_years * 12))["emi"]
    if abs(float(request.emi) - expected_emi) > 0.01:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EMI does not match the 10% annual-rate calculation.")
    eligibility = json.loads(
        check_loan_eligibility(
            request.customer_id,
            float(customer.salary),
            float(customer.existing_emi),
            expected_emi,
        )
    )
    if not eligibility["eligible"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=eligibility["reason"])

    candidate = {
        "customer_id": request.customer_id,
        "loan_amount": float(request.loan_amount),
        "tenure_years": request.tenure_years,
        "emi": expected_emi,
        "eligibility": eligibility,
    }
    context = ToolRunContext(
        customer_id=request.customer_id,
        confirmation_authorized=True,
        candidate=candidate,
        idempotency_key=f"direct-{uuid.uuid4()}",
    )
    token = current_tool_context.set(context)
    try:
        result = json.loads(
            submit_loan_application(
                request.customer_id,
                float(request.loan_amount),
                request.tenure_years,
                expected_emi,
            )
        )
    finally:
        current_tool_context.reset(token)
    return LoanApplicationResponse(**result)