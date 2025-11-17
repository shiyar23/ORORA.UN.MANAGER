import telebot
import random
import string
import json
import os
import requests
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import time

# جايب الكل من المتغيرات البيئية (Railway)
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")

bot = telebot.TeleBot(TOKEN)
DB_FILE = "db.json"

# تحميل قاعدة البيانات
if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"members": {}, "lang": {}, "referrals": {}, "pending": {}}

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

# روابط القنوات من المتغيرات
CHANNELS = {
    "vip": os.getenv("VIP_CHANNEL"),
    "ai": os.getenv("AI_CHANNEL")
}

PRICES = {"vip_only": 15, "ai_only": 75, "both": 65}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}

TEXT = {
    "ar": {"welcome": "🔥 مرحبًا بك في أقوى بوت VIP!\nاختر باقتك:", "vip_only": "📈 توصيات VIP فقط - 15$", "ai_only": "🤖 مساعد ذكي فقط - 75$", "both": "💎 الكل - 65$", "renew": "🔄 تجديد (خصم)", "activated": "تم التفعيل بنجاح! 🎉", "referral": "شارك رابطك وحصل 7 أيام مجانًا:\n"},
    "en": {"welcome": "🔥 Welcome to the strongest VIP bot!\nChoose plan:", "vip_only": "📈 VIP Signals - 15$", "ai_only": "🤖 AI Assistant - 75$", "both": "💎 All - 65$", "renew": "🔄 Renew (Discount)", "activated": "Activated successfully! 🎉", "referral": "Share & get 7 free days:\n"}
}

def t(uid, key):
    return TEXT[db["lang"].get(str(uid), "ar")][key]

# /start + اختيار اللغة + رفرال
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.chat.id
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        db["referrals"][str(uid)] = args[1][3:]
        save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("العربية", callback_data="lang_ar"), InlineKeyboardButton("English", callback_data="lang_en"))
    bot.send_message(uid, "🌍 اختر لغتك / Choose language", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data in ["lang_ar", "lang_en"])
def set_lang(c):
    db["lang"][str(c.message.chat.id)] = c.data.split("_")[1]
    save_db()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(t(c.message.chat.id, "vip_only"), callback_data="plan_vip_only"),
        InlineKeyboardButton(t(c.message.chat.id, "ai_only"), callback_data="plan_ai_only"),
        InlineKeyboardButton(t(c.message.chat.id, "both"), callback_data="plan_both"),
        InlineKeyboardButton(t(c.message.chat.id, "renew"), callback_data="renew")
    )
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=t(c.message.chat.id, "welcome"), reply_markup=markup)

# إنشاء فاتورة تلقائية
def create_invoice(uid, plan, renew=False):
    price = RENEW_PRICES.get(plan, PRICES[plan]) if renew else PRICES[plan]
    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": "usdttrc20",
        "order_id": f"{uid}_{int(time.time())}",
        "order_description": f"VIP {plan}",
        "success_url": f"https://t.me/{bot.get_me().username}"
    }
    try:
        r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers={"x-api-key": NOWPAYMENTS_KEY})
        data = r.json()
        url = data["invoice_url"]
        inv_id = data["id"]
        db["pending"][inv_id] = {"user_id": uid, "plan": plan}
        save_db()

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💸 ادفع الآن - Pay Now", url=url))
        bot.send_message(uid, f"💰 المبلغ: {price} USD\nاضغط الزر للدفع الفوري:", reply_markup=markup)
    except:
        bot.send_message(uid, "خطأ مؤقت، جرب تاني بعد دقيقة")

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data == "renew")
def plan_selected(c):
    uid = c.message.chat.id
    plan = c.data.replace("plan_", "") if "plan_" in c.data else db["members"].get(str(uid), {}).get("plan", "both")
    create_invoice(uid, plan, c.data == "renew")

# فحص الدفعات كل 15 ثانية
def check_payments():
    while True:
        for inv_id, info in list(db["pending"].items()):
            try:
                r = requests.get(f"https://api.nowpayments.io/v1/invoice/{inv_id}", headers={"x-api-key": NOWPAYMENTS_KEY})
                if r.json().get("invoice_status") == "paid":
                    activate_member(info["user_id"], info["plan"])
                    del db["pending"][inv_id]
                    save_db()
            except: pass
        time.sleep(15)

def activate_member(uid, plan):
    membership = "VIP-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    db["members"][str(uid)] = {"membership": membership, "plan": plan, "expiry": expiry}
    save_db()

    # رفرال: 7 أيام مجانًا للي جابه
    ref = db["referrals"].get(str(uid))
    if ref and ref in db["members"]:
        old = datetime.strptime(db["members"][ref]["expiry"], "%Y-%m-%d")
        db["members"][ref]["expiry"] = (old + timedelta(days=7)).strftime("%Y-%m-%d")
        save_db()
        bot.send_message(int(ref), "🎉 حصلت على 7 أيام مجانًا بسبب رفرال جديد!")

    links = f"قناة التوصيات:\n{CHANNELS['vip']}\n\n" if "vip" in plan or plan == "both" else ""
    links += f"المساعد الذكي:\n{CHANNELS['ai']}" if "ai" in plan or plan == "both" else ""

    bot.send_message(uid, f"""
{t(uid, "activated")}

رقم العضوية: `{membership}`
الصلاحية: حتى {expiry}

{links}

{t(uid, "referral")}t.me/{bot.get_me().username}?start=ref{uid}
    """, parse_mode="Markdown")

# تشغيل الفحص التلقائي
threading.Thread(target=check_payments, daemon=True).start()

print("البوت شغال 100% - دفع تلقائي + رفرال + لغتين")
bot.infinity_polling()
