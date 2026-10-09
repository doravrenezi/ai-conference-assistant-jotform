# This file defines the shared data models and validation rules for the registration assistant.
from typing import Literal

from pydantic import BaseModel, Field, field_validator, EmailStr
from knowledge_base import get_registration_allowed_values

ALLOWED_VALUES = get_registration_allowed_values()
ALLOWED_TICKET_TYPES = ALLOWED_VALUES["ticket_types"]
ALLOWED_WORKSHOPS = ALLOWED_VALUES["workshops"]
ALLOWED_DAYS = ALLOWED_VALUES["days"]
REQUIRED_REGISTRATION_FIELDS = (
    "full_name",
    "email",
    "company_or_university",
    "role",
    "ticket_type",
    "selected_days",
    "workshop_preference",
    "dietary_preference",
)
OPTIONAL_REGISTRATION_FIELDS = ("accessibility_needs",)
REGISTRATION_COLLECTION_ORDER = REQUIRED_REGISTRATION_FIELDS + OPTIONAL_REGISTRATION_FIELDS


def normalize_choice_value(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def validate_choice_value(value: str, allowed_values: set[str], error_message: str) -> str:
    normalized_value = normalize_choice_value(value)

    if normalized_value not in allowed_values:
        raise ValueError(error_message)
    return normalized_value


def validate_ticket_type_value(value: str) -> str:
    return validate_choice_value(value, ALLOWED_TICKET_TYPES, "Ticket type doesn't exist!")


def validate_workshop_preference_value(value: str) -> str:
    return validate_choice_value(value, ALLOWED_WORKSHOPS, "Workshop doesn't exist!")


def validate_selected_days_value(value: list[str], allow_empty: bool = False) -> list[str]:
    if not value:
        if allow_empty:
            return value
        raise ValueError("No days selected!")

    normalized_days = []
    for day in value:
        normalized_days.append(validate_choice_value(day, ALLOWED_DAYS, "No conference on these days!"))

    return normalized_days


def validate_full_name_value(value: str) -> str:
    cleaned_value = value.strip()
    name_parts = cleaned_value.split()

    if len(name_parts) < 2:
        raise ValueError("Please provide both first and last name.")

    return cleaned_value


class RegistrationRequest(BaseModel):
    full_name: str
    email: EmailStr
    company_or_university: str
    role: str
    ticket_type: str
    selected_days: list[str]
    workshop_preference: str
    dietary_preference: str
    accessibility_needs: str | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value):
        return validate_full_name_value(value)

    @field_validator("ticket_type")
    @classmethod
    def validate_ticket_type(cls, value):
        return validate_ticket_type_value(value)

    @field_validator("workshop_preference")
    @classmethod
    def validate_workshop_preference(cls, value):
        return validate_workshop_preference_value(value)

    @field_validator("selected_days")
    @classmethod
    def validate_selected_days(cls, value):        
        return validate_selected_days_value(value)


class RegistrationDraft(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    company_or_university: str | None = None
    role: str | None = None
    ticket_type: str | None = None
    selected_days: list[str] = Field(default_factory=list)
    workshop_preference: str | None = None
    dietary_preference: str | None = None
    accessibility_needs: str | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value):
        if value is None:
            return value
        return validate_full_name_value(value)

    @field_validator("ticket_type")
    @classmethod
    def validate_ticket_type(cls, value):
        if value is None:
            return value
        return validate_ticket_type_value(value)

    @field_validator("workshop_preference")
    @classmethod
    def validate_workshop_preference(cls, value):
        if value is None:
            return value
        return validate_workshop_preference_value(value)

    @field_validator("selected_days")
    @classmethod
    def validate_selected_days(cls, value):
        return validate_selected_days_value(value, allow_empty=True)

    def missing_fields(self) -> list[str]:
        missing = []

        for field_name in REQUIRED_REGISTRATION_FIELDS:
            value = getattr(self, field_name)
            if value in (None, "", []):
                missing.append(field_name)

        return missing

    def is_complete(self) -> bool:
        return not self.missing_fields()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value):
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("Message content cannot be empty.")
        return cleaned_value


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value):
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("Message cannot be empty.")
        return cleaned_value


class ChatResult(BaseModel):
    type: Literal["registration_confirmation_request", "registration_confirmation", "registration_lookup", "registration_update", "registration_cancellation"]
    title: str
    subtitle: str | None = None
    details: dict[str, str] = Field(default_factory=dict)
    action_label: str | None = None
    action_value: str | None = None


class ChatResponse(BaseModel):
    reply: str
    result: ChatResult | None = None


class RegistrationLookupRequest(BaseModel):
    registration_code: str
    email: EmailStr

    @field_validator("registration_code")
    @classmethod
    def validate_registration_code(cls, value):
        cleaned_value = value.strip().upper()
        if not cleaned_value:
            raise ValueError("Registration code cannot be empty.")
        return cleaned_value


class RegistrationLookupDraft(BaseModel):
    registration_code: str | None = None
    email: EmailStr | None = None

    @field_validator("registration_code")
    @classmethod
    def validate_registration_code(cls, value):
        if value is None:
            return value
        cleaned_value = value.strip().upper()
        if not cleaned_value:
            raise ValueError("Registration code cannot be empty.")
        return cleaned_value

    def missing_fields(self) -> list[str]:
        missing = []

        if not self.registration_code:
            missing.append("registration_code")
        if self.email is None:
            missing.append("email")

        return missing

    def is_complete(self) -> bool:
        return not self.missing_fields()
