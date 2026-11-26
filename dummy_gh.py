from calendar import monthrange
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

GOOD_MIN_CYCLE_SECONDS = 30.0    # 30 detik saat kondisi sangat bersih (0% dirty)
THRESHOLD_CYCLE_SECONDS = 120.0  # 2 menit tepat saat menyentuh ambang 20% dirty
MAX_CLEAN_CYCLE_SECONDS = 240.0  # 4 menit saat sangat kotor (>= 50% dirty)
DIRTY_CYCLE_CAP = 50.0           # ambang kekotoran penuh untuk durasi maksimum
AUTO_CLEAN_DIRTY_THRESHOLD = 20.0
AUTO_CLEAN_LIGHT_THRESHOLD = 30.0


def calculate_water_usage_liters(duration_seconds: float) -> float:
    """Menghitung pemakaian air (liter) dari pompa 2 m3/jam berdasarkan durasi (detik)."""
    return round(PUMP_FLOW_LITERS_PER_SEC * duration_seconds, 2)


def calculate_cleaning_duration_seconds(roof_dirty: float) -> float:
    """
    Menghitung estimasi durasi siklus pembersihan (detik) berdasarkan tingkat kotor atap (0 - 100%):
    - Kondisi GOOD (0% - 20%): 30s - 120s (di bawah 2 menit).
    - Kondisi CRITICAL (> 20% - 50%+): 120s - 240s (2 - 4 menit).
    """
    clamped_dirty = max(0.0, min(100.0, float(roof_dirty)))
    if clamped_dirty <= AUTO_CLEAN_DIRTY_THRESHOLD:
        ratio = clamped_dirty / AUTO_CLEAN_DIRTY_THRESHOLD
        duration = GOOD_MIN_CYCLE_SECONDS + ratio * (THRESHOLD_CYCLE_SECONDS - GOOD_MIN_CYCLE_SECONDS)
    else:
        over_span = max(1.0, DIRTY_CYCLE_CAP - AUTO_CLEAN_DIRTY_THRESHOLD)
        ratio = max(0.0, min(1.0, (clamped_dirty - AUTO_CLEAN_DIRTY_THRESHOLD) / over_span))
        duration = THRESHOLD_CYCLE_SECONDS + ratio * (MAX_CLEAN_CYCLE_SECONDS - THRESHOLD_CYCLE_SECONDS)
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


def _compute_ai_score(
    roof_dirty: float,
    light_transmission: float,
    system_health: str,
) -> int:
    """Menghitung AI Score secara deterministik sebagai ringkasan kondisi atap & sistem."""
    dirty_penalty = max(0.0, roof_dirty - 3.0) * 2.1
    light_penalty = max(0.0, 100.0 - light_transmission) * 0.45
    health_penalty = 18.0 if system_health != "NORMAL" else 0.0

    score = 98.0 - dirty_penalty - light_penalty - health_penalty
    return int(round(max(25.0, min(98.0, score))))


def _light_from_dirty(roof_dirty: float) -> float:
    """
    Menghitung light_transmission:
    - Saat roof_dirty = 0%, light_transmission = 100.0%.
    - Saat roof_dirty naik hingga 20.0%, light_transmission turun ke 70.0%.
    - Saat roof_dirty > 20.0%, light_transmission turun bertahap hingga menembus < 30.0%.
    """
    clamped_dirty = max(0.0, min(95.0, float(roof_dirty)))
    if clamped_dirty <= AUTO_CLEAN_DIRTY_THRESHOLD:
        light = 100.0 - (clamped_dirty * 1.5)
    else:
        over = clamped_dirty - AUTO_CLEAN_DIRTY_THRESHOLD
        light = 69.8 - (over * 1.2)
    return round(max(5.0, min(100.0, light)), 1)


def _build_report_from_values(
    light_transmission: float,
    roof_dirty: float,
    system_health: str,
    timestamp_str: str | None = None,
    time_label: str | None = None,
) -> dict[str, Any]:
    roof_dirty = round(max(0.0, min(95.0, roof_dirty)), 1)
    light_transmission = round(max(5.0, min(100.0, light_transmission)), 1)

    is_light_trigger = light_transmission < AUTO_CLEAN_LIGHT_THRESHOLD
    cleaning_recommendation = "CLEANING" if is_light_trigger else "TIDAK PERLU"

    spray_seconds = _calculate_spray_seconds_from_dirt(roof_dirty)
    estimated_water_liters = calculate_water_usage_liters(spray_seconds)
    ai_score = _compute_ai_score(roof_dirty, light_transmission, system_health)

    if is_light_trigger or roof_dirty > AUTO_CLEAN_DIRTY_THRESHOLD:
        ai_status = "CRITICAL"
    elif system_health != "NORMAL":
        ai_status = "WARNING"
    else:
        ai_status = "GOOD"

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
    """Menghasilkan data realtime yang bergerak sangat pelan; perubahan besar hanya pada /f atau cleaning."""
    if force_clean_after_cleaning:
        dirty_val = 2.0
        return _build_report_from_values(
            light_transmission=_light_from_dirty(dirty_val),
            roof_dirty=dirty_val,
            system_health="NORMAL",
        )

    if force_dirty_next:
        dirty_val = 58.0
        return _build_report_from_values(
            light_transmission=_light_from_dirty(dirty_val),
            roof_dirty=dirty_val,
            system_health="NORMAL",
        )

    if prev_report is None:
        dirty_val = 2.0
        return _build_report_from_values(
            light_transmission=_light_from_dirty(dirty_val),
            roof_dirty=dirty_val,
            system_health="NORMAL",
        )

    prev_dirty = float(prev_report.get("roof_dirty", 2.0))
    prev_health = str(prev_report.get("system_health", "NORMAL"))

    dirty_step = random.uniform(0.008, 0.025)
    next_dirty = min(AUTO_CLEAN_DIRTY_THRESHOLD + 3.0, prev_dirty + dirty_step)
    next_light = _light_from_dirty(next_dirty)

    if prev_health == "NORMAL":
        next_health = "BAD" if random.random() < 0.005 else "NORMAL"
    else:
        next_health = "NORMAL" if random.random() < 0.35 else "BAD"

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


def _pick_month_clean_days(
    rng: random.Random,
    year: int,
    month: int,
    target_count: int,
    max_gap_days: int,
) -> set[int]:
    """
    Memilih hari pembersihan dalam sebulan secara terdistribusi agar tidak terlalu acak,
    dengan batas jarak maksimal antar pembersihan (max_gap_days) agar tidak bolong terlalu lama.
    """
    _, days_in_month = monthrange(year, month)
    count = max(1, min(target_count, days_in_month))

    selected: list[int] = []
    for idx in range(count):
        start_day = int(round(idx * (days_in_month / count))) + 1
        end_day = int(round((idx + 1) * (days_in_month / count)))
        start_day = max(1, min(days_in_month, start_day))
        end_day = max(start_day, min(days_in_month, end_day))
        selected.append(rng.randint(start_day, end_day))

    chosen_set = set(selected)
    prev_day = 0
    for d in range(1, days_in_month + 1):
        if d in chosen_set:
            prev_day = d
        elif d - prev_day >= max_gap_days:
            chosen_set.add(d)
            prev_day = d

    return chosen_set


def _weather_profile_for_date(d: date) -> dict[str, float]:
    """
    Profil cuaca/musim:
    - Jul s/d Sep: kemarau (~8x/bulan), akumulasi kotor bertahap hingga light < 30%.
    - Okt dan seterusnya: ~seminggu sekali (~4x/bulan), akumulasi kotor lebih landai.
    """
    if d.month in (7, 8, 9):
        return {
            "dust_gain_min": 13.5,
            "dust_gain_max": 18.5,
            "target_cleans_min": 8,
            "target_cleans_max": 9,
            "max_gap_days": 4,
        }
    return {
        "dust_gain_min": 6.8,
        "dust_gain_max": 9.8,
        "target_cleans_min": 4,
        "target_cleans_max": 4,
        "max_gap_days": 9,
    }


def build_daily_summaries(
    start_date: date = _START_DATE,
    end_date: date | None = None,
    extra_cleaned_dates: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Menghasilkan 1 summary harian sejak Juli 2026:
    - Kotoran atap naik secara bertahap dan landai dari hari ke hari sehingga
      intensitas cahaya (light_transmission) turun pelan menuju < 30% sebelum dibersihkan.
    - Pemakaian air pada hari pembersihan dihitung berdasarkan kondisi kotor sebelum dibersihkan
      dengan variasi alami di sekitarnya.
    """
    if end_date is None:
        end_date = _now_wib().date()
    if end_date < start_date:
        end_date = start_date

    extra_cleaned = extra_cleaned_dates or {}
    summaries: list[dict[str, Any]] = []
    rng = random.Random(20260701)

    current_month_key: tuple[int, int] | None = None
    month_random_clean_days: set[int] = set()

    dirty_val = 2.0
    light_val = _light_from_dirty(dirty_val)
    pending_auto_clean_next_day = False

    cur = start_date
    while cur <= end_date:
        ym = (cur.year, cur.month)
        profile = _weather_profile_for_date(cur)
        if ym != current_month_key:
            current_month_key = ym
            clean_count = rng.randint(
                int(profile["target_cleans_min"]),
                int(profile["target_cleans_max"]),
            )
            month_random_clean_days = _pick_month_clean_days(
                rng,
                cur.year,
                cur.month,
                clean_count,
                int(profile["max_gap_days"]),
            )

        date_str = cur.isoformat()
        extra_clean_ts = extra_cleaned.get(date_str)
        dirty_before_clean: float | None = None
        clean_water_liters: float | None = None
        clean_spray_seconds: float | None = None

        if extra_clean_ts or pending_auto_clean_next_day:
            was_cleaned = True
            base_dirty = max(54.0, dirty_val)
            jitter_dirty = rng.uniform(-1.0, 5.5)
            dirty_before_clean = round(
                max(53.5, min(63.0, base_dirty + jitter_dirty)),
                1,
            )
            clean_spray_seconds = _calculate_spray_seconds_from_dirt(dirty_before_clean)
            clean_water_liters = calculate_water_usage_liters(clean_spray_seconds)

            pending_auto_clean_next_day = False
            dirty_val = round(rng.uniform(1.5, 4.5), 1)
            light_val = _light_from_dirty(dirty_val)
            cleaned_at = (
                extra_clean_ts
                if extra_clean_ts
                else f"{date_str} {rng.randint(7, 15):02d}:{rng.randint(0, 59):02d}:00 WIB"
            )
        else:
            was_cleaned = False
            cleaned_at = None

            # Hitung berapa hari lagi menuju hari trigger berikutnya agar kenaikan landai & tidak curam
            days_until_trigger = 1
            probe = cur
            while probe.day not in month_random_clean_days and days_until_trigger < int(profile["max_gap_days"]):
                probe += timedelta(days=1)
                if probe.month != cur.month:
                    break
                days_until_trigger += 1

            target_trigger_dirty = rng.uniform(53.5, 57.5)
            needed_gain = max(0.0, target_trigger_dirty - dirty_val)

            if cur.day in month_random_clean_days:
                # Hari trigger: pastikan melewati ambang cahaya < 30% (dirty >= 53.3%) secara halus
                step_gain = max(rng.uniform(5.5, 11.5), needed_gain)
                dirty_val = round(min(61.0, dirty_val + step_gain), 1)
                pending_auto_clean_next_day = True
            else:
                # Bagi sisa kenaikan secara bertahap di hari-hari sebelum trigger
                avg_step = needed_gain / max(1, days_until_trigger)
                jitter = rng.uniform(0.85, 1.15)
                step_gain = max(2.5, avg_step * jitter)
                dirty_val = round(min(52.5, dirty_val + step_gain), 1)

            light_val = _light_from_dirty(dirty_val)

        day_report = _build_report_from_values(
            light_transmission=light_val,
            roof_dirty=dirty_val,
            system_health="NORMAL",
            timestamp_str=f"{date_str} 18:00:00 WIB",
            time_label=date_str[5:],  # MM-DD
        )

        if was_cleaned and clean_water_liters is not None and clean_spray_seconds is not None:
            day_report["spray_seconds"] = clean_spray_seconds
            day_report["estimated_water_liters"] = clean_water_liters

        summaries.append(
            {
                "date": date_str,
                "month": f"{cur.year:04d}-{cur.month:02d}",
                "cleaned": was_cleaned,
                "cleaned_at": cleaned_at,
                "roof_dirty_before_clean": dirty_before_clean,
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
            "roof_dirty_before": item.get("roof_dirty_before_clean"),
            "roof_dirty_after": item["roof_dirty"],
            "light_transmission_after": item["light_transmission"],
            "estimated_water_liters": item["estimated_water_liters"],
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