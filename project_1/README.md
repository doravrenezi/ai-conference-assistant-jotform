# AI Conference Registration Assistant

## Public Demonstration

This copy contains source code and fictional demo conference content. Configure your own API credentials locally. Run with fictional attendee data only. It has not been deployed as a live service.

## Problem And Goal

This project is a full-stack prototype for conversational conference registration. The goal is to let attendees handle conference registration through natural-language chat instead of a traditional form flow.

The assistant supports five core intents:

- new registration
- registration lookup
- registration update
- registration cancellation
- conference information questions

The system uses:

- FastAPI for the backend API and frontend hosting
- plain JavaScript for the chat UI
- SQLite as the source of truth for registration state
- OpenAI for assistant reasoning, tool selection, and field normalization
- Jotform as an external submission sync target

## Repository Structure

```text
project_1/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── chat_service.py
│   │   ├── chat_llm.py
│   │   ├── chat_state.py
│   │   ├── schemas.py
│   │   ├── database.py
│   │   ├── registration_service.py
│   │   ├── jotform_service.py
│   │   ├── knowledge_base.py
│   │   └── prompts/
├── frontend/
│   ├── index.html
│   └── static/
├── knowledge_base/
├── .env.example
└── conference.db (generated locally; excluded from Git)
```

## Architecture

### Frontend

The frontend lives in `frontend/` and is intentionally simple. It is responsible for:

- rendering the conversation history
- showing loading and error states
- sending user messages to `POST /chat`
- displaying backend result cards and confirmation buttons

The frontend does not contain registration business logic. It only captures input and renders backend results.

### Backend API

The FastAPI app in `backend/app/main.py` provides:

- `GET /` to serve the chat UI
- `GET /health` for a health check
- `POST /chat` for the AI assistant flow
- `POST /registrations` for direct registration creation
- `POST /registrations/lookup` for direct registration lookup

On startup, the backend initializes the SQLite schema and loads the conference knowledge base.

### Agent Orchestration

The chat orchestration logic lives in `backend/app/chat_service.py` and `backend/app/chat_llm.py`.

Responsibilities:

- keep per-session chat history
- keep per-session registration drafts and lookup drafts
- track pending confirmations for create, update, and cancellation
- send conversation state to OpenAI
- execute backend-owned tool calls
- generate the final user-facing reply

### Database

SQLite is the source of truth for all registration state. Jotform is never treated as the authoritative record.

Database operations live in `backend/app/database.py`, while registration business logic lives in `backend/app/registration_service.py`.

### Jotform Integration

The Jotform integration lives in `backend/app/jotform_service.py`.

Responsibilities:

- read Jotform question metadata
- map canonical internal values to Jotform option labels
- create Jotform submissions
- update existing submissions when possible

### Knowledge Base / RAG

The knowledge-base logic lives in `backend/app/knowledge_base.py`.

Responsibilities:

- load structured conference configuration from `conference_config.json`
- load and chunk conference markdown documents
- answer supported questions using structured lookup plus document retrieval
- fall back to lexical retrieval when embeddings are not available

## Custom Tool-Calling Loop

The backend owns the tool loop so registration actions are performed by validated Python functions.

This project does that in `backend/app/chat_llm.py`.

High-level flow:

1. The backend sends the current conversation and session context to OpenAI.
2. The model may request a tool such as:
   - `save_registration_details`
   - `lookup_registration_record`
   - `load_registration_for_update`
   - `save_registration_update_fields`
   - `prepare_registration_cancellation`
   - `search_conference_knowledge_base`
3. The backend validates tool arguments with Pydantic models.
4. The backend executes the real Python function.
5. The backend feeds the tool output back into the loop.
6. The loop continues until the model returns a final natural-language response.

For state-changing registration completion work, the backend also requires exact tool calls for:

- `validate_registration_data`
- `create_registration`
- `submit_registration_to_jotform`
- `update_registration`
- `cancel_registration`
- `update_jotform_submission`

This keeps the LLM responsible for planning and wording, while the backend stays responsible for validation, persistence, and side effects.

## Registration Lifecycle

### New Registration

The assistant collects:

- full name
- email
- company or university
- role/title
- ticket type
- selected conference days
- workshop preference
- dietary preference
- accessibility needs

After all required fields are collected and accessibility needs are explicitly handled, the backend produces a confirmation result card. Only after user confirmation does the backend:

1. validate the final draft
2. create the SQLite record
3. attempt Jotform sync
4. return the final confirmation result

### Lookup

Lookup requires:

- registration code
- email

The registration is fetched from SQLite and shown in a result card.

### Update

Update requires:

- registration code
- email

The assistant loads the existing record into a draft, applies the requested field changes, shows a confirmation card, and only saves after explicit confirmation.

### Cancellation

Cancellation requires:

- registration code
- email

The assistant shows a cancellation review card before setting the local status to `cancelled`.

## Database Schema

### `registrations`

The current database stores:

- `id`
- `registration_code`
- `full_name`
- `email`
- `company_or_university`
- `role`
- `ticket_type`
- `selected_days`
- `workshop_preference`
- `dietary_preference`
- `accessibility_needs`
- `status`
- `jotform_submission_id`
- `jotform_sync_status`
- `created_at`
- `updated_at`

Supported lifecycle statuses:

- `active`
- `cancelled`

### `registration_events`

The project also writes event records for key lifecycle events such as:

- registration creation
- registration update
- registration cancellation
- Jotform sync success
- Jotform sync failure

Current implementation note:

- this project currently stores serialized event payloads in the available event columns rather than a richer field-by-field change history

## Jotform Integration Details

Configure your own Jotform form ID in the local `JOTFORM_FORM_ID` environment variable. This public copy does not include the original form identifier.

Current field mapping:

- `3` -> full name
- `4` -> email
- `5` -> company or university
- `6` -> role
- `7` -> ticket type
- `8` -> selected conference days
- `9` -> workshop preference
- `10` -> dietary preference
- `11` -> accessibility needs
- `12` -> registration code
- `13` -> registration status

Sync policy:

1. Save the registration locally first.
2. Attempt the Jotform sync second.
3. If Jotform fails, keep the local state.
4. Record the sync result in SQLite.
5. Return a graceful message to the user.

Local state is preserved when an external sync fails.

## Knowledge Base / RAG Implementation

The project includes a lightweight local retrieval pipeline built around fictional demonstration conference documents.

### Knowledge Sources

- `conference_config.json` for structured facts and allowed values
- markdown files such as:
  - `conference_overview.md`
  - `schedule.md`
  - `speakers.md`
  - `workshops.md`
  - `venue_and_travel.md`
  - `ticket_policy.md`
  - `cancellation_policy.md`
  - `faq.md`

### Retrieval Approach

The current implementation combines:

- structured lookup for ticket types, workshops, dates, dietary options, and conference metadata
- markdown section chunking
- embedding-based retrieval when embeddings are available
- lexical keyword fallback when embeddings are unavailable

### Validation Source

Valid values for:

- ticket type
- selected conference days
- workshop preference

are loaded from the conference config and reused by the Pydantic validators.

### Hallucination Control

If the knowledge base cannot support an answer, the assistant is instructed to say the information is unavailable instead of inventing it.

## OpenAI Usage

The backend currently uses OpenAI for three main tasks:

### 1. Assistant routing and tool selection

The model reads the session context and decides what backend tool to use next.

### 2. Field normalization

The model normalizes user-friendly answers into canonical values for fields such as:

- `ticket_type`
- `selected_days`
- `workshop_preference`
- `accessibility_needs`

### 3. Final reply generation

After backend work is complete, the model produces the final user-facing response in natural language.

## Setup Instructions

### Prerequisites

- Python 3.11 or compatible local Python
- a Jotform account and API key
- an OpenAI API key

### Environment Variables

Copy the example file:

```bash
cp .env.example .env
```

Current example variables:

```text
OPENAI_API_KEY
OPENAI_MODEL
JOTFORM_API_KEY
JOTFORM_FORM_ID
DATABASE_URL
```

Implementation note:

- the current code still uses a fixed local SQLite path at `project_1/conference.db`

### Install Dependencies

Create a local virtual environment from the `project_1` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

If you are recreating the environment yourself, install the dependencies required by the code:

```bash
pip install fastapi uvicorn python-dotenv pydantic email-validator openai
```

## Running The Project

From the `project_1` directory:

```bash
source .venv/bin/activate
cd backend/app
python -m uvicorn main:app --reload --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Original Project Validation

The original project README reported verification through manual end-to-end testing of:

- new registration
- registration lookup
- registration update
- registration cancellation
- supported conference questions
- unsupported conference questions returning an unavailable-information response

## Known Limitations

- In-progress chat session state is stored in memory, so active conversations are reset if the backend restarts.
- The chat flow depends on OpenAI responses, so end-to-end behavior is not fully deterministic.
- `DATABASE_URL` is included in `.env.example` as a configuration example, but the current code uses a fixed local SQLite path.
- The `registration_events` table records lifecycle events, but it is not yet a full field-by-field audit trail.
- If Jotform sync fails, the local SQLite record remains correct, but the external Jotform submission may be missing or outdated until retried.
- There is no separate authentication layer; lookup, update, and cancellation rely on registration code plus email.

## Future Improvements

- move the database path to a configurable environment variable
- add richer `registration_events` auditing with previous and new values per field
- add deterministic integration tests for chat orchestration with mocked OpenAI tool responses
- expand UI polish and add explicit user flow examples
- add deeper retrieval evaluation and citation-style grounding for knowledge-base answers
- document the final live demo flow and sample conversations
