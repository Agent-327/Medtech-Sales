import os
import asyncio
import threading
import queue as _queue
import requests as http_requests
import aiohttp
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_sock import Sock
from agent_app import (
    build_practice_agent, build_presentation_agent, build_workflow,
    build_followup_workflow, send_email_direct, _email_draft,
    build_podcast_agent, PODCAST_VOICES,
    PRODUCTS, SURGEON_PERSONAS, SUPPORTED_LANGUAGES,
)
import re as _re

app = Flask(__name__, static_folder="static")
sock = Sock(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Keep practice agent sessions in memory (keyed by session id)
_practice_sessions: dict[str, list] = {}


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Practice: conversational role-play ──
@app.route("/api/practice/options", methods=["GET"])
def practice_options():
    products = [{"key": k, "name": v["name"]} for k, v in PRODUCTS.items()]
    personas = [{"key": k, "name": v["name"], "subtitle": v["subtitle"]} for k, v in SURGEON_PERSONAS.items()]
    return jsonify({"products": products, "personas": personas})


@app.route("/api/practice", methods=["POST"])
def practice():
    data = request.get_json()
    message = data.get("message", "").strip()
    session_id = data.get("sessionId", "default")
    product = data.get("product")
    persona = data.get("persona")
    if not message:
        return jsonify({"error": "Message is required"}), 400

    history = _practice_sessions.setdefault(session_id, [])
    history.append({"role": "user", "content": message})

    agent = build_practice_agent(product_key=product, persona_key=persona)
    # Build the full conversation prompt from history
    conversation = "\n".join(
        f"{'Sales Rep' if m['role'] == 'user' else 'Agent'}: {m['content']}"
        for m in history
    )
    result = asyncio.run(agent.run(conversation))
    reply = str(result)
    history.append({"role": "assistant", "content": reply})

    return jsonify({"reply": reply})


@app.route("/api/practice/reset", methods=["POST"])
def practice_reset():
    data = request.get_json() or {}
    session_id = data.get("sessionId", "default")
    _practice_sessions.pop(session_id, None)
    return jsonify({"status": "ok"})


# ── Practice: Voice session via Azure OpenAI Realtime API ──
_VOICE_ENDPOINT = "https://foundry-medtechsales.services.ai.azure.com/"
_VOICE_API_KEY = os.environ.get("AZURE_VOICE_API_KEY", "").strip()


def _build_voice_instructions(product_key, persona_key):
    """Build the same practice instructions used by the text agent."""
    product = PRODUCTS.get(product_key) if product_key else None
    persona = SURGEON_PERSONAS.get(persona_key) if persona_key else None

    product_context = ""
    if product:
        product_context = (
            f"\n\nPRODUCT CONTEXT: The rep is practicing a pitch for {product['name']}. "
            f"{product['description']} Stay focused on this product."
        )

    persona_context = ""
    surgeon_name = "Dr. Simmons"
    if persona:
        surgeon_name = f"Dr. {persona['name'].split()[0]}"
        persona_context = (
            f"\n\nSURGEON PERSONA: You are playing {persona['name']} ({persona['subtitle']}). "
            f"Personality: {persona['personality']} "
            f"Key barriers you raise: {'; '.join(persona['barriers'])}. "
            f"Do NOT reveal which messages would convince you. Only respond positively when "
            f"the rep's messaging naturally aligns with what would land."
        )

    return (
        f"You are an AI voice role-play coach for MedTech Sales Representatives. "
        f"You play the role of {surgeon_name}, an orthopedic surgeon the rep is pitching to. "
        f"You are curious and open-minded but still ask realistic questions about clinical evidence, "
        f"cost justification, OR workflow, and competitive alternatives. "
        f"Stay in character as the surgeon throughout the voice conversation. "
        f"Keep your responses concise (2-4 sentences) since this is a voice conversation. "
        f"Be fair — challenge vague claims gently, but acknowledge good points and show genuine interest "
        f"when the rep makes a strong case. Be encouraging, not adversarial. "
        f"Start by greeting the rep warmly as {surgeon_name} and asking what they would like to discuss. "
        f"If the rep asks for feedback, be constructive and motivating — lead with positives."
        f"{product_context}"
        f"{persona_context}"
    )


@app.route("/api/practice/voice-config", methods=["POST"])
def voice_config():
    """Return instructions & voice config for the browser to send after WS connects."""
    data = request.get_json() or {}
    product_key = data.get("product")
    persona_key = data.get("persona")
    instructions = _build_voice_instructions(product_key, persona_key)
    return jsonify({
        "instructions": instructions,
        "voice": "ash",
    })


@app.route("/api/exam/voice-config", methods=["POST"])
def exam_voice_config():
    """Return exam agent instructions for the voice-based knowledge test."""
    return jsonify({
        "instructions": _EXAM_INSTRUCTIONS,
        "voice": "ash",
    })


_EXAM_INSTRUCTIONS = r"""You are a voice to voice conversational examiner who test whether a specialist rep knows the OptiVu Shoulder product well enough to support training, setup, workflow execution, and field troubleshooting. Below are the 10 questions that you will ask the user one by one, after each question allow the user to provide their response and then you check if the provided answer is correct or not by referring to the Answer Key provided to you. If the user deviates from the exam, gracefully tell them that let's focus on the exam questions first and then we can address other concerns. After the exam is concluded, provide feedback to the user on how they did, the number of questions they answered correctly for example "you answered 7 out of 10 correctly", the percentage for example "that is a score of 70%" and the question numbers that the user answered incorrectly. Let them know what areas they need to review.

Knowledge Test

Section A — Product Overview, Intended Use, and Positioning

1. What is the primary purpose of the OptiVu Shoulder system?
A. To autonomously perform shoulder arthroplasty
B. To aid the surgeon in locating anatomical structures, humeral resection, and aligning the endoprosthesis during shoulder arthroplasty
C. To replace pre-operative planning
D. To provide postoperative implant analysis

2. OptiVu Shoulder is intended to be used specifically with which Zimmer Biomet systems?
A. Persona Knee and ROSA Knee
B. Alliance Glenoid and Comprehensive Reverse Shoulder
C. Signature Guides only
D. Any shoulder implant from any manufacturer

3. True or False: OptiVu Shoulder can be used without a pre-operative planning file.

4. Which planning platform provides the pre-operative planning files used by OptiVu Shoulder?
A. ROSA Planning
B. Signature ONE
C. Blueprint
D. GPS Navigation Software

5. According to the internal strategy materials, what problem is this technology intended to solve?
Short answer

6. True or False: Most surveyed surgeons viewed the technology as more beneficial only in hospital settings than in ASCs.

7. What analogy did surgeons commonly use to describe the technology in the messaging research?
Short answer

8. According to the internal materials, which area of the procedure was highlighted as especially valuable by surgeons in feedback sessions?
A. Skin closure
B. Glenoid-side accuracy and consistency
C. Cement mixing
D. Post-op recovery scoring

Section C — Safety, Warnings, and Limitations

9. True or False: The HMD should be relied upon as the sole method of intraoperative decision-making.

10. What should happen if the anchor is accidentally moved after registration?
Short answer

Answer Key
1. B — The manual states the system is designed to aid surgeons in locating anatomical structures, humerus resection, and aligning the endoprosthesis during total or reverse shoulder arthroplasty.
2. B — The manual specifies use with the Zimmer Biomet Alliance Glenoid and Comprehensive Reverse Shoulder systems.
3. False — A patient planning file must be uploaded before using the software.
4. B — The planning files are provided by Signature ONE.
5. Expected answer: Surgeons lack a comprehensive solution to help flexibly and accurately execute shoulder arthroplasty procedures in a cost-efficient, small-footprint manner.
6. False — Most surveyed surgeons viewed it as similarly beneficial in both hospital and ASC settings.
7. Expected answer: A "GPS for shoulder arthroplasty," or equivalent wording describing real-time navigation guidance.
8. B — Internal surgeon feedback emphasized the value of consistent glenoid-side accuracy.
9. False — The manual states the HMD should not be relied upon solely and should be used with traditional methods.
10. Expected answer: If the anchor is accidentally moved, the anatomy needs to be re-registered; the workflow should go back to the registration step or reset as appropriate.

Keep your responses concise since this is a voice conversation. When reading questions with multiple choice options, read the question and all options clearly. For True/False and Short Answer questions, just read the question. After the user answers, confirm if they are correct or incorrect and briefly explain the right answer before moving to the next question."""


@sock.route("/api/practice/voice-ws")
def voice_ws_proxy(ws):
    """WebSocket proxy: browser <-> Flask <-> Azure VoiceLive Realtime API."""
    if not _VOICE_API_KEY:
        try:
            ws.send('{"error":"Server is missing AZURE_VOICE_API_KEY"}')
        except Exception:
            pass
        return

    azure_url = (
        _VOICE_ENDPOINT.replace("https://", "wss://").rstrip("/")
        + "/voice-live/realtime?api-version=2025-10-01&model=gpt-realtime"
    )
    headers = {"api-key": _VOICE_API_KEY}

    browser_q = _queue.Queue()          # thread-safe queue for browser→azure
    stop = threading.Event()

    def azure_thread():
        """Run aiohttp WS to Azure in its own event loop / thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        azure_url, headers=headers, heartbeat=30,
                        max_msg_size=4 * 1024 * 1024,
                    ) as azure_ws:

                        async def send_loop():
                            """Pull from thread-safe queue, forward to Azure."""
                            while not stop.is_set():
                                try:
                                    msg = await loop.run_in_executor(
                                        None, lambda: browser_q.get(timeout=0.1),
                                    )
                                    await azure_ws.send_str(msg)
                                except _queue.Empty:
                                    continue
                                except Exception:
                                    return

                        async def recv_loop():
                            """Read from Azure, forward to browser via flask-sock."""
                            async for msg in azure_ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    try:
                                        ws.send(msg.data)
                                    except Exception:
                                        return
                                elif msg.type in (
                                    aiohttp.WSMsgType.CLOSED,
                                    aiohttp.WSMsgType.ERROR,
                                ):
                                    return

                        await asyncio.gather(send_loop(), recv_loop())
            except Exception as exc:
                print(f"[voice-ws] Azure connection error: {exc}")
            finally:
                stop.set()

        loop.run_until_complete(_run())
        loop.close()

    t = threading.Thread(target=azure_thread, daemon=True)
    t.start()

    # Main thread: read from browser WebSocket, feed thread-safe queue.
    # receive(timeout=1) returns None on timeout (no data yet) — only break
    # on ConnectionClosed which signals the peer actually disconnected.
    from simple_websocket import ConnectionClosed
    try:
        while not stop.is_set():
            try:
                msg = ws.receive(timeout=1)
            except ConnectionClosed:
                break
            if msg is not None:
                browser_q.put(msg)
    except Exception:
        pass
    finally:
        stop.set()
        t.join(timeout=5)


# ── Deliver: create presentation & email ──
@app.route("/api/deliver/options", methods=["GET"])
def deliver_options():
    products = [{"key": k, "name": v["name"]} for k, v in PRODUCTS.items()]
    personas = [{"key": k, "name": v["name"], "subtitle": v["subtitle"]} for k, v in SURGEON_PERSONAS.items()]
    return jsonify({"products": products, "personas": personas})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "").strip()
    product = data.get("product")
    persona = data.get("persona")
    if not message:
        return jsonify({"error": "Message is required"}), 400

    agent = build_presentation_agent(product_key=product, persona_key=persona)
    result = asyncio.run(agent.run(message))
    return jsonify({"reply": str(result)})


# ── Follow Up: transcript → presentation → email draft workflow ──
@app.route("/api/transcript", methods=["POST"])
def transcript():
    data = request.get_json()
    transcript_text = data.get("transcript", "").strip()
    email = data.get("email", "").strip()
    if not transcript_text:
        return jsonify({"error": "Transcript is required"}), 400

    prompt = f"Here is the call transcript:\n\n{transcript_text}"
    if email:
        prompt += f"\n\nPrepare the email draft for {email}."

    _email_draft.clear()
    workflow_agent = build_followup_workflow()
    result = asyncio.run(workflow_agent.run(prompt))

    return jsonify({
        "reply": str(result),
        "draft": _email_draft.copy() if _email_draft else None,
    })


@app.route("/api/send-email", methods=["POST"])
def send_email():
    data = request.get_json()
    to = data.get("to", "").strip()
    subject = data.get("subject", "").strip()
    body = data.get("body", "").strip()
    if not to or not subject or not body:
        return jsonify({"error": "to, subject and body are required"}), 400

    file_path = os.path.join(BASE_DIR, "demo.pptx")
    if not os.path.exists(file_path):
        return jsonify({"error": "No presentation found to attach"}), 404

    result = send_email_direct(to, subject, body, file_path)
    if "Failed" in result:
        return jsonify({"error": result}), 500
    return jsonify({"status": "sent", "message": result})


@app.route("/api/download")
def download():
    path = os.path.join(BASE_DIR, "demo.pptx")
    if not os.path.exists(path):
        return jsonify({"error": "No presentation found"}), 404
    return send_file(path, as_attachment=True, download_name="demo.pptx")


# ── Translate: Azure Document Translation ──
_DOC_TRANSLATE_ENDPOINT = "https://resource-translatormed.cognitiveservices.azure.com/"
_DOC_TRANSLATE_KEY = os.environ.get("AZURE_TRANSLATOR_KEY", "").strip()


@app.route("/api/translate/languages", methods=["GET"])
def translate_languages():
    languages = [{"key": k, "name": v} for k, v in SUPPORTED_LANGUAGES.items() if k != "en"]
    return jsonify({"languages": languages})


@app.route("/api/translate/text", methods=["POST"])
def translate_text():
    data = request.get_json()
    texts = data.get("texts", [])
    target_lang = data.get("language", "").strip()
    if not texts or not target_lang or target_lang == "en":
        return jsonify({"error": "texts and a non-English target language are required"}), 400
    if not _DOC_TRANSLATE_KEY:
        return jsonify({"error": "Server is missing AZURE_TRANSLATOR_KEY"}), 500

    url = f"{_DOC_TRANSLATE_ENDPOINT}/translator/text/v3.0/translate?to={target_lang}&api-version=3.0"
    headers = {
        "Ocp-Apim-Subscription-Key": _DOC_TRANSLATE_KEY,
        "Content-Type": "application/json",
    }
    body = [{"Text": t} for t in texts]

    try:
        resp = http_requests.post(url, headers=headers, json=body, timeout=30)
    except Exception as e:
        return jsonify({"error": f"Translation request failed: {e}"}), 502

    if resp.status_code != 200:
        return jsonify({"error": f"Translation service returned {resp.status_code}: {resp.text[:500]}"}), 502

    results = resp.json()
    translated = [r["translations"][0]["text"] for r in results]
    return jsonify({"translated": translated})


@app.route("/api/translate", methods=["POST"])
def translate_document():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    target_lang = request.form.get("language", "").strip()
    if not target_lang or target_lang == "en":
        return jsonify({"error": "Please select a target language"}), 400
    if not _DOC_TRANSLATE_KEY:
        return jsonify({"error": "Server is missing AZURE_TRANSLATOR_KEY"}), 500

    # Read the uploaded PPTX bytes
    file_bytes = file.read()
    filename = file.filename or "presentation.pptx"

    # Call Azure Document Translation synchronous API
    url = (
        f"{_DOC_TRANSLATE_ENDPOINT}/translator/document:translate"
        f"?targetLanguage={target_lang}&api-version=2024-05-01"
    )
    headers = {"Ocp-Apim-Subscription-Key": _DOC_TRANSLATE_KEY}
    files_payload = {
        "document": (
            filename,
            file_bytes,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    }

    try:
        resp = http_requests.post(url, headers=headers, files=files_payload, timeout=120)
    except Exception as e:
        return jsonify({"error": f"Translation request failed: {e}"}), 502

    if resp.status_code != 200:
        detail = resp.text[:500]
        return jsonify({"error": f"Translation service returned {resp.status_code}: {detail}"}), 502

    # Save translated file and return it
    translated_path = os.path.join(BASE_DIR, "demo_translated.pptx")
    with open(translated_path, "wb") as f:
        f.write(resp.content)
    return send_file(translated_path, as_attachment=True, download_name=f"translated_{filename}")


# ── Podcast: SSML script generation + Azure TTS synthesis ──
_SPEECH_ENDPOINT = os.environ.get(
    "AZURE_SPEECH_ENDPOINT",
    "https://foundry-medtechsales.cognitiveservices.azure.com/",
)
_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY", "").strip()

# Store latest SSML so the synthesize step can retrieve it
_podcast_ssml: dict = {"ssml": ""}


def _extract_ssml(raw: str) -> str:
    """Pull the <speak>...</speak> block from agent output, stripping markdown fences."""
    # Remove markdown code fences if present
    cleaned = _re.sub(r"```(?:xml|ssml)?\s*", "", raw)
    cleaned = cleaned.replace("```", "")
    match = _re.search(r"(<speak[\s\S]*</speak>)", cleaned)
    ssml = match.group(1).strip() if match else cleaned.strip()
    return _sanitize_ssml(ssml)


def _sanitize_ssml(ssml: str) -> str:
    """Move stray <break> elements between <voice> tags inside the preceding voice.

    Azure TTS requires all content elements to be inside <voice>. The agent
    sometimes puts <break time="500ms"/> between </voice> and <voice>, which
    causes HTTP 400.
    """
    # Pattern: </voice> ... <break .../> ... <voice  →  move break before </voice>
    ssml = _re.sub(
        r'</voice>(\s*)(<break\s[^/]*/\s*>)(\s*)(<voice)',
        r'\2</voice>\1\3\4',
        ssml,
    )
    # Also remove any remaining bare <break> directly under <speak>
    # (between </voice> and the next <voice> or </speak>)
    ssml = _re.sub(
        r'</voice>(\s*)<break\s[^/]*/\s*>(\s*)</speak>',
        r'</voice>\1\2</speak>',
        ssml,
    )
    return ssml


@app.route("/api/podcast/options", methods=["GET"])
def podcast_options():
    products = [{"key": k, "name": v["name"]} for k, v in PRODUCTS.items()]
    voices = [
        {"key": k, "name": v["name"], "role": v["role"], "voice": v["voice"]}
        for k, v in PODCAST_VOICES.items()
    ]
    return jsonify({"products": products, "voices": voices})


@app.route("/api/podcast/generate", methods=["POST"])
def podcast_generate():
    """Generate the SSML podcast script via the agent."""
    data = request.get_json() or {}
    product_key = data.get("product")
    if not product_key or product_key not in PRODUCTS:
        return jsonify({"error": "A valid product key is required"}), 400

    product_name = PRODUCTS[product_key]["name"]
    agent = build_podcast_agent(product_key=product_key)
    result = asyncio.run(agent.run(
        f"Write a podcast episode script about {product_name}. "
        f"Cover the product features, clinical benefits, and sales positioning."
    ))
    ssml = _extract_ssml(str(result))
    _podcast_ssml["ssml"] = ssml
    return jsonify({"ssml": ssml})


@app.route("/api/podcast/synthesize", methods=["POST"])
def podcast_synthesize():
    """Send SSML to Azure TTS and return MP3 audio."""
    data = request.get_json() or {}
    ssml = data.get("ssml", "").strip() or _podcast_ssml.get("ssml", "")
    if not ssml:
        return jsonify({"error": "No SSML to synthesize"}), 400
    if not _SPEECH_KEY:
        return jsonify({"error": "Server is missing AZURE_SPEECH_KEY"}), 500

    tts_url = f"{_SPEECH_ENDPOINT.rstrip('/')}/tts/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": _SPEECH_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3",
    }

    try:
        resp = http_requests.post(tts_url, headers=headers, data=ssml.encode("utf-8"), timeout=120)
    except Exception as e:
        return jsonify({"error": f"TTS request failed: {e}"}), 502

    if resp.status_code != 200:
        detail = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
        return jsonify({"error": f"TTS service returned {resp.status_code}: {detail}"}), 502

    audio_path = os.path.join(BASE_DIR, "podcast.mp3")
    with open(audio_path, "wb") as f:
        f.write(resp.content)
    return send_file(audio_path, mimetype="audio/mpeg", as_attachment=True, download_name="podcast.mp3")


# ── Ambient Listening: Real-time transcription with diarization ──
import azure.cognitiveservices.speech as speechsdk
import json as _json
import base64 as _base64


@sock.route("/api/ambient/ws")
def ambient_ws(ws):
    """WebSocket endpoint for real-time transcription with speaker diarization.

    Browser sends JSON messages:
      {"type": "audio", "data": "<base64 PCM16 24kHz mono>"}
      {"type": "stop"}

    Server sends back:
      {"type": "transcribing", "speaker": "...", "text": "..."}
      {"type": "transcribed",  "speaker": "...", "text": "..."}
      {"type": "stopped"}
      {"type": "error", "message": "..."}
    """
    from simple_websocket import ConnectionClosed

    # Set up push stream (PCM 16-bit, 24 kHz, mono)
    audio_format = speechsdk.audio.AudioStreamFormat(
        samples_per_second=24000, bits_per_sample=16, channels=1,
    )
    push_stream = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
    audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

    # Speech config
    speech_config = speechsdk.SpeechConfig(
        subscription=_SPEECH_KEY,
        endpoint=_SPEECH_ENDPOINT,
    )
    speech_config.speech_recognition_language = "en-US"
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous",
    )

    # Conversation transcriber with diarization
    transcriber = speechsdk.transcription.ConversationTranscriber(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    stop_event = threading.Event()

    def on_transcribing(evt):
        try:
            ws.send(_json.dumps({
                "type": "transcribing",
                "speaker": evt.result.speaker_id or "Unknown",
                "text": evt.result.text,
            }))
        except Exception:
            pass

    def on_transcribed(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            try:
                ws.send(_json.dumps({
                    "type": "transcribed",
                    "speaker": evt.result.speaker_id or "Unknown",
                    "text": evt.result.text,
                }))
            except Exception:
                pass

    def on_canceled(evt):
        if evt.reason == speechsdk.CancellationReason.Error:
            try:
                ws.send(_json.dumps({
                    "type": "error",
                    "message": f"Speech service error: {evt.error_details}",
                }))
            except Exception:
                pass
        stop_event.set()

    def on_session_stopped(evt):
        stop_event.set()

    transcriber.transcribing.connect(on_transcribing)
    transcriber.transcribed.connect(on_transcribed)
    transcriber.canceled.connect(on_canceled)
    transcriber.session_stopped.connect(on_session_stopped)

    transcriber.start_transcribing_async().get()

    try:
        while not stop_event.is_set():
            try:
                raw = ws.receive(timeout=1)
            except ConnectionClosed:
                break
            if raw is None:
                continue
            try:
                msg = _json.loads(raw)
            except Exception:
                continue

            if msg.get("type") == "audio" and msg.get("data"):
                pcm_bytes = _base64.b64decode(msg["data"])
                push_stream.write(pcm_bytes)
            elif msg.get("type") == "stop":
                break
    except Exception:
        pass
    finally:
        push_stream.close()
        transcriber.stop_transcribing_async().get()
        try:
            ws.send(_json.dumps({"type": "stopped"}))
        except Exception:
            pass


if __name__ == "__main__":
    app.run(debug=True, port=5000)
