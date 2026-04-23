import uuid
import httpx
from typing import Optional
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel

from config import settings
from core.session_manager import SessionManager
from core.message_router import route_message
from handlers.whatsapp_handler import WhatsAppHandler
from shared.utils.logger import get_logger
from database.repository import save_message, save_intent_message, get_or_create_user
from core.message_router import _get_recent_messages
from database.models import Session

logger = get_logger("conversation-orchestrator")


# Singletons initialisés au démarrage
_session_mgr: Optional[SessionManager] = None
_wa: Optional[WhatsAppHandler] = None



from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global _session_mgr, _wa
    _session_mgr = SessionManager()
    _wa = WhatsAppHandler()
    logger.info("Conversation Orchestrator started")
    yield
    # Shutdown
    if _wa:
        await _wa.close()

app = FastAPI(title="Conversation Orchestrator", version="1.0.0", lifespan=lifespan)


# ── Health ────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "conversation-orchestrator"}


# ── Webhook verification (GET) ────────────────────────────
@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification — répond au challenge."""
    params = request.query_params
    mode      = params.get("hub.mode", "")
    token     = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("Webhook verified successfully")
        return PlainTextResponse(challenge)

    logger.warning(f"Webhook verification failed — token={token!r}")
    return PlainTextResponse("Forbidden", status_code=403)


# ── Webhook receive (POST) ────────────────────────────────
@app.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """Receive WhatsApp messages from Meta."""
    try:
        payload = await request.json()
    except Exception:
        return PlainTextResponse("Bad Request", status_code=400)

    # Signature check (skipped if no APP_SECRET)
    if _wa and not _wa.verify_signature(await request.body(), request.headers.get("X-Hub-Signature-256", "")):
        return PlainTextResponse("Forbidden", status_code=403)

    background_tasks.add_task(_process, payload)
    return {"status": "ok"}


# ── Postman / test endpoint ───────────────────────────────
class ChatRequest(BaseModel):
    phone: str
    message: str

@app.post("/chat")
async def chat(req: ChatRequest):
    """Endpoint de test Postman — retourne la réponse du bot directement en JSON (sans envoi WhatsApp)."""
    if not _session_mgr:
        return JSONResponse({"error": "Service not ready"}, status_code=503)

    phone = req.phone.strip()
    text  = req.message.strip()

    if not text:
        return JSONResponse({"error": "Le champ 'message' est vide"}, status_code=400)

    logger.info(f"[/chat] Message de {phone}: {text[:60]}")

    # Création du user s'il n'existe pas avec ce numéro
    await _safe(get_or_create_user(phone))

    # Récupération ou création de la session liée à l'user
    session = await _session_mgr.get(phone)
    if not session:
        session = await _session_mgr.create(phone, str(uuid.uuid4()))

    # Persist inbound message
    db_message_id = await _safe(save_message(session["session_id"], phone, text, "inbound"))

    # Intent
    intent_data = await _get_intent(text, session["session_id"])
    intent      = intent_data.get("intent", "UNKNOWN")
    print(f"Intent identifié: {intent}")
    # Persist intent classification result
    if db_message_id:
        await _safe(save_intent_message(db_message_id, intent))

    # Route
    result = await route_message(intent, text, session)

    # Update session state
    await _session_mgr.save(phone, session)

    # Persist outbound bot message
    response = result.get("message", "Je n'ai pas compris votre demande. Pouvez-vous reformuler ?")
    await _safe(save_message(session["session_id"], phone, response, "outbound"))

    return {"phone": phone, "response": response}


# ── Core processing ───────────────────────────────────────
async def _process(payload: dict):
    if not _session_mgr or not _wa:
        return

    msg = _wa.parse_incoming(payload)
    if not msg or not msg.get("text"):
        return

    phone      = msg["from"]
    text       = msg["text"].strip()
    message_id = msg["message_id"]

    logger.info(f"Message from {phone}: {text[:60]}")

    await _wa.mark_as_read(message_id)

    # Session
    session = await _session_mgr.get(phone)
    if not session:
        session = await _session_mgr.create(phone, str(uuid.uuid4()))

    # Persist inbound message
    db_message_id = await _safe(save_message(session["session_id"], phone, text, "inbound"))

    # Intent
    intent_data = await _get_intent(text)
    intent      = intent_data.get("intent", "UNKNOWN")
    print(f"Identified intent: {intent}")
    # Persist intent classification result
    if db_message_id:
        await _safe(save_intent_message(db_message_id, intent))

    # Route
    result = await route_message(intent, text, session)

    # Update session state
    await _session_mgr.save(phone, session)

    # Reply
    response = result.get("message", "Je n'ai pas compris votre demande. Pouvez-vous reformuler ?")

    # Persist outbound bot message
    await _safe(save_message(session["session_id"], phone, response, "outbound"))

    await _wa.send_text(phone, response)


async def _safe(coro):


    
    """Run a DB coroutine without letting errors break the main flow."""
    try:
        return await coro
    except Exception as exc:
        logger.error(f"DB persistence error: {exc}")
        return None

async def _get_intent(text: str, session_id: str) -> dict:
    try:
        # Récupérer le contexte
        contexte = None
        if session_id:
            # Pour l'instant, désactiver contexte pour tester
            # contexte = await _get_recent_messages(session_id)
            pass
        
        # Construire le payload
        payload = {"question": text}
        if contexte:
            payload["contexte"] = contexte
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{settings.intent_service_url}/rag/getIntent",
                json=payload,
            )
            if r.status_code == 200:
                return r.json()
            else:
                logger.warning(f"Intent service returned {r.status_code}")
                
    except Exception as e:
        logger.error(f"Intent service error: {e}")
    
    return {"intent": "UNKNOWN"}