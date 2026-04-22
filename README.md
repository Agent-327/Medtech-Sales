# MedTechSales

MedTechSales is a Flask-based AI sales enablement app for MedTech reps. It combines Azure OpenAI/Foundry-powered agents with voice workflows, presentation generation, translation, podcast script/audio generation, and ambient transcription.

## What This Solution Does

- Practice mode for role-play conversations with configurable product and surgeon personas
- Voice practice over WebSocket using Azure Realtime Voice
- Exam voice configuration endpoint for knowledge-check conversations
- Delivery workflow to generate presentation/email content from prompts and transcripts
- Follow-up workflow to prepare presentation + email draft from transcript
- PowerPoint translation (text and whole document)
- Podcast SSML generation + Azure Speech synthesis to MP3
- Ambient listening WebSocket for real-time transcription with diarization

## Project Structure

- app.py: Flask app, REST APIs, WebSocket endpoints, orchestration glue
- agent_app.py: Agent definitions, workflows, PowerPoint/email tooling
- static/index.html: Frontend entry page
- requirements.txt: Python dependencies
- .env.example: Environment variable template

## Prerequisites

- Python 3.10+
- Windows PowerShell (for the provided local workflow)
- Azure resources and valid keys for:
  - Azure OpenAI/Foundry
  - Azure Voice Realtime API
  - Azure Translator
  - Azure Speech
- Network access to your configured Azure endpoints

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   pip install -r requirements.txt

3. Create a local environment file from the template and fill real values:

   copy .env.example .env

4. Ensure these variables are present in your shell session before starting the app.

## Environment Variables

The application expects these values (see .env.example):

- AZURE_OPENAI_ENDPOINT
- AZURE_OPENAI_API_KEY
- AZURE_OPENAI_MODEL (optional, default in code)
- AZURE_OPENAI_API_VERSION (optional, default in code)
- AZURE_VOICE_API_KEY
- AZURE_TRANSLATOR_KEY
- AZURE_SPEECH_ENDPOINT
- AZURE_SPEECH_KEY

Optional aliases supported by agent_app.py:

- FOUNDRY_ENDPOINT
- FOUNDRY_API_KEY
- FOUNDRY_MODEL
- FOUNDRY_API_VERSION

## Run Locally

Start the Flask app:

python app.py

Then open:

http://127.0.0.1:5000

## Main API Endpoints

### Practice

- GET /api/practice/options
- POST /api/practice
- POST /api/practice/reset
- POST /api/practice/voice-config
- POST /api/exam/voice-config
- WS /api/practice/voice-ws

### Delivery / Follow-up

- GET /api/deliver/options
- POST /api/chat
- POST /api/transcript
- POST /api/send-email
- GET /api/download

### Translation

- GET /api/translate/languages
- POST /api/translate/text
- POST /api/translate

### Podcast

- GET /api/podcast/options
- POST /api/podcast/generate
- POST /api/podcast/synthesize

### Ambient Transcription

- WS /api/ambient/ws

## WebSocket Notes

Practice voice WS and ambient WS both expect active browser-client connections.

- Practice voice WS proxies between browser and Azure Voice Realtime API.
- Ambient WS expects JSON messages with base64 PCM audio payloads and returns partial/final transcription events.

## Security Notes

- Do not commit .env
- Keep secrets in local environment or secure secret stores
- Rotate any key that was previously exposed

## Troubleshooting

- Missing environment variable errors:
  - Confirm .env values are loaded into your running shell/process
- 500 errors on translation/speech/voice routes:
  - Verify corresponding Azure keys and endpoint access
- WebSocket issues:
  - Check browser console, proxy/firewall settings, and Azure endpoint reachability

## Known Outputs Created by App

During local usage, the app may create:

- demo.pptx
- demo_translated.pptx
- podcast.mp3
