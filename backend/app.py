from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import wave
import subprocess
import paho.mqtt.publish as publish
from vosk import Model, KaldiRecognizer

# -------------------- FLASK SETUP -------------------- #
app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -------------------- MQTT TOPICS -------------------- #
BROKER = "broker.hivemq.com"

MQTT_TOPICS = {
    "bedroom_led": "home/led/bedroom",
    "livingroom_led": "home/led/livingroom",
    "kitchen_led": "home/led/kitchen",
    "door": "home/door"
}

def mqtt_send(message, device_key):
    topic = MQTT_TOPICS.get(device_key)
    if topic:
        publish.single(topic, message, hostname=BROKER)
        print(f"📡 MQTT Sent: {message} to topic {topic}")
    else:
        print(f"❌ Unknown device key: {device_key}")

# -------------------- LOAD VOSK MODEL -------------------- #
MODEL_PATH = "vosk-model-small-en-us-0.15"

if not os.path.exists(MODEL_PATH):
    print("❌ Vosk model not found!")
    exit()

model = Model(MODEL_PATH)
print("✅ Vosk model loaded")

# -------------------- AUDIO CONVERSION -------------------- #
def convert_to_wav(input_file, output_file):
    command = [
        "ffmpeg",
        "-y",
        "-i", input_file,
        "-ar", "16000",
        "-ac", "1",
        output_file
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# -------------------- SPEECH ENDPOINT -------------------- #
@app.route("/speech", methods=["POST"])
def speech_to_text():
    if "file" not in request.files:
        return jsonify({"error": "No audio file received"}), 400

    file = request.files["file"]
    input_path = os.path.join(UPLOAD_FOLDER, "input_audio")
    wav_path = os.path.join(UPLOAD_FOLDER, "converted.wav")

    file.save(input_path)

    # Convert audio to 16kHz mono WAV
    convert_to_wav(input_path, wav_path)

    wf = wave.open(wav_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())

    recognized_text = ""

    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            recognized_text += " " + result.get("text", "")

    final_result = json.loads(rec.FinalResult())
    recognized_text += " " + final_result.get("text", "")
    recognized_text = recognized_text.strip()

    print("🗣 Recognized:", recognized_text)

    # ---------------- COMMAND LOGIC ---------------- #
    cmd = recognized_text.lower()
    response_text = recognized_text

    # Device keywords mapping
    devices = {
        "bedroom": "bedroom_led",
        "living room": "livingroom_led",
        "kitchen": "kitchen_led",
        "door": "door"
    }

    for keyword, device_key in devices.items():
        if keyword in cmd:
            # Door uses OPEN/CLOSE, others use ON/OFF
            if device_key == "door":
                if "open" in cmd:
                    mqtt_send("OPEN", device_key)
                    response_text = f"{keyword.capitalize()} OPENED"
                elif "close" in cmd:
                    mqtt_send("CLOSE", device_key)
                    response_text = f"{keyword.capitalize()} CLOSED"
            else:  # LEDs and fan
                if "on" in cmd:
                    mqtt_send("ON", device_key)
                    response_text = f"{keyword.capitalize()} turned ON"
                elif "off" in cmd:
                    mqtt_send("OFF", device_key)
                    response_text = f"{keyword.capitalize()} turned OFF"
            break  # Control only one device at a time

    return jsonify({"text": response_text})

# -------------------- RUN SERVER -------------------- #
if __name__ == "__main__":
    print("\n🚀 Backend running on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
