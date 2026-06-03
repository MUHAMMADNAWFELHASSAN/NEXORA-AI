import os
import json
import datetime
import tempfile
from flask import Flask, request, send_file, jsonify
import google.generativeai as genai
from elevenlabs import generate, set_api_key, clone, voices

# Strip any whitespace/newlines from keys
GEMINI_KEY     = os.environ.get('GEMINI_API_KEY',    'AIzaSyCYLoD9uuFCG5fSU-xabRBtgiI1wQbz-rM').strip()
ELEVENLABS_KEY = os.environ.get('ELEVENLABS_API_KEY','a198689782586550cbaf6bfca6f94326556e800f072f678ecd1d39341668adcd').strip()
DEFAULT_VOICE  = os.environ.get('DEFAULT_VOICE_ID',  'kK8aJj3uYen5Xf3p9rPU').strip()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')
set_api_key(ELEVENLABS_KEY)

app = Flask(__name__)
_voice_id = DEFAULT_VOICE

@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'online', 'service': 'Nexora AI'}), 200

@app.route('/process_audio', methods=['POST'])
@app.route('/process_call',  methods=['POST'])
def process_call():
    caller_text = (request.form.get('spoken_text') or
                   request.form.get('text') or
                   'Hello, I need to speak with you.').strip()
    voice_id = (request.form.get('voice_id') or _voice_id).strip()

    print(f'[Nexora] Caller says: {caller_text}')

    # Gemini 2.5 Flash generates reply
    try:
        prompt = f"""You are Nexora AI, an intelligent voice assistant answering a phone call on behalf of the owner.
The caller said: "{caller_text}"
Reply naturally and professionally in 1-2 sentences maximum.
Be helpful, polite, and sound like a real person."""
        response = model.generate_content(prompt)
        ai_reply = response.text.strip()
        print(f'[Nexora] AI replies: {ai_reply}')
    except Exception as e:
        print(f'[Nexora] Gemini error: {e}')
        ai_reply = 'Thank you for calling. The owner is unavailable right now but will get back to you shortly.'

    # ElevenLabs speaks in cloned voice
    try:
        audio_bytes = generate(
            text  = ai_reply,
            voice = voice_id,
            model = 'eleven_multilingual_v2',
        )
        tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tmp.write(audio_bytes)
        tmp.close()

        # Convert mp3 to wav
        wav_path = tmp.name.replace('.mp3', '.wav')
        ret = os.system(f'ffmpeg -y -i {tmp.name} {wav_path} -loglevel quiet 2>/dev/null')
        if ret != 0:
            wav_path = tmp.name  # use mp3 if ffmpeg fails

        print(f'[Nexora] Audio generated successfully')
        resp = send_file(wav_path, mimetype='audio/wav')
        resp.headers['X-AI-Response'] = ai_reply[:200]
        resp.headers['X-Transcript']  = caller_text[:200]
        return resp

    except Exception as e:
        print(f'[Nexora] ElevenLabs error: {e}')
        return jsonify({
            'success':     True,
            'ai_response': ai_reply,
            'transcript':  caller_text,
            'audio':       False,
            'error':       str(e),
        }), 200

@app.route('/clone_voice_text', methods=['POST'])
def clone_voice_text():
    global _voice_id
    try:
        data      = request.get_json()
        sentences = data.get('sentences', [])
        tone      = data.get('tone', 'Professional')
        name      = data.get('name', 'Nexora Owner').strip()
        print(f'[Nexora] Voice clone request for: {name}')
        # Without real recordings we keep the default voice
        # Real cloning needs audio files — handled by /clone_voice
        return jsonify({
            'success':  True,
            'voice_id': _voice_id,
            'message':  'Using existing voice. Upload audio for real cloning.',
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/clone_voice', methods=['POST'])
def clone_voice():
    global _voice_id
    files = request.files.getlist('recordings')
    name  = request.form.get('name', 'Nexora Owner').strip()
    if not files:
        return jsonify({'success': False, 'error': 'No recordings'}), 400
    try:
        saved = []
        for i, f in enumerate(files):
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            f.save(tmp.name)
            saved.append(tmp.name)
        voice = clone(name=name, description='Nexora voice clone', files=saved)
        _voice_id = voice.voice_id
        print(f'[Nexora] Voice cloned: {_voice_id}')
        for p in saved:
            try: os.unlink(p)
            except: pass
        return jsonify({'success': True, 'voice_id': _voice_id}), 200
    except Exception as e:
        print(f'[Nexora] Clone error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/voices', methods=['GET'])
def get_voices():
    try:
        v = voices()
        return jsonify({'voices': [{'id': x.voice_id, 'name': x.name} for x in v]}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f'[Nexora] Starting on port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)

