
import httpx
from typing import Dict, Any, List
from config import settings
from shared.constants.intents import Intent
from shared.utils.logger import get_logger
from database.repository import save_ticket
from database.db import get_db
from database.models import Session as DBSession, Message, User
from sqlalchemy import select
from core.service import handle_workflow


logger = get_logger("conversation-orchestrator")

TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


async def _get_recent_messages(session: Dict[str, Any], limit: int = 5) -> List[Dict[str, str]]:
    """
    Retrieve the last `limit` messages for this session from the DB.
    Returns a list of {"role": "user"|"bot", "content": str} dicts.
    """
    session_id = session.get("session_id")
    if not session_id:
        return []

    async with get_db() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = result.scalars().all()

    # Reverse to chronological order and map direction to role
    context = []
    for msg in reversed(messages):
        role = "user" if msg.direction == "inbound" else "bot"
        context.append({"role": role, "content": msg.content})
    return context

async def _get_recent_messages_reclamation(session: Dict[str, Any], limit: int = 5) -> List[Dict[str, str]]:
    """
    Retrieve the last `limit` messages *before the most recent one* for this session from the DB.
    Returns a list of {"role": "user"|"bot", "content": str} dicts.
    """
    session_id = session.get("session_id")
    if not session_id:
        return []

    async with get_db() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .offset(1)  # ignore the most recent message
            .limit(limit)
        )
        messages = result.scalars().all()

    # Reverse to chronological order and map direction to role
    context = []
    for msg in reversed(messages):
        role = "user" if msg.direction == "inbound" else "bot"
        context.append({"role": role, "content": msg.content})
    return context


async def route_message(
    intent: str,
    user_input: str,
    session: Dict[str, Any],
) -> Dict[str, Any]:
    """Route message to correct service based on intent."""

    if intent == "INFORMATION":
        return await _call_rag_service(user_input, session, intent)

    if intent == "RECLAMATION":
        return await _call_workflow_service("complaint", user_input, session, intent)

    if intent == "VALIDATION":
        return await _call_workflow_service("wallet", user_input, session, intent)

    return {
        "message": (
            "Je suis désolé, je ne suis pas en mesure de traiter cette demande. "
            "Souhaitez-vous parler à un conseiller ?"
        ),
    }


async def _call_rag_service(user_input: str, session: Dict, intent: str) -> Dict:
    # Build context from the last 10 messages of this session
    context = await _get_recent_messages(session, limit=5)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{settings.rag_service_url}/rag/getAnswer",
                json={
                    "question": user_input,
                    "context": context,
                    "intent": intent,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"message": data["answer"]}
    except Exception as e:
        logger.error(f"RAG service error: {e}")
    return {"message": "Je n'ai pas pu trouver une réponse. Souhaitez-vous parler à un conseiller ?"}


async def _call_workflow_service(wf_type: str, user_input: str, session: Dict, intent: str) -> Dict:
    # Build context from the last 10 messages of this session
    context = await _get_recent_messages_reclamation(session, limit=5)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{settings.rag_service_url}/rag/postAnswer",
                json={
                    "question": user_input,
                    "context": context,
                    "intent": intent,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"LLM open_conversation {data.get('create_ticket')    }")

                # If the conversation is still open (collecting data), just return the answer
                if data.get("create_ticket", True):
                    await _trigger_workflow(wf_type, session, data)
                    return {"message": data["answer"]}
                    
                # Conversation is complete — trigger the appropriate workflow to create a ticket
                
                return {"message": data["answer"]}

    except Exception as e:
        logger.error(f"Workflow service error: {e}")
    return {"message": "Je n'ai pas pu trouver une réponse. Souhaitez-vous parler à un conseiller ?"}


async def _trigger_workflow(wf_type: str, session: Dict, rag_data: Dict) -> None:
    """Call the workflow service to finalise a complaint or wallet validation."""
    try:
            await handle_workflow(wf_type, session, rag_data)
            print("ticket cree")
    except Exception as e:
        logger.error(f"Trigger workflow error (type={wf_type}): {e}")
