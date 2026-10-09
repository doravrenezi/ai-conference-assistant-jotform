# This file stores per-session chat history, drafts, pending actions, and flow state.
import uuid

from schemas import ChatMessage, RegistrationDraft, RegistrationLookupDraft


class ChatStateStore:
    def __init__(self):
        self.chat_histories = {}
        self.registration_drafts = {}
        self.lookup_drafts = {}
        self.pending_registration_confirmations = {}
        self.active_update_registrations = {}
        self.pending_registration_updates = {}
        self.pending_registration_cancellations = {}
        self.registration_flow = {}
        self.last_loaded_registrations = {}
        self.accessibility_collected = {}

    def get_session_history(self, session_id: str | None) -> tuple[str, list[ChatMessage]]:
        if not session_id:
            session_id = str(uuid.uuid4())
        raw_history = self.chat_histories.get(session_id, [])
        history = [ChatMessage(**message) for message in raw_history]
        return session_id, history

    def store_session_history(self, session_id: str, history: list[ChatMessage]) -> None:
        self.chat_histories[session_id] = [message.model_dump() for message in history]

    def append_and_store_history(self, session_id: str, history: list[ChatMessage], reply: str) -> list[ChatMessage]:
        history.append(ChatMessage(role="assistant", content=reply))
        self.store_session_history(session_id, history)
        return history

    def get_registration_draft(self, session_id: str) -> RegistrationDraft:
        raw_draft = self.registration_drafts.get(session_id)
        if not raw_draft:
            return RegistrationDraft()
        return RegistrationDraft(**raw_draft)

    def store_registration_draft(self, session_id: str, draft: RegistrationDraft) -> None:
        self.registration_drafts[session_id] = draft.model_dump(mode="json")

    def get_pending_registration_confirmation(self, session_id: str) -> RegistrationDraft | None:
        raw_draft = self.pending_registration_confirmations.get(session_id)
        if not raw_draft:
            return None
        return RegistrationDraft(**raw_draft)

    def store_pending_registration_confirmation(self, session_id: str, draft: RegistrationDraft) -> None:
        self.pending_registration_confirmations[session_id] = draft.model_dump(mode="json")

    def clear_pending_registration_confirmation(self, session_id: str) -> None:
        self.pending_registration_confirmations.pop(session_id, None)

    def get_active_update_registration(self, session_id: str) -> dict | None:
        return self.active_update_registrations.get(session_id)

    def store_active_update_registration(self, session_id: str, registration_id: int, registration_code: str, status: str) -> None:
        self.active_update_registrations[session_id] = {
            "registration_id": registration_id,
            "registration_code": registration_code,
            "status": status,
        }

    def clear_active_update_registration(self, session_id: str) -> None:
        self.active_update_registrations.pop(session_id, None)

    def get_pending_registration_update(self, session_id: str) -> dict | None:
        raw_update = self.pending_registration_updates.get(session_id)
        if not raw_update:
            return None
        return {
            "registration_id": raw_update["registration_id"],
            "registration_code": raw_update["registration_code"],
            "status": raw_update["status"],
            "jotform_submission_id": raw_update.get("jotform_submission_id"),
            "draft": RegistrationDraft(**raw_update["draft"]),
        }

    def store_pending_registration_update(
        self,
        session_id: str,
        registration_id: int,
        registration_code: str,
        status: str,
        jotform_submission_id: str | None,
        draft: RegistrationDraft,
    ) -> None:
        self.pending_registration_updates[session_id] = {
            "registration_id": registration_id,
            "registration_code": registration_code,
            "status": status,
            "jotform_submission_id": jotform_submission_id,
            "draft": draft.model_dump(mode="json"),
        }

    def clear_pending_registration_update(self, session_id: str) -> None:
        self.pending_registration_updates.pop(session_id, None)

    def get_lookup_draft(self, session_id: str) -> RegistrationLookupDraft:
        raw_draft = self.lookup_drafts.get(session_id)
        if not raw_draft:
            return RegistrationLookupDraft()
        return RegistrationLookupDraft(**raw_draft)

    def store_lookup_draft(self, session_id: str, draft: RegistrationLookupDraft) -> None:
        self.lookup_drafts[session_id] = draft.model_dump(mode="json")

    def get_pending_registration_cancellation(self, session_id: str) -> dict | None:
        return self.pending_registration_cancellations.get(session_id)

    def store_pending_registration_cancellation(self, session_id: str, registration: dict) -> None:
        self.pending_registration_cancellations[session_id] = registration

    def clear_pending_registration_cancellation(self, session_id: str) -> None:
        self.pending_registration_cancellations.pop(session_id, None)

    def get_last_loaded_registration(self, session_id: str) -> dict | None:
        return self.last_loaded_registrations.get(session_id)

    def store_last_loaded_registration(self, session_id: str, registration: dict) -> None:
        self.last_loaded_registrations[session_id] = registration

    def clear_last_loaded_registration(self, session_id: str) -> None:
        self.last_loaded_registrations.pop(session_id, None)

    def has_accessibility_been_collected(self, session_id: str) -> bool:
        return bool(self.accessibility_collected.get(session_id, False))

    def mark_accessibility_collected(self, session_id: str, collected: bool = True) -> None:
        self.accessibility_collected[session_id] = collected

    def clear_accessibility_collected(self, session_id: str) -> None:
        self.accessibility_collected.pop(session_id, None)

    def get_flow_state(self, session_id: str) -> dict[str, str | bool | None]:
        return self.registration_flow.get(
            session_id,
            {"collecting": False, "awaiting_field": None, "mode": None},
        )

    def store_flow_state(self, session_id: str, collecting: bool, awaiting_field: str | None, mode: str | None) -> None:
        self.registration_flow[session_id] = {
            "collecting": collecting,
            "awaiting_field": awaiting_field,
            "mode": mode,
        }

    def start_collecting_field(self, session_id: str, field_name: str, mode: str) -> None:
        self.store_flow_state(session_id, collecting=True, awaiting_field=field_name, mode=mode)

    def reset_registration(self, session_id: str) -> None:
        self.store_registration_draft(session_id, RegistrationDraft())
        self.clear_pending_registration_confirmation(session_id)
        self.clear_active_update_registration(session_id)
        self.clear_pending_registration_update(session_id)
        self.clear_pending_registration_cancellation(session_id)
        self.clear_last_loaded_registration(session_id)
        self.clear_accessibility_collected(session_id)
        self.store_flow_state(session_id, collecting=False, awaiting_field=None, mode=None)

    def reset_lookup(self, session_id: str) -> None:
        self.store_lookup_draft(session_id, RegistrationLookupDraft())
        self.clear_last_loaded_registration(session_id)
        self.store_flow_state(session_id, collecting=False, awaiting_field=None, mode=None)

    def reset_update(self, session_id: str) -> None:
        self.store_lookup_draft(session_id, RegistrationLookupDraft())
        self.store_registration_draft(session_id, RegistrationDraft())
        self.clear_active_update_registration(session_id)
        self.clear_pending_registration_update(session_id)
        self.clear_pending_registration_cancellation(session_id)
        self.clear_last_loaded_registration(session_id)
        self.clear_accessibility_collected(session_id)
        self.store_flow_state(session_id, collecting=False, awaiting_field=None, mode=None)
