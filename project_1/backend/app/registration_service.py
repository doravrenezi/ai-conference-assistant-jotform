# This file contains business logic for creating, formatting, updating, looking up, and canceling registrations.
import json
from datetime import datetime, timezone

from fastapi import HTTPException

from database import (
    create_registration,
    create_registration_event,
    find_registration_by_code_and_email,
    generate_registration_code,
    update_registration,
    update_registration_jotform_sync,
)
from jotform_service import submit_registration_to_jotform, update_registration_in_jotform
from schemas import RegistrationDraft, RegistrationLookupRequest, RegistrationRequest


def humanize_choice_value(value: str) -> str:
    words = str(value).replace("_", " ").split()
    return " ".join(word.upper() if word.isalpha() and len(word) <= 3 else word.capitalize() for word in words)


def display_registration_value(field_name: str, value):
    if value in (None, ""):
        return "None"
    if field_name == "selected_days":
        return ", ".join(humanize_choice_value(day) for day in value)
    if field_name in {"ticket_type", "workshop_preference"}:
        return humanize_choice_value(str(value))
    return str(value)


def log_registration_event(registration_id: int, event_type: str, event_data: dict) -> None:
    create_registration_event(
        registration_id,
        event_type,
        event_data,
        datetime.now(timezone.utc).isoformat(),
    )


def build_registration_confirmation_request_result(draft: RegistrationDraft) -> dict:
    details = {
        "Full name": display_registration_value("full_name", draft.full_name),
        "Email": display_registration_value("email", draft.email),
        "Company or university": display_registration_value("company_or_university", draft.company_or_university),
        "Role": display_registration_value("role", draft.role),
        "Ticket type": display_registration_value("ticket_type", draft.ticket_type),
        "Selected days": display_registration_value("selected_days", draft.selected_days),
        "Workshop preference": display_registration_value("workshop_preference", draft.workshop_preference),
        "Dietary preference": display_registration_value("dietary_preference", draft.dietary_preference),
        "Accessibility needs": display_registration_value("accessibility_needs", draft.accessibility_needs),
    }

    return {
        "type": "registration_confirmation_request",
        "title": "Confirm registration",
        "subtitle": "Review your registration details before submitting.",
        "details": details,
        "action_label": "Confirm submission",
        "action_value": "__confirm_registration__",
    }


def build_registration_confirmation_result(
    reg_id: int,
    reg_code: str,
    status: str,
    draft: RegistrationDraft,
    jotform_submission_id: str | None = None,
    jotform_sync_error: str | None = None,
) -> dict:
    details = {
        "Registration ID": str(reg_id),
        "Registration code": reg_code,
        "Status": status,
        "Full name": display_registration_value("full_name", draft.full_name),
        "Email": display_registration_value("email", draft.email),
        "Company or university": display_registration_value("company_or_university", draft.company_or_university),
        "Role": display_registration_value("role", draft.role),
        "Ticket type": display_registration_value("ticket_type", draft.ticket_type),
        "Selected days": display_registration_value("selected_days", draft.selected_days),
        "Workshop preference": display_registration_value("workshop_preference", draft.workshop_preference),
        "Dietary preference": display_registration_value("dietary_preference", draft.dietary_preference),
        "Accessibility needs": display_registration_value("accessibility_needs", draft.accessibility_needs),
    }
    if jotform_submission_id:
        details["Jotform submission ID"] = jotform_submission_id
    if jotform_sync_error:
        details["Jotform sync"] = jotform_sync_error

    return {
        "type": "registration_confirmation",
        "title": "Registration created",
        "subtitle": (
            "Your registration has been saved locally and synced to Jotform."
            if jotform_submission_id
            else "Your registration has been saved locally, but Jotform sync could not be completed."
            if jotform_sync_error
            else "Your registration has been saved locally."
        ),
        "details": details,
    }


def build_registration_lookup_result(registration: dict) -> dict:
    selected_days = json.loads(registration["selected_days"])
    details = {
        "Registration ID": str(registration["id"]),
        "Registration code": registration["registration_code"],
        "Status": registration["status"],
        "Full name": registration["full_name"],
        "Email": registration["email"],
        "Company or university": registration["company_or_university"],
        "Role": registration["role"],
        "Ticket type": display_registration_value("ticket_type", registration["ticket_type"]),
        "Selected days": display_registration_value("selected_days", selected_days),
        "Workshop preference": display_registration_value("workshop_preference", registration["workshop_preference"]),
        "Dietary preference": registration["dietary_preference"],
        "Accessibility needs": registration["accessibility_needs"] or "None",
    }

    if registration.get("jotform_submission_id"):
        details["Jotform submission ID"] = registration["jotform_submission_id"]
    if registration.get("jotform_sync_status"):
        details["Jotform sync status"] = registration["jotform_sync_status"]

    return {
        "type": "registration_lookup",
        "title": "Registration found",
        "subtitle": "Here are the saved registration details.",
        "details": details,
    }


def build_registration_update_request_result(
    registration_id: int,
    registration_code: str,
    status: str,
    draft: RegistrationDraft,
) -> dict:
    details = {
        "Registration ID": str(registration_id),
        "Registration code": registration_code,
        "Status": status,
        "Full name": display_registration_value("full_name", draft.full_name),
        "Email": display_registration_value("email", draft.email),
        "Company or university": display_registration_value("company_or_university", draft.company_or_university),
        "Role": display_registration_value("role", draft.role),
        "Ticket type": display_registration_value("ticket_type", draft.ticket_type),
        "Selected days": display_registration_value("selected_days", draft.selected_days),
        "Workshop preference": display_registration_value("workshop_preference", draft.workshop_preference),
        "Dietary preference": display_registration_value("dietary_preference", draft.dietary_preference),
        "Accessibility needs": display_registration_value("accessibility_needs", draft.accessibility_needs),
    }

    return {
        "type": "registration_update",
        "title": "Confirm update",
        "subtitle": "Review your updated registration details before saving them.",
        "details": details,
        "action_label": "Confirm update",
        "action_value": "__confirm_registration_update__",
    }


def build_registration_update_result(
    registration_id: int,
    registration_code: str,
    status: str,
    draft: RegistrationDraft,
    jotform_sync_error: str | None = None,
) -> dict:
    details = {
        "Registration ID": str(registration_id),
        "Registration code": registration_code,
        "Status": status,
        "Full name": display_registration_value("full_name", draft.full_name),
        "Email": display_registration_value("email", draft.email),
        "Company or university": display_registration_value("company_or_university", draft.company_or_university),
        "Role": display_registration_value("role", draft.role),
        "Ticket type": display_registration_value("ticket_type", draft.ticket_type),
        "Selected days": display_registration_value("selected_days", draft.selected_days),
        "Workshop preference": display_registration_value("workshop_preference", draft.workshop_preference),
        "Dietary preference": display_registration_value("dietary_preference", draft.dietary_preference),
        "Accessibility needs": display_registration_value("accessibility_needs", draft.accessibility_needs),
    }
    if jotform_sync_error:
        details["Jotform sync"] = jotform_sync_error

    return {
        "type": "registration_update",
        "title": "Registration updated",
        "subtitle": (
            "Your registration was updated locally and synced to Jotform."
            if not jotform_sync_error
            else "Your registration was updated locally, but the Jotform update could not be completed."
        ),
        "details": details,
    }


def build_registration_cancellation_request_result(registration: dict) -> dict:
    return {
        "type": "registration_cancellation",
        "title": "Confirm cancellation",
        "subtitle": "Review the registration before canceling it.",
        "details": build_registration_lookup_result(registration)["details"],
        "action_label": "Confirm cancellation",
        "action_value": "__confirm_registration_cancellation__",
    }


def build_registration_cancellation_result(
    registration_id: int,
    registration_code: str,
    status: str,
    draft: RegistrationDraft,
    jotform_sync_error: str | None = None,
) -> dict:
    details = {
        "Registration ID": str(registration_id),
        "Registration code": registration_code,
        "Status": status,
        "Full name": display_registration_value("full_name", draft.full_name),
        "Email": display_registration_value("email", draft.email),
        "Company or university": display_registration_value("company_or_university", draft.company_or_university),
        "Role": display_registration_value("role", draft.role),
        "Ticket type": display_registration_value("ticket_type", draft.ticket_type),
        "Selected days": display_registration_value("selected_days", draft.selected_days),
        "Workshop preference": display_registration_value("workshop_preference", draft.workshop_preference),
        "Dietary preference": display_registration_value("dietary_preference", draft.dietary_preference),
        "Accessibility needs": display_registration_value("accessibility_needs", draft.accessibility_needs),
    }
    if jotform_sync_error:
        details["Jotform sync"] = jotform_sync_error

    return {
        "type": "registration_cancellation",
        "title": "Registration cancelled",
        "subtitle": (
            "The registration was cancelled locally and the cancellation was synced to Jotform."
            if not jotform_sync_error
            else "The registration was cancelled locally, but the Jotform cancellation sync could not be completed."
        ),
        "details": details,
    }


def validate_registration_draft(draft: RegistrationDraft) -> dict:
    missing_fields = draft.missing_fields()
    return {
        "valid": not missing_fields,
        "missing_fields": missing_fields,
        "draft": draft.model_dump(mode="json"),
    }


def registration_to_draft(registration: dict) -> RegistrationDraft:
    return RegistrationDraft(
        full_name=registration["full_name"],
        email=registration["email"],
        company_or_university=registration["company_or_university"],
        role=registration["role"],
        ticket_type=registration["ticket_type"],
        selected_days=json.loads(registration["selected_days"]),
        workshop_preference=registration["workshop_preference"],
        dietary_preference=registration["dietary_preference"],
        accessibility_needs=registration["accessibility_needs"],
    )


def create_registration_record(draft: RegistrationDraft) -> dict:
    reg_code = generate_registration_code()
    days_string = json.dumps(draft.selected_days)
    status = "active"
    now = datetime.now(timezone.utc).isoformat()
    reg_id = create_registration(
        reg_code,
        draft.full_name,
        str(draft.email),
        draft.company_or_university,
        draft.role,
        draft.ticket_type,
        days_string,
        draft.workshop_preference,
        draft.dietary_preference,
        draft.accessibility_needs,
        status,
        now,
        now,
    )
    log_registration_event(
        reg_id,
        "registration_created",
        {
            "registration_code": reg_code,
            "status": status,
            "email": str(draft.email),
            "ticket_type": draft.ticket_type,
            "selected_days": draft.selected_days,
            "workshop_preference": draft.workshop_preference,
        },
    )
    return {
        "registration_id": reg_id,
        "registration_code": reg_code,
        "status": status,
    }


def sync_registration_record_to_jotform(
    registration_id: int,
    draft: RegistrationDraft,
    registration_code: str,
    status: str,
) -> dict:
    jotform_submission_id = None
    jotform_sync_error = None
    jotform_sync_status = "failed"
    try:
        jotform_submission_id = submit_registration_to_jotform(draft, registration_code, status)
        jotform_sync_status = "synced"
    except HTTPException as exc:
        jotform_sync_error = str(exc.detail)

    update_registration_jotform_sync(
        registration_id,
        jotform_submission_id,
        jotform_sync_status,
    )
    log_registration_event(
        registration_id,
        "jotform_sync_succeeded" if jotform_submission_id else "jotform_sync_failed",
        {
            "registration_code": registration_code,
            "status": status,
            "jotform_submission_id": jotform_submission_id,
            "jotform_sync_status": jotform_sync_status,
            "error_detail": jotform_sync_error,
        },
    )

    return {
        "jotform_submission_id": jotform_submission_id,
        "jotform_sync_status": jotform_sync_status,
        "jotform_sync_error": jotform_sync_error,
    }


def save_registration_from_draft(draft: RegistrationDraft) -> tuple[int, str, str, dict]:
    creation = create_registration_record(draft)
    sync_result = sync_registration_record_to_jotform(
        creation["registration_id"],
        draft,
        creation["registration_code"],
        creation["status"],
    )
    result = build_registration_confirmation_result(
        creation["registration_id"],
        creation["registration_code"],
        creation["status"],
        draft,
        sync_result["jotform_submission_id"],
        sync_result["jotform_sync_error"],
    )
    return creation["registration_id"], creation["registration_code"], creation["status"], result


def create_registration_response(reg: RegistrationRequest) -> dict:
    draft = RegistrationDraft(**reg.model_dump())
    reg_id, reg_code, status, result = save_registration_from_draft(draft)
    return {
        "registration_id": reg_id,
        "registration_code": reg_code,
        "status": status,
        "result": result,
    }


def lookup_registration_response(lookup: RegistrationLookupRequest) -> dict:
    registration = find_registration_or_404(lookup)

    return {
        "registration_id": registration["id"],
        "registration_code": registration["registration_code"],
        "status": registration["status"],
        "result": build_registration_lookup_result(registration),
    }


def find_registration_or_404(lookup: RegistrationLookupRequest) -> dict:
    registration = find_registration_by_code_and_email(lookup.registration_code, str(lookup.email))
    if registration is None:
        raise HTTPException(status_code=404, detail="Registration not found.")
    return registration


def update_registration_record(
    registration_id: int,
    draft: RegistrationDraft,
    status: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    update_registration(
        registration_id,
        draft.full_name,
        str(draft.email),
        draft.company_or_university,
        draft.role,
        draft.ticket_type,
        json.dumps(draft.selected_days),
        draft.workshop_preference,
        draft.dietary_preference,
        draft.accessibility_needs,
        status,
        now,
    )
    log_registration_event(
        registration_id,
        "registration_updated" if status != "cancelled" else "registration_cancelled",
        {
            "status": status,
            "email": str(draft.email),
            "ticket_type": draft.ticket_type,
            "selected_days": draft.selected_days,
            "workshop_preference": draft.workshop_preference,
        },
    )


def sync_registration_update_to_jotform(
    registration: dict,
    draft: RegistrationDraft,
    registration_code: str,
    status: str,
) -> dict:
    submission_id = registration.get("jotform_submission_id")
    if not submission_id:
        log_registration_event(
            registration["id"],
            "jotform_sync_failed",
            {
                "registration_code": registration_code,
                "status": status,
                "jotform_submission_id": None,
                "jotform_sync_status": "missing_submission_id",
                "error_detail": None,
            },
        )
        return {
            "sync_status": "missing_submission_id",
            "error_detail": None,
        }

    try:
        update_registration_in_jotform(
            submission_id,
            draft,
            registration_code,
            status,
        )
    except HTTPException as exc:
        log_registration_event(
            registration["id"],
            "jotform_sync_failed",
            {
                "registration_code": registration_code,
                "status": status,
                "jotform_submission_id": submission_id,
                "jotform_sync_status": "failed",
                "error_detail": str(exc.detail),
            },
        )
        return {
            "sync_status": "failed",
            "error_detail": str(exc.detail),
        }

    log_registration_event(
        registration["id"],
        "jotform_sync_succeeded",
        {
            "registration_code": registration_code,
            "status": status,
            "jotform_submission_id": submission_id,
            "jotform_sync_status": "synced",
            "error_detail": None,
        },
    )
    return {
        "sync_status": "synced",
        "error_detail": None,
    }


def sync_registration_update_by_submission_id(
    registration_id: int,
    jotform_submission_id: str | None,
    draft: RegistrationDraft,
    registration_code: str,
    status: str,
) -> dict:
    if not jotform_submission_id:
        update_registration_jotform_sync(registration_id, None, "missing_submission_id")
        log_registration_event(
            registration_id,
            "jotform_sync_failed",
            {
                "registration_code": registration_code,
                "status": status,
                "jotform_submission_id": None,
                "jotform_sync_status": "missing_submission_id",
                "error_detail": None,
            },
        )
        return {
            "sync_status": "missing_submission_id",
            "error_detail": None,
        }

    try:
        update_registration_in_jotform(
            jotform_submission_id,
            draft,
            registration_code,
            status,
        )
    except HTTPException as exc:
        update_registration_jotform_sync(registration_id, jotform_submission_id, "failed")
        log_registration_event(
            registration_id,
            "jotform_sync_failed",
            {
                "registration_code": registration_code,
                "status": status,
                "jotform_submission_id": jotform_submission_id,
                "jotform_sync_status": "failed",
                "error_detail": str(exc.detail),
            },
        )
        return {
            "sync_status": "failed",
            "error_detail": str(exc.detail),
        }

    update_registration_jotform_sync(registration_id, jotform_submission_id, "synced")
    log_registration_event(
        registration_id,
        "jotform_sync_succeeded",
        {
            "registration_code": registration_code,
            "status": status,
            "jotform_submission_id": jotform_submission_id,
            "jotform_sync_status": "synced",
            "error_detail": None,
        },
    )
    return {
        "sync_status": "synced",
        "error_detail": None,
    }


def cancel_registration_record(registration: dict) -> dict:
    draft = registration_to_draft(registration)
    status = "cancelled"
    update_registration_record(registration["id"], draft, status)
    sync_result = sync_registration_update_to_jotform(
        registration,
        draft,
        registration["registration_code"],
        status,
    )
    update_registration_jotform_sync(
        registration["id"],
        registration.get("jotform_submission_id"),
        sync_result["sync_status"],
    )
    return {
        "registration_id": registration["id"],
        "registration_code": registration["registration_code"],
        "status": status,
        "result": build_registration_cancellation_result(
            registration["id"],
            registration["registration_code"],
            status,
            draft,
            sync_result["error_detail"],
        ),
    }
