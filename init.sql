-- Create database if not exists
CREATE DATABASE banking_chatbot;

-- Grant privileges to user
GRANT ALL PRIVILEGES ON DATABASE banking_chatbot TO chatbot_user;

-- Connect to the database
\c banking_chatbot

-- Grant schema privileges
GRANT ALL PRIVILEGES ON SCHEMA public TO chatbot_user;

-- Grant default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO chatbot_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO chatbot_user;
