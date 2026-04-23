from sqlalchemy import select, asc
from datetime import datetime, timezone
import uuid

from database.db import get_db
from database.models import Ticket, Session, Agent


def generate_ticket_number(prefix="REC"):
    return f"{prefix}-{str(uuid.uuid4())[:8].upper()}"


async def handle_workflow(wf_type: str, session: dict, rag_data: dict):
    async with get_db() as db:
        try:
            session_id = session.get("session_id")

            # 1. récupérer session DB
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            db_session = result.scalar_one_or_none()

            if not db_session:
                raise Exception("Session not found")

            # ─────────────────────────────
            # 🎯 WORKFLOW RECLAMATION
            # ─────────────────────────────
            if wf_type == "complaint":

                # 2. choisir agent
                result = await db.execute(
                    select(Agent)
                    .where(Agent.is_active == True)
                    .order_by(asc(Agent.active_tickets_count))
                    .with_for_update()
                )
                agent = result.scalars().first()

                if not agent:
                    raise Exception("No agent available")

                # 3. créer ticket
                ticket = Ticket(
                    number=generate_ticket_number("REC"),
                    session_id=db_session.id,
                    agent_id=agent.id,
                    description=rag_data.get("summary", "Réclamation client"),
                    status="open"
                )

                db.add(ticket)

                # 4. incrémenter agent
                agent.active_tickets_count += 1

                # 5. fermer session
                db_session.state = "COMPLETED"
                db_session.closed_at = datetime.now(timezone.utc)

                await db.commit()

                return {"ticket_number": ticket.number}

            # ─────────────────────────────
            # 🎯 WORKFLOW WALLET
            # ─────────────────────────────
            # ─────────────────────────────
            # 🎯 WORKFLOW WALLET
            # ─────────────────────────────
            if wf_type == "wallet":

                # 2. choisir agent
                result = await db.execute(
                    select(Agent)
                    .where(Agent.is_active == True)
                    .order_by(asc(Agent.active_tickets_count))
                    .with_for_update()
                )
                agent = result.scalars().first()

                if not agent:
                    raise Exception("No agent available")

                # 3. créer ticket
                ticket = Ticket(
                    number=generate_ticket_number("WAL"),
                    session_id=db_session.id,
                    agent_id=agent.id,
                    description=rag_data.get("summary", "Demande wallet"),
                    status="open"
                )

                db.add(ticket)

                # 4. incrémenter agent
                agent.active_tickets_count += 1

                # 5. fermer session
                db_session.state = "COMPLETED"
                db_session.closed_at = datetime.now(timezone.utc)

                await db.commit()

                return {"ticket_number": ticket.number}
        except Exception as e:
            await db.rollback()
            raise e