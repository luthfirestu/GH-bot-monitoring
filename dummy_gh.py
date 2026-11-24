from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import random
import time
from typing import Any

_CACHE_TTL_SECONDS = 5.0
_MAX_REALTIME_POINTS = 25
_START_DATE = date(2026, 7, 1)

_STATE_FILE = Path(__file__).resolve().parent / "gh_state.json"

PUMP_CAPACITY_M3_PER_HOUR = 2.0
PUMP_FLOW_LITERS_PER_SEC = (PUMP_CAPACITY_M3_PER_HOUR * 1000.0) / 3600.0  # ~0.5556 L/s
WIB = timezone(timedelta(hours=7))

MIN_CLEAN_CYCLE_SECONDS = 120.0  # 2 menit saat bersih / debu tipis
MAX_CLEAN_CYCLE_SECONDS = 240.0  # 4 menit saat sangat kotor
DIRTY_CYCLE_CAP = 50.0           # ambang kekotoran penuh untuk durasi maksimum


def calculate_water_usage_liters(duration_seconds: float) -> float:
    """Menghitung pemakaian air (liter) dari pompa 2 m3/jam berdasarkan durasi (detik)."""
    return round(PUMP_FLOW_LITERS_PER_SEC * duration_seconds, 2)


def calculate_cleaning_duration_seconds(roof_dirty: float) -> float:
    """Menghitung estimasi durasi siklus pembersihan (detik) berdasarkan tingkat kotor atap (0 - 100%)."""
    clamped_dirty = max(0.0, min(100.0, float(roof_dirty)))
    ratio = max(0.0, min(1.0, clamped_dirty / DIRTY_CYCLE_CAP))
    duration = MIN_CLEAN_CYCLE_SECONDS + ratio * (MAX_CLEAN_CYCLE_SECONDS - MIN_CLEAN_CYCLE_SECONDS)
    return round(duration, 1)


def _calculate_spray_seconds_from_dirt(roof_dirty: float) -> float:
    """Menghitung durasi siklus proporsional terhadap tingkat kotor atap."""
    return calculate_cleaning_duration_seconds(roof_dirty)


def _now_wib() -> datetime:
    return datetime.now(WIB)


def _now_timestamp_str() -> str:
    return _now_wib().strftime("%Y-%m-%d %H:%M:%S WIB")


def _now_short_time() -> str:
    return _now_wib().strftime("%H:%M:%S")


def _default_state() -> dict[str, Any]:
    return {
        "force_dirty_next": False,
        "force_clean_after_cleaning": False,
        "last_generated_mono": 0.0,
        "current_report": None,
        "realtime_history": [],
        "extra_cleaned_dates": {},
    }


def _load_state() -> dict[str, Any]:
    if not _STATE_FILE.exists():
        return _default_state()
    try:
        raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        base = _default_state()
        base.update(raw)
        if not isinstance(base.get("realtime_history"), list):
            base["realtime_history"] = []
        if not isinstance(base.get("extra_cleaned_dates"), dict):
            base["extra_cleaned_dates"] = {}
        return base
    except (json.JSONDecodeError, OSError):
        return _default_state()


def _save_state(state: dict[str, Any]) -> None:
    tmp_file = _STATE_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp_file.replace(_STATE_FILE)


def force_dirty_state() -> None:
    """Mengaktifkan flag agar data realtime berikutnya berada dalam kondisi perlu dibersihkan."""
    state = _load_state()
    state["force_dirty_next"] = True
    state["force_clean_after_cleaning"] = False
    state["last_generated_mono"] = 0.0
    _save_state(state)


def mark_cleaning_completed() -> None:
    """Menandai bahwa cleaning selesai dijalankan: data realtime berikutnya bersih & hari ini tercatat."""
    state = _load_state()
    today_str = _now_wib().strftime("%Y-%m-%d")
    extra = dict(state.get("extra_cleaned_dates") or {})
    if today_str not in extra:
        extra[today_str] = _now_timestamp_str()

    state["extra_cleaned_dates"] = extra
    state["force_clean_after_cleaning"] = True
    state["force_dirty_next"] = False
    state["last_generated_mono"] = 0.0
    _save_state(state)


def _build_report_from_values(
    light_transmission: float,
    roof_dirty: float,
    system_health: str,
    timestamp_str: str | None = None,
    time_label: str | None = None,
    stable_score: bool = False,
) -> dict[str, Any]:
    light_transmission = round(max(5.0, min(99.0, light_transmission)), 1)
    roof_dirty = round(max(1.0, min(95.0, roof_dirty)), 1)

    needs_cleaning = roof_dirty >= 20.0 or light_transmission <= 70.0
    cleaning_recommendation = "CLEANING" if needs_cleaning else "TIDAK PERLU"

    spray_seconds = _calculate_spray_seconds_from_dirt(roof_dirty)
    estimated_water_liters = calculate_water_usage_liters(spray_seconds)

    if system_health == "BAD" and not needs_cleaning:
        ai_status = "WARNING"
        ai_score = 72 if stable_score else random.randint(65, 78)
    elif not needs_cleaning and system_health == "NORMAL":
        ai_status = "GOOD"
        raw_score = 96.0 - (roof_dirty * 0.35) - max(0.0, (88.0 - light_transmission) * 0.25)
        jitter = 0.0 if stable_score else random.uniform(-1.5, 1.5)
        ai_score = int(round(max(82.0, min(98.0, raw_score + jitter))))
    elif light_transmission < 30.0 or roof_dirty >= 50.0:
        ai_status = "CRITICAL"
        ai_score = 45 if stable_score else random.randint(35, 55)
    else:
        ai_status = "WARNING"
        raw_warn = 80.0 - max(0.0, (roof_dirty - 20.0) * 0.55) - max(0.0, (70.0 - light_transmission) * 0.35)
        jitter = 0.0 if stable_score else random.uniform(-1.5, 1.5)
        ai_score = int(round(max(60.0, min(82.0, raw_warn + jitter))))

    return {
        "ai_status": ai_status,
        "ai_score": ai_score,
        "light_transmission": light_transmission,
        "roof_dirty": roof_dirty,
        "cleaning_recommendation": cleaning_recommendation,
        "system_health": system_health,
        "spray_seconds": spray_seconds,
        "estimated_water_liters": estimated_water_liters,
        "updated_at": timestamp_str or _now_timestamp_str(),
        "time_label": time_label or _now_short_time(),
    }


def _generate_gradual_report(
    prev_report: dict[str, Any] | None,
    force_dirty_next: bool,
    force_clean_after_cleaning: bool,
) -> dict[str, Any]:
    """Menghasilkan data realtime yang bergerak gradual, dengan perubahan kontras saat cleaning / /f."""
    if force_clean_after_cleaning:
        clean_dirty = round(random.uniform(3.0, 8.0), 1)
        clean_light = round(random.uniform(86.0, 94.0), 1)
        return _build_report_from_values(
            light_transmission=clean_light,
            roof_dirty=clean_dirty,
            system_health="NORMAL",
        )

    if force_dirty_next:
        dirty_val = round(random.uniform(38.0, 62.0), 1)
        light_val = round(random.uniform(36.0, 58.0), 1)
        health_val = random.choices(["NORMAL", "BAD"], weights=[0.85, 0.15], k=1)[0]
        return _build_report_from_values(
            light_transmission=light_val,
            roof_dirty=dirty_val,
            system_health=health_val,
        )

    if prev_report is None:
        return _build_report_from_values(
            light_transmission=88.0,
            roof_dirty=6.0,
            system_health="NORMAL",
        )

    prev_dirty = float(prev_report.get("roof_dirty", 6.0))
    prev_light = float(prev_report.get("light_transmission", 88.0))
    prev_health = str(prev_report.get("system_health", "NORMAL"))

    dirty_delta = random.uniform(0.3, 1.2)
    next_dirty = prev_dirty + dirty_delta
    next_light = prev_light - (dirty_delta * 0.65) + random.uniform(-0.8, 0.8)

    if prev_health == "NORMAL":
        next_health = "BAD" if random.random() < 0.03 else "NORMAL"
    else:
        next_health = "NORMAL" if random.random() < 0.30 else "BAD"

    return _build_report_from_values(
        light_transmission=next_light,
        roof_dirty=next_dirty,
        system_health=next_health,
    )


def get_gh_report(force_refresh: bool = False) -> dict[str, Any]:
    """Mengambil data kondisi greenhouse realtime dengan cache singkat dan riwayat realtime."""
    state = _load_state()
    now = time.monotonic()
    last_gen = float(state.get("last_generated_mono") or 0.0)
    current = state.get("current_report")

    should_generate = (
        force_refresh
        or current is None
        or state.get("force_dirty_next")
        or state.get("force_clean_after_cleaning")
        or (now - last_gen) >= _CACHE_TTL_SECONDS
    )

    if should_generate:
        report = _generate_gradual_report(
            prev_report=current if isinstance(current, dict) else None,
            force_dirty_next=bool(state.get("force_dirty_next")),
            force_clean_after_cleaning=bool(state.get("force_clean_after_cleaning")),
        )
        state["current_report"] = report
        state["last_generated_mono"] = now
        state["force_dirty_next"] = False
        state["force_clean_after_cleaning"] = False

        history = list(state.get("realtime_history") or [])
        history.append(
            {
                "time": report["time_label"],
                "light_transmission": report["light_transmission"],
                "roof_dirty": report["roof_dirty"],
                "ai_score": report["ai_score"],
            }
        )
        state["realtime_history"] = history[-_MAX_REALTIME_POINTS:]
        _save_state(state)
        return report

    return current


def _weather_profile_for_date(d: date) -> dict[str, float]:
    """
    Profil cuaca/musim:
    - Jul s/d Sep: kemarau (debu lebih cepat menumpuk, peluang pembersihan lebih sering).
    - Okt awal: transisi awal.
    - Okt akhir s/d Nov+: lebih basah/berawan (penumpukan debu lebih pelan, pembersihan lebih jarang).
    """
    if d.month in (7, 8, 9):
        return {
            "dust_gain_min": 4.5,
            "dust_gain_max": 9.5,
            "light_loss_factor": 0.72,
            "clean_chance_low": 0.10,
            "clean_chance_med": 0.35,
            "clean_chance_high": 0.75,
        }
    if d.month == 10 and d.day < 20:
        return {
            "dust_gain_min": 3.0,
            "dust_gain_max": 7.0,
            "light_loss_factor": 0.62,
            "clean_chance_low": 0.05,
            "clean_chance_med": 0.22,
            "clean_chance_high": 0.55,
        }
    return {
        "dust_gain_min": 1.5,
        "dust_gain_max": 4.8,
        "light_loss_factor": 0.50,
        "clean_chance_low": 0.02,
        "clean_chance_med": 0.12,
        "clean_chance_high": 0.35,
    }


def build_daily_summaries(
    start_date: date = _START_DATE,
    end_date: date | None = None,
    extra_cleaned_dates: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Menghasilkan 1 summary harian sejak Juli 2026 dengan pola penumpukan debu dan
    pembersihan acak yang menyesuaikan kondisi musim/cuaca (tidak terjadwal kaku).
    """
    if end_date is None:
        end_date = _now_wib().date()
    if end_date < start_date:
        end_date = start_date

    extra_cleaned = extra_cleaned_dates or {}
    summaries: list[dict[str, Any]] = []
    rng = random.Random(20260701)

    dirty_val = 5.0
    light_val = 90.0

    cur = start_date
    while cur <= end_date:
        date_str = cur.isoformat()
        profile = _weather_profile_for_date(cur)
        extra_clean_ts = extra_cleaned.get(date_str)

        if extra_clean_ts:
            was_cleaned = True
        else:
            if dirty_val >= 46.0:
                clean_prob = 0.90
            elif dirty_val >= 28.0:
                clean_prob = profile["clean_chance_high"]
            elif dirty_val >= 18.0:
                clean_prob = profile["clean_chance_med"]
            else:
                clean_prob = profile["clean_chance_low"]
            was_cleaned = rng.random() < clean_prob

        if was_cleaned:
            dirty_val = round(rng.uniform(3.0, 8.0), 1)
            light_val = round(rng.uniform(86.0, 93.0), 1)
            cleaned_at = extra_clean_ts or f"{date_str} {rng.randint(7, 16):02d}:{rng.randint(0, 59):02d}:00 WIB"
        else:
            gain = rng.uniform(profile["dust_gain_min"], profile["dust_gain_max"])
            dirty_val = min(55.0, dirty_val + gain)
            light_val = max(44.0, light_val - (gain * profile["light_loss_factor"]) + rng.uniform(-1.2, 1.2))
            cleaned_at = None

        day_report = _build_report_from_values(
            light_transmission=light_val,
            roof_dirty=dirty_val,
            system_health="NORMAL",
            timestamp_str=f"{date_str} 18:00:00 WIB",
            time_label=date_str[5:],  # MM-DD
            stable_score=True,
        )

        summaries.append(
            {
                "date": date_str,
                "month": f"{cur.year:04d}-{cur.month:02d}",
                "cleaned": was_cleaned,
                "cleaned_at": cleaned_at,
                **day_report,
            }
        )

        cur += timedelta(days=1)

    return summaries


def get_dashboard_payload(
    force_refresh: bool = False,
    month: str | None = None,
) -> dict[str, Any]:
    """Mengembalikan data realtime, grafik realtime, serta summary harian & riwayat cleaning per bulan."""
    report = get_gh_report(force_refresh=force_refresh)
    state = _load_state()
    extra_cleaned = state.get("extra_cleaned_dates") or {}

    all_daily = build_daily_summaries(
        start_date=_START_DATE,
        end_date=_now_wib().date(),
        extra_cleaned_dates=extra_cleaned if isinstance(extra_cleaned, dict) else {},
    )

    available_months = sorted({item["month"] for item in all_daily}, reverse=True)
    selected_month = (
        month
        if (month and month in available_months)
        else ("ALL" if month == "ALL" else (available_months[0] if available_months else "ALL"))
    )

    if selected_month == "ALL":
        filtered_daily = all_daily
    else:
        filtered_daily = [item for item in all_daily if item["month"] == selected_month]

    cleaning_events = [
        {
            "date": item["date"],
            "cleaned_at": item["cleaned_at"],
            "roof_dirty_after": item["roof_dirty"],
            "light_transmission_after": item["light_transmission"],
        }
        for item in filtered_daily
        if item["cleaned"]
    ]

    return {
        "report": report,
        "realtime_history": state.get("realtime_history") or [],
        "available_months": available_months,
        "selected_month": selected_month,
        "daily_summaries": filtered_daily,
        "cleaning_events": cleaning_events,
    }


def get_cleaning_plan(
    roof_dirty: float | None = None,
    total_duration_sec: float | None = None,
) -> dict[str, Any]:
    """Menyiapkan rencana estimasi pembersihan atap IoT berdasarkan tingkat kotor atap."""
    if total_duration_sec is not None:
        duration = round(max(1.0, float(total_duration_sec)), 2)
    else:
        dirty_val = (
            float(roof_dirty)
            if roof_dirty is not None
            else float(get_gh_report().get("roof_dirty", 0.0))
        )
        duration = calculate_cleaning_duration_seconds(dirty_val)

    water_liters = calculate_water_usage_liters(duration)
    return {
        "device_id": "GH-ROOF-CLEANER-01",
        "pump_capacity_m3_per_hour": PUMP_CAPACITY_M3_PER_HOUR,
        "total_duration_sec": duration,
        "estimated_water_liters": water_liters,
    }