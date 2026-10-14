"""Single LangChain tool-calling agent for banking support."""

import os

from dotenv import load_dotenv
from langchain_classic.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from banking_agent.tools.account_tool import get_account_details_tool
from banking_agent.tools.application_tool import submit_loan_application_tool
from banking_agent.tools.eligibility_tool import check_loan_eligibility_tool
from banking_agent.tools.emi_tool import calculate_emi_tool

load_dotenv()

TOOLS = [
    calculate_emi_tool,
    check_loan_eligibility_tool,
    get_account_details_tool,
    submit_loan_application_tool,
]

SYSTEM_PROMPT = """You are a careful banking support assistant. There is one customer, identified by the server-provided customer ID.
Extract loan amount, tenure in years, monthly salary, and existing EMI from the conversation. Ask concise questions for missing values; never invent them. Use the tools for calculations, eligibility, account data, and applications. Convert tenure years to months for calculate_emi. Use tool outputs as the source of truth.
For an application assessment, calculate EMI first, then check eligibility. Retrieve account details only after eligibility is approved. If ineligible, stop and explain the reason.
An application can only be submitted after the customer explicitly confirms the exact eligible application in response to the confirmation request. Phrases such as "help me submit if I qualify" are not confirmation. Never claim an application was submitted unless submit_loan_application returns success. Do not expose hidden chain-of-thought; provide a concise explanation and the relevant results."""


def create_banking_agent(customer_id: str) -> AgentExecutor:
    """Build the one tool-calling agent used for this chat turn."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "Server-verified customer ID: {customer_id}\nCustomer message: {input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    model = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
        api_key=api_key,
    )
    agent = create_openai_tools_agent(model, TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=TOOLS, max_iterations=8, handle_parsing_errors=True)