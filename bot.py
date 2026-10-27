import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ========== التكوين ==========
# طريقة 1 (الأفضل): set BOT_TOKEN=التوكن   قبل التشغيل
# طريقة 2: اكتب التوكن هنا بين العلامتين
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8534099445:AAHXWeBaHj5X-jRNB7-Wf_krprxo8hRNkkU").strip() or ""
# بروكسي اختياري مثال: "http://127.0.0.1:7890"
PROXY = os.environ.get("PROXY", "").strip() or ""

if not BOT_TOKEN:
    sys.exit("❌ التوكن مش موجود. اكتب في CMD:  set BOT_TOKEN=التوكن")

VOICES_DIR = Path("voices")
OUTPUT_DIR = Path("outputs")
VOICES_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_TEXT = 1000
MAX_NAME = 15  # عشان حد callback_data في تيليجرام 64 بايت
_tts = None
_tts_lock = asyncio.Lock()

# ألوان الأزرار: primary=أزرق | success=أخضر | danger=أحمر
BLUE, GREEN, RED = "primary", "success", "danger"


# ========== أدوات ==========
def btn(text, data=None, style=None, url=None):
    """زر ملوّن. يشتغل على كل إصدارات المكتبة."""
    kw = {"url": url} if url else {"callback_data": data}
    if not style:
        return InlineKeyboardButton(text, **kw)
    try:
        return InlineKeyboardButton(text, style=style, **kw)
    except TypeError:
        return InlineKeyboardButton(text, api_kwargs={"style": style}, **kw)


def kb(*rows):
    return InlineKeyboardMarkup([list(r) for r in rows])


def get_tts():
    global _tts
    if _tts is None:
        from voicetut_tts import VoiceTutTTS

        _tts = VoiceTutTTS.from_pretrained("mohammedaly22/VoiceTut-TTS")
    return _tts


def user_dir(uid: int) -> Path:
    d = VOICES_DIR / str(uid)
    d.mkdir(exist_ok=True)
    return d


def safe_name(name: str):
    name = name.strip()
    if not (1 <= len(name) <= MAX_NAME):
        return None
    if not re.fullmatch(r"[\w\u0600-\u06FF\- ]+", name):
        return None
    return name


def list_voices(uid: int) -> list:
    return sorted(f.stem for f in user_dir(uid).glob("*.wav"))


async def run_ffmpeg(*args: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    return (await proc.wait()) == 0


async def show(q, text, markup):
    """يعدّل الرسالة الحالية، أو يبعت رسالة جديدة لو الرسالة فويس."""
    if q.message.text is None:  # رسالة فويس/كابشن
        await q.message.reply_text(text, reply_markup=markup)
        return
    try:
        await q.edit_message_text(text, reply_markup=markup)
    except BadRequest:
        pass  # الرسالة ما اتغيرتش


# ========== القوائم ==========
def main_menu(context):
    sel = context.user_data.get("selected_voice")
    text = (
        "🎙️ أهلاً بك في بوت استنساخ الصوت\n\n"
        f"🔊 الصوت الحالي: {sel if sel else 'لم يتم اختيار صوت'}\n\n"
        "اختر من الأزرار:\n"
        "⚠️ استخدم صوتك أنت أو صوت شخص وافق صراحةً."
    )
    markup = kb(
        [btn("🎤 تسجيل صوت جديد", "rec", GREEN)],
        [btn("🔊 أصواتي واختيار الصوت", "voices", BLUE)],
        [btn("✍️ تحويل نص إلى صوت", "tts", BLUE)],
        [btn("🗑️ حذف صوت", "del_menu", RED)],
        [btn("ℹ️ مساعدة", "help", BLUE)],
        [btn("💬 المطور", url="https://t.me/xcode000", style=BLUE),
         btn("📢 القناة", url="https://t.me/L_ZOR_L", style=GREEN)],
    )
    return text, markup


def voices_menu(uid):
    voices = list_voices(uid)
    if not voices:
        return "📭 لا توجد أصوات محفوظة.", kb(
            [btn("🎤 تسجيل صوت جديد", "rec", GREEN)],
            [btn("🏠 القائمة الرئيسية", "menu", BLUE)],
        )
    rows = [[btn(f"🔊 {v}", f"pick:{v}", BLUE)] for v in voices]
    rows.append([btn("🎤 إضافة صوت", "rec", GREEN), btn("🗑️ حذف", "del_menu", RED)])
    rows.append([btn("🏠 القائمة الرئيسية", "menu", BLUE)])
    return "اختر الصوت:", InlineKeyboardMarkup(rows)


def delete_menu(uid):
    voices = list_voices(uid)
    if not voices:
        return "📭 لا توجد أصوات للحذف.", kb([btn("🏠 القائمة الرئيسية", "menu", BLUE)])
    rows = [[btn(f"🗑️ {v}", f"delask:{v}", RED)] for v in voices]
    rows.append([btn("🔙 رجوع", "menu", BLUE)])
    return "اختر الصوت الذي تريد حذفه:", InlineKeyboardMarkup(rows)


HELP_TEXT = (
    "ℹ️ طريقة الاستخدام:\n\n"
    "1️⃣ اضغط «تسجيل صوت جديد» وابعت فويس بصوتك (10-30 ثانية، هادي وبدون دوشة)\n"
    "2️⃣ سمّي الصوت أو اضغط «اسم تلقائي»\n"
    "3️⃣ اختر الصوت من «أصواتي»\n"
    "4️⃣ ابعت النص بالمصري زي ما بتتكلم، وهيرجعلك فويس بنفس البصمة\n\n"
    "💡 اكتب النص بالعامية المصرية عشان اللهجة تطلع صح."
)


# ========== الأوامر ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = None
    text, markup = main_menu(context)
    await update.message.reply_text(text, reply_markup=markup)


# ========== استقبال الفويس ==========
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    file = await context.bot.get_file(update.message.voice.file_id)

    tmp = user_dir(uid) / f"tmp_{uuid.uuid4().hex}.ogg"
    await file.download_to_drive(tmp)
    wav = tmp.with_suffix(".tmpwav")
    ok = await run_ffmpeg("-i", str(tmp), "-ar", "24000", "-ac", "1", "-f", "wav", str(wav))
    tmp.unlink(missing_ok=True)
    if not ok:
        await update.message.reply_text(
            "❌ فشل تحويل الصوت. تأكد إن ffmpeg متثبت.",
            reply_markup=kb([btn("🏠 القائمة الرئيسية", "menu", BLUE)]),
        )
        return

    old = context.user_data.pop("pending_voice", None)
    if old:
        Path(old).unlink(missing_ok=True)
    context.user_data["pending_voice"] = str(wav)
    context.user_data["state"] = "await_name"
    await update.message.reply_text(
        f"✅ تم استلام الصوت.\nاكتب اسماً للصوت (حتى {MAX_NAME} حرفاً) أو اضغط اسم تلقائي:",
        reply_markup=kb(
            [btn("⚡ اسم تلقائي", "autoname", GREEN)],
            [btn("❌ إلغاء", "cancel_rec", RED)],
        ),
    )


def save_voice(context, uid, name):
    pending = context.user_data.pop("pending_voice")
    os.replace(pending, user_dir(uid) / f"{name}.wav")
    context.user_data["state"] = None


def saved_markup(name):
    return kb(
        [btn("✅ استخدم هذا الصوت الآن", f"pick:{name}", GREEN)],
        [btn("🔊 أصواتي", "voices", BLUE), btn("🏠 القائمة", "menu", BLUE)],
    )


# ========== النصوص ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get("state")

    # --- إدخال اسم الصوت ---
    if state == "await_name" and context.user_data.get("pending_voice"):
        name = safe_name(text)
        if not name:
            await update.message.reply_text(
                f"⚠️ الاسم غير صالح (1-{MAX_NAME} حرفاً، حروف وأرقام فقط). جرّب تاني:",
                reply_markup=kb(
                    [btn("⚡ اسم تلقائي", "autoname", GREEN)],
                    [btn("❌ إلغاء", "cancel_rec", RED)],
                ),
            )
            return
        save_voice(context, uid, name)
        await update.message.reply_text(f"✅ تم حفظ الصوت: {name}", reply_markup=saved_markup(name))
        return

    # --- تحويل نص إلى صوت ---
    selected = context.user_data.get("selected_voice")
    if not selected or selected not in list_voices(uid):
        context.user_data.pop("selected_voice", None)
        t, m = voices_menu(uid)
        await update.message.reply_text("⚠️ اختر صوتاً أولاً.\n\n" + t, reply_markup=m)
        return
    if len(text) > MAX_TEXT:
        await update.message.reply_text(f"⚠️ النص طويل (الحد {MAX_TEXT} حرف).")
        return

    ref_audio = user_dir(uid) / f"{selected}.wav"
    wait_msg = await update.message.reply_text("⏳ جاري التوليد... (أول مرة بيطول عشان تحميل الموديل)")
    out_wav = OUTPUT_DIR / f"out_{uuid.uuid4().hex}.wav"
    ogg = out_wav.with_suffix(".ogg")
    try:
        async with _tts_lock:
            tts = await asyncio.to_thread(get_tts)
            await asyncio.to_thread(
                tts.synthesize, text,
                ref_audio=str(ref_audio), ref_text="", output=str(out_wav),
            )
        ok = await run_ffmpeg(
            "-i", str(out_wav), "-c:a", "libopus", "-b:a", "32k",
            "-vbr", "on", "-application", "voip", str(ogg),
        )
        if not ok:
            raise RuntimeError("فشل تحويل الصوت بـ ffmpeg")

        with open(ogg, "rb") as f:
            await update.message.reply_voice(
                voice=f,
                caption=f"🔊 {selected}",
                reply_markup=kb(
                    [btn("✍️ نص جديد", "tts", GREEN)],
                    [btn("🔊 تغيير الصوت", "voices", BLUE), btn("🏠 القائمة", "menu", BLUE)],
                ),
            )
        await wait_msg.delete()
    except Exception as e:
        await wait_msg.edit_text(
            f"❌ خطأ: {str(e)[:300]}",
            reply_markup=kb([btn("🏠 القائمة الرئيسية", "menu", BLUE)]),
        )
    finally:
        out_wav.unlink(missing_ok=True)
        ogg.unlink(missing_ok=True)


# ========== الأزرار ==========
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data == "menu":
        context.user_data["state"] = None
        t, m = main_menu(context)
        await show(q, t, m)

    elif data == "help":
        await show(q, HELP_TEXT, kb([btn("🏠 القائمة الرئيسية", "menu", BLUE)]))

    elif data == "rec":
        context.user_data["state"] = "await_voice"
        await show(
            q,
            "🎤 ابعت دلوقتي رسالة صوتية بصوتك (10-30 ثانية).\nيفضل مكان هادي وكلام واضح.",
            kb([btn("❌ إلغاء", "menu", RED)]),
        )

    elif data == "cancel_rec":
        pending = context.user_data.pop("pending_voice", None)
        if pending:
            Path(pending).unlink(missing_ok=True)
        context.user_data["state"] = None
        t, m = main_menu(context)
        await show(q, t, m)

    elif data == "autoname":
        if not context.user_data.get("pending_voice"):
            await show(q, "⚠️ لا يوجد صوت في الانتظار.", kb([btn("🎤 تسجيل صوت", "rec", GREEN)]))
            return
        existing = set(list_voices(uid))
        n = len(existing) + 1
        while f"صوت {n}" in existing:
            n += 1
        name = f"صوت {n}"
        save_voice(context, uid, name)
        await show(q, f"✅ تم حفظ الصوت: {name}", saved_markup(name))

    elif data == "voices":
        t, m = voices_menu(uid)
        await show(q, t, m)

    elif data == "tts":
        sel = context.user_data.get("selected_voice")
        if sel and sel in list_voices(uid):
            context.user_data["state"] = "await_text"
            await show(
                q,
                f"✍️ الصوت: {sel}\nابعت النص دلوقتي (بالمصري زي ما بتتكلم):",
                kb(
                    [btn("🔊 تغيير الصوت", "voices", BLUE)],
                    [btn("🏠 القائمة الرئيسية", "menu", BLUE)],
                ),
            )
        else:
            t, m = voices_menu(uid)
            await show(q, "⚠️ اختر صوتاً أولاً.\n\n" + t, m)

    elif data.startswith("pick:"):
        name = data.split(":", 1)[1]
        if name not in list_voices(uid):
            await show(q, "⚠️ الصوت غير موجود.", kb([btn("🔊 أصواتي", "voices", BLUE)]))
            return
        context.user_data["selected_voice"] = name
        context.user_data["state"] = "await_text"
        await show(
            q,
            f"✅ تم اختيار الصوت: {name}\n\n✍️ ابعت النص الآن وهحوّله لفويس.",
            kb(
                [btn("🔊 تغيير الصوت", "voices", BLUE)],
                [btn("🏠 القائمة الرئيسية", "menu", BLUE)],
            ),
        )

    elif data == "del_menu":
        t, m = delete_menu(uid)
        await show(q, t, m)

    elif data.startswith("delask:"):
        name = data.split(":", 1)[1]
        await show(
            q,
            f"⚠️ متأكد إنك عايز تحذف الصوت «{name}»؟",
            kb(
                [btn("✅ نعم، احذف", f"delok:{name}", RED)],
                [btn("🔙 لا، رجوع", "del_menu", GREEN)],
            ),
        )

    elif data.startswith("delok:"):
        name = data.split(":", 1)[1]
        if safe_name(name):
            (user_dir(uid) / f"{name}.wav").unlink(missing_ok=True)
            if context.user_data.get("selected_voice") == name:
                context.user_data.pop("selected_voice", None)
        t, m = delete_menu(uid)
        await show(q, f"🗑️ تم حذف: {name}\n\n{t}", m)


# ========== التشغيل ==========
def main():
    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(60)
    )
    if PROXY:
        builder = builder.proxy(PROXY).get_updates_proxy(PROXY)

    app = builder.build()
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(on_button))

    print("✅ البوت شغال...")
    app.run_polling()


if __name__ == "__main__":
    main()