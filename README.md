# aioelecway

Asynchronous Python client for local Elecway energy storage telemetry. The
library has no Home Assistant dependency and uses a caller-owned `aiohttp`
session. It only reads telemetry and does not change device settings.

Source repository: <https://github.com/Elecway001/aioelecway-ha>.
The distribution name remains `aioelecway` and the import is `import aioelecway`.

## Requirements

- Python 3.14 or later.
- An Elecway storage device with local WebSocket telemetry enabled, reachable
  on the same network.
- The actual device address and advertised port. Discovery is handled by the
  consumer; this library does not perform mDNS discovery.

The native Home Assistant integration was tested on 2026-09-29 with model
`S3-20-EW02-08`. Compatibility with other models or a minimum firmware version
has not yet been established.

## Installation

Install version `0.1.1` from [PyPI](https://pypi.org/project/aioelecway/0.1.1/):

```sh
python3 -m pip install 'aioelecway==0.1.1'
```

## Development installation

To develop the library, install from the package directory:

```sh
python3 -m pip install -e '.[dev]'
```

## Usage

Set `ELECWAY_HOST` to the device address and `ELECWAY_SERIAL_NUMBER` to its
serial number. Set `ELECWAY_PORT` if the advertised port is not 80.

```python
import asyncio
import os

from aiohttp import ClientSession
from aioelecway import StorageClient


async def main() -> None:
    async with ClientSession() as session:
        client = StorageClient(
            session,
            host=os.environ["ELECWAY_HOST"],
            port=int(os.environ.get("ELECWAY_PORT", "80")),
            serial_number=os.environ["ELECWAY_SERIAL_NUMBER"],
        )
        try:
            data = await client.connect()
            print(data.serial_number, data.model, data.telemetry)
            print("Rated power (W):", data.rated_power)
            async for update in client.updates():
                if update is None:
                    print("Device unavailable; reconnecting")
                else:
                    print(update.telemetry)
        finally:
            await client.disconnect()


asyncio.run(main())
```

`connect()` raises `ElecwayError` if the client cannot establish a connection
and receive a matching full report. The connection timeout is 10 seconds and
the valid report timeout is 30 seconds. `updates()` yields `None` on connection
loss or telemetry timeout and retries after 5 seconds. Each successful
connection must receive a full report before accepting incremental updates.

Call `disconnect()` when finished, including when a consumer cancels iteration.
The caller remains responsible for closing its `ClientSession`.

## Data contract

`StorageData` contains `serial_number`, `model`, and an immutable `Telemetry`.
Power is expressed in W, energy in kWh, and state of charge in percent. Missing
or invalid measurements remain `None`; they are not replaced with zero.
Battery power keeps the sign reported by the device.

Since version `0.1.1`, `StorageData.rated_power` provides rated power in W for
`S2-` and `S3-` models. The final hyphen-separated segment is a positive ASCII
integer representing hundreds of watts: `S3-20-EW02-08` is 800 W and
`S3-20-EW02-10` is 1000 W. Missing, invalid, or zero power codes fall back to
800 W. Other model families return `None`.

This property derives model metadata; it does not measure power or change
device settings. The parsing rule alone does not establish device or firmware
compatibility.

| Field | Unit |
| --- | --- |
| `output_power` | W |
| `pv_power` | W |
| `battery_power` | W |
| `battery_soc` | % |
| `pv_daily_generation` | kWh |
| `pv_total_generation` | kWh |
| `battery_daily_charge` | kWh |
| `battery_total_charge` | kWh |
| `battery_daily_discharge` | kWh |
| `battery_total_discharge` | kWh |

Supported telemetry topics are `event/storage/mini/post`,
`event/storage/group/post`, and `event/storage/group/fast/post`, prefixed with
the model and serial number. Fast reports update the preceding full snapshot.
Unrelated frames do not extend the valid telemetry timeout. Command responses,
cloud MQTT, and other Elecway product categories are outside this package's
initial scope.

## Checks and builds

```sh
python3 -m pytest tests
python3 -m ruff check src tests
python3 -m ruff format --check src tests
python3 -m build
python3 -m twine check --strict dist/*
```

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for the
complete license text.
