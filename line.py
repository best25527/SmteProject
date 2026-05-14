from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError

import json
import os
import re
from datetime import datetime

# ================= CONFIG =================
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
DATA_FILE = "thaiwater_wl.json"
# =========================================

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    raise RuntimeError("Missing env vars: CHANNEL_ACCESS_TOKEN / CHANNEL_SECRET")

app = Flask(__name__)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


# ---------------- Health Check ----------------
@app.route("/", methods=["GET"])
def home():
    return "Server is running", 200


# ---------------- Data Handling ----------------
def load_station_data():
    if not os.path.exists(DATA_FILE):
        print("❌ DATA FILE NOT FOUND:", DATA_FILE)
        return []

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data

    return []


def normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def normalize_thai_place(s: str) -> str:
    """
    Make matching easier:
    - remove spaces
    - remove common prefixes: ต., ตำบล, อ., อำเภอ, จ., จังหวัด, แขวง, เขต
    - keep Thai letters/numbers
    """
    s = normalize_text(s)
    s = s.replace(" ", "")

    # remove common administrative prefixes
    for p in ["ตำบล", "ต.", "อำเภอ", "อ.", "จังหวัด", "จ.", "แขวง", "เขต"]:
        s = s.replace(p, "")

    return s

def extract_tambon_from_location(location: str) -> str:
    """
    Extract tambon name from 'ต.คลองโคน อ.เมือง... จ....'
    Returns tambon only (e.g., 'คลองโคน') or "" if not found.
    """
    loc = normalize_text(location)

    # match ต.XXXX or ตำบลXXXX up to space or end
    m = re.search(r"(?:ต\.|ตำบล)\s*([^\s]+)", loc)
    if m:
        return m.group(1).strip()

    return ""

def search_station(keyword: str):
    stations = load_station_data()
    kw_raw = normalize_text(keyword)
    if not kw_raw:
        return None

    kw_norm = normalize_thai_place(kw_raw)

    # 1) exact match on tambon name (best behavior for your use case)
    for item in stations:
        tambon = extract_tambon_from_location(item.get("location", ""))
        if tambon and normalize_thai_place(tambon) == kw_norm:
            return item

    # 2) fallback: match anywhere in normalized full location / station name
    for item in stations:
        loc = normalize_thai_place(item.get("location", ""))
        name = normalize_thai_place(item.get("station_name", ""))
        if kw_norm in loc or kw_norm in name:
            return item

    return None


# ---------------- Flex Builder ----------------
def build_station_flex(d: dict):

    status_color = {
        "น้อย": "#43A047",
        "ปกติ": "#1E88E5",
        "มาก": "#FB8C00",
        "ล้นตลิ่ง": "#E53935"
    }.get(d.get("status"), "#757575")

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    rain_today = d.get("water_level", "-")
    dam_level = d.get("bank_level", "-")

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "สถานการณ์น้ำล่าสุด",
                    "weight": "bold",
                    "color": "#2E7D32",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": f"วันที่ {updated_at}",
                    "size": "xs",
                    "color": "#9E9E9E"
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "text",
                    "text": d.get("station_name", "-"),
                    "weight": "bold",
                    "size": "lg",
                    "wrap": True,
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": d.get("location", "-"),
                    "size": "sm",
                    "color": "#616161",
                    "wrap": True
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "ปริมาณฝนวันนี้", "size": "sm", "color": "#555555", "flex": 5},
                        {"type": "text", "text": f"{rain_today} มม.", "size": "sm", "weight": "bold", "flex": 4, "align": "end"}
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "ระดับน้ำในเขื่อน", "size": "sm", "color": "#555555", "flex": 5},
                        {"type": "text", "text": f"{dam_level} %", "size": "sm", "weight": "bold", "flex": 4, "align": "end"}
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "สถานะน้ำ", "size": "sm", "color": "#555555", "flex": 5},
                        {"type": "text", "text": d.get("status", "-"), "size": "sm", "weight": "bold", "color": status_color, "flex": 4, "align": "end"}
                    ]
                },
                {
                    "type": "text",
                    "text": f"อัปเดตข้อมูล: {d.get('update_time','-')}",
                    "size": "xs",
                    "color": "#9E9E9E",
                    "margin": "md",
                    "wrap": True
                }
            ]
        }
    }


# ---------------- Webhook ----------------
@app.route("/callback", methods=["GET", "POST"])
def callback():

    if request.method == "GET":
        return "Callback endpoint ready", 200

    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    print("=== WEBHOOK RECEIVED ===")
    print("Body:", body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature")
        return "Invalid signature", 400
    except Exception as e:
        print("Error:", e)
        return "Error", 500

    return "OK", 200


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    user_text = event.message.text.strip()
    print("User:", user_text)

    result = search_station(user_text)

    if not result:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ ไม่พบสถานีที่ค้นหา")
        )
        return

    flex = build_station_flex(result)

    line_bot_api.reply_message(
        event.reply_token,
        FlexSendMessage(
            alt_text="สถานการณ์น้ำล่าสุด",
            contents=flex
        )
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)