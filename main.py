import telebot
import requests
import json
import os
import time
import hmac
import hashlib
import random
import re
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from flask import Flask, request, abort

load_dotenv()

# === المتغيرات ===
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = os.getenv("IPN_SECRET", "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35")  # ضع الـ IPN secret الصحيح في .env
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")  # مثال: https://yourapp.example.com  (مهم!)

if not TOKEN:
    raise RuntimeError("BOT_TOKEN غير معرّف في .env")
if not NOWPAYMENTS_KEY:
    raise RuntimeError("NOWPAYMENTS_KEY غير معرّف في .env")
if not WEBHOOK_BASE:
    # مجرد تحذير — لكن إنشاء الفاتورة سيفشل لو لم يكن لديك رابط Webhook فعّال
    print("تحذير: WEBHOOK_BASE غير معرّف. اضبطه في .env (مثال: https://yourapp.example.com)")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
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
CHANNELS = {"vip": os.getenv("VIP_CHANNEL", "t.me/your_vip_channel"), "ai": os.getenv("AI_CHANNEL", "t.me/your_ai_channel")}
PRICES = {"vip_only": 16, "ai_only": 76, "both": 66}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}

# === النصوص ===
TEXT = {
    "ar": {
        "welcome": "ORORA.UN \n\n🟢 مرحبًا بك في البوابة الرسمية... اختر الباقة اللي تناسب طموحك الآن ⬇️",
        "vip_only": "📈 توصيات VIP فقط\n• أرباح يومية مضمونة\nالسعر: 16$",
        "ai_only": "🤖 المساعد الذكي فقط\nالسعر: 76$",
        "both": "💎 الباقة الكاملة\n• توصيات VIP + المساعد الذكي\nالسعر: 66$",
        "ask_name": "✍️ اكتب اسمك الكامل (الأول + الأخير):",
        "ask_email": "📧 ادخل إيميلك الصحيح (إجباري):",
        "invalid_email": "🚫 الإيميل غير صحيح! أعد إرساله بشكل صحيح (مثال: name@example.com)",
        "choose_coin": "💰 اختر العملة الدفع:",
        "pay_now": "💸 اضغط الزر تحت عشان تدفع الآن:",
        "success": "🎉 تم التفعيل بنجاح!\n\nرقم العضوية: {code}\nالصلاحية: حتى {date}\n\n{links}\n\nرابط الدعوة الخاص بك:\nt.me/{botname}?start=ref{uid}"
    }
}

def t(key):
    return TEXT["ar"][key]

# === البدء ===
@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    args = m.text.split()

    # نظام الإحالة
    if len(args) > 1 and args[1].startswith("ref"):
        ref_id = args[1][3:]
        if ref_id.isdigit() and ref_id != uid:
            db["referrals"][uid] = ref_id
            save_db()

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📈 VIP فقط - 16$", callback_data="plan_vip_only"),
        InlineKeyboardButton("🤖 مساعد ذكي فقط - 76$", callback_data="plan_ai_only"),
        InlineKeyboardButton("💎 الكل مع بعض - 66$", callback_data="plan_both")
    )

    if uid in db["members"]:
        markup.add(InlineKeyboardButton("🔄 تجديد بخصم", callback_data="renew"))

    bot.send_message(m.chat.id, t("welcome"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data == "renew")
def plan_selected(c):
    uid = str(c.message.chat.id)
    bot.answer_callback_query(c.id)

    if c.data == "renew":
        if uid not in db["members"]:
            bot.answer_callback_query(c.id, "ليس لديك عضوية لتجديدها!", show_alert=True)
            return
        plan = db["members"][uid]["plan"]
        renew = True
    else:
        plan = c.data.replace("plan_", "")
        renew = False

    db["users"][uid] = {"step": "name", "plan": plan, "renew": renew}
    save_db()

    desc_map = {"vip_only": "vip_only", "ai_only": "ai_only", "both": "both"}
    bot.edit_message_text(
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        text=t(desc_map[plan])
    )
    bot.send_message(c.message.chat.id, t("ask_name"))

# === الخطوات ===
@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "name")
def get_name(m):
    uid = str(m.chat.id)
    name = m.text.strip()
    if len(name.split()) < 2:
        bot.reply_to(m, "🚫 اكتب الاسم الكامل (اسم + كنية)")
        return

    db["users"][uid]["name"] = name
    db["users"][uid]["step"] = "email"
    save_db()
    bot.reply_to(m, t("ask_email"))

# التحقق من صحة الإيميل
def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email.strip()) is not None

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "coin")
def choose_coin(m):
    uid = str(m.chat.id)

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("USDT", callback_data="coin_USDT"),
        InlineKeyboardButton("USDC", callback_data="coin_USDC")
    )
    bot.send_message(uid, "💰 اختر العملة:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_")[1]
    db["users"][uid]["coin"] = coin
    save_db()
    bot.answer_callback_query(c.id)

    create_payment(uid, coin.lower())

@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_")[1]  # USDT / USDC
    db["users"][uid]["coin"] = coin
    db["users"][uid]["step"] = "network"
    save_db()
    bot.answer_callback_query(c.id)

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("TRC20", callback_data=f"net_TRC20"),
        InlineKeyboardButton("ERC20", callback_data=f"net_ERC20"),
        InlineKeyboardButton("BSC", callback_data=f"net_BSC")
    )

    bot.send_message(uid, f"🌐 اختر الشبكة الخاصة بعملة {coin}:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("net_"))
def network_selected(c):
    uid = str(c.message.chat.id)
    network = c.data.split("_")[1]  # TRC20 / ERC20 / BSC

    coin = db["users"][uid]["coin"]

    # خريطة الشبكات الرسمية لـ NOWPayments
    mapping = {
        "USDT": {
            "TRC20": "usdttrc20",
            "ERC20": "usdteth",
            "BSC": "usdtbsc"
        },
        "USDC": {
            "TRC20": "usdctrc20",
            "ERC20": "usdceth",
            "BSC": "usdcbsc"
        }
    }

    pay_currency = mapping[coin][network]

    db["users"][uid]["network"] = network
    db["users"][uid]["pay_currency"] = pay_currency
    save_db()
    bot.answer_callback_query(c.id)

    create_payment(uid, pay_currency)

# === مساعدة: الحصول على رقم الفاتورة من استجابة NOWPayments بشكل آمن ===
def extract_invoice_id(resp_json: dict):
    """
    NOWPayments قد ترجع 'id' أو 'invoice_id' بحسب الـ endpoint/version.
    نستخدم أيًا منهما إذا وُجد.
    """
    return resp_json.get("id") or resp_json.get("invoice_id") or resp_json.get("invoiceId")

# === إنشاء الفاتورة ===
def create_payment(uid, pay_currency):
    user = db["users"].get(uid)
    if not user:
        bot.send_message(uid, "حدث خطأ: بيانات المستخدم غير موجودة. أعد المحاولة.")
        return

    plan = user["plan"]
    price = RENEW_PRICES[plan] if user.get("renew") else PRICES[plan]

    # تأكد من وجود رابط webhook فعّال
    ipn_url = f"{WEBHOOK_BASE.rstrip('/')}/webhook" if WEBHOOK_BASE else None

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": f"{uid}_{int(time.time())}",
        "order_description": f"ORORA.UN - {plan}",
    }
    if ipn_url:
        payload["ipn_callback_url"] = ipn_url
    # success_url يوجّه المستخدم بعد الدفع (اختياري)
    try:
        bot_username = bot.get_me().username
        payload["success_url"] = f"https://t.me/{bot_username}"
    except Exception:
        payload["success_url"] = ""

    headers = {"x-api-key": NOWPAYMENTS_KEY, "Content-Type": "application/json"}

    try:
        r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers, timeout=15)
    except requests.RequestException as e:
        bot.send_message(uid, "⚠️ حدث خطأ في الاتصال ببوابة الدفع. حاول لاحقًا.")
        print("NowPayments request failed:", e)
        return

    try:
        data = r.json()
    except ValueError:
        bot.send_message(uid, "⚠️ استجابة غير متوقعة من بوابة الدفع.")
        print("Invalid JSON from nowpayments:", r.text)
        return

    if r.status_code not in (200, 201):
        # حاول إظهار رسالة خطأ مفيدة للمستخدم
        msg = data.get("message") or data.get("error") or data.get("detail") or r.text
        bot.send_message(uid, f"⚠️ حدث خطأ في إنشاء الفاتورة: {msg}")
        print("NowPayments create invoice error:", r.status_code, data)
        return

    inv_id = extract_invoice_id(data)
    url = data.get("invoice_url") or data.get("payment_url") or data.get("url")

    if not inv_id or not url:
        bot.send_message(uid, "⚠️ استجابة البوابة ناقصة (لا يوجد رابط الدفع). تواصل مع الدعم.")
        print("Missing invoice id or url:", data)
        return

    # خزن باستخدام str(inv_id) لضمان التوافق في المقارنة لاحقًا
    db["pending"][str(inv_id)] = {"user_id": uid, "plan": plan, "order_id": payload["order_id"]}
    save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💸 ادفع الآن", url=url))
    bot.send_message(uid, t("pay_now"), reply_markup=markup)

# === تفعيل العضوية ===
def activate_user(uid, plan):
    uid = str(uid)
    code = "VIP-" + ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    db["members"][uid] = {"code": code, "plan": plan, "expiry": expiry}
    save_db()

    links = ""
    # التحقق من وجود الكلمات الصحيحة في اسم الخطة
    if "vip" in plan or plan == "both":
        links += f"قناة التوصيات:\n{CHANNELS['vip']}\n\n"
    if "ai" in plan or plan == "both":
        links += f"المساعد الذكي:\n{CHANNELS['ai']}\n"

    try:
        botname = bot.get_me().username
    except Exception:
        botname = "your_bot"

    clean_uid = uid.lstrip('-') if uid.startswith('-') else uid

    bot.send_message(int(uid), t("success").format(
        code=code, date=expiry, links=links,
        botname=botname, uid=clean_uid
    ))

# === الـ Webhook (HMAC-SHA512) ===
@app.route("/webhook", methods=["POST"])
def webhook():
    # NOWPayments يرسل هيدر التوقيع؛ قد يكون بصيغة مختلفة. نحاول الالتقاط بعدة أسماء
    signature = request.headers.get("x-nowpayments-signature") or request.headers.get("X-NowPayments-Signature") or request.headers.get("x-nowpayments-signature-sha512")
    data = request.get_data()  # bytes

    if not signature:
        print("No signature header present")
        abort(400)

    # حساب HMAC-SHA512 على الجسم كما هو
    expected_sig = hmac.new(
        IPN_SECRET.encode('utf-8'),
        data,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        print("Invalid IPN signature", signature, expected_sig)
        abort(400)

    try:
        payload = request.get_json(force=True)
    except Exception as e:
        print("Invalid JSON in webhook:", e)
        abort(400)

    # بعض إصدارات NOWPayments ترسل invoice_id وفيها payment_status أو status
    inv_id = str(payload.get("invoice_id") or payload.get("id") or payload.get("invoiceId"))
    status = payload.get("payment_status") or payload.get("status")

    print("Webhook received:", inv_id, status)

    # الحالات التي نعتبرها مدفوعة / مكتملة
    if status and inv_id:
        if status in ["finished", "confirmed", "partially_paid", "paid", "successful"]:
            # تطابق مع db
            if inv_id in db.get("pending", {}):
                info = db["pending"][inv_id]
                try:
                    activate_user(info["user_id"], info["plan"])
                except Exception as e:
                    print("Failed to activate user:", e)
                # احذف من pending
                db["pending"].pop(inv_id, None)
                save_db()

    return "OK", 200

# === تشغيل البوت + فلاسْك ===
if __name__ == "__main__":
    import threading
    port = int(os.getenv("PORT", 8080))
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": port}, daemon=True).start()
    print("البوت شغال 100% - التفعيل الآلي مفعل!")
    bot.infinity_polling(none_stop=True, interval=0)
