"""Protocol tests independent of Home Assistant."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from aioelecway.models import StorageData, Telemetry, parse_message

SERIAL = "ES25082799999"
MODEL = "S3-20-EW02-08"


@pytest.fixture
def report() -> dict:
    """Load the recorded firmware report."""
    return json.loads((Path(__file__).parent / "storage_mini.json").read_text())


def test_recorded_units(report: dict) -> None:
    """The confirmed wire units are W and kWh, including negative battery power."""
    data = parse_message(report, SERIAL)
    assert data == StorageData(
        SERIAL,
        MODEL,
        Telemetry(797.3, 803, -3.2, 99, 0.74, 1.72, 0.07, 1.05, 0.06, 0.06),
    )


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        pytest.param("S3-20-EW02-08", 800, id="s3-800w"),
        pytest.param("S3-20-EW02-10", 1000, id="s3-1000w"),
        pytest.param("S2-25-TW01-30", 3000, id="s2-3000w"),
        pytest.param("S2-25-TW01-10", 1000, id="s2-1000w"),
        pytest.param("S3-20-EW02-8", 800, id="single-digit"),
        pytest.param("S3-20-EW02-0010", 1000, id="leading-zeroes"),
        pytest.param("S3-20-EW02-", 800, id="empty-code"),
        pytest.param("S2-", 800, id="missing-model-segments"),
        pytest.param("S3-20-EW02", 800, id="missing-power-code"),
        pytest.param("S3-20-EW02-00", 800, id="zero"),
        pytest.param("S2-25-TW01-invalid", 800, id="invalid-code"),
        pytest.param("S3-20-EW02-+10", 800, id="signed-code"),
        pytest.param("S3-20-EW02-10.0", 800, id="decimal-code"),
        pytest.param("S3-20-EW02- 10", 800, id="whitespace"),
        pytest.param("S3-20-EW02-１０", 800, id="non-ascii-digits"),
        pytest.param("S3-20-EW02-" + "1" * 5000, 800, id="oversized-code"),
        pytest.param("S-A-10", None, id="other-series"),
        pytest.param("UNKNOWN", None, id="unknown-model"),
        pytest.param("S3", None, id="missing-series-separator"),
    ],
)
def test_rated_power(report: dict, model: str, expected: int | None) -> None:
    """Model metadata follows the DC naming rule without changing telemetry."""
    report["topic"] = f"/{model}/{SERIAL}/event/storage/mini/post"
    data = parse_message(report)
    assert data is not None
    assert data.rated_power == expected
    assert data.telemetry.output_power == 797.3


def test_full_report_clears_missing_values(report: dict) -> None:
    """A missing field in a full report must not become zero or stale data."""
    previous = parse_message(report)
    report["payload"] = {"outputPower": 0}
    data = parse_message(report, SERIAL, previous)
    assert data == StorageData(SERIAL, MODEL, Telemetry(output_power=0))


def test_fast_report_retains_counters(report: dict) -> None:
    """Partial fast reports retain counters from the latest full report."""
    previous = parse_message(report)
    report["topic"] = f"/{MODEL}/{SERIAL}/event/storage/group/fast/post"
    report["payload"] = {"outputPower": 0}
    data = parse_message(report, SERIAL, previous)
    assert data is not None
    assert data.telemetry.output_power == 0
    assert data.telemetry.pv_total_generation == 1.72
    assert parse_message(report) is None


def test_group_discharge_alias(report: dict) -> None:
    """The full group report uses a different discharge counter name."""
    report["topic"] = f"/{MODEL}/{SERIAL}/event/storage/group/post"
    report["payload"]["battery"] = {"batteryTotalDischargeHigh": 12.5}
    data = parse_message(report)
    assert data is not None
    assert data.telemetry.battery_total_discharge == 12.5


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="boolean"),
        pytest.param("800", id="string"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
        pytest.param(10**400, id="overflow"),
    ],
)
def test_invalid_measurement(report: dict, value: object) -> None:
    """Invalid values cannot enter HA statistics."""
    report["payload"]["outputPower"] = value
    data = parse_message(report)
    assert data is not None
    assert data.telemetry.output_power is None


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(None, id="null"),
        pytest.param({"topic": 1}, id="invalid-topic"),
        pytest.param({"topic": "/model/sn", "payload": {}}, id="short-topic"),
        pytest.param(
            {"topic": "/m/s/info/post", "payload": {}}, id="info-is-not-telemetry"
        ),
        pytest.param(
            {"topic": "/m/s/event/storage/mini/post", "payload": {}}, id="empty"
        ),
        pytest.param(
            {"topic": "/m/s/event/storage/mini/post", "payload": {"pv": None}},
            id="invalid-pv",
        ),
    ],
)
def test_ignored_frames(message: object) -> None:
    """Unrelated or malformed frames do not establish a device connection."""
    assert parse_message(message) is None


def test_wrong_identity(report: dict) -> None:
    """A frame cannot change the configured serial number or model."""
    assert parse_message(report, "other") is None
    previous = parse_message(report)
    report["topic"] = f"/OTHER/{SERIAL}/event/storage/mini/post"
    assert parse_message(report, SERIAL, previous) is None


def test_batch_identity(report: dict) -> None:
    """A batched frame locks identity after its first valid report."""
    other = deepcopy(report)
    other["topic"] = f"/{MODEL}/OTHER/event/storage/mini/post"
    assert parse_message([None, report, other]) == parse_message(report)
