"""
NEXORA AI - PERMANENT BACKEND SERVER
=====================================
Deploy this to Railway.app (free, always online, fixed URL).
No Colab needed. Owner never touches anything.

HOW IT WORKS:
  1. Flutter app sends caller text to /process_call
  2. Gemini 2.5 Flash generates a smart reply
  3. ElevenLabs speaks the reply in the owner's cloned voice
  4. WAV audio + transcript sent back to Flutter app
  5. App plays audio + shows transcript on screen

VOICE CLONING:
  - Owner records 10 sentences in Voice Clone screen
  - App sends recordings to /clone_voice
  - ElevenLabs creates a permanent voice clone
  - Voice ID saved to Firestore
  - All future calls use this cloned voice automatically
"""

import os
import json
import datetime
import tempfile
from flask import Flask, request, send_file, jsonify
import google.generativeai as genai
from elevenlabs import generate, set_api_key, clone, voices

# ─── API KEYS (set as environment variables on Railway) ───
GEMINI_KEY    = os.environ.get('GEMINI_API_KEY',    'AIzaSyCYLoD9uuFCG5fSU-xabRBtgiI1wQbz-rM')
ELEVENLABS_KEY= os.environ.get('ELEVENLABS_API_KEY','a198689782586550cbaf6bfca6f94326556e800f072f678ecd1d39341668adcd')

# Default voice (Mehboob's cloned voice from your Colab)
# This gets replaced when owner completes Voice Clone in the app
DEFAULT_VOICE_ID = os.environ.get('DEFAULT_VOICE_ID', 'kK8aJj3uYen5Xf3p9rPU')

# ─── SETUP ─────────────────────────────────────────────────
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')
set_api_key(ELEVENLABS_KEY)

app = Flask(__name__)

# Store active voice ID in memory (loaded from request or default)
_voice_id = DEFAULT_VOICE_ID

# ═══════════════════════════════════════════════════════════
# HEALTH CHECK - Flutter app pings this to check if online
# ═══════════════════════════════════════════════════════════
@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'online', 'service': 'Nexora AI'}), 200

# ═══════════════════════════════════════════════════════════
# PROCESS CALL
# Flutter sends: spoken_text (what caller said)
# Returns: WAV audio (ElevenLabs voice) + JSON transcript
# ═══════════════════════════════════════════════════════════
@app.route('/process_audio', methods=['POST'])
@app.route('/process_call',  methods=['POST'])
def process_call():
    # Get caller's spoken text
    caller_text = request.form.get('spoken_text', '') or \
                  request.form.get('text', '') or \
                  'Hello, I need to speak with you.'

    # Get voice ID from request (set after voice clone) or use default
    voice_id = request.form.get('voice_id', _voice_id)

    print(f'[Nexora] Caller says: {caller_text}')

    # ── Step 1: Gemini 2.5 Flash thinks ───────────────────
    try:
        prompt = f"""You are Nexora AI, an intelligent voice assistant answering a phone call on behalf of the owner.

The caller said: "{caller_text}"

Reply naturally and professionally. Keep it to 1-2 sentences maximum.
Be helpful, polite, and sound like a real person — not a robot.
If it sounds urgent or emergency, acknowledge it and say the owner will be contacted immediately."""

        response = model.generate_content(prompt)
        ai_reply = response.text.strip()
        print(f'[Nexora] AI replies: {ai_reply}')

    except Exception as e:
        print(f'[Nexora] Gemini error: {e}')
        ai_reply = 'Thank you for calling. The owner is unavailable right now but will get back to you shortly.'

    # ── Step 2: ElevenLabs speaks in cloned voice ──────────
    try:
        audio_bytes = generate(
            text  = ai_reply,
            voice = voice_id,
            model = 'eleven_multilingual_v2',
        )

        # Save to temp file and send
        tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tmp.write(audio_bytes)
        tmp.close()

        # Convert to WAV for Android compatibility
        wav_path = tmp.name.replace('.mp3', '.wav')
        os.system(f'ffmpeg -y -i {tmp.name} {wav_path} -loglevel quiet 2>/dev/null || cp {tmp.name} {wav_path}')

        print(f'[Nexora] Voice generated successfully')

        # Send WAV back to Flutter app
        response_obj = send_file(
            wav_path,
            mimetype   = 'audio/wav',
            as_attachment = False,
        )
        # Include transcript in headers so Flutter can read it
        response_obj.headers['X-AI-Response']  = ai_reply[:200]
        response_obj.headers['X-Transcript']   = caller_text[:200]
        response_obj.headers['X-Voice-ID']     = voice_id
        return response_obj

    except Exception as e:
        print(f'[Nexora] ElevenLabs error: {e}')
        # Return JSON with just text if audio fails
        return jsonify({
            'success':     True,
            'ai_response': ai_reply,
            'transcript':  caller_text,
            'audio':       False,
            'error':       str(e),
        }), 200

# ═══════════════════════════════════════════════════════════
# CLONE VOICE
# Flutter sends: multiple WAV recordings from Voice Clone screen
# Returns: voice_id (permanent ElevenLabs voice clone)
# ═══════════════════════════════════════════════════════════
@app.route('/clone_voice', methods=['POST'])
def clone_voice():
    global _voice_id

    files = request.files.getlist('recordings')
    name  = request.form.get('name', 'Nexora Owner Voice')

    if not files:
        return jsonify({'success': False, 'error': 'No recordings received'}), 400

    print(f'[Nexora] Cloning voice with {len(files)} recordings...')

    try:
        # Save uploaded recordings to temp files
        saved_paths = []
        for i, f in enumerate(files):
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            f.save(tmp.name)
            saved_paths.append(tmp.name)

        # Create voice clone on ElevenLabs
        voice = clone(
            name        = name,
            description = 'Nexora AI owner voice clone',
            files       = saved_paths,
        )

        # Save this as the new default voice
        _voice_id = voice.voice_id
        print(f'[Nexora] Voice cloned! ID: {_voice_id}')

        # Clean up temp files
        for p in saved_paths:
            try: os.unlink(p)
            except: pass

        return jsonify({
            'success':  True,
            'voice_id': _voice_id,
            'name':     name,
        }), 200

    except Exception as e:
        print(f'[Nexora] Clone error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════
# GET VOICES - List all available voices
# ═══════════════════════════════════════════════════════════
@app.route('/voices', methods=['GET'])
def get_voices():
    try:
        v = voices()
        return jsonify({'voices': [{'id': x.voice_id, 'name': x.name} for x in v]}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    print(f'[Nexora] Server starting on port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
