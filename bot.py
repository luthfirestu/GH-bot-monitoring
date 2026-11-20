import asyncio
import os
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from dummy_gh import (
    force_dirty_state,
    get_cleaning_plan,
    get_gh_report,
    mark_cleaning_completed,
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Mode demo: update tiap 0.5 detik agar responsif & mulus saat presentasi/demo.
# set CLEANING_DEMO_MODE = False jika ingin kembali ke durasi penuh (240 - 300 detik).
CLEANING_DEMO_MODE = True
CLEANING_DEMO_INTERVAL = 0.5
CLEANING_DEMO_TOTAL_STEPS = 10  # 10 * 0.5s = 5 detik waktu loading
CLEANING_ESTIMATE_SECONDS = 270.0  # 4.5 menit untuk estimasi rencana siklus asli
CLEANING_ANIM_SECONDS = 5.0  # 5 detik animasi loading saat demo
CLEANING_REAL_STEPS = 10


def _make_progress_bar(percent: int, width: int = 12) -> str:
    filled = int(round((percent / 100) * width))
    filled = max(0, min(width, filled))
    return "▰" * filled + "▱" * (width - filled)


def _status_badge(ai_status: str) -> str:
    badges = {
        "GOOD": "🟢 GOOD",
        "WARNING": "🟡 WARNING",
        "CRITICAL": "🔴 CRITICAL",
    }
    return badges.get(ai_status, f"⚪ {ai_status}")


def _health_badge(system_health: str) -> str:
    return "🟢 NORMAL" if system_health == "NORMAL" else "🔴 BAD"


def _build_status_view(data: dict) -> tuple[str, InlineKeyboardMarkup]:
    rec_icon = "🧹" if data["cleaning_recommendation"] == "CLEANING" else "✅"
    plan = get_cleaning_plan(CLEANING_ESTIMATE_SECONDS)
    est_seconds = plan["total_duration_sec"]
    est_minutes = round(est_seconds / 60, 1)
    est_water = plan["estimated_water_liters"]

    lines = [
        "🌿 *GREENHOUSE SMART MONITORING PT. NYALINDUNG*",
        "",
        f"🤖 *AI Status:* {_status_badge(data['ai_status'])}",
        "",
        f"📈 *AI Score:* `{data['ai_score']}%`",
        "",
        f"☀️ *Light Transmission:* `{data['light_transmission']}%`",
        "",
        f"🧱 *Roof Dirty:* `{data['roof_dirty']}%`",
        "",
        f"{rec_icon} *Cleaning Recommendation:* *{data['cleaning_recommendation']}*",
        "",
        f"🩺 *System Health:* {_health_badge(data['system_health'])}",
        "",
        f"💧 *Estimasi Air Siklus (~{est_minutes} mnt / {est_seconds:g}s):* `{est_water} L`",
        "",
        f"🕒 _Update: {data['updated_at']}_",
    ]

    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="status_refresh")]
    ]

    if data["cleaning_recommendation"] == "CLEANING":
        buttons.append([InlineKeyboardButton("🧹 Jalankan Cleaning", callback_data="ask_cleaning")])

    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def _safe_edit_text(message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📊 Cek /status", callback_data="status_refresh"),
                    InlineKeyboardButton("🧹 /cleaning", callback_data="ask_cleaning"),
                ]
            ]
        )
        await update.message.reply_text(
            "🌿 *Bot Monitoring Greenhouse IoT Aktif*\n\n"
            "Pantau kondisi atap, transmisi cahaya, dan picu pembersihan otomatis.\n"
            "Ketik /help untuk melihat daftar perintah.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "📋 *Daftar Perintah Bot Greenhouse*\n\n"
            "• `/status` — Laporan lengkap kondisi greenhouse\n"
            "• `/score` — Lihat nilai AI Score\n"
            "• `/health` — Cek System Health\n"
            "• `/cleaning` — Simulasi pembersihan atap IoT\n"
            "• `/ping` — Cek status koneksi bot\n"
            "• `/help` — Tampilkan bantuan perintah",
            parse_mode="Markdown",
        )


async def f_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        force_dirty_state()
        await update.message.reply_text("ok.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        data = get_gh_report()
        text, markup = _build_status_view(data)
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def score_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        data = get_gh_report()
        await update.message.reply_text(f"📈 *AI Score:* `{data['ai_score']}%`", parse_mode="Markdown")


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        data = get_gh_report()
        await update.message.reply_text(
            f"🩺 *System Health:* {_health_badge(data['system_health'])}",
            parse_mode="Markdown",
        )


async def _send_cleaning_confirmation(target_message) -> None:
    plan = get_cleaning_plan(CLEANING_ESTIMATE_SECONDS)
    est_minutes = round(plan["total_duration_sec"] / 60, 1)
    mode_note = (
        f" _(Loading demo {CLEANING_ANIM_SECONDS:g}s, update tiap {CLEANING_DEMO_INTERVAL:g}s)_"
        if CLEANING_DEMO_MODE
        else ""
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Ya, Mulai", callback_data="cleaning_confirm"),
                InlineKeyboardButton("❌ Batal", callback_data="cleaning_cancel"),
            ]
        ]
    )
    await target_message.reply_text(
        "🧹 *Konfirmasi Pembersihan Atap IoT*\n\n"
        f"• *Unit:* `{plan['device_id']}`\n"
        f"• *Pompa:* `{plan['pump_capacity_m3_per_hour']} m³/jam`\n"
        f"• *Estimasi Durasi Siklus:* `~{est_minutes} menit` (`{plan['total_duration_sec']:g}s`){mode_note}\n"
        f"• *Estimasi Air Siklus:* `{plan['estimated_water_liters']} L`\n\n"
        "Lanjutkan proses pembersihan?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cleaning_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await _send_cleaning_confirmation(update.message)


async def _run_cleaning_animation(message) -> None:
    plan = get_cleaning_plan(CLEANING_ESTIMATE_SECONDS)
    total_target_water = float(plan["estimated_water_liters"])

    if CLEANING_DEMO_MODE:
        total_steps = CLEANING_DEMO_TOTAL_STEPS
        sleep_interval = CLEANING_ANIM_SECONDS / total_steps  # 5.0 / 10 = 0.5 detik
    else:
        total_steps = CLEANING_REAL_STEPS
        sleep_interval = CLEANING_ANIM_SECONDS / total_steps

    await _safe_edit_text(
        message,
        f"🧹 *Memulai Pembersihan Atap IoT* (`{plan['device_id']}`)\n\n"
        f"Pompa: `{plan['pump_capacity_m3_per_hour']} m³/jam` | Estimasi Siklus: `{total_target_water} L`\n\n"
        f"`{_make_progress_bar(0)}` *0%*",
    )

    for step in range(1, total_steps + 1):
        await asyncio.sleep(sleep_interval)
        ratio = step / total_steps
        pct = int(round(ratio * 100))
        pct = max(0, min(100, pct))
        used_water = round(total_target_water * ratio, 2)
        bar = _make_progress_bar(pct)

        if step < total_steps:
            await _safe_edit_text(
                message,
                f"🧹 *Proses Pembersihan Atap IoT* (`{plan['device_id']}`)\n\n"
                "Status: Menyemprot & membilas permukaan atap...\n\n"
                f"Pemakaian air: `{used_water} L` / `{total_target_water} L`\n\n"
                f"`{bar}` *{pct}%*",
            )
        else:
            mark_cleaning_completed()
            done_keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📊 Cek Status Terbaru", callback_data="status_refresh")]]
            )
            await _safe_edit_text(
                message,
                f"✅ *Pembersihan Atap IoT Selesai* (`{plan['device_id']}`)\n\n"
                f"Total estimasi siklus: `{total_target_water} L` (`{plan['pump_capacity_m3_per_hour']} m³/jam`)\n"
                "Kondisi atap telah diperbarui menjadi bersih.\n\n"
                f"`{bar}` *100%*",
                reply_markup=done_keyboard,
            )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return

    await query.answer()
    data_key = query.data or ""

    if data_key == "status_refresh":
        report = get_gh_report(force_refresh=True)
        text, markup = _build_status_view(report)
        await _safe_edit_text(query.message, text, reply_markup=markup)

    elif data_key == "ask_cleaning":
        await _send_cleaning_confirmation(query.message)

    elif data_key == "cleaning_cancel":
        await _safe_edit_text(query.message, "❎ Pembersihan atap dibatalkan.")

    elif data_key == "cleaning_confirm":
        await _run_cleaning_animation(query.message)


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("🏓 pong")


async def post_init(application) -> None:
    await application.bot.set_my_commands(
        [
            ("status", "Laporan lengkap kondisi greenhouse"),
            ("score", "Lihat nilai AI Score"),
            ("health", "Cek System Health"),
            ("cleaning", "Simulasi pembersihan atap IoT"),
            ("ping", "Cek koneksi bot"),
            ("help", "Daftar perintah"),
        ]
    )


def main() -> None:
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN belum diatur di file .env atau environment variable.")

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("f", f_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("cleaning", cleaning_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot berjalan...")
    app.run_polling()


if __name__ == "__main__":
    main()