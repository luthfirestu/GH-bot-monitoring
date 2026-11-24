import asyncio
import os
import time
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
CLEANING_DEMO_MODE = True
CLEANING_DEMO_INTERVAL = 0.5
CLEANING_DEMO_TOTAL_STEPS = 10  # 10 * 0.5s = 5 detik waktu loading
CLEANING_ANIM_SECONDS = 5.0  # 5 detik animasi loading saat demo
CLEANING_REAL_STEPS = 10

# Konfigurasi pembersihan otomatis (background loop)
AUTO_CLEAN_CHECK_INTERVAL = 15.0  # cek tiap 15 detik
AUTO_CLEAN_COOLDOWN_SECONDS = 30.0  # jeda minimal antar auto-cleaning

# State runtime untuk melacak proses cleaning yang sedang berjalan
_active_cleaning: dict | None = None
_active_cleaning_lock = asyncio.Lock()
_last_auto_clean_mono = 0.0
_auto_loop_task: asyncio.Task | None = None


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


def _format_cleaning_progress_block(state: dict) -> str:
    pct = max(0, min(100, int(state.get("pct", 0))))
    used_water = state.get("used_water", 0.0)
    total_water = state.get("total_target_water", 0.0)
    mode_label = "Otomatis (/auto)" if state.get("mode") == "auto" else "Manual"
    bar = _make_progress_bar(pct)

    return (
        f"⚙️ *Sedang Proses Cleaning ({mode_label})*\n"
        f"• Unit: `{state.get('device_id', 'GH-ROOF-CLEANER-01')}`\n"
        f"• Status: Menyemprot & membilas permukaan atap...\n"
        f"• Pemakaian air: `{used_water} L` / `{total_water} L`\n"
        f"`{bar}` *{pct}%*"
    )


def _build_status_view(data: dict) -> tuple[str, InlineKeyboardMarkup]:
    rec_icon = "🧹" if data["cleaning_recommendation"] == "CLEANING" else "✅"
    plan = _get_plan_for_dirty(float(data.get("roof_dirty", 0.0)))
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
    ]

    if _active_cleaning and _active_cleaning.get("running"):
        lines.extend(["", _format_cleaning_progress_block(_active_cleaning)])

    lines.extend(["", f"🕒 _Update: {data['updated_at']}_"])

    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="status_refresh")]
    ]

    if data["cleaning_recommendation"] == "CLEANING" and not (
        _active_cleaning and _active_cleaning.get("running")
    ):
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
    report = get_gh_report()
    plan = _get_plan_for_dirty(float(report.get("roof_dirty", 0.0)))
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
        f"• *Roof Dirty Saat Ini:* `{report['roof_dirty']}%`\n"
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


async def _execute_cleaning_cycle(
    message=None,
    bot=None,
    chat_id: int | None = None,
    mode: str = "manual",
) -> None:
    global _active_cleaning, _last_auto_clean_mono

    if _active_cleaning_lock.locked():
        if message:
            await message.reply_text(
                "⏳ Proses pembersihan atap sedang berlangsung. Cek `/status` untuk memantau progres."
            )
        return

    async with _active_cleaning_lock:
        report = get_gh_report()
        roof_dirty = float(report.get("roof_dirty", 0.0))
        plan = _get_plan_for_dirty(roof_dirty)
        total_target_water = float(plan["estimated_water_liters"])
        est_minutes = round(float(plan["total_duration_sec"]) / 60, 1)

        total_steps = CLEANING_DEMO_TOTAL_STEPS if CLEANING_DEMO_MODE else CLEANING_REAL_STEPS
        sleep_interval = CLEANING_ANIM_SECONDS / total_steps

        _active_cleaning = {
            "running": True,
            "mode": mode,
            "device_id": plan["device_id"],
            "pump_capacity": plan["pump_capacity_m3_per_hour"],
            "est_seconds": plan["total_duration_sec"],
            "est_minutes": est_minutes,
            "roof_dirty_start": roof_dirty,
            "total_target_water": total_target_water,
            "used_water": 0.0,
            "pct": 0,
        }
        _last_auto_clean_mono = time.monotonic()

        target_msg = message
        if target_msg is None and bot is not None and chat_id is not None:
            target_msg = await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🤖 *Pembersihan Otomatis Dimulai* (`{plan['device_id']}`)\n\n"
                    f"Roof Dirty: `{roof_dirty}%` | Estimasi: `~{est_minutes} mnt` (`{total_target_water} L`)\n\n"
                    f"`{_make_progress_bar(0)}` *0%*"
                ),
                parse_mode="Markdown",
            )

        if target_msg:
            header = (
                "🤖 *Memulai Pembersihan Otomatis Atap IoT*"
                if mode == "auto"
                else "🧹 *Memulai Pembersihan Atap IoT*"
            )
            await _safe_edit_text(
                target_msg,
                f"{header} (`{plan['device_id']}`)\n\n"
                f"Roof Dirty: `{roof_dirty}%` | Durasi: `~{est_minutes} mnt` (`{plan['total_duration_sec']:g}s`)\n"
                f"Pompa: `{plan['pump_capacity_m3_per_hour']} m³/jam` | Estimasi Siklus: `{total_target_water} L`\n\n"
                f"`{_make_progress_bar(0)}` *0%*",
            )

        try:
            for step in range(1, total_steps + 1):
                await asyncio.sleep(sleep_interval)
                ratio = step / total_steps
                pct = max(0, min(100, int(round(ratio * 100))))
                used_water = round(total_target_water * ratio, 2)
                bar = _make_progress_bar(pct)

                if _active_cleaning is not None:
                    _active_cleaning["pct"] = pct
                    _active_cleaning["used_water"] = used_water

                if step < total_steps:
                    if target_msg:
                        await _safe_edit_text(
                            target_msg,
                            f"🧹 *Proses Pembersihan Atap IoT* (`{plan['device_id']}`)\n\n"
                            f"Mode: *{'Otomatis' if mode == 'auto' else 'Manual'}*\n"
                            "Status: Menyemprot & membilas permukaan atap...\n\n"
                            f"Pemakaian air: `{used_water} L` / `{total_target_water} L`\n\n"
                            f"`{bar}` *{pct}%*",
                        )
                else:
                    mark_cleaning_completed()
                    if _active_cleaning is not None:
                        _active_cleaning["pct"] = 100
                        _active_cleaning["used_water"] = total_target_water
                    if target_msg:
                        done_keyboard = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("📊 Cek Status Terbaru", callback_data="status_refresh")]]
                        )
                        await _safe_edit_text(
                            target_msg,
                            f"✅ *Pembersihan Atap IoT Selesai* (`{plan['device_id']}`)\n\n"
                            f"Durasi siklus: `~{est_minutes} mnt` (`{plan['total_duration_sec']:g}s`)\n"
                            f"Total pemakaian air: `{total_target_water} L` (`{plan['pump_capacity_m3_per_hour']} m³/jam`)\n"
                            "Kondisi atap telah diperbarui menjadi bersih.\n\n"
                            f"`{bar}` *100%*",
                            reply_markup=done_keyboard,
                        )
        finally:
            _active_cleaning = None


async def auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command rahasia: set kondisi menjadi kotor lalu langsung jalankan proses cleaning."""
    if not update.message:
        return

    if update.effective_chat:
        context.application.bot_data["notify_chat_id"] = update.effective_chat.id

    force_dirty_state()
    dirty_report = get_gh_report(force_refresh=True)
    plan = _get_plan_for_dirty(float(dirty_report.get("roof_dirty", 0.0)))
    est_minutes = round(float(plan["total_duration_sec"]) / 60, 1)

    progress_msg = await update.message.reply_text(
        f"⚡ *Mode Kotor & Auto-Cleaning Diaktifkan*\n\n"
        f"• Roof Dirty: `{dirty_report['roof_dirty']}%` ({_status_badge(dirty_report['ai_status'])})\n"
        f"• Estimasi Siklus: `~{est_minutes} mnt` (`{plan['total_duration_sec']:g}s`) | `{plan['estimated_water_liters']} L`\n\n"
        f"`{_make_progress_bar(0)}` *0%*",
        parse_mode="Markdown",
    )

    asyncio.create_task(
        _execute_cleaning_cycle(
            message=progress_msg,
            bot=context.bot,
            chat_id=update.effective_chat.id if update.effective_chat else None,
            mode="auto",
        )
    )


async def _auto_cleaning_background_loop(application) -> None:
    """Memantau kondisi greenhouse secara otomatis dan memicu cleaning saat kotor."""
    global _last_auto_clean_mono
    await asyncio.sleep(5.0)

    while True:
        try:
            if not _active_cleaning_lock.locked():
                elapsed = time.monotonic() - _last_auto_clean_mono
                if elapsed >= AUTO_CLEAN_COOLDOWN_SECONDS:
                    report = get_gh_report(force_refresh=True)
                    is_dirty = (
                        report.get("cleaning_recommendation") == "CLEANING"
                        or float(report.get("roof_dirty", 0.0)) >= 20.0
                        or float(report.get("light_transmission", 100.0)) <= 70.0
                    )
                    if is_dirty:
                        chat_id = application.bot_data.get("notify_chat_id")
                        await _execute_cleaning_cycle(
                            message=None,
                            bot=application.bot,
                            chat_id=chat_id,
                            mode="auto",
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[AutoCleaning] Error: {exc}")

        await asyncio.sleep(AUTO_CLEAN_CHECK_INTERVAL)


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
        await _execute_cleaning_cycle(message=query.message, mode="manual")


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("🏓 pong")


async def post_init(application) -> None:
    global _auto_loop_task
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
    _auto_loop_task = asyncio.create_task(_auto_cleaning_background_loop(application))


async def post_shutdown(application) -> None:
    global _auto_loop_task
    if _auto_loop_task and not _auto_loop_task.done():
        _auto_loop_task.cancel()
        try:
            await _auto_loop_task
        except asyncio.CancelledError:
            pass


def main() -> None:
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN belum diatur di file .env atau environment variable.")

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

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