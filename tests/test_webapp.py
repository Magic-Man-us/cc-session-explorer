"""create_app wires the health endpoint the plugin's uptime monitor polls, and
SystemdActivation decides whether we were handed a socket-activated fd."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.webapp import SystemdActivation, create_app


def test_healthz_reports_ok(tmp_path: Path) -> None:
    app = create_app(ExplorerSettings(home_dir=tmp_path))
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_spa_fallback_serves_the_shell_for_a_client_side_route(tmp_path: Path) -> None:
    app = create_app(ExplorerSettings(home_dir=tmp_path))
    with TestClient(app) as client:
        root = client.get("/")
        deep_link = client.get("/context/sessions/aaaa-1111")
    assert deep_link.status_code == 200
    assert deep_link.text == root.text


def test_spa_fallback_404s_an_unknown_api_path(tmp_path: Path) -> None:
    app = create_app(ExplorerSettings(home_dir=tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/does-not-exist")
    assert response.status_code == 404


def test_systemd_activation_claims_the_fd_when_pid_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "1")
    assert SystemdActivation().fd == 3


def test_systemd_activation_ignores_a_fd_meant_for_another_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LISTEN_PID", str(os.getpid() + 1))
    monkeypatch.setenv("LISTEN_FDS", "1")
    assert SystemdActivation().fd is None


def test_systemd_activation_none_when_not_socket_activated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LISTEN_PID", raising=False)
    monkeypatch.delenv("LISTEN_FDS", raising=False)
    assert SystemdActivation().fd is None
