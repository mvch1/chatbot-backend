
import httpx
import json
from urllib.parse import urljoin
from typing import Dict, Any, List
from config import settings
from shared.constants.intents import Intent
from shared.utils.logger import get_logger
from database.repository import save_ticket
from database.db import get_db
from database.models import Session as DBSession, Message, User, Ticket
from sqlalchemy import select
from core.service import handle_workflow


logger = get_logger("conversation-orchestrator")

TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


async def _get_recent_messages(session: Dict[str, Any], limit: int = 5) -> List[Dict[str, str]]:
    """
    Retrieve the last `limit` messages for this session from the DB.
    Returns a list of {"role": "client"|"assistant", "content": str} dicts.
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
        role = "client" if msg.direction == "inbound" else "assistant"
        context.append({"role": role, "content": msg.content})
    return context

async def _get_recent_messages_reclamation(session: Dict[str, Any], limit: int = 5) -> List[Dict[str, str]]:
    """
    Retrieve the last `limit` messages *before the most recent one* for this session from the DB.
    Returns a list of {"role": "client"|"assistant", "content": str} dicts.
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
        role = "client" if msg.direction == "inbound" else "assistant"
        context.append({"role": role, "content": msg.content})
    return context


async def _get_user_tickets(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch all tickets for the user linked to this session."""
    session_id = session.get("session_id")
    if not session_id:
        return []

    async with get_db() as db:
        # 1. Get user_id from the current session
        result = await db.execute(select(DBSession.user_id).where(DBSession.id == session_id))
        user_id = result.scalar_one_or_none()
        if not user_id:
            return []

        # 2. Get all tickets for all sessions of this user
        result = await db.execute(
            select(Ticket)
            .join(DBSession, Ticket.session_id == DBSession.id)
            .where(DBSession.user_id == user_id)
            .order_by(Ticket.created_at.desc())
        )
        tickets = result.scalars().all()
        logger.info(f"Retrieved {len(tickets)} tickets for user_id={user_id}")

        return [
            {
                "id": t.number,
                "titre": t.description or "Sans titre",
                "statut": t.status,
                "date": t.created_at.isoformat() if t.created_at else ""
            }
            for t in tickets
        ]


async def route_message(
    intent: str,
    user_input: str,
    session: Dict[str, Any],
) -> Dict[str, Any]:
    """Route message to correct service based on intent."""

    if intent == "INFORMATION":
        return await _call_endpoint("information", user_input, session, intent)

    if intent == "RECLAMATION":
        return await _call_endpoint("reclamation", user_input, session, intent, wf_type="complaint", use_offset=True)

    if intent == "VALIDATION":
        return await _call_endpoint("validation", user_input, session, intent, wf_type="wallet", use_offset=True)

    return {
        "message": (
            "Je suis désolé, je ne suis pas en mesure de traiter cette demande. "
            "Souhaitez-vous parler à un conseiller ?"
        ),
    }


async def _call_endpoint(
    path: str,
    user_input: str,
    session: Dict[str, Any],
    intent: str,
    wf_type: str = None,
    use_offset: bool = False
) -> Dict[str, Any]:
    """Generic helper to call RAG/Workflow endpoints at settings.rag_service_url."""
    
    # 1. Build context
    if use_offset:
        context = await _get_recent_messages_reclamation(session, limit=5)
    else:
        context = await _get_recent_messages(session, limit=5)

    # 2. Fetch tickets if it's a relevant intent
    tickets = []
    if intent in ["RECLAMATION", "VALIDATION"]:
        tickets = await _get_user_tickets(session)

    # 3. Build robust URL
    base_url = settings.rag_service_url.rstrip("/")
    target_url = f"{base_url}/rag/{path}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            payload = {
                "question": user_input,
                "context": context,
                "intent": intent,
                "tickets": tickets,  # Always include the tickets list (even if empty)
            }
            
            logger.debug(f"Calling endpoint: {target_url} with intent {intent}")
            
            resp = await client.post(target_url, json=payload)
            
            logger.info(f"Endpoint {path} response status: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                logger.debug(f"Endpoint {path} response data: {data}")
                
                answer = data.get("answer", "Désolé, je n'ai pas pu obtenir de réponse.")
                nouveau_ticket = data.get("nouveau_ticket")
                
                # Check if we should trigger a workflow to create a ticket
                if nouveau_ticket and wf_type:
                    logger.info(f"Triggering workflow {wf_type} for session {session.get('session_id')}")
                    await _trigger_workflow(wf_type, session, {"summary": nouveau_ticket})
                
                return {"message": answer}
            else:
                logger.error(f"Endpoint {path} returned error {resp.status_code}: {resp.text}")
                
    except Exception as e:
        logger.error(f"Communication error with {path}: {e}")
        
    return {"message": "Je n'ai pas pu trouver une réponse. Souhaitez-vous parler à un conseiller ?"}


async def _trigger_workflow(wf_type: str, session: Dict, rag_data: Dict) -> None:
    """Call the workflow service to finalise a complaint or wallet validation."""
    try:
            await handle_workflow(wf_type, session, rag_data)
            print("ticket cree")
    except Exception as e:
        logger.error(f"Trigger workflow error (type={wf_type}): {e}")
