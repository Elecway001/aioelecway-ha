"""Exercise the client against local WebSocket servers."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from aioelecway import ElecwayError, StorageClient

REPORT = {
    "topic": "/S3-20-EW02-08/ES25082799999/event/storage/mini/post",
    "payload": {"outputPower": 797.3},
}


@pytest.fixture
async def session() -> AsyncIterator[ClientSession]:
    """Provide a caller-owned HTTP session."""
    async with ClientSession() as client_session:
        yield client_session


async def test_reconnect(
    session: ClientSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remote close invalidates telemetry and the next connection recovers."""
    monkeypatch.setattr("aioelecway.client.RECONNECT_DELAY", 0)

    async def handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        await websocket.send_json(REPORT)
        await websocket.close()
        return websocket

    app = web.Application()
    app.router.add_get("/", handler)
    async with TestServer(app) as server:
        client = StorageClient(session, server.host, server.port)
        initial = await client.connect()
        stream = client.updates()
        assert await anext(stream) is None
        assert await anext(stream) == initial
        await stream.aclose()
        assert not session.closed


async def test_missing_telemetry_times_out(
    session: ClientSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open socket and unrelated reports do not establish availability."""
    monkeypatch.setattr("aioelecway.client.REPORT_TIMEOUT", 0.05)

    async def handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        await websocket.send_str("invalid json")
        await websocket.send_json({"topic": "/other/sn/info/post", "payload": {}})
        await websocket.receive()
        return websocket

    app = web.Application()
    app.router.add_get("/", handler)
    async with TestServer(app) as server:
        client = StorageClient(session, server.host, server.port)
        with pytest.raises(ElecwayError):
            await client.connect()
        assert client._websocket is None
        assert not session.closed


async def test_cancel_connect_closes_socket(session: ClientSession) -> None:
    """Cancelling a configuration probe releases its WebSocket."""
    connected = asyncio.Event()

    async def handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        connected.set()
        await websocket.receive()
        return websocket

    app = web.Application()
    app.router.add_get("/", handler)
    async with TestServer(app) as server:
        client = StorageClient(session, server.host, server.port)
        task = asyncio.create_task(client.connect())
        await connected.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client._websocket is None
        assert not session.closed


async def test_cancel_updates_closes_socket(session: ClientSession) -> None:
    """Cancelling a running subscription releases its connection."""

    async def handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        await websocket.send_json(REPORT)
        await websocket.receive()
        return websocket

    app = web.Application()
    app.router.add_get("/", handler)
    async with TestServer(app) as server:
        client = StorageClient(session, server.host, server.port)
        await client.connect()
        stream = client.updates()
        task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client._websocket is None
        assert not session.closed
