# Conversation Orchestrator — Chef d'orchestre du dialogue

## Rôle
Microservice central qui coordonne toute la logique conversationnelle.
Il reçoit les messages WhatsApp, maintient l'état des conversations,
appelle les services appropriés et retourne les réponses.

## Interactions
- Reçoit les messages de l'API Gateway
- Appelle l'Intent Service pour comprendre la demande
- Appelle le RAG Service (questions FAQ) ou le Workflow Service (réclamations)
- Appelle l'Agent Service si escalade nécessaire
- Écrit/lit la session dans Redis
- Envoie les réponses via WhatsApp Business API

## Technologies
- Python 3.11 + FastAPI (API REST async haute performance)
- Redis (sessions conversationnelles, TTL 1h)
- httpx (appels HTTP async vers les autres services)
# chatbot-backend
