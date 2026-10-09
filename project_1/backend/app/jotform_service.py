# This file reads Jotform form metadata and syncs registration data to Jotform submissions.
import json
import os
from urllib import error, parse, request

from fastapi import HTTPException

from schemas import RegistrationDraft, normalize_choice_value


JOTFORM_API_BASE_URL = "https://api.jotform.com"
JOTFORM_FIELD_IDS = {
    "full_name": "3",
    "email": "4",
    "company_or_university": "5",
    "role": "6",
    "ticket_type": "7",
    "selected_days": "8",
    "workshop_preference": "9",
    "dietary_preference": "10",
    "accessibility_needs": "11",
    "registration_code": "12",
    "registration_status": "13",
}


def split_full_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split(maxsplit=1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    return first_name, last_name


def get_jotform_questions(api_key: str, form_id: str) -> dict:
    http_request = request.Request(
        url=f"{JOTFORM_API_BASE_URL}/form/{form_id}/questions",
        headers={"APIKEY": api_key},
        method="GET",
    )

    with request.urlopen(http_request, timeout=15) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    if response_data.get("responseCode") != 200:
        raise HTTPException(status_code=502, detail="Could not read Jotform questions.")

    return response_data.get("content", {})


def get_jotform_options(questions: dict, field_name: str) -> list[str]:
    question = questions.get(JOTFORM_FIELD_IDS[field_name], {})
    raw_options = question.get("options", "")
    if not raw_options:
        return []
    return [option for option in raw_options.split("|") if option]


def match_jotform_option(value: str, options: list[str]) -> str:
    normalized_value = normalize_choice_value(value)
    for option in options:
        if normalize_choice_value(option) == normalized_value:
            return option
    return value.replace("_", " ").title()


def get_jotform_option_label(questions: dict, field_name: str, value: str) -> str:
    return match_jotform_option(value, get_jotform_options(questions, field_name))


def build_jotform_submission_payload(
    draft: RegistrationDraft,
    registration_code: str,
    registration_status: str,
    questions: dict,
) -> bytes:
    first_name, last_name = split_full_name(draft.full_name or "")
    payload = [
        (f"submission[{JOTFORM_FIELD_IDS['full_name']}][first]", first_name),
        (f"submission[{JOTFORM_FIELD_IDS['full_name']}][last]", last_name),
        (f"submission[{JOTFORM_FIELD_IDS['email']}]", str(draft.email)),
        (f"submission[{JOTFORM_FIELD_IDS['company_or_university']}]", draft.company_or_university or ""),
        (f"submission[{JOTFORM_FIELD_IDS['role']}]", draft.role or ""),
        (f"submission[{JOTFORM_FIELD_IDS['ticket_type']}]", get_jotform_option_label(questions, "ticket_type", draft.ticket_type or "")),
        (f"submission[{JOTFORM_FIELD_IDS['workshop_preference']}]", get_jotform_option_label(questions, "workshop_preference", draft.workshop_preference or "")),
        (f"submission[{JOTFORM_FIELD_IDS['dietary_preference']}]", draft.dietary_preference or ""),
        (f"submission[{JOTFORM_FIELD_IDS['accessibility_needs']}]", draft.accessibility_needs or ""),
        (f"submission[{JOTFORM_FIELD_IDS['registration_code']}]", registration_code),
        (f"submission[{JOTFORM_FIELD_IDS['registration_status']}]", get_jotform_option_label(questions, "registration_status", registration_status)),
    ]

    for selected_day in draft.selected_days:
        payload.append((f"submission[{JOTFORM_FIELD_IDS['selected_days']}][]", get_jotform_option_label(questions, "selected_days", selected_day)))

    return parse.urlencode(payload).encode("utf-8")


def submit_registration_to_jotform(
    draft: RegistrationDraft,
    registration_code: str,
    registration_status: str,
) -> str:
    api_key = os.getenv("JOTFORM_API_KEY")
    form_id = os.getenv("JOTFORM_FORM_ID")

    if not api_key:
        raise HTTPException(status_code=500, detail="JOTFORM_API_KEY is not set.")

    if not form_id:
        raise HTTPException(status_code=500, detail="JOTFORM_FORM_ID is not set.")

    try:
        questions = get_jotform_questions(api_key, form_id)
        payload = build_jotform_submission_payload(draft, registration_code, registration_status, questions)
        http_request = request.Request(
            url=f"{JOTFORM_API_BASE_URL}/form/{form_id}/submissions",
            data=payload,
            headers={
                "APIKEY": api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=15) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Jotform submission failed: {error_body}") from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail="Could not reach Jotform.") from exc

    if response_data.get("responseCode") != 200:
        raise HTTPException(status_code=502, detail="Jotform submission was not accepted.")

    submission_id = response_data.get("content", {}).get("submissionID")
    if not submission_id:
        raise HTTPException(status_code=502, detail="Jotform did not return a submission ID.")

    return submission_id


def update_registration_in_jotform(
    submission_id: str,
    draft: RegistrationDraft,
    registration_code: str,
    registration_status: str,
) -> None:
    api_key = os.getenv("JOTFORM_API_KEY")
    form_id = os.getenv("JOTFORM_FORM_ID")

    if not api_key:
        raise HTTPException(status_code=500, detail="JOTFORM_API_KEY is not set.")

    if not form_id:
        raise HTTPException(status_code=500, detail="JOTFORM_FORM_ID is not set.")

    try:
        questions = get_jotform_questions(api_key, form_id)
        payload = build_jotform_submission_payload(draft, registration_code, registration_status, questions)
        http_request = request.Request(
            url=f"{JOTFORM_API_BASE_URL}/submission/{submission_id}",
            data=payload,
            headers={
                "APIKEY": api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=15) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Jotform update failed: {error_body}") from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail="Could not reach Jotform.") from exc

    if response_data.get("responseCode") != 200:
        raise HTTPException(status_code=502, detail="Jotform update was not accepted.")
