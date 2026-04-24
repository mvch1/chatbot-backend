import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    openai_api_key = os.getenv("OPENAI_API_KEY", "dummy")
    whatsapp_token = os.getenv("WHATSAPP_TOKEN", "EAAUz384Y1HQBRdVUhtRJkiWKWKTwe4uy6MnwCiXv33vUUyNrNyHhcW7ZAsvMZBySpkbQhyOX7BiShVjWyf104Anp9kw5RtInuXtzxh7oNAhZAaJvbescZATLb7eqIE9ZCFDi7L9uiFt1KnA5vJRe3k5KQSe6EdoyPu2vSVGMxJEN6gXf4J0obbnXvDPmxugax5ZChyBFuzbeWCVWRzZBmFSkk4oSdl1M83vEo9Q0Rkv7nyJDSuvYDKNHH75QZAUj0NjNAy0LiRedSHcrGE1vb4JT")
    whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    whatsapp_app_secret = os.getenv("WHATSAPP_APP_SECRET", "testtoken123")
    database_url = os.getenv("DATABASE_URL", "postgresql://chatbot_user:motdepasse@localhost:5432/banking_chatbot")
    intent_service_url = os.getenv("INTENT_SERVICE_URL", "http://localhost:8021")
    rag_service_url = os.getenv("RAG_SERVICE_URL", "http://localhost:8021")
    workflow_service_url = os.getenv("WORKFLOW_SERVICE_URL", "http://localhost:8020")
    agent_service_url = os.getenv("AGENT_SERVICE_URL", "http://agent-service:8005")
    confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))
    complaint_amount_threshold = float(os.getenv("COMPLAINT_AMOUNT_THRESHOLD", "500000"))
    log_level = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()
