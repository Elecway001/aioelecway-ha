"""Decode storage telemetry without Home Assistant dependencies."""

import math
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class Telemetry:
    """Storage measurements in W, kWh and percent; absent values stay unknown."""

    output_power: float | None = None
    pv_power: float | None = None
    battery_power: float | None = None
    battery_soc: float | None = None
    pv_daily_generation: float | None = None
    pv_total_generation: float | None = None
    battery_daily_charge: float | None = None
    battery_total_charge: float | None = None
    battery_daily_discharge: float | None = None
    battery_total_discharge: float | None = None


@dataclass(frozen=True)
class StorageData:
    """Device identity and its latest telemetry snapshot."""

    serial_number: str
    model: str
    telemetry: Telemetry


def _number(value: object) -> float | None:
    """Reject nonnumeric and nonfinite values at the protocol boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def parse_message(
    message: object,
    serial_number: str | None = None,
    previous: StorageData | None = None,
) -> StorageData | None:
    """Decode matching mini/group reports, including batched WebSocket frames."""
    if isinstance(message, list):
        result = None
        for item in message:
            if update := parse_message(item, serial_number, previous):
                result = previous = update
                serial_number = update.serial_number
        return result
    if not isinstance(message, dict):
        return None
    topic = message.get("topic")
    payload = message.get("payload")
    if not isinstance(topic, str) or not isinstance(payload, dict):
        return None
    parts = topic.strip("/").split("/")
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return None
    kind = "/".join(parts[2:])
    if kind not in (
        "event/storage/mini/post",
        "event/storage/group/post",
        "event/storage/group/fast/post",
    ):
        return None
    model, serial = parts[:2]
    if serial_number is not None and serial != serial_number:
        return None
    if previous and (serial != previous.serial_number or model != previous.model):
        return None
    pv = payload.get("pv", {})
    battery = payload.get("battery", {})
    if not isinstance(pv, dict) or not isinstance(battery, dict):
        return None
    telemetry = Telemetry(
        output_power=_number(payload.get("outputPower")),
        pv_power=_number(pv.get("power")),
        battery_power=_number(battery.get("batteryPower")),
        battery_soc=_number(battery.get("batteryTotalSOC")),
        pv_daily_generation=_number(pv.get("dailyGen")),
        pv_total_generation=_number(pv.get("totalGen")),
        battery_daily_charge=_number(battery.get("batteryDailyCharge")),
        battery_total_charge=_number(battery.get("batteryTotalCharge")),
        battery_daily_discharge=_number(battery.get("batteryDailyDischarge")),
        battery_total_discharge=_number(
            battery.get(
                "batteryTotalDischarge", battery.get("batteryTotalDischargeHigh")
            )
        ),
    )
    if all(getattr(telemetry, field.name) is None for field in fields(Telemetry)):
        return None
    if kind == "event/storage/group/fast/post":
        # Fast reports omit counters; only a full report establishes a baseline.
        if previous is None:
            return None
        telemetry = replace(
            previous.telemetry,
            **{
                field.name: value
                for field in fields(Telemetry)
                if (value := getattr(telemetry, field.name)) is not None
            },
        )
    return StorageData(serial, model, telemetry)
