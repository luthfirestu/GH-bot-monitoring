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

CLEANING_STEPS = 20

# State proses cleaning yang tampil langsung di dalam pesan /status (dipicu via /auto)
_status_cleaning_state: dict | None = None
_status_cleaning_task: asyncio.Task | None = None
_status_live_message = None


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


def _get_plan_for_dirty(roof_dirty: float) -> dict:
    """Mengambil rencana durasi & estimasi air dinamis sesuai tingkat kekotoran atap."""
    try:
        return get_cleaning_plan(roof_dirty=roof_dirty)
    except TypeError:
        return get_cleaning_plan()


def _format_status_cleaning_block(state: dict) -> str:
    pct = max(0, min(100, int(state.get("pct", 0))))
    used_water = state.get("used_water", 0.0)
    total_water = state.get("total_target_water", 0.0)
    est_seconds = float(state.get("est_seconds", 0.0))
    est_minutes = round(est_seconds / 60, 1)
    bar = _make_progress_bar(pct)

    if state.get("completed"):
        return (
            "⚙️ *Status Proses:* Pembersihan selesai\n"
            f"• Estimasi siklus: `~{est_minutes} mnt ({est_seconds:g}s)` | `{total_water} L`\n"
            "• Status: Permukaan atap telah dibersihkan.\n"
            f"• Pemakaian air: `{total_water} L` / `{total_water} L`\n"
            f"`{bar}` *100%*"
        )

    return (
        "⚙️ *Status Proses:* Sedang proses cleaning\n"
        f"• Estimasi siklus: `~{est_minutes} mnt ({est_seconds:g}s)` | `{total_water} L`\n"
        "• Status: Menyemprot & membilas permukaan atap...\n"
        f"• Pemakaian air: `{used_water} L` / `{total_water} L`\n"
        f"`{bar}` *{pct}%*"
    )


def _build_status_view(data: dict) -> tuple[str, InlineKeyboardMarkup]:
    rec_icon = "🧹" if data["cleaning_recommendation"] == "CLEANING" else "✅"
    plan = _get_plan_for_dirty(float(data.get("roof_dirty", 0.0)))
    est_seconds = float(plan["total_duration_sec"])
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
    ]

    if _status_cleaning_state is not None:
        lines.extend(["", _format_status_cleaning_block(_status_cleaning_state)])

    lines.extend(["", f"🕒 _Update: {data['updated_at']}_"])

    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="status_refresh")]
    ]

    is_cleaning_now = _status_cleaning_state is not None and not _status_cleaning_state.get("completed")
    if data["cleaning_recommendation"] == "CLEANING" and not is_cleaning_now:
        buttons.append([InlineKeyboardButton("🧹 Jalankan Cleaning", callback_data="ask_cleaning")])

    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def _safe_edit_text(message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def _run_status_cleaning_worker() -> None:
    """Menjalankan progres cleaning sesuai estimasi siklus dan memperbarui pesan /status."""
    global _status_cleaning_state, _status_live_message

    state = _status_cleaning_state
    if state is None:
        return

    total_steps = CLEANING_STEPS
    total_duration = max(1.0, float(state["est_seconds"]))
    sleep_interval = total_duration / total_steps
    total_target_water = float(state["total_target_water"])

    try:
        for step in range(1, total_steps + 1):
            await asyncio.sleep(sleep_interval)
            if _status_cleaning_state is None:
                return

            ratio = step / total_steps
            pct = max(0, min(100, int(round(ratio * 100))))
            used_water = round(total_target_water * ratio, 2)

            _status_cleaning_state["pct"] = pct
            _status_cleaning_state["used_water"] = used_water

            if step == total_steps:
                mark_cleaning_completed()
                _status_cleaning_state["completed"] = True

            if _status_live_message is not None:
                report = get_gh_report()
                text, markup = _build_status_view(report)
                await _safe_edit_text(_status_live_message, text, reply_markup=markup)
    except asyncio.CancelledError:
        raise


def _start_status_cleaning_if_needed(report: dict) -> None:
    """Menyiapkan & memulai task cleaning berbasis estimasi durasi siklus saat /status dipanggil setelah /auto."""
    global _status_cleaning_state, _status_cleaning_task

    if _status_cleaning_state is not None and (
        not _status_cleaning_state.get("completed")
        or (_status_cleaning_task is not None and not _status_cleaning_task.done())
    ):
        return

    plan = _get_plan_for_dirty(float(report.get("roof_dirty", 0.0)))
    _status_cleaning_state = {
        "est_seconds": float(plan["total_duration_sec"]),
        "total_target_water": float(plan["estimated_water_liters"]),
        "used_water": 0.0,
        "pct": 0,
        "completed": False,
    }
    _status_cleaning_task = asyncio.create_task(_run_status_cleaning_worker())


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
            "• `/status` — Status lengkap kondisi greenhouse\n"
            "• `/score` — Lihat nilai AI Score\n"
            "• `/health` — Cek System Health\n"
            "• `/cleaning` — Pembersihan atap greenhouse\n"
            "• `/ping` — Cek koneksi bot\n"
            "• `/help` — Daftar perintah",
            parse_mode="Markdown",
        )


async def f_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        force_dirty_state()
        await update.message.reply_text("ok.")


async def auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command rahasia: set kondisi jadi kotor seperti /f dan siapkan proses cleaning otomatis di /status."""
    global _status_cleaning_state, _status_cleaning_task, _status_live_message
    if update.message:
        if _status_cleaning_task is not None and not _status_cleaning_task.done():
            _status_cleaning_task.cancel()
        _status_cleaning_state = None
        _status_cleaning_task = None
        _status_live_message = None

        force_dirty_state()
        get_gh_report(force_refresh=True)
        await update.message.reply_text("ok.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _status_live_message
    if update.message:
        data = get_gh_report()
        if _status_cleaning_state is None and data.get("cleaning_recommendation") == "CLEANING":
            # Jika baru saja dipicu lewat /auto, mulai cleaning otomatis sesuai estimasi siklus
            if _status_cleaning_task is None:
                _start_status_cleaning_if_needed(data)

        text, markup = _build_status_view(data)
        sent = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
        if _status_cleaning_state is not None and not _status_cleaning_state.get("completed"):
            _status_live_message = sent


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
    report = get_gh_report()
    plan = _get_plan_for_dirty(float(report.get("roof_dirty", 0.0)))
    est_minutes = round(float(plan["total_duration_sec"]) / 60, 1)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Ya, Mulai", callback_data="cleaning_confirm"),
                InlineKeyboardButton("❌ Batal", callback_data="cleaning_cancel"),
            ]
        ]
    )
    # Kirim sebagai pesan baru agar pesan status sebelumnya tidak tertimpa
    await target_message.reply_text(
        "🧹 *Konfirmasi Pembersihan Atap IoT*\n\n"
        f"• *Roof Dirty Saat Ini:* `{report['roof_dirty']}%`\n"
        f"• *Unit:* `{plan['device_id']}`\n"
        f"• *Pompa:* `{plan['pump_capacity_m3_per_hour']} m³/jam`\n"
        f"• *Estimasi Durasi Siklus:* `~{est_minutes} menit` (`{plan['total_duration_sec']:g}s`)\n"
        f"• *Estimasi Air Siklus:* `{plan['estimated_water_liters']} L`\n\n"
        "Lanjutkan proses pembersihan?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cleaning_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await _send_cleaning_confirmation(update.message)


async def _run_cleaning_animation(progress_message) -> None:
    global _status_cleaning_state
    report = get_gh_report()
    plan = _get_plan_for_dirty(float(report.get("roof_dirty", 0.0)))
    total_target_water = float(plan["estimated_water_liters"])
    total_duration = max(1.0, float(plan["total_duration_sec"]))

    total_steps = CLEANING_STEPS
    sleep_interval = total_duration / total_steps

    await _safe_edit_text(
        progress_message,
        f"🧹 *Memulai Pembersihan Atap IoT* (`{plan['device_id']}`)\n\n"
        f"Durasi: `{total_duration:g}s` | Pompa: `{plan['pump_capacity_m3_per_hour']} m³/jam` | Estimasi Siklus: `{total_target_water} L`\n\n"
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
                progress_message,
                f"🧹 *Proses Pembersihan Atap IoT* (`{plan['device_id']}`)\n\n"
                "Status: Menyemprot & membilas permukaan atap...\n\n"
                f"Pemakaian air: `{used_water} L` / `{total_target_water} L`\n\n"
                f"`{bar}` *{pct}%*",
            )
        else:
            mark_cleaning_completed()
            _status_cleaning_state = None
            done_keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📊 Cek Status Terbaru", callback_data="status_refresh")]]
            )
            await _safe_edit_text(
                progress_message,
                f"✅ *Pembersihan Atap IoT Selesai* (`{plan['device_id']}`)\n\n"
                f"Total estimasi siklus: `{total_target_water} L` (`{plan['pump_capacity_m3_per_hour']} m³/jam`)\n"
                "Kondisi atap telah diperbarui. Tekan *Refresh* pada pesan status atau cek status terbaru untuk melihat data baru.\n\n"
                f"`{bar}` *100%*",
                reply_markup=done_keyboard,
            )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _status_live_message
    query = update.callback_query
    if not query or not query.message:
        return

    await query.answer()
    data_key = query.data or ""

    if data_key == "status_refresh":
        report = get_gh_report(force_refresh=True)
        text, markup = _build_status_view(report)
        await _safe_edit_text(query.message, text, reply_markup=markup)
        if _status_cleaning_state is not None and not _status_cleaning_state.get("completed"):
            _status_live_message = query.message

    elif data_key == "ask_cleaning":
        # Kirim konfirmasi di pesan baru agar pesan status sebelumnya tetap tersimpan
        await _send_cleaning_confirmation(query.message)

    elif data_key == "cleaning_cancel":
        await _safe_edit_text(query.message, "❎ Pembersihan atap dibatalkan.")

    elif data_key == "cleaning_confirm":
        # Buat pesan progress baru agar pesan konfirmasi & pesan status sebelumnya tetap utuh
        progress_msg = await query.message.reply_text(
            "🧹 *Menyiapkan pembersihan atap IoT...*",
            parse_mode="Markdown",
        )
        await _run_cleaning_animation(progress_msg)


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("🏓 pong")


async def post_init(application) -> None:
    await application.bot.set_my_commands(
        [
            ("status", "Status lengkap kondisi greenhouse"),
            ("score", "Lihat nilai AI Score"),
            ("health", "Cek System Health"),
            ("cleaning", "Pembersihan atap greenhouse"),
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
    app.add_handler(CommandHandler("auto", auto_cmd))
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