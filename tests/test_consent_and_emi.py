"""Focused checks for calculations and server-side submission authorization."""

import json

import pytest
from langchain_core.tools import ToolException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from banking_agent.database import Base
from banking_agent.models import ChatRequest, Customer, LoanApplication
from banking_agent.api import routes as api_routes
from banking_agent.tools import account_tool, eligibility_tool
from banking_agent.api.routes import is_explicit_confirmation
from banking_agent.tools import application_tool
from banking_agent.tools.account_tool import get_account_details
from banking_agent.tools.application_tool import submit_loan_application
from banking_agent.tools.context import ToolRunContext, current_tool_context
from banking_agent.tools.eligibility_tool import check_loan_eligibility
from banking_agent.tools.emi_tool import calculate_emi


def test_default_rate_emi_for_demo_loan() -> None:
    result = json.loads(calculate_emi(500000, 36))
    assert result["emi"] == pytest.approx(16133.59, abs=0.01)


def test_zero_interest_emi() -> None:
    result = json.loads(calculate_emi(120000, 12, 0))
    assert result["emi"] == 10000


def test_submission_is_blocked_without_explicit_confirmation() -> None:
    context = ToolRunContext(
        customer_id="CUST1001",
        candidate={"customer_id": "CUST1001", "loan_amount": 500000, "tenure_years": 3, "emi": 16133.59},
    )
    token = current_tool_context.set(context)
    try:
        with pytest.raises(ToolException, match="explicit customer confirmation"):
            submit_loan_application("CUST1001", 500000, 3, 16134.65)
        assert context.results["submission_denied"] is True
    finally:
        current_tool_context.reset(token)


def test_account_lookup_is_blocked_before_eligibility() -> None:
    context = ToolRunContext(customer_id="CUST1001")
    token = current_tool_context.set(context)
    try:
        with pytest.raises(ToolException, match="only after this customer has passed"):
            get_account_details("CUST1001")
    finally:
        current_tool_context.reset(token)


def test_confirmation_must_be_standalone() -> None:
    assert is_explicit_confirmation("Yes.")
    assert is_explicit_confirmation("go ahead and submit the application")
    assert not is_explicit_confirmation("help me submit if I qualify")
    assert not is_explicit_confirmation("yes, but first change the amount")


def test_confirmed_submission_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with test_sessions() as session:
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
    monkeypatch.setattr(application_tool, "SessionLocal", test_sessions)
    context = ToolRunContext(
        customer_id="CUST1001",
        confirmation_authorized=True,
        candidate={
            "customer_id": "CUST1001",
            "loan_amount": 500000,
            "tenure_years": 3,
            "emi": 16133.59,
            "eligibility": {"eligible": True},
        },
        idempotency_key="test-confirmation",
    )
    token = current_tool_context.set(context)
    try:
        first = json.loads(submit_loan_application("CUST1001", 500000, 3, 16133.59))
        second = json.loads(submit_loan_application("CUST1001", 500000, 3, 16133.59))
    finally:
        current_tool_context.reset(token)
    with test_sessions() as session:
        count = session.scalar(select(func.count()).select_from(LoanApplication))
    assert first == second
    assert first["status"] == "Submitted"
    assert count == 1
    engine.dispose()


def test_chat_confirmation_workflow_persists_pending_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chat.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with test_sessions() as session:
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
    monkeypatch.setattr(eligibility_tool, "SessionLocal", test_sessions)
    monkeypatch.setattr(account_tool, "SessionLocal", test_sessions)
    monkeypatch.setattr(application_tool, "SessionLocal", test_sessions)

    class FakeAgent:
        def invoke(self, payload: dict) -> dict[str, str]:
            if is_explicit_confirmation(payload["input"]):
                submit_loan_application("CUST1001", 500000, 3, 16133.59)
            else:
                emi = json.loads(calculate_emi(500000, 36))
                check_loan_eligibility("CUST1001", 60000, 5000, emi["emi"])
                get_account_details("CUST1001")
            return {"output": "Tool workflow completed."}

    monkeypatch.setattr(api_routes, "create_banking_agent", lambda customer_id: FakeAgent())
    with test_sessions() as session:
        first = api_routes.chat(
            ChatRequest(
                customer_id="CUST1001",
                conversation_id="chat-test",
                message="Loan 500000 for 3 years; salary 60000; existing EMI 5000.",
            ),
            session,
        )
        second = api_routes.chat(
            ChatRequest(customer_id="CUST1001", conversation_id="chat-test", message="Yes, submit the application."),
            session,
        )
        count = session.scalar(select(func.count()).select_from(LoanApplication))
    assert first.response.startswith("=======================\nLoan Summary")
    assert "Do you want me to submit" in first.response
    assert "Application Status: Submitted" in second.response
    assert "Application ID: APP-" in second.response
    assert count == 1
    engine.dispose()