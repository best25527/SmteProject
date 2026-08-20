from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
from linebot.models import QuickReply, QuickReplyButton, MessageAction

import json
import os
import re
from datetime import datetime

user_states = {}

# ================= CONFIG =================
CHANNEL_ACCESS_TOKEN = 'wnsTqaDAsIrH4ji3xwbYDLRk0B/SmOeJ1RSbrStvgnvif+b1yMdRYvvnXJU69LmEfYa27g0OyEj4mEbNxnnDlJdaEaDpLLuDiUVLG/rPhSB3rPfC5uz38kEm4vVyQPx/yTIiJjOWpl7aCZyGeJNHkgdB04t89/1O/w1cDnyilFU='
CHANNEL_SECRET = '8f589c689f6e385203791151355b9ab6'
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
    user_id = event.source.user_id      # ดึง ID ประจำตัวของผู้ใช้
    user_text = event.message.text.strip()
    print(f"User ({user_id}): {user_text}")

    # ดึงสถานะปัจจุบันของผู้ใช้ ถ้าไม่มีให้สถานะเริ่มต้นเป็น 'IDLE'
    current_state = user_states.get(user_id, "IDLE")

    # ================= 1. ดักจับปุ่มเปิดระบบค้นหาจาก Rich Menu =================
    if user_text == "เปิดระบบค้นหาสถานีน้ำ":
        user_states[user_id] = "SEARCHING"  # เปลี่ยนสถานะเป็นกำลังค้นหา
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔍 เปิดระบบค้นหา!\nกรุณาพิมพ์ชื่อสถานีน้ำที่คุณต้องการตรวจสอบ (ค้นหาได้ 1 ครั้ง)")
        )
        return

    # ================= 2. ทำงานเฉพาะตอนที่สถานะเป็น 'SEARCHING' เท่านั้น =================
    if current_state == "SEARCHING":
        result = search_station(user_text)

        if not result:
            # ถ้าพิมพ์ผิด บอทเตือน แต่ยังไม่ปิดระบบค้นหา ให้พิมพ์ใหม่ได้
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ไม่พบสถานีที่ค้นหา กรุณาลองตรวจสอบชื่อสถานีแล้วพิมพ์ใหม่อีกครั้ง")
            )
            return

        # หากค้นหาเจอ -> ดึงข้อมูลสำเร็จ -> ทำการปิดฟังก์ชันทันที (กลับไป IDLE)
        user_states[user_id] = "IDLE"

        flex = build_station_flex(result)
        line_bot_api.reply_message(
            event.reply_token,
            [
                FlexSendMessage(
                    alt_text="สถานการณ์น้ำล่าสุด",
                    contents=flex
                ),
                TextSendMessage(text="✅ ส่งข้อมูลเรียบร้อยและปิดระบบค้นหา\nหากต้องการค้นหาใหม่อีกครั้ง กรุณากดปุ่มเปิดระบบที่เมนูด้านล่าง")
            ]
        )
        return

    # --- ส่วนที่เพิ่มใหม่: สำหรับปุ่มคู่มือ ---
    # ตรงเงื่อนไขเปิดคลังข้อมูล
    if user_text == "เปิดคลังข้อมูลน้ำท่วม":
        user_states[user_id] = "IDLE"
        
        # เพิ่มปุ่มให้ครบ 6 อันตามที่คุณทำใน Auto-response
        quick_reply_buttons = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="แนวทางปฏิบัติขณะน้ำท่วม", text="แนวทางปฏิบัติขณะน้ำท่วม")),
                QuickReplyButton(action=MessageAction(label="แนวทางปฏิบัติหลังน้ำท่วม", text="แนวทางปฏิบัติหลังน้ำท่วม")),
                QuickReplyButton(action=MessageAction(label="แนวทางปฏิบัติก่อนน้ำท่วม", text="แนวทางปฏิบัติก่อนน้ำท่วม")),
                QuickReplyButton(action=MessageAction(label="เบอร์ฉุกเฉิน", text="เบอร์ฉุกเฉิน")), # ตัวอย่างหัวข้อใหม่
                QuickReplyButton(action=MessageAction(label="เช็คลิสต์ของที่เตรียม", text="เช็คลิสต์ของที่เตรียม")),  # ตัวอย่างหัวข้อใหม่
                QuickReplyButton(action=MessageAction(label="โรคที่ควรระวัง", text="โรคที่ควรระวัง"))  # ตัวอย่างหัวข้อใหม่
            ]
        )
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="📚 เลือกหัวข้อคู่มือที่คุณต้องการทราบ (มี 6 หัวข้อ):",
                quick_reply=quick_reply_buttons
            )
        )
        return

    # และอย่าลืมเพิ่มตัวดักจับเพื่อให้ Python ไม่แย่ง LINE OA ตอบ
    if user_text in ["แนวทางปฏิบัติขณะน้ำท่วม", "แนวทางปฏิบัติหลังน้ำท่วม", "แนวทางปฏิบัติก่อนน้ำท่วม", "เบอร์ฉุกเฉิน", "เช็คลิสต์ของที่เตรียม", "โรคที่ควรระวัง"]:
        return
    
    # ================= 5. กรณีที่ผู้ใช้พิมพ์ข้อความอื่น (ต้องอยู่ล่างสุดเสมอ) =================
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="หากต้องการใช้งาน กรุณากดเลือกเมนูจากปุ่มด้านล่าง")
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)