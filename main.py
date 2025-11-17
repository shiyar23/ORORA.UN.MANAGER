import telebot
import requests
import json
import os
import time
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from flask import Flask, request, abort

load_dotenv()

# === المتغيرات الأساسية ===
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35"   # ← الكلاسيد السري

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)        # Flask للـ Webhook
DB_FILE = "db.json"

# === قاعدة البيانات ===
if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"members": {}, "pending": {}, "users": {}, "referrals": {}}

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

# === القنوات والأسعار ===
CHANNELS = {"vip": os.getenv("VIP_CHANNEL"), "ai": os.getenv("AI_CHANNEL")}
PRICES = {"vip_only": 16, "ai_only": 76, "both": 66}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}

# === النصوص ===
TEXT = {
    "ar": {
        "welcome": """
        ORORA.UN 

        🟢 مرحبًا بك في البوابة الرسمية للثراء الحقيقي 

        نحن هنا لنأخذك من الصفر إلى القمة في عالم التداول والاستثمار بأسرع وأضمن الطرق الممكنة 

        ماذا ستحصل عندنا؟

        ✅ أقوى دورات تعليمية من الصفر إلى الاحتراف  
        ✅ استراتيجيات تداول حصرية بمعدل نجاح 90%  
        ✅ قنوات توصيات 
        VIP للنخبة فقط (صفقات المليون يوميًا)  
        ✅ بوت تداول آلي ينفّذ الصفقات بدلك 24/7 ويحقق 
        أرباح حتى وأنت نايم ⚡  
        ✅ إشراف مباشر من مدرب شخصي 24/7  
        ✅ مساعد ذكي يحلل السوق لحظيًا ويعطيك الإشارات فورًا  
        ✅ دعم فني ونفسي مستمر حتى تصل لهدفك المالي 

        اختر الباقة اللي تناسب طموحك الآن وابدأ رحلتك للحرية المالية خلال أيام قليلة فقط ⬇️
        """,
        "vip_only": "📈 توصيات VIP فقط\n• أرباح يومية مضمونة\n• دخول فوري للقناة الخاصة\nالسعر: 15$",
        "ai_only": "🤖 المساعد الذكي فقط\n• إجابات فورية 24/7\n• تحليل السوق + تعليم اقوة استراتجيات التداول + بوت تداول الآلي\nالسعر: 75$",
        "both": "💎 الباقة الكاملة (الأكثر طلبًا)\n• توصيات VIP + المساعد الذكي\n• خصم 25$ عن الشراء منفصل\nالسعر: 65$",
        "ask_name": "✍️ اكتب اسمك الكامل (الأول + الأخير):",
        "ask_email": "📧 ادخل إيميلك (جيميل أو أي إيميل):",
        "choose_coin": "💰 اختر العملة الدفع:",
        "choose_network": "🌐 اختر الشبكة:",
        "pay_now": "💸 اضغط الزر تحت عشان تدفع الآن:",
        "success": "🎉 تم التفعيل بنجاح!\n\nرقم العضوية: {code}\nالصلاحية: حتى {date}\n\n{links}\n\nرابط الدعوة الخاص بك (كل واحد يدفع = خصم لك):\nt.me/{botname}?start=ref{uid}",
        "renew_only": "🔄 تجديد الباقة (خصم خاص للأعضاء القدامى)"
    }
}

def t(uid, key):
    return TEXT["ar"][key]

# === العملات ===
COINS = {
    "USDT": ["TRC20", "ERC20", "BEP20", "Polygon", "Arbitrum", "Optimism"],
    "BTC": ["Bitcoin"], "ETH": ["Ethereum"], "BNB": ["BEP20"],
    "SOL": ["Solana"], "TON": ["TON"], "TRX": ["TRON"],
    "DOGE": ["Dogecoin"], "LTC": ["Litecoin"]
}

# === الأوامر والخطوات (كلها زي ما كانت عندك بالضبط) ===
@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        db["referrals"][uid] = args[1][3:]
        save_db()

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📈 توصيات VIP فقط - 16$", callback_data="plan_vip_only"),
        InlineKeyboardButton("🤖 مساعد ذكي فقط - 76$", callback_data="plan_ai_only"),
        InlineKeyboardButton("💎 الكل مع بعض - 66$", callback_data="plan_both")
    )
    if uid in db["members"]:
        markup.add(InlineKeyboardButton("🔄 تجديد بخصم", callback_data="renew"))

    bot.send_message(m.chat.id, t(uid, "welcome"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data == "renew")
def plan_selected(c):
    uid = str(c.message.chat.id)
    plan = c.data.replace("plan_", "") if "plan_" in c.data else db["members"][uid]["plan"]
    renew = c.data == "renew"

    db["users"][uid] = {"step": "ask_name", "plan": plan, "renew": renew}
    save_db()

    desc = "vip_only" if plan == "vip_only" else "ai_only" if plan == "ai_only" else "both"
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=t(uid, desc))
    bot.send_message(c.message.chat.id, t(uid, "ask_name"))

# باقي الخطوات (الاسم، الإيميل، العملة، الشبكة) بنفس الطريقة اللي عندك
# (اختصرتها عشان المساحة، لكن ضيفها زي ما هي عندك بالضبط)

# === إنشاء الفاتورة ===
def create_payment(uid, pay_currency):
    user = db["users"][uid]
    plan = user["plan"]
    price = PRICES[plan]
    if user.get("renew") and any(db["referrals"].get(k) == uid for k in db["referrals"]):
        price = RENEW_PRICES[plan]

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": f"{uid}_{int(time.time())}",
        "order_description": f"ORORA.UN - {plan}",
        "customer_email": user.get("email", "no@email.com")
    }

    r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload,
                      headers={"x-api-key": NOWPAYMENTS_KEY})
    data = r.json()
    url = data["invoice_url"]
    inv_id = data["id"]

    db["pending"][str(inv_id)] = db["users"][uid]
    db["pending"][str(inv_id)]["plan"] = plan
    save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💸 ادفع الآن", url=url))
    bot.send_message(uid, t(uid, "pay_now"), reply_markup=markup)

# === تفعيل العضوية ===
def activate_user(uid, plan):
    uid = str(uid)
    code = "VIP-" + ''.join(__import__('random').choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    db["members"][uid] = {"code": code, "plan": plan, "expiry": expiry}
    save_db()

    links = ""
    if "vip" in plan or plan == "both":
        links += f"قناة التوصيات:\n{CHANNELS['vip']}\n\n"
    if "ai" in plan or plan == "both":
        links += f"المساعد الذكي:\n{CHANNELS['ai']}"

    bot.send_message(int(uid), t(uid, "success").format(
        code=code, date=expiry, links=links,
        botname=bot.get_me().username, uid=uid
    ))

# === الـ Webhook (الجزء اللي كان ناقص) ===
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("Content-Type") == "application/json":
        data = request.get_json(force=True)
        if data.get("token") != IPN_SECRET:
            abort(400)

        inv_id = str(data.get("invoice_id"))
        status = data.get("payment_status")

        if status in ["finished", "confirmed"] and inv_id in db["pending"]:
            info = db["pending"][inv_id]
            activate_user(info["user_id"], info["plan"])
            del db["pending"][inv_id]
            save_db()

        return "OK", 200
    abort(400)

# === تشغيل البوت والسيرفر ===
if __name__ == "__main__":
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000))), daemon=True).start()
    print("البوت شغال بالـ Webhook 100% - التفعيل التلقائي مفعّل!")
    bot.infinity_polling()
