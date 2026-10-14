# Agentic Banking Support

A Python 3.11+ banking support API using one LangChain OpenAI tool-calling agent, FastAPI, SQLAlchemy, and SQLite. The agent has four ordinary Python tools: `calculate_emi`, `check_loan_eligibility`, `get_account_details`, and `submit_loan_application`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. The default model is `gpt-4o-mini`; override it with `OPENAI_MODEL`. The SQLite database defaults to `./banking.db` and is initialized with sample customer `CUST1001` (Asha Mehta, salary ₹60,000, existing EMI ₹5,000, credit score 760). The masked account number is `XXXXXX1001`.

Start the service:

```bash
uvicorn banking_agent.app:app --reload
```

Interactive API docs are available at `http://127.0.0.1:8000/docs`.

## Endpoints

`POST /chat` accepts a customer ID, message, and an optional conversation ID. Keep the returned conversation ID and pass it on each subsequent turn. Conversation state and the pending confirmation are stored in SQLite.

```json
{
	"customer_id": "CUST1001",
	"conversation_id": "loan-chat-001",
	"message": "I want a personal loan of ₹5,00,000 for three years. My monthly salary is ₹60,000, and I already pay ₹5,000 as EMI. Calculate my EMI, check eligibility, retrieve my account details, and help me submit if I qualify."
}
```

For this sample, the 10% annual-rate EMI is ₹16,133.59 (about ₹16,134). The customer meets the sample eligibility rules. The response contains the loan summary and asks whether to submit. Then send a separate confirmation:

```json
{
	"customer_id": "CUST1001",
	"conversation_id": "loan-chat-001",
	"message": "Yes, submit the application."
}
```

Only standalone confirmation phrases are accepted, and only while that conversation is awaiting confirmation for an eligible loan. Any other message clears the pending offer; the agent must assess it again. The submission tool enforces this server-side and uses an idempotency key to prevent duplicate inserts on retries.

`GET /customer/{id}` returns the sample customer's profile. `POST /loan/apply` is a direct, non-chat submission endpoint; it requires `confirmed: true`, validates the 10% EMI, and checks eligibility again against customer data stored in SQLite.

Example direct application body:

```json
{
	"customer_id": "CUST1001",
	"loan_amount": 500000,
	"tenure_years": 3,
	"emi": 16133.59,
	"confirmed": true
}
```

Eligibility requires monthly salary of at least ₹30,000, credit score of at least 700, and `(existing EMI + proposed EMI) / salary <= 0.5`. The agent uses the salary and existing EMI stated in the chat and retrieves credit score from the customer record. The direct endpoint uses the stored customer salary and EMI.

## Deployment security

This sample does not implement customer authentication or authorization. A `customer_id` is an identifier, not proof of identity. Before exposing these endpoints outside a trusted development environment, integrate the bank's identity provider and derive the authorized customer ID from the verified principal rather than trusting request data. Keep `OPENAI_API_KEY` in a secret manager and use an appropriately protected database in production.

## Development checks

```bash
pytest -q
```

The tests cover EMI calculation, confirmation phrase recognition, rejection of unauthorized submissions, and idempotent confirmed submissions. An OpenAI key is needed only for live `/chat` calls; database and tool tests run offline.

## Project layout

```text
banking_agent/
	app.py
	agent.py
	database.py
	models.py
	api/routes.py
	tools/
		emi_tool.py
		eligibility_tool.py
		account_tool.py
		application_tool.py
```
# Smart-Banking-Support-Agent-Using-Agentic-AI