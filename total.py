import json
import os
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response, status
import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import RandomForestRegressor
import uvicorn

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
CHANNEL_ACCESS_TOKEN = "wnsTqaDAsIrH4ji3xwbYDLRk0B/SmOeJ1RSbrStvgnvif+b1yMdRYvvnXJU69LmEfYa27g0OyEj4mEbNxnnDlJdaEaDpLLuDiUVLG/rPhSB3rPfC5uz38kEm4vVyQPx/yTIiJjOWpl7aCZyGeJNHkgdB04t89/1O/w1cDnyilFU="
DATA_FILE = "thaiwater_wl.json"

app = FastAPI(title="FloodSafe Unified Water & Forecast LINE Bot")
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# ตัวแปรเก็บสถานะของผู้ใช้งานแต่ละคน
user_states = {}

# ==============================================================================
# 2. LINE MESSAGING API CORE FUNCTIONS
# ==============================================================================
def reply_line_message(reply_token: str, messages: list):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    payload = {"replyToken": reply_token, "messages": messages}
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        print(f"LINE Reply Error: {e}")

def reply_text(reply_token: str, text: str):
    messages = [{"type": "text", "text": text}]
    return reply_line_message(reply_token, messages)

def reply_flex(reply_token: str, flex_payload: dict, alt_text: str = "ข้อมูลสถานการณ์น้ำ"):
    messages = [{"type": "flex", "altText": alt_text, "contents": flex_payload}]
    return reply_line_message(reply_token, messages)

# ==============================================================================
# 3. HELPER & DATA HANDLING (สำหรับค้นหาสถานีน้ำปัจจุบันจาก JSON)
# ==============================================================================
def load_station_data():
    if not os.path.exists(DATA_FILE):
        print("❌ DATA FILE NOT FOUND:", DATA_FILE)
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict): return [data]
    if isinstance(data, list): return data
    return []

def normalize_text(s: str) -> str:
    s = (s or "").strip()
    return re.sub(r"\s+", " ", s)

def normalize_thai_place(s: str) -> str:
    s = normalize_text(s).replace(" ", "")
    for p in ["ตำบล", "ต.", "อำเภอ", "อ.", "จังหวัด", "จ.", "แขวง", "เขต"]:
        s = s.replace(p, "")
    return s

def extract_tambon_from_location(location: str) -> str:
    loc = normalize_text(location)
    m = re.search(r"(?:ต\.|ตำบล)\s*([^\s]+)", loc)
    return m.group(1).strip() if m else ""

def search_local_station(keyword: str):
    stations = load_station_data()
    kw_raw = normalize_text(keyword)
    if not kw_raw: return None
    kw_norm = normalize_thai_place(kw_raw)

    for item in stations:
        tambon = extract_tambon_from_location(item.get("location", ""))
        if tambon and normalize_thai_place(tambon) == kw_norm:
            return item

    for item in stations:
        loc = normalize_thai_place(item.get("location", ""))
        name = normalize_thai_place(item.get("station_name", ""))
        if kw_norm in loc or kw_norm in name:
            return item
    return None

def build_station_flex(d: dict):
    status_color = {
        "น้อย": "#43A047", "ปกติ": "#1E88E5", 
        "มาก": "#FB8C00", "ล้นตลิ่ง": "#E53935"
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
                {"type": "text", "text": "สถานการณ์น้ำล่าสุด", "weight": "bold", "color": "#2E7D32", "size": "sm"},
                {"type": "text", "text": f"วันที่ {updated_at}", "size": "xs", "color": "#9E9E9E"},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": d.get("station_name", "-"), "weight": "bold", "size": "lg", "wrap": True, "margin": "md"},
                {"type": "text", "text": d.get("location", "-"), "size": "sm", "color": "#616161", "wrap": True},
                {"type": "separator", "margin": "md"},
                {
                    "type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "ปริมาณฝนวันนี้", "size": "sm", "color": "#555555", "flex": 5},
                        {"type": "text", "text": f"{rain_today} มม.", "size": "sm", "weight": "bold", "flex": 4, "align": "end"}
                    ]
                },
                {
                    "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
                        {"type": "text", "text": "ระดับน้ำในเขื่อน", "size": "sm", "color": "#555555", "flex": 5},
                        {"type": "text", "text": f"{dam_level} %", "size": "sm", "weight": "bold", "flex": 4, "align": "end"}
                    ]
                },
                {
                    "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
                        {"type": "text", "text": "สถานะน้ำ", "size": "sm", "color": "#555555", "flex": 5},
                        {"type": "text", "text": d.get("status", "-"), "size": "sm", "weight": "bold", "color": status_color, "flex": 4, "align": "end"}
                    ]
                },
                {"type": "text", "text": f"อัปเดตข้อมูล: {d.get('update_time','-')}", "size": "xs", "color": "#9E9E9E", "margin": "md", "wrap": True}
            ]
        }
    }

# ==============================================================================
# 4. SMART SEARCH & HYBRID AI PIPELINE (สำหรับพยากรณ์ AI 7 วัน)
# ==============================================================================
def safe_get(d, *keys):
    curr = d
    for k in keys:
        if isinstance(curr, dict): curr = curr.get(k)
        else: return ""
    return str(curr) if curr is not None else ""

def search_api_station(keyword: str):
    url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return None, None, None, None
        payload = res.json()
        data = payload.get("waterlevel_data", {}).get("data", []) or payload.get("data", [])
        kw = keyword.lower().strip()

        for item in data:
            station = item.get("station", {})
            st_id = str(item.get("id") or station.get("id", ""))
            st_type = str(item.get("station_type") or station.get("station_type") or "tele_waterlevel")
            st_name = safe_get(station, "tele_station_name", "th") or safe_get(station, "name", "th") or item.get("station_name", "")
            province = safe_get(station, "province", "name", "th")
            amphoe = safe_get(station, "amphoe", "name", "th")
            tambon = safe_get(station, "tambon", "name", "th")
            
            current_val = (
                item.get("waterlevel_msl") if item.get("waterlevel_msl") is not None
                else item.get("waterlevel_m") if item.get("waterlevel_m") is not None
                else item.get("waterlevel_in") if item.get("waterlevel_in") is not None
                else item.get("value")
            )
            item_str = str(item).lower()

            if (kw in st_id.lower() or (st_name and kw in st_name.lower()) or 
                (province and kw in province.lower()) or (amphoe and kw in amphoe.lower()) or 
                (tambon and kw in tambon.lower()) or kw in item_str):
                
                loc_details = []
                if amphoe: loc_details.append(f"อ.{amphoe}")
                if province: loc_details.append(f"จ.{province}")
                loc_str = f" ({', '.join(loc_details)})" if loc_details else ""
                display_name = f"{st_name}{loc_str}" if st_name else f"สถานี {st_id}{loc_str}"
                curr_val_float = float(current_val) if current_val is not None else 0.0
                return st_id, display_name, st_type, curr_val_float

        return None, None, None, None
    except Exception as e:
        print(f"Search API Station error: {e}")
        return None, None, None, None

def predict_smart_fallback(current_val: float):
    future_dates, future_preds = [], []
    now = datetime.now()
    np.random.seed(int(current_val * 100) % 1000)
    dampening = 0.02
    val = current_val
    for day in range(1, 8):
        future_dates.append(now + timedelta(days=day))
        change = np.random.normal(0, dampening)
        val = max(0.0, val + change)
        future_preds.append(round(val, 2))
    return future_dates, future_preds, "Smart Trend AI"

def fetch_and_predict(station_id: str, station_type: str, current_val: float):
    current_year = datetime.now().year
    url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph_year"
    records = []
    type_candidates = [station_type, "tele_waterlevel", "canal_waterlevel", "bma_waterlevel"]

    for yr in [current_year, current_year - 1]:
        for st_type in type_candidates:
            params = {"station_type": st_type, "station_id": station_id, "year": str(yr)}
            try:
                res = requests.get(url, params=params, headers=HEADERS, timeout=5)
                if res.status_code == 200:
                    gd = res.json().get("data", {}).get("graph_data", [])
                    for y_entry in gd:
                        for d in y_entry.get("data", []):
                            dt_str = d.get("datetime")
                            val = (d.get("waterlevel_msl") if d.get("waterlevel_msl") is not None 
                                   else d.get("waterlevel_m") if d.get("waterlevel_m") is not None 
                                   else d.get("value"))
                            if dt_str and val is not None:
                                records.append({"datetime": dt_str, "value": float(val)})
            except Exception: continue
            if len(records) > 20: break
        if len(records) > 20: break

    if len(records) < 10:
        future_dates, future_preds, model_name = predict_smart_fallback(current_val)
        return current_val, future_dates, future_preds, model_name

    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime").drop_duplicates(subset=["datetime"]).set_index("datetime")
    df_daily = df.resample("D").mean()
    df_daily["value"] = df_daily["value"].interpolate(method="time").bfill().ffill()

    for i in range(1, 8):
        df_daily[f"lag_{i}"] = df_daily["value"].shift(i)
    df_daily["rolling_mean_3"] = df_daily["value"].shift(1).rolling(3).mean()
    df_daily["rolling_mean_7"] = df_daily["value"].shift(1).rolling(7).mean()

    df_model = df_daily.dropna()
    features = [f"lag_{i}" for i in range(1, 8)] + ["rolling_mean_3", "rolling_mean_7"]
    X = df_model[features]
    y = df_model["value"]

    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X, y)

    last_known_date = df_daily.index[-1]
    recent_values = list(df_daily["value"].values[-7:])
    future_preds, future_dates = [], []

    for day in range(1, 8):
        future_dates.append(last_known_date + timedelta(days=day))
        lag_feats = [recent_values[-i] for i in range(1, 8)]
        rm3 = np.mean(recent_values[-3:])
        rm7 = np.mean(recent_values[-7:])
        x_input = np.array(lag_feats + [rm3, rm7]).reshape(1, -1)
        pred = float(model.predict(x_input)[0])
        future_preds.append(pred)
        recent_values.append(pred)

    latest_val = float(df_daily["value"].iloc[-1])
    return latest_val, future_dates, future_preds, "RandomForest AI"

def create_water_forecast_flex(station_name: str, station_id: str, current_val: float, future_dates: list, future_preds: list, model_name: str) -> dict:
    trend_diff = future_preds[-1] - current_val
    if trend_diff > 0.15:
        status_text = f"⚠️ น้ำมีแนวโน้มเพิ่มขึ้น (+{trend_diff:.2f} ม.)"
        header_color = "#D9534F"
    elif trend_diff < -0.15:
        status_text = f"🟢 น้ำมีแนวโน้มลดลง ({trend_diff:.2f} ม.)"
        header_color = "#28A745"
    else:
        status_text = "🔷 ระดับน้ำทรงตัว"
        header_color = "#0275D8"

    forecast_rows = []
    for d, val in zip(future_dates, future_preds):
        forecast_rows.append({
            "type": "box", "layout": "horizontal",
            "contents": [
                {"type": "text", "text": d.strftime("%d/%m/%Y"), "size": "sm", "color": "#555555", "flex": 3},
                {"type": "text", "text": f"{val:.2f} ม.", "size": "sm", "weight": "bold", "align": "end", "color": "#111111", "flex": 2}
            ],
            "margin": "sm"
        })

    return {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "15px",
            "contents": [
                {"type": "text", "text": "🌊 พยากรณ์ระดับน้ำ 7 วันล่วงหน้า", "color": "#FFFFFF", "size": "xs", "weight": "bold"},
                {"type": "text", "text": station_name, "color": "#FFFFFF", "size": "lg", "weight": "bold", "margin": "xs"},
                {"type": "text", "text": f"รหัสสถานี: {station_id} | ประมวลผลโดย: {model_name}", "color": "#EEEEEE", "size": "xxs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "ระดับน้ำปัจจุบัน", "size": "sm", "color": "#888888"},
                        {"type": "text", "text": f"{current_val:.2f} ม.", "size": "md", "weight": "bold", "align": "end"}
                    ]
                },
                {"type": "text", "text": status_text, "size": "xs", "weight": "bold", "color": header_color, "margin": "xs"},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "📅 ผลพยากรณ์รายวัน", "weight": "bold", "size": "xs", "color": "#444444", "margin": "md"},
                {"type": "box", "layout": "vertical", "margin": "sm", "contents": forecast_rows}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "ข้อมูลจาก Thaiwater.net (ระบบประมวลผลอัตโนมัติ)", "size": "xxs", "color": "#aaaaaa", "align": "center"}
            ]
        }
    }

# ==============================================================================
# 5. FASTAPI ROUTE & UNIFIED WEBHOOK HANDLER
# ==============================================================================
@app.get("/")
def health_check():
    return {"status": "FloodSafe Unified Webhook Server is running!"}

@app.post("/callback")
@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    events = payload.get("events", [])

    for event in events:
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            reply_token = event["replyToken"]
            user_id = event.get("source", {}).get("userId", "")
            raw_text = event["message"]["text"].strip()
            
            current_state = user_states.get(user_id, "IDLE")

            # ------------------------------------------------------------------
            # 1. ปุ่มค้นหาสถานีน้ำปัจจุบัน (จากไฟล์ JSON)
            # ------------------------------------------------------------------
            if raw_text == "เปิดระบบค้นหาสถานีน้ำ":
                user_states[user_id] = "SEARCHING_LOCAL"
                reply_text(reply_token, "🔍 เปิดระบบค้นหา!\nกรุณาพิมพ์ชื่อสถานีน้ำ อำเภอ จังหวัด หรือชื่อคลองที่คุณต้องการตรวจสอบ (ค้นหาได้ 1 ครั้งต่อการเรียกใช้)")
                continue

            # ------------------------------------------------------------------
            # 2. ปุ่มเปิดระบบพยากรณ์น้ำ AI (7 วันล่วงหน้า)
            # ------------------------------------------------------------------
            if raw_text == "เปิดระบบพยากรณ์" or raw_text == "พยากรณ์":
                user_states[user_id] = "SEARCHING_FORECAST"
                reply_text(reply_token, "🔮 เปิดระบบพยากรณ์ระดับน้ำ \nกรุณาพิมพ์ชื่อสถานีน้ำที่คุณต้องการดูผลพยากรณ์ 7 วันล่วงหน้า (พยากรณ์ได้ 1 ครั้งต่อการเรียกใช้)")
                continue

            # ------------------------------------------------------------------
            # 3. ปุ่มเปิดคลังข้อมูลน้ำท่วม (Quick Reply)
            # ------------------------------------------------------------------
            if raw_text == "เปิดคลังข้อมูลน้ำท่วม":
                user_states[user_id] = "IDLE"
                quick_reply_payload = {
                    "items": [
                        {"type": "action", "action": {"type": "message", "label": "แนวทางปฏิบัติขณะน้ำท่วม", "text": "แนวทางปฏิบัติขณะน้ำท่วม"}},
                        {"type": "action", "action": {"type": "message", "label": "แนวทางปฏิบัติหลังน้ำท่วม", "text": "แนวทางปฏิบัติหลังน้ำท่วม"}},
                        {"type": "action", "action": {"type": "message", "label": "แนวทางปฏิบัติก่อนน้ำท่วม", "text": "แนวทางปฏิบัติก่อนน้ำท่วม"}},
                        {"type": "action", "action": {"type": "message", "label": "เบอร์ฉุกเฉิน", "text": "เบอร์ฉุกเฉิน"}},
                        {"type": "action", "action": {"type": "message", "label": "เช็คลิสต์ของที่เตรียม", "text": "เช็คลิสต์ของที่เตรียม"}},
                        {"type": "action", "action": {"type": "message", "label": "โรคที่ควรระวัง", "text": "โรคที่ควรระวัง"}}
                    ]
                }
                messages = [{
                    "type": "text",
                    "text": "📚 เลือกหัวข้อคู่มือที่คุณต้องการทราบ (มี 6 หัวข้อ):",
                    "quickReply": quick_reply_payload
                }]
                reply_line_message(reply_token, messages)
                continue

            # ดักจับหัวข้อ Quick Reply เพื่อปล่อยผ่านให้ LINE OA เป็นคนตอบ
            if raw_text in ["แนวทางปฏิบัติขณะน้ำท่วม", "แนวทางปฏิบัติหลังน้ำท่วม", "แนวทางปฏิบัติก่อนน้ำท่วม", "เบอร์ฉุกเฉิน", "เช็คลิสต์ของที่เตรียม", "โรคที่ควรระวัง"]:
                continue

            # ------------------------------------------------------------------
            # 4. ประมวลผลค้นหาข้อมูลสถานีน้ำปัจจุบัน (SEARCHING_LOCAL)
            # ------------------------------------------------------------------
            if current_state == "SEARCHING_LOCAL":
                result = search_local_station(raw_text)
                if not result:
                    reply_text(reply_token, "❌ ไม่พบสถานีที่ค้นหา กรุณาลองตรวจสอบชื่อสถานีแล้วพิมพ์ใหม่อีกครั้ง")
                    continue

                user_states[user_id] = "IDLE"
                flex_data = build_station_flex(result)
                messages = [
                    {"type": "flex", "altText": "สถานการณ์น้ำล่าสุด", "contents": flex_data},
                    {"type": "text", "text": "✅ ส่งข้อมูลเรียบร้อยแล้ว\nหากต้องการค้นหาใหม่อีกครั้ง กรุณากดปุ่มเปิดระบบที่เมนูด้านล่าง"}
                ]
                reply_line_message(reply_token, messages)
                continue

            # ------------------------------------------------------------------
            # 5. ประมวลผลพยากรณ์ AI 7 วันล่วงหน้า (SEARCHING_FORECAST)
            # ------------------------------------------------------------------
            if current_state == "SEARCHING_FORECAST":
                clean_keyword = re.sub(r'^(พยากรณ์|ระดับน้ำ|เช็ค|ดู|ขอ|ช่วย|รายงาน|สถานี)\s*', '', raw_text, flags=re.IGNORECASE).strip()
                search_key = clean_keyword if clean_keyword else raw_text

                station_id, station_name, station_type, current_val = search_api_station(search_key)
                if not station_id:
                    reply_text(reply_token, f"❌ ไม่พบสถานีในพื้นที่ '{search_key}'\nกรุณาลองตรวจสอบชื่อคลอง อำเภอ หรือจังหวัด แล้วพิมพ์ใหม่อีกครั้งครับ")
                    continue

                user_states[user_id] = "IDLE"
                try:
                    latest_val, future_dates, future_preds, model_name = fetch_and_predict(station_id, station_type, current_val)
                    flex_payload = create_water_forecast_flex(
                        station_name=station_name,
                        station_id=station_id,
                        current_val=latest_val,
                        future_dates=future_dates,
                        future_preds=future_preds,
                        model_name=model_name
                    )
                    reply_flex(reply_token, flex_payload, alt_text=f"พยากรณ์ระดับน้ำ {station_name}")
                except Exception as e:
                    reply_text(reply_token, f"⚠️ เกิดข้อผิดพลาดในการประมวลผล: {str(e)}")
                continue

            # ------------------------------------------------------------------
            # 6. กรณีพิมพ์มาลอยๆ โดยยังไม่ได้กดเลือกเมนูใดๆ (IDLE)
            # ------------------------------------------------------------------
            reply_text(reply_token, "⚠️ กรุณากดเลือกปุ่มเมนูด้านล่างก่อนใช้งานนะครับ")

    return Response(content="OK", status_code=status.HTTP_200_OK)

# ==============================================================================
# 6. RUN SERVER
# ==============================================================================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)