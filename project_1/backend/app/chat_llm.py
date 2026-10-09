# This file handles OpenAI-based routing, reply generation, field normalization, and tool-call checks.
import json
import os
from typing import Literal
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field, ValidationError, model_validator

from knowledge_base import search_conference_knowledge_base as search_conference_knowledge_base_impl
from registration_service import (
    build_registration_cancellation_request_result,
    build_registration_cancellation_result,
    build_registration_confirmation_request_result,
    build_registration_confirmation_result,
    build_registration_lookup_result,
    build_registration_update_request_result,
    build_registration_update_result,
    create_registration_record,
    find_registration_or_404,
    registration_to_draft,
    sync_registration_record_to_jotform,
    sync_registration_update_by_submission_id,
    update_registration_record,
    validate_registration_draft,
)
from schemas import (
    ALLOWED_DAYS,
    ALLOWED_TICKET_TYPES,
    ALLOWED_WORKSHOPS,
    ChatMessage,
    REGISTRATION_COLLECTION_ORDER,
    RegistrationDraft,
    RegistrationLookupDraft,
)


APP_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = APP_DIR / "prompts"
ASSISTANT_PROMPT = (PROMPTS_DIR / "conference_registration_assistant_prompt.txt").read_text(encoding="utf-8").strip()
REGISTRATION_COMPLETION_TOOL_PROMPT = (PROMPTS_DIR / "registration_completion_tool_prompt.txt").read_text(encoding="utf-8").strip()
REGISTRATION_FIELD_NORMALIZATION_PROMPT = (PROMPTS_DIR / "registration_field_normalization_prompt.txt").read_text(encoding="utf-8").strip()
REGISTRATION_FIELD_ORDER = list(REGISTRATION_COLLECTION_ORDER)
LOOKUP_FIELD_ORDER = list(RegistrationLookupDraft.model_fields)

def get_openai_():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="OpenAI SDK is not installed.") from exc

    return OpenAI(api_key=api_key)


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

OPENAI_ = get_openai_()
OPENAI_MODEL = get_openai_model()


class AssistantToolValidationError(Exception):
    def __init__(
        self,
        tool_name: str,
        invalid_fields: list[dict[str, str | None]],
        retry_field_name: str | None = None,
        retry_mode: str | None = None,
    ):
        self.tool_name = tool_name
        self.invalid_fields = invalid_fields
        self.retry_field_name = retry_field_name
        self.retry_mode = retry_mode
        super().__init__(f"Invalid assistant tool input for {tool_name}.")


class MissingFollowupRegistrationError(Exception):
    def __init__(self, mode: str):
        self.mode = mode
        super().__init__(f"No previously loaded registration is available for {mode}.")


class RegistrationDraftToolArgs(BaseModel):
    full_name: str
    email: EmailStr
    company_or_university: str
    role: str
    ticket_type: str
    selected_days: list[str]
    workshop_preference: str
    dietary_preference: str
    accessibility_needs: str | None = None


class ValidateRegistrationDataToolArgs(BaseModel):
    draft: RegistrationDraftToolArgs


class CreateRegistrationToolArgs(BaseModel):
    draft: RegistrationDraftToolArgs


class FindRegistrationToolArgs(BaseModel):
    registration_code: str
    email: EmailStr


class UpdateRegistrationToolArgs(BaseModel):
    registration_id: int = Field(gt=0)
    registration_code: str
    status: str
    draft: RegistrationDraftToolArgs


class CancelRegistrationToolArgs(BaseModel):
    registration_id: int = Field(gt=0)
    registration_code: str
    email: EmailStr
    status: Literal["cancelled"]


class SubmitRegistrationToJotformToolArgs(BaseModel):
    registration_id: int = Field(gt=0)
    registration_code: str
    status: str
    draft: RegistrationDraftToolArgs


class UpdateJotformSubmissionToolArgs(BaseModel):
    registration_id: int = Field(gt=0)
    jotform_submission_id: str | None = None
    registration_code: str
    status: str
    draft: RegistrationDraftToolArgs


class SearchConferenceKnowledgeBaseToolArgs(BaseModel):
    query: str
    topic: Literal["ticket_types", "workshops", "dates", "general"]


def empty_tool_parameters() -> dict:
    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def registration_draft_tool_parameters() -> dict:
    return {
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "email": {"type": "string"},
            "company_or_university": {"type": "string"},
            "role": {"type": "string"},
            "ticket_type": {"type": "string", "enum": sorted(ALLOWED_TICKET_TYPES)},
            "selected_days": {"type": "array", "items": {"type": "string", "enum": sorted(ALLOWED_DAYS)}},
            "workshop_preference": {"type": "string", "enum": sorted(ALLOWED_WORKSHOPS)},
            "dietary_preference": {"type": "string"},
            "accessibility_needs": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": [
            "full_name",
            "email",
            "company_or_university",
            "role",
            "ticket_type",
            "selected_days",
            "workshop_preference",
            "dietary_preference",
            "accessibility_needs",
        ],
        "additionalProperties": False,
    }


def partial_registration_update_tool_parameters() -> dict:
    return {
        "type": "object",
        "properties": {
            "full_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "email": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "company_or_university": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "role": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "ticket_type": {"anyOf": [{"type": "string", "enum": sorted(ALLOWED_TICKET_TYPES)}, {"type": "null"}]},
            "selected_days": {
                "anyOf": [
                    {"type": "array", "items": {"type": "string", "enum": sorted(ALLOWED_DAYS)}},
                    {"type": "null"},
                ]
            },
            "workshop_preference": {
                "anyOf": [{"type": "string", "enum": sorted(ALLOWED_WORKSHOPS)}, {"type": "null"}]
            },
            "dietary_preference": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "accessibility_needs": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": [
            "full_name",
            "email",
            "company_or_university",
            "role",
            "ticket_type",
            "selected_days",
            "workshop_preference",
            "dietary_preference",
            "accessibility_needs",
        ],
        "additionalProperties": False,
    }


def normalized_text_value_schema(field_name: str) -> dict:
    if field_name == "ticket_type":
        return {
            "type": "string",
            "enum": sorted(ALLOWED_TICKET_TYPES),
            "description": "The normalized ticket type.",
        }

    if field_name == "workshop_preference":
        return {
            "type": "string",
            "enum": sorted(ALLOWED_WORKSHOPS),
            "description": "The normalized workshop preference.",
        }

    if field_name == "accessibility_needs":
        return {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "The normalized accessibility needs value. Use null when the user says they have no accessibility needs.",
        }

    return {
        "type": "string",
        "description": "The normalized text value. Use this for every field except selected_days.",
    }


def registration_value_normalization_tools(field_name: str) -> list[dict]:
    return [
        {
            "type": "function",
            "name": "normalize_registration_field_value",
            "description": "Normalize a user's raw answer into the canonical value expected by the registration backend.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_name": {
                        "type": "string",
                        "enum": [field_name],
                        "description": "The registration field being normalized.",
                    },
                    "text_value": normalized_text_value_schema(field_name),
                    "list_value": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(ALLOWED_DAYS)},
                        "description": "The normalized list value for selected_days. Use an empty list for other fields.",
                    },
                },
                "required": ["field_name", "text_value", "list_value"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


def registration_completion_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "validate_registration_data",
            "description": "Validate that the collected registration draft is complete and ready for registration creation.",
            "parameters": {
                "type": "object",
                "properties": {"draft": registration_draft_tool_parameters()},
                "required": ["draft"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "create_registration",
            "description": "Create the local SQLite registration after validation succeeds.",
            "parameters": {
                "type": "object",
                "properties": {"draft": registration_draft_tool_parameters()},
                "required": ["draft"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "submit_registration_to_jotform",
            "description": "Submit the created registration to Jotform after the local registration has been created.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_id": {"type": "integer", "minimum": 1},
                    "registration_code": {"type": "string"},
                    "status": {"type": "string"},
                    "draft": registration_draft_tool_parameters(),
                },
                "required": ["registration_id", "registration_code", "status", "draft"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


def registration_completion_tool(tool_name: str) -> dict:
    for tool in registration_completion_tools():
        if tool["name"] == tool_name:
            return tool
    raise HTTPException(status_code=500, detail=f"Unknown registration completion tool: {tool_name}")


def lookup_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "find_registration",
            "description": "Find an existing registration using the registration code and attendee email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_code": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["registration_code", "email"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


def lookup_tool(tool_name: str) -> dict:
    for tool in lookup_tools():
        if tool["name"] == tool_name:
            return tool
    raise HTTPException(status_code=500, detail=f"Unknown lookup tool: {tool_name}")


def mutation_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "update_registration",
            "description": "Update an existing local SQLite registration with the validated registration draft.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_id": {"type": "integer", "minimum": 1},
                    "registration_code": {"type": "string"},
                    "status": {"type": "string"},
                    "draft": registration_draft_tool_parameters(),
                },
                "required": ["registration_id", "registration_code", "status", "draft"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "cancel_registration",
            "description": "Cancel an existing registration locally after the registration has been verified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_id": {"type": "integer", "minimum": 1},
                    "registration_code": {"type": "string"},
                    "email": {"type": "string"},
                    "status": {"type": "string", "enum": ["cancelled"]},
                },
                "required": ["registration_id", "registration_code", "email", "status"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "update_jotform_submission",
            "description": "Sync an updated or cancelled registration to the existing Jotform submission when possible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_id": {"type": "integer", "minimum": 1},
                    "jotform_submission_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "registration_code": {"type": "string"},
                    "status": {"type": "string"},
                    "draft": registration_draft_tool_parameters(),
                },
                "required": ["registration_id", "jotform_submission_id", "registration_code", "status", "draft"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


def mutation_tool(tool_name: str) -> dict:
    for tool in mutation_tools():
        if tool["name"] == tool_name:
            return tool
    raise HTTPException(status_code=500, detail=f"Unknown mutation tool: {tool_name}")


def knowledge_base_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "search_conference_knowledge_base",
            "description": "Search the conference knowledge base using structured facts and retrieved document sections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "topic": {"type": "string", "enum": ["ticket_types", "workshops", "dates", "general"]},
                },
                "required": ["query", "topic"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]


def knowledge_base_tool(tool_name: str) -> dict:
    for tool in knowledge_base_tools():
        if tool["name"] == tool_name:
            return tool
    raise HTTPException(status_code=500, detail=f"Unknown knowledge base tool: {tool_name}")



def build_registration_draft_summary(draft: RegistrationDraft) -> dict[str, str | list[str]]:
    return {
        field_name: value
        for field_name in REGISTRATION_FIELD_ORDER
        if (value := getattr(draft, field_name)) not in (None, "", [])
    }


def build_lookup_draft_summary(draft: RegistrationLookupDraft) -> dict[str, str]:
    return {
        field_name: value
        for field_name in LOOKUP_FIELD_ORDER
        if (value := getattr(draft, field_name)) not in (None, "")
    }


TOOL_ARGUMENT_MODELS = {
    "validate_registration_data": ValidateRegistrationDataToolArgs,
    "create_registration": CreateRegistrationToolArgs,
    "find_registration": FindRegistrationToolArgs,
    "update_registration": UpdateRegistrationToolArgs,
    "cancel_registration": CancelRegistrationToolArgs,
    "submit_registration_to_jotform": SubmitRegistrationToJotformToolArgs,
    "update_jotform_submission": UpdateJotformSubmissionToolArgs,
    "search_conference_knowledge_base": SearchConferenceKnowledgeBaseToolArgs,
}


def parse_tool_arguments(tool_name: str, arguments: dict) -> BaseModel:
    model_class = TOOL_ARGUMENT_MODELS.get(tool_name)
    if model_class is None:
        raise HTTPException(status_code=500, detail=f"Unknown tool validator for {tool_name}.")
    try:
        return model_class.model_validate(arguments)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid arguments for {tool_name}.") from exc


def require_exact_tool_arguments(tool_name: str, parsed_arguments: BaseModel, expected_arguments: dict) -> None:
    actual = parsed_arguments.model_dump(mode="json")
    if actual != expected_arguments:
        raise HTTPException(status_code=502, detail=f"Assistant called {tool_name} with unexpected arguments.")


def require_tool_call(
    *,
    tool_definition: dict,
    system_prompt: str,
    payload: dict,
) -> BaseModel:
    response = OPENAI_.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)},
        ],
        tools=[tool_definition],
        tool_choice="required",
        parallel_tool_calls=False,
    )

    for output_item in response.output:
        if output_item.type != "function_call":
            continue
        if output_item.name != tool_definition["name"]:
            raise HTTPException(status_code=502, detail=f"Assistant called an unknown tool instead of {tool_definition['name']}.")
        try:
            arguments = json.loads(output_item.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail=f"Assistant returned invalid JSON for {tool_definition['name']}.") from exc
        parsed_arguments = parse_tool_arguments(tool_definition["name"], arguments)
        require_exact_tool_arguments(tool_definition["name"], parsed_arguments, payload)
        return parsed_arguments

    raise HTTPException(status_code=502, detail=f"Assistant did not call {tool_definition['name']}.")


def require_registration_tool_call(tool_name: str, draft: RegistrationDraft) -> None:
    require_tool_call(
        tool_definition=registration_completion_tool(tool_name),
        system_prompt=REGISTRATION_COMPLETION_TOOL_PROMPT,
        payload={"draft": draft.model_dump(mode="json")},
    )


def require_lookup_tool_call(tool_name: str, draft: RegistrationLookupDraft) -> None:
    payload = {
        "registration_code": draft.registration_code,
        "email": str(draft.email),
    }
    require_tool_call(
        tool_definition=lookup_tool(tool_name),
        system_prompt=(
            "You must call the backend tool needed to find a saved conference registration. "
            "Call find_registration with the verified registration code and attendee email. "
            "Do not omit or change either field."
        ),
        payload=payload,
    )


def require_mutation_tool_call(tool_name: str, payload: dict, instruction: str) -> None:
    require_tool_call(
        tool_definition=mutation_tool(tool_name),
        system_prompt=instruction,
        payload=payload,
    )


def require_knowledge_base_tool_call(query: str, topic: str) -> None:
    require_tool_call(
        tool_definition=knowledge_base_tool("search_conference_knowledge_base"),
        system_prompt=(
            "You must call search_conference_knowledge_base before answering a conference information question. "
            "Call it with the exact user query and the selected topic."
        ),
        payload={"query": query, "topic": topic},
    )


def run_registration_completion_tool_loop(draft: RegistrationDraft) -> dict:
    require_registration_tool_call("validate_registration_data", draft)
    validation_result = validate_registration_draft(draft)
    if not validation_result["valid"]:
        return {
            "success": False,
            "error": {"type": "missing_required_fields", "missing_fields": validation_result["missing_fields"]},
        }

    require_registration_tool_call("create_registration", draft)
    created_registration = create_registration_record(draft)
    require_tool_call(
        tool_definition=registration_completion_tool("submit_registration_to_jotform"),
        system_prompt=(
            "You must call submit_registration_to_jotform after local registration creation succeeds. "
            "Use the exact created registration identifiers and the validated registration draft."
        ),
        payload={
            "registration_id": created_registration["registration_id"],
            "registration_code": created_registration["registration_code"],
            "status": created_registration["status"],
            "draft": draft.model_dump(mode="json"),
        },
    )
    sync_result = sync_registration_record_to_jotform(
        created_registration["registration_id"],
        draft,
        created_registration["registration_code"],
        created_registration["status"],
    )
    confirmation_result = build_registration_confirmation_result(
        created_registration["registration_id"],
        created_registration["registration_code"],
        created_registration["status"],
        draft,
        sync_result["jotform_submission_id"],
        sync_result["jotform_sync_error"],
    )
    return {
        "success": True,
        "result": confirmation_result,
        "registration_id": created_registration["registration_id"],
        "registration_code": created_registration["registration_code"],
        "status": created_registration["status"],
        "jotform_submission_id": sync_result["jotform_submission_id"],
        "jotform_sync_error": sync_result["jotform_sync_error"],
    }


def run_registration_update(
    draft: RegistrationDraft,
    registration_id: int,
    registration_code: str,
    status: str,
    jotform_submission_id: str | None,
) -> dict:
    require_registration_tool_call("validate_registration_data", draft)
    validation_result = validate_registration_draft(draft)
    if not validation_result["valid"]:
        return {
            "success": False,
            "error": {"type": "missing_required_fields", "missing_fields": validation_result["missing_fields"]},
        }

    require_mutation_tool_call(
        "update_registration",
        {
            "registration_id": registration_id,
            "registration_code": registration_code,
            "status": status,
            "draft": draft.model_dump(mode="json"),
        },
        (
            "You must call update_registration to save the revised registration locally. "
            "Use the exact registration identifiers, current status, and validated registration draft."
        ),
    )
    update_registration_record(registration_id, draft, status)
    require_mutation_tool_call(
        "update_jotform_submission",
        {
            "registration_id": registration_id,
            "jotform_submission_id": jotform_submission_id,
            "registration_code": registration_code,
            "status": status,
            "draft": draft.model_dump(mode="json"),
        },
        (
            "You must call update_jotform_submission after the local registration update succeeds. "
            "Use the exact identifiers and draft. If the Jotform submission ID is missing, still call the tool with null."
        ),
    )
    jotform_sync_result = sync_registration_update_by_submission_id(
        registration_id,
        jotform_submission_id,
        draft,
        registration_code,
        status,
    )
    return {
        "success": True,
        "result": build_registration_update_result(
            registration_id,
            registration_code,
            status,
            draft,
            jotform_sync_result["error_detail"],
        ),
        "registration_id": registration_id,
        "registration_code": registration_code,
        "status": status,
        "jotform_sync_error": jotform_sync_result["error_detail"],
        "jotform_sync_status": jotform_sync_result["sync_status"],
    }


def run_registration_cancellation(registration: dict) -> dict:
    draft = registration_to_draft(registration)
    status = "cancelled"
    require_mutation_tool_call(
        "cancel_registration",
        {
            "registration_id": registration["id"],
            "registration_code": registration["registration_code"],
            "email": registration["email"],
            "status": status,
        },
        (
            "You must call cancel_registration before the backend changes the registration status to cancelled. "
            "Use the exact registration identifiers, attendee email, and cancelled status."
        ),
    )
    update_registration_record(registration["id"], draft, status)
    require_mutation_tool_call(
        "update_jotform_submission",
        {
            "registration_id": registration["id"],
            "jotform_submission_id": registration.get("jotform_submission_id"),
            "registration_code": registration["registration_code"],
            "status": status,
            "draft": draft.model_dump(mode="json"),
        },
        (
            "You must call update_jotform_submission after the local cancellation is saved. "
            "Use the exact identifiers and cancelled registration draft. If the Jotform submission ID is missing, still call the tool with null."
        ),
    )
    sync_result = sync_registration_update_by_submission_id(
        registration["id"],
        registration.get("jotform_submission_id"),
        draft,
        registration["registration_code"],
        status,
    )
    return {
        "registration_id": registration["id"],
        "registration_code": registration["registration_code"],
        "status": status,
        "jotform_sync_error": sync_result["error_detail"],
        "jotform_sync_status": sync_result["sync_status"],
        "result": build_registration_cancellation_result(
            registration["id"],
            registration["registration_code"],
            status,
            draft,
            sync_result["error_detail"],
        ),
    }


def run_conference_knowledge_search(query: str, topic: str) -> dict:
    require_knowledge_base_tool_call(query, topic)
    return search_conference_knowledge_base_impl(query, topic=topic, limit=3)


def normalize_registration_field_value(field_name: str, raw_value: str):
    if field_name == "full_name":
        return " ".join(raw_value.strip().split())

    normalization_prompt = REGISTRATION_FIELD_NORMALIZATION_PROMPT.format(
        field_name=field_name,
        ticket_types=", ".join(sorted(ALLOWED_TICKET_TYPES)),
        workshops=", ".join(sorted(ALLOWED_WORKSHOPS)),
        days=", ".join(sorted(ALLOWED_DAYS)),
    )
    response = OPENAI_.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": normalization_prompt},
            {"role": "user", "content": raw_value},
        ],
        tools=registration_value_normalization_tools(field_name),
        tool_choice="required",
        parallel_tool_calls=False,
    )

    for output_item in response.output:
        if output_item.type != "function_call":
            continue
        arguments = json.loads(output_item.arguments or "{}")
        if field_name == "selected_days":
            return arguments.get("list_value", [])
        normalized_text_value = arguments.get("text_value", raw_value)
        if normalized_text_value is None:
            return None
        return str(normalized_text_value).strip() or raw_value.strip()

    return [] if field_name == "selected_days" else raw_value.strip()


class SaveRegistrationDetailsArgs(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    company_or_university: str | None = None
    role: str | None = None
    ticket_type: str | None = None
    selected_days: list[str] | None = None
    workshop_preference: str | None = None
    dietary_preference: str | None = None
    accessibility_needs: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("At least one registration field must be provided.")
        return self


class LookupRegistrationRecordArgs(BaseModel):
    registration_code: str
    email: EmailStr


class LoadRegistrationForUpdateArgs(BaseModel):
    registration_code: str | None = None
    email: EmailStr | None = None
    use_last_loaded: bool = False

    @model_validator(mode="after")
    def validate_source(self):
        if self.use_last_loaded:
            return self
        if self.registration_code and self.email:
            return self
        raise ValueError("Provide registration_code and email, or set use_last_loaded to true.")


class SaveRegistrationUpdateFieldsArgs(SaveRegistrationDetailsArgs):
    pass


class PrepareRegistrationCancellationArgs(BaseModel):
    registration_code: str | None = None
    email: EmailStr | None = None
    use_last_loaded: bool = False

    @model_validator(mode="after")
    def validate_source(self):
        if self.use_last_loaded:
            return self
        if self.registration_code and self.email:
            return self
        raise ValueError("Provide registration_code and email, or set use_last_loaded to true.")


class ResetSessionStateArgs(BaseModel):
    scope: Literal["all", "registration", "lookup", "update", "cancel"]


ASSISTANT_TOOL_MODELS = {
    "save_registration_details": SaveRegistrationDetailsArgs,
    "lookup_registration_record": LookupRegistrationRecordArgs,
    "load_registration_for_update": LoadRegistrationForUpdateArgs,
    "save_registration_update_fields": SaveRegistrationUpdateFieldsArgs,
    "prepare_registration_cancellation": PrepareRegistrationCancellationArgs,
    "reset_session_state": ResetSessionStateArgs,
    "search_conference_knowledge_base": SearchConferenceKnowledgeBaseToolArgs,
}


def assistant_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "save_registration_details",
            "description": "Save one or more registration fields for a new registration draft.",
            "parameters": partial_registration_update_tool_parameters(),
            "strict": True,
        },
        {
            "type": "function",
            "name": "confirm_registration_submission",
            "description": "Confirm and submit a pending registration after the user approves it.",
            "parameters": empty_tool_parameters(),
            "strict": True,
        },
        {
            "type": "function",
            "name": "lookup_registration_record",
            "description": "Look up a saved registration by registration code and attendee email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_code": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["registration_code", "email"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "load_registration_for_update",
            "description": "Load a saved registration into update mode, either by explicit code and email or by reusing the last loaded registration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_code": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "email": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "use_last_loaded": {"type": "boolean"},
                },
                "required": ["registration_code", "email", "use_last_loaded"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "save_registration_update_fields",
            "description": "Apply one or more field changes to the currently loaded registration and prepare an update confirmation.",
            "parameters": partial_registration_update_tool_parameters(),
            "strict": True,
        },
        {
            "type": "function",
            "name": "confirm_registration_update",
            "description": "Confirm and save a pending registration update after the user approves it.",
            "parameters": empty_tool_parameters(),
            "strict": True,
        },
        {
            "type": "function",
            "name": "prepare_registration_cancellation",
            "description": "Load a saved registration into cancellation review, either by explicit code and email or by reusing the last loaded registration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_code": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "email": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "use_last_loaded": {"type": "boolean"},
                },
                "required": ["registration_code", "email", "use_last_loaded"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "confirm_registration_cancellation",
            "description": "Confirm and execute a pending registration cancellation after the user approves it.",
            "parameters": empty_tool_parameters(),
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_conference_knowledge_base",
            "description": "Search the conference knowledge base for conference questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "topic": {"type": "string", "enum": ["ticket_types", "workshops", "dates", "general"]},
                },
                "required": ["query", "topic"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "reset_session_state",
            "description": "Clear the current in-progress task when the user wants to start over.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["all", "registration", "lookup", "update", "cancel"]},
                },
                "required": ["scope"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


def parse_assistant_tool_arguments(tool_name: str, arguments: dict) -> BaseModel | None:
    if tool_name in {"confirm_registration_submission", "confirm_registration_update", "confirm_registration_cancellation"}:
        return None
    model_class = ASSISTANT_TOOL_MODELS.get(tool_name)
    if model_class is None:
        raise HTTPException(status_code=500, detail=f"Unknown assistant tool: {tool_name}.")
    try:
        return model_class.model_validate(arguments)
    except ValidationError as exc:
        raise AssistantToolValidationError(
            tool_name,
            _validation_error_details(exc),
            retry_field_name=_first_invalid_field(exc),
            retry_mode=_retry_mode_for_tool(tool_name),
        ) from exc


def _validation_error_details(exc: ValidationError) -> list[dict[str, str | None]]:
    errors = []
    for error in exc.errors():
        field_name = next(
            (
                str(part)
                for part in reversed(error.get("loc", ()))
                if isinstance(part, (str, int)) and str(part) != "__root__"
            ),
            None,
        )
        errors.append(
            {
                "field_name": field_name,
                "message": error.get("msg", "Invalid value."),
            }
        )
    return errors or [{"field_name": None, "message": "Invalid value."}]


def _first_invalid_field(exc: ValidationError) -> str | None:
    return next(
        (
            error["field_name"]
            for error in _validation_error_details(exc)
            if error["field_name"]
        ),
        None,
    )


def _retry_mode_for_tool(tool_name: str) -> str | None:
    return {
        "save_registration_details": "registration",
        "lookup_registration_record": "lookup",
        "load_registration_for_update": "update_lookup",
        "save_registration_update_fields": "update",
        "prepare_registration_cancellation": "cancel_lookup",
    }.get(tool_name)


def _build_invalid_input_output(
    tool_name: str,
    invalid_fields: list[dict[str, str | None]],
    retry_field_name: str | None,
    state_snapshot: dict | None = None,
) -> dict:
    return {
        "error": "invalid_user_input",
        "tool_name": tool_name,
        "invalid_fields": invalid_fields,
        "retry_field_name": retry_field_name,
        "state_snapshot": state_snapshot or {},
    }


def _handle_assistant_tool_validation_error(exc: AssistantToolValidationError, session_id: str, state) -> tuple[dict, None]:
    if exc.retry_field_name and exc.retry_mode:
        state.start_collecting_field(session_id, exc.retry_field_name, exc.retry_mode)

    state_snapshot = {
        "registration_draft": build_registration_draft_summary(state.get_registration_draft(session_id)),
        "lookup_draft": build_lookup_draft_summary(state.get_lookup_draft(session_id)),
    }
    return _build_invalid_input_output(
        exc.tool_name,
        exc.invalid_fields,
        exc.retry_field_name,
        state_snapshot,
    ), None


def _normalize_partial_registration_updates(updates: dict) -> dict:
    normalized = {}
    for field_name, value in updates.items():
        if value is None:
            normalized[field_name] = None
            continue
        if field_name == "selected_days":
            normalized[field_name] = [str(day).strip().lower().replace("-", "_").replace(" ", "_") for day in value]
            continue
        if field_name in {"ticket_type", "workshop_preference"}:
            normalized[field_name] = str(value).strip().lower().replace("-", "_").replace(" ", "_")
            continue
        if field_name == "full_name":
            normalized[field_name] = " ".join(str(value).strip().split())
            continue
        normalized[field_name] = value
    return normalized


def build_assistant_context(session_id: str, state) -> dict:
    registration_draft = state.get_registration_draft(session_id)
    pending_registration = state.get_pending_registration_confirmation(session_id)
    pending_update = state.get_pending_registration_update(session_id)
    pending_cancellation = state.get_pending_registration_cancellation(session_id)
    active_update = state.get_active_update_registration(session_id)
    last_loaded = state.get_last_loaded_registration(session_id)

    return {
        "available_values": {
            "ticket_type": sorted(ALLOWED_TICKET_TYPES),
            "selected_days": sorted(ALLOWED_DAYS),
            "workshop_preference": sorted(ALLOWED_WORKSHOPS),
        },
        "session_state": {
            "flow_state": state.get_flow_state(session_id),
            "accessibility_collected": state.has_accessibility_been_collected(session_id),
            "registration_draft": build_registration_draft_summary(registration_draft),
            "lookup_draft": build_lookup_draft_summary(state.get_lookup_draft(session_id)),
            "pending_registration_confirmation": build_registration_draft_summary(pending_registration) if pending_registration else None,
            "pending_registration_update": {
                "registration_id": pending_update["registration_id"],
                "registration_code": pending_update["registration_code"],
                "status": pending_update["status"],
                "draft": build_registration_draft_summary(pending_update["draft"]),
            }
            if pending_update
            else None,
            "pending_registration_cancellation": {
                "registration_id": pending_cancellation["id"],
                "registration_code": pending_cancellation["registration_code"],
                "status": pending_cancellation["status"],
                "email": pending_cancellation["email"],
            }
            if pending_cancellation
            else None,
            "active_update_registration": active_update,
            "last_loaded_registration": {
                "registration_id": last_loaded["id"],
                "registration_code": last_loaded["registration_code"],
                "status": last_loaded["status"],
                "email": last_loaded["email"],
            }
            if last_loaded
            else None,
        },
    }


def _resolve_registration_for_followup(session_id: str, state, registration_code: str | None, email: str | None, use_last_loaded: bool) -> dict:
    if use_last_loaded:
        registration = state.get_last_loaded_registration(session_id)
        if registration is None:
            raise MissingFollowupRegistrationError("followup")
        if "full_name" not in registration:
            lookup = RegistrationLookupDraft(
                registration_code=registration["registration_code"],
                email=registration["email"],
            )
            require_lookup_tool_call("find_registration", lookup)
            return find_registration_or_404(lookup)
        return registration

    lookup = RegistrationLookupDraft(registration_code=registration_code, email=email)
    require_lookup_tool_call("find_registration", lookup)
    return find_registration_or_404(lookup)


def execute_assistant_tool(tool_name: str, arguments: dict, session_id: str, state) -> tuple[dict, dict | None]:
    parsed = parse_assistant_tool_arguments(tool_name, arguments)

    if tool_name == "save_registration_details":
        current = state.get_registration_draft(session_id).model_dump(mode="python")
        raw_updates = parsed.model_dump(exclude_none=True)
        updates = _normalize_partial_registration_updates(raw_updates)
        current.update(updates)
        try:
            updated_draft = RegistrationDraft(**current)
        except ValidationError as exc:
            retry_field_name = _first_invalid_field(exc) or next(iter(raw_updates), None)
            state.start_collecting_field(session_id, retry_field_name, "registration")
            return _build_invalid_input_output(
                tool_name,
                _validation_error_details(exc),
                retry_field_name,
                {"registration_draft": build_registration_draft_summary(state.get_registration_draft(session_id))},
            ), None
        state.store_registration_draft(session_id, updated_draft)
        if "accessibility_needs" in raw_updates:
            state.mark_accessibility_collected(session_id, True)
        validation = validate_registration_draft(updated_draft)
        accessibility_collected = state.has_accessibility_been_collected(session_id)
        result = None
        state.clear_pending_registration_confirmation(session_id)
        if validation["valid"] and accessibility_collected:
            state.store_pending_registration_confirmation(session_id, updated_draft)
            result = build_registration_confirmation_request_result(updated_draft)
        state.store_flow_state(session_id, collecting=False, awaiting_field=None, mode="registration")
        return {
            "registration_draft": build_registration_draft_summary(updated_draft),
            "missing_fields": validation["missing_fields"],
            "accessibility_collected": accessibility_collected,
            "ready_for_confirmation": validation["valid"] and accessibility_collected,
        }, result

    if tool_name == "confirm_registration_submission":
        pending_draft = state.get_pending_registration_confirmation(session_id)
        if pending_draft is None:
            return {"error": "no_pending_registration_confirmation"}, None
        completion = run_registration_completion_tool_loop(pending_draft)
        if completion["success"]:
            state.clear_pending_registration_confirmation(session_id)
            state.store_last_loaded_registration(
                session_id,
                {
                    "id": completion["registration_id"],
                    "registration_code": completion["registration_code"],
                    "status": completion["status"],
                    "email": str(pending_draft.email),
                },
            )
            return completion, completion["result"]
        return completion, build_registration_confirmation_request_result(pending_draft)

    if tool_name == "lookup_registration_record":
        lookup = RegistrationLookupDraft(
            registration_code=parsed.registration_code,
            email=str(parsed.email),
        )
        require_lookup_tool_call("find_registration", lookup)
        registration = find_registration_or_404(lookup)
        state.store_last_loaded_registration(session_id, registration)
        return {
            "registration": {
                "id": registration["id"],
                "registration_code": registration["registration_code"],
                "status": registration["status"],
                "email": registration["email"],
            }
        }, build_registration_lookup_result(registration)

    if tool_name == "load_registration_for_update":
        try:
            registration = _resolve_registration_for_followup(
                session_id,
                state,
                parsed.registration_code,
                str(parsed.email) if parsed.email else None,
                parsed.use_last_loaded,
            )
        except MissingFollowupRegistrationError:
            state.reset_update(session_id)
            state.start_collecting_field(session_id, "registration_code", "update_lookup")
            return {
                "error": "missing_followup_registration",
                "retry_field_name": "registration_code",
                "required_fields": ["registration_code", "email"],
            }, None
        state.store_last_loaded_registration(session_id, registration)
        if str(registration.get("status", "")).lower() == "cancelled":
            return {"error": "cancelled_registration", "status": registration["status"]}, build_registration_lookup_result(registration)
        registration_draft = registration_to_draft(registration)
        state.store_registration_draft(session_id, registration_draft)
        state.store_active_update_registration(
            session_id,
            registration["id"],
            registration["registration_code"],
            registration["status"],
        )
        state.active_update_registrations[session_id]["jotform_submission_id"] = registration.get("jotform_submission_id")
        state.store_flow_state(session_id, collecting=False, awaiting_field=None, mode="update")
        return {
            "registration": {
                "id": registration["id"],
                "registration_code": registration["registration_code"],
                "status": registration["status"],
                "email": registration["email"],
            },
            "editable_fields": REGISTRATION_FIELD_ORDER,
        }, build_registration_lookup_result(registration)

    if tool_name == "save_registration_update_fields":
        active_update = state.get_active_update_registration(session_id)
        if active_update is None:
            return {"error": "no_active_update_registration"}, None
        current = state.get_registration_draft(session_id).model_dump(mode="python")
        updates = _normalize_partial_registration_updates(parsed.model_dump(exclude_none=True))
        current.update(updates)
        try:
            updated_draft = RegistrationDraft(**current)
        except ValidationError as exc:
            retry_field_name = _first_invalid_field(exc) or next(iter(updates), None)
            state.start_collecting_field(session_id, retry_field_name, "update")
            return _build_invalid_input_output(
                tool_name,
                _validation_error_details(exc),
                retry_field_name,
                {"registration_draft": build_registration_draft_summary(state.get_registration_draft(session_id))},
            ), None
        state.store_registration_draft(session_id, updated_draft)
        state.store_pending_registration_update(
            session_id,
            active_update["registration_id"],
            active_update["registration_code"],
            active_update["status"],
            active_update.get("jotform_submission_id"),
            updated_draft,
        )
        state.store_flow_state(session_id, collecting=False, awaiting_field=None, mode="update_confirmation")
        result = build_registration_update_request_result(
            active_update["registration_id"],
            active_update["registration_code"],
            active_update["status"],
            updated_draft,
        )
        return {
            "registration_draft": build_registration_draft_summary(updated_draft),
            "ready_for_confirmation": True,
        }, result

    if tool_name == "confirm_registration_update":
        pending_update = state.get_pending_registration_update(session_id)
        if pending_update is None:
            return {"error": "no_pending_registration_update"}, None
        completion = run_registration_update(
            pending_update["draft"],
            pending_update["registration_id"],
            pending_update["registration_code"],
            pending_update["status"],
            pending_update.get("jotform_submission_id"),
        )
        if completion["success"]:
            state.clear_pending_registration_update(session_id)
            state.clear_active_update_registration(session_id)
            state.store_last_loaded_registration(
                session_id,
                {
                    "id": completion["registration_id"],
                    "registration_code": completion["registration_code"],
                    "status": completion["status"],
                    "email": str(pending_update["draft"].email),
                },
            )
            return completion, completion["result"]
        return completion, build_registration_update_request_result(
            pending_update["registration_id"],
            pending_update["registration_code"],
            pending_update["status"],
            pending_update["draft"],
        )

    if tool_name == "prepare_registration_cancellation":
        try:
            registration = _resolve_registration_for_followup(
                session_id,
                state,
                parsed.registration_code,
                str(parsed.email) if parsed.email else None,
                parsed.use_last_loaded,
            )
        except MissingFollowupRegistrationError:
            state.reset_update(session_id)
            state.start_collecting_field(session_id, "registration_code", "cancel_lookup")
            return {
                "error": "missing_followup_registration",
                "retry_field_name": "registration_code",
                "required_fields": ["registration_code", "email"],
            }, None
        state.store_last_loaded_registration(session_id, registration)
        state.store_pending_registration_cancellation(session_id, registration)
        state.store_flow_state(session_id, collecting=False, awaiting_field=None, mode="cancellation_confirmation")
        return {
            "registration": {
                "id": registration["id"],
                "registration_code": registration["registration_code"],
                "status": registration["status"],
                "email": registration["email"],
            }
        }, build_registration_cancellation_request_result(registration)

    if tool_name == "confirm_registration_cancellation":
        pending_cancellation = state.get_pending_registration_cancellation(session_id)
        if pending_cancellation is None:
            return {"error": "no_pending_registration_cancellation"}, None
        completion = run_registration_cancellation(pending_cancellation)
        state.clear_pending_registration_cancellation(session_id)
        state.clear_active_update_registration(session_id)
        state.store_last_loaded_registration(
            session_id,
            {
                "id": completion["registration_id"],
                "registration_code": completion["registration_code"],
                "status": completion["status"],
                "email": pending_cancellation["email"],
            },
        )
        return completion, completion["result"]

    if tool_name == "search_conference_knowledge_base":
        return run_conference_knowledge_search(parsed.query, parsed.topic), None

    if tool_name == "reset_session_state":
        if parsed.scope == "all":
            state.reset_registration(session_id)
            state.reset_lookup(session_id)
        elif parsed.scope == "registration":
            state.reset_registration(session_id)
        elif parsed.scope == "lookup":
            state.reset_lookup(session_id)
        elif parsed.scope in {"update", "cancel"}:
            state.reset_update(session_id)
        return {"reset_scope": parsed.scope}, None

    raise HTTPException(status_code=500, detail=f"Unhandled assistant tool: {tool_name}.")


def run_assistant_turn(conversation_history: list[ChatMessage], user_message: str, session_id: str, state) -> dict:
    latest_result = None
    model_input = [
        {"role": "system", "content": ASSISTANT_PROMPT},
        {"role": "system", "content": json.dumps(build_assistant_context(session_id, state))},
    ] + [{"role": message.role, "content": message.content} for message in conversation_history[:-1]] + [
        {"role": "user", "content": user_message}
    ]

    for _ in range(8):
        response = OPENAI_.responses.create(
            model=OPENAI_MODEL,
            input=model_input,
            tools=assistant_tools(),
            parallel_tool_calls=False,
        )
        function_calls = [item for item in response.output if item.type == "function_call"]
        if not function_calls:
            return {"reply": response.output_text, "result": latest_result}

        for function_call in function_calls:
            try:
                arguments = json.loads(function_call.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=502, detail=f"Invalid tool JSON for {function_call.name}.") from exc
            try:
                output_data, result = execute_assistant_tool(function_call.name, arguments, session_id, state)
            except AssistantToolValidationError as exc:
                output_data, result = _handle_assistant_tool_validation_error(exc, session_id, state)
            if result is not None:
                latest_result = result
            model_input.append(
                {
                    "role": "assistant",
                    "content": f"Calling tool {function_call.name} with arguments: {json.dumps(arguments, ensure_ascii=True, sort_keys=True)}",
                }
            )
            model_input.append(
                {
                    "role": "system",
                    "content": json.dumps(
                        {
                            "tool_name": function_call.name,
                            "tool_output": output_data,
                            "updated_context": build_assistant_context(session_id, state),
                            "result": result,
                        }
                    ),
                }
            )
    raise HTTPException(status_code=502, detail="Assistant tool loop exceeded the allowed number of steps.")
