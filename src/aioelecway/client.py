"""Local push client with bounded reads and reconnects."""

import asyncio
import json
from collections.abc import AsyncIterator

from aiohttp import ClientError, ClientSession, ClientWebSocketResponse, WSMsgType
from yarl import URL

from .models import StorageData, parse_message

CONNECT_TIMEOUT = 10
REPORT_TIMEOUT = 30
RECONNECT_DELAY = 5


class ElecwayError(Exception):
    """The device could not provide valid storage telemetry."""


class StorageClient:
    """Consume telemetry using a caller-owned session; never change device settings."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int = 80,
        serial_number: str | None = None,
    ) -> None:
        """Initialize the client without opening a connection."""
        self._session = session
        self._url = URL.build(scheme="ws", host=host, port=port)
        self._serial_number = serial_number
        self._websocket: ClientWebSocketResponse | None = None
        self._data: StorageData | None = None

    async def connect(self) -> StorageData:
        """Connect and validate identity from the first full telemetry report."""
        await self.disconnect()
        self._data = None
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._websocket = await self._session.ws_connect(
                    self._url, heartbeat=20, max_msg_size=1024 * 1024
                )
            data = await self._receive()
        except (ClientError, OSError, TimeoutError, ElecwayError) as err:
            await self.disconnect()
            raise ElecwayError("Unable to receive storage telemetry") from err
        except asyncio.CancelledError:
            await self.disconnect()
            raise
        self._serial_number = data.serial_number
        return data

    async def disconnect(self) -> None:
        """Close only the WebSocket, leaving the caller's session open."""
        if self._websocket is not None:
            websocket, self._websocket = self._websocket, None
            await websocket.close()

    async def _receive(self) -> StorageData:
        """Bound time since valid telemetry, even when unrelated frames arrive."""
        assert self._websocket is not None
        async with asyncio.timeout(REPORT_TIMEOUT):
            while True:
                message = await self._websocket.receive()
                if message.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                    raise ElecwayError("Storage WebSocket closed")
                try:
                    decoded = json.loads(message.data)
                except ValueError, UnicodeDecodeError:
                    continue
                if data := parse_message(decoded, self._serial_number, self._data):
                    self._data = data
                    return data

    async def updates(self) -> AsyncIterator[StorageData | None]:
        """Yield reports or an offline marker; reconnect until the consumer cancels."""
        try:
            while True:
                try:
                    data = (
                        await self.connect()
                        if self._websocket is None
                        else await self._receive()
                    )
                except ClientError, OSError, TimeoutError, ElecwayError:
                    await self.disconnect()
                    yield None
                    await asyncio.sleep(RECONNECT_DELAY)
                else:
                    yield data
        finally:
            await self.disconnect()
