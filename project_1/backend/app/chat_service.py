# This file coordinates each chat request by combining session state, workflow execution, and LLM responses.
import logging

from fastapi import HTTPException

from chat_llm import run_assistant_turn
from chat_state import ChatStateStore
from schemas import ChatMessage, ChatRequest


logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self):
        self.state = ChatStateStore()

    def process_chat(self, chat: ChatRequest, raw_session_id: str | None) -> dict:
        try:
            session_id, session_history = self.state.get_session_history(raw_session_id)
            base_history = session_history if session_history else chat.history
            conversation_history = [*base_history, ChatMessage(role="user", content=chat.message)]
            user_message = chat.message.strip()
            assistant_turn = run_assistant_turn(conversation_history, user_message, session_id, self.state)
            reply = assistant_turn["reply"]
            result = assistant_turn.get("result")

            self.state.append_and_store_history(session_id, conversation_history, reply)
            return {"reply": reply, "result": result}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unhandled chat processing error")
            raise HTTPException(status_code=502, detail="Backend request failed.") from exc
