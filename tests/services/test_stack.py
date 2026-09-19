import json
import os
import pickle
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from neftecode.services.stack import command_plan, run


ROOT = Path(__file__).parents[2]

POSIX_ONLY_STOP = pytest.mark.skipif(
    sys.platform == "win32",
    reason="stack.py останавливает сервисы по группе процессов POSIX (os.killpg, SIGTERM/SIGKILL, "
           "start_new_session); на Windows групп процессов в этом виде нет, а SIGTERM доставляется "
           "как TerminateProcess с кодом 1 без обработчика. Остановка стека на Windows не реализована.")


def test_stack_plan_uses_four_modules_and_default_ports(tmp_path):
    args = SimpleNamespace(root=tmp_path, artifacts=tmp_path / "artifacts", host=None,
                           data_port=None, model_port=None, decision_port=None,
                           gateway_port=None, timeout=1.0)
    commands, urls = command_plan(args)
    assert [command[2] for command in commands] == [
        "neftecode.services.data_service", "neftecode.services.model_service",
        "neftecode.services.decision_service", "neftecode.services.gateway_service"]
    assert [urls[name] for name in ("data", "model", "decision", "gateway")] == [
        "http://127.0.0.1:8766", "http://127.0.0.1:8767",
        "http://127.0.0.1:8768", "http://127.0.0.1:8765"]


def test_stack_plan_honours_explicit_ports(tmp_path):
    args = SimpleNamespace(root=Path(tmp_path), artifacts=Path(tmp_path), host="127.0.0.2",
                           data_port=19001, model_port=19002, decision_port=19003,
                           gateway_port=19004, timeout=1.0)
    _, urls = command_plan(args)
    assert urls["gateway"] == "http://127.0.0.2:19004"


def test_stack_plan_honours_env_ports_including_8765(tmp_path, monkeypatch):
    monkeypatch.setenv("NEFTECODE_DATA_PORT", "8765")
    args = SimpleNamespace(root=tmp_path, artifacts=tmp_path, host=None,
                           data_port=None, model_port=None, decision_port=None,
                           gateway_port=None, timeout=1.0)
    _, urls = command_plan(args)
    assert urls["data"] == "http://127.0.0.1:8765"


@POSIX_ONLY_STOP
def test_stack_cleans_started_process_groups_when_a_child_fails(tmp_path, monkeypatch):
    class Process:
        next_pid = 30000

        def __init__(self, failed=False):
            self.pid = Process.next_pid
            Process.next_pid += 1
            self.failed = failed
            self.waited = False

        def poll(self):
            return 1 if self.failed else None

        def wait(self, timeout):
            self.waited = True
            return 0

    processes = []

    def popen(_command, **_kwargs):
        process = Process(failed=not processes)
        processes.append(process)
        return process

    killed = []
    monkeypatch.setattr(os, "killpg", lambda pid, signum: killed.append((pid, signum)))
    args = SimpleNamespace(root=tmp_path, artifacts=tmp_path, host=None,
                           data_port=19011, model_port=19012, decision_port=19013,
                           gateway_port=19014, timeout=0.1)
    assert run(args, popen=popen) == 1
    assert {pid for pid, signum in killed if signum == signal.SIGTERM} == {
        process.pid for process in processes[1:]
    }
    assert all(process.waited for process in processes)


def _free_ports(count):
    sockets = []
    try:
        for _ in range(count):
            server = socket.socket()
            server.bind(("127.0.0.1", 0))
            sockets.append(server)
        return [server.getsockname()[1] for server in sockets]
    finally:
        for server in sockets:
            server.close()


def _minimal_root(tmp_path):
    scenario_dir = tmp_path / "config" / "scenarios"
    scenario_dir.mkdir(parents=True)
    scenario_dir.joinpath("baseline.json").write_bytes(
        (ROOT / "config" / "scenarios" / "baseline.json").read_bytes()
    )
    tmp_path.joinpath("config", "experiment.json").write_bytes(
        (ROOT / "config" / "experiment.json").read_bytes()
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    manifest = {"fingerprint": "stack-smoke"}
    bundle = {
        "config": {"calibration_end": "2025-07-01"},
        "models": {}, "columns": {}, "selected": "last_pak", "fallback": "last_lab",
        "radii": {"last_pak": 0.1, "last_lab": 0.2}, "manifest": manifest,
    }
    with artifacts.joinpath("model.pkl").open("wb") as stream:
        pickle.dump(bundle, stream)
    artifacts.joinpath("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return artifacts


@POSIX_ONLY_STOP
def test_real_stack_starts_routes_and_stops_all_processes(tmp_path):
    artifacts = _minimal_root(tmp_path)
    data, model, decision, gateway = _free_ports(4)
    command = [
        sys.executable, "-m", "neftecode.services.stack", "--root", str(tmp_path),
        "--artifacts", str(artifacts), "--data-port", str(data),
        "--model-port", str(model), "--decision-port", str(decision),
        "--gateway-port", str(gateway), "--timeout", "15",
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8")
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.stderr.read())
            try:
                with urlopen(f"http://127.0.0.1:{gateway}/readyz", timeout=.5) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError("gateway не стал готов")

        with urlopen(f"http://127.0.0.1:{gateway}/api/decide?scenario=baseline",
                     timeout=10) as response:
            payload = json.loads(response.read())
        assert payload["decision"]["decision_id"]

        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 0
        for port in (data, model, decision, gateway):
            probe = socket.socket()
            probe.settimeout(.2)
            try:
                assert probe.connect_ex(("127.0.0.1", port)) != 0
            finally:
                probe.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
