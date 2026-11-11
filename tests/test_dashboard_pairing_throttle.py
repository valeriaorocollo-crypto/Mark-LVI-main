from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket
import ssl
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from dashboard import server
from dashboard.server import DashboardServer


class DashboardPairingThrottleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = DashboardServer()

    def _client(self, address: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=self.server.app, client=(address, 1234)
            ),
            base_url="http://dashboard.test",
        )

    def _auth(self) -> dict[str, str]:
        token = "test-session-token"
        self.server._tokens[token] = time.time()
        return {"authorization": f"Bearer {token}"}

    async def test_dashboard_startup_does_not_modify_firewall(self):
        class ProbeSocket:
            def bind(self, _address) -> None:
                pass

            def close(self) -> None:
                pass

        with (
            patch.object(server, "_DEPS_OK", True),
            patch.object(self.server, "_https_requested", return_value=False),
            patch.object(self.server, "_ssl_enabled", return_value=False),
            patch.object(self.server, "get_url", return_value="http://127.0.0.1"),
            patch.object(server.uvicorn, "Config"),
            patch.object(server.uvicorn, "Server") as uvicorn_server,
            patch("socket.socket", return_value=ProbeSocket()),
        ):
            uvicorn_server.return_value.serve = AsyncMock()
            await self.server.serve()

        self.assertFalse(hasattr(server, "_ensure_network_access"))
        uvicorn_server.return_value.serve.assert_awaited_once()

    async def test_auto_login_limits_failed_attempts_and_sets_security_headers(self):
        async with self._client("192.0.2.10") as client:
            for attempt in range(6):
                response = await client.get(
                    "/auto-login",
                    params={"key": f"INVALID{attempt}"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(
                    response.headers["referrer-policy"], "no-referrer"
                )

            blocked = await client.get(
                "/auto-login",
                params={"key": "ANOTHER"},
            )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers["cache-control"], "no-store")
        self.assertEqual(blocked.headers["referrer-policy"], "no-referrer")

    async def test_login_and_auto_login_share_the_same_ip_limit(self):
        async with self._client("192.0.2.20") as client:
            for _ in range(3):
                response = await client.post(
                    "/login",
                    json={"pin": "INVALID"},
                )
                self.assertEqual(response.status_code, 401)

            for attempt in range(3):
                response = await client.get(
                    "/auto-login",
                    params={"key": f"INVALID{attempt}"},
                )
                self.assertEqual(response.status_code, 200)

            blocked = await client.get(
                "/auto-login",
                params={"key": "ANOTHER"},
            )

        self.assertEqual(blocked.status_code, 429)

    async def test_login_rejects_malformed_and_oversized_request_bodies(self):
        async with self._client("192.0.2.21") as client:
            malformed = await client.post(
                "/login", json={"pin": ["not", "a", "pin"]}
            )
        async with self._client("192.0.2.22") as client:
            oversized = await client.post(
                "/login",
                content=b'{"pin":"' + b"x" * 1_024 + b'"}',
                headers={"content-type": "application/json"},
            )

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(oversized.status_code, 413)

    async def test_blocked_request_does_not_consume_a_valid_pairing_key(self):
        pairing_key = self.server.new_key()
        async with self._client("192.0.2.30") as client:
            for attempt in range(6):
                await client.get(
                    "/auto-login",
                    params={"key": f"INVALID{attempt}"},
                )

            blocked = await client.get(
                "/auto-login",
                params={"key": pairing_key},
            )

        self.assertEqual(blocked.status_code, 429)
        self.assertIn(pairing_key, self.server._pending_keys)

        async with self._client("192.0.2.31") as client:
            accepted = await client.get(
                "/auto-login",
                params={"key": pairing_key},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.headers["cache-control"], "no-store")
        self.assertEqual(accepted.headers["referrer-policy"], "no-referrer")
        self.assertNotIn(pairing_key, self.server._pending_keys)

    async def test_http_command_enforces_command_size_limit(self):
        async with self._client("192.0.2.40") as client:
            response = await client.post(
                "/api/command",
                json={"text": "x" * 4_001},
                headers=self._auth(),
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.server._command_queue.qsize(), 0)

    async def test_http_command_rejects_oversized_request_body(self):
        async with self._client("192.0.2.41") as client:
            response = await client.post(
                "/api/command",
                content=b'{"text":"' + b"x" * (32 * 1024) + b'"}',
                headers={**self._auth(), "content-type": "application/json"},
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.server._command_queue.qsize(), 0)

    async def test_http_command_rate_limit_and_queue_capacity(self):
        async with self._client("192.0.2.42") as client:
            for attempt in range(30):
                response = await client.post(
                    "/api/command",
                    json={"text": f"synthetic command {attempt}"},
                    headers=self._auth(),
                )
                self.assertEqual(response.status_code, 200)

            limited = await client.post(
                "/api/command",
                json={"text": "excess command"},
                headers=self._auth(),
            )

        self.assertEqual(limited.status_code, 429)
        self.assertEqual(self.server._command_queue.qsize(), 30)

        self.server._command_queue = asyncio.Queue(maxsize=1)
        self.server._command_queue.put_nowait("already queued")
        async with self._client("192.0.2.43") as client:
            full = await client.post(
                "/api/command",
                json={"text": "another command"},
                headers=self._auth(),
            )

        self.assertEqual(full.status_code, 503)
        self.assertEqual(self.server._command_queue.qsize(), 1)

    async def test_websocket_command_uses_size_and_queue_limits(self):
        token = "websocket-test-token"
        self.server._tokens[token] = time.time()
        with TestClient(self.server.app) as client:
            with client.websocket_connect(f"/ws?token={token}") as websocket:
                websocket.send_text(json.dumps({"type": "command", "text": "x" * 4_001}))
                oversized = websocket.receive_json()
                self.assertEqual(oversized["type"], "error")
                self.assertEqual(self.server._command_queue.qsize(), 0)

                websocket.send_text(json.dumps(
                    {"type": "command", "text": "synthetic websocket command"}
                ))

        self.assertEqual(self.server._command_queue.get_nowait(),
                         "synthetic websocket command")

    async def test_https_is_default_and_http_requires_explicit_opt_out(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir()
            config_file = config_dir / "api_keys.json"
            with patch("dashboard.server.BASE_DIR", Path(temp_dir)):
                self.assertTrue(DashboardServer._https_requested())
                self.assertTrue(self.server.get_url().startswith("https://"))

                config_file.write_text(
                    json.dumps({"dashboard_https": False}), encoding="utf-8"
                )
                self.assertFalse(DashboardServer._https_requested())
                self.assertTrue(self.server.get_url().startswith("http://"))

    def test_https_certificate_pair_is_generated_and_loadable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            with (
                patch("dashboard.server.BASE_DIR", root),
                patch("dashboard.server._local_ip", return_value="127.0.0.1"),
            ):
                self.assertTrue(server._ensure_certs())
                cert_path = root / "config" / "certs" / "jarvis.crt"
                key_path = root / "config" / "certs" / "jarvis.key"
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(str(cert_path), str(key_path))
                self.assertTrue(server._ensure_certs())

    async def test_dashboard_https_is_verified_by_a_local_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            with (
                patch("dashboard.server.BASE_DIR", root),
                patch("dashboard.server._local_ip", return_value="127.0.0.1"),
            ):
                self.assertTrue(server._ensure_certs())
                cert_path = root / "config" / "certs" / "jarvis.crt"
                key_path = root / "config" / "certs" / "jarvis.key"

                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                port = listener.getsockname()[1]
                config = server.uvicorn.Config(
                    self.server.app,
                    host="127.0.0.1",
                    port=port,
                    log_level="critical",
                    ssl_certfile=str(cert_path),
                    ssl_keyfile=str(key_path),
                )
                uvicorn_server = server.uvicorn.Server(config)
                serving = asyncio.create_task(
                    uvicorn_server.serve(sockets=[listener])
                )
                try:
                    deadline = time.monotonic() + 5
                    while not uvicorn_server.started and time.monotonic() < deadline:
                        if serving.done():
                            await serving
                        await asyncio.sleep(0.01)
                    self.assertTrue(uvicorn_server.started)

                    trusted_certificate = ssl.create_default_context(
                        cafile=str(cert_path)
                    )
                    async with httpx.AsyncClient(
                        verify=trusted_certificate,
                        trust_env=False,
                        timeout=5,
                    ) as client:
                        response = await client.get(
                            f"https://127.0.0.1:{port}/"
                        )

                    self.assertEqual(response.status_code, 200)
                finally:
                    uvicorn_server.should_exit = True
                    try:
                        await asyncio.wait_for(serving, timeout=5)
                    finally:
                        listener.close()

    async def test_https_certificate_failure_does_not_downgrade_to_http(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir()
            (config_dir / "api_keys.json").write_text("{}", encoding="utf-8")
            with (
                patch("dashboard.server.BASE_DIR", Path(temp_dir)),
                patch("dashboard.server._ensure_certs", return_value=False),
            ):
                await self.server.serve()

        self.assertIn("not started", self.server._bind_error)

    async def test_device_login_rejects_malformed_and_oversized_requests(self):
        async with self._client("192.0.2.50") as client:
            malformed = await client.post(
                "/api/device-login", json={"device_token": ["not", "a", "token"]}
            )
            oversized = await client.post(
                "/api/device-login",
                content=b'{"device_token":"' + b"x" * 1_024 + b'"}',
                headers={"content-type": "application/json"},
            )

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(oversized.status_code, 413)

    async def test_device_login_is_rate_limited_per_ip(self):
        device_token = "A" * 43
        self.server._device_sessions[device_token] = {"session_key": "KEY12345"}
        async with self._client("192.0.2.51") as client:
            for _ in range(10):
                response = await client.post(
                    "/api/device-login", json={"device_token": "B" * 43}
                )
                self.assertEqual(response.status_code, 401)

            blocked = await client.post(
                "/api/device-login", json={"device_token": device_token}
            )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers["retry-after"], "60")
        self.assertEqual(self.server._tokens, {})

        async with self._client("192.0.2.52") as client:
            accepted = await client.post(
                "/api/device-login", json={"device_token": device_token}
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.headers["cache-control"], "no-store")
        token = accepted.json()["token"]
        self.assertIn(token, self.server._tokens)


if __name__ == "__main__":
    unittest.main()
