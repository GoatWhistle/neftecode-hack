from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .common import ServiceHTTPClient, ServiceError


SERVICES = ("data", "model", "decision", "gateway")


def build_parser():
    parser = argparse.ArgumentParser(description="Нефтекод local service stack")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--host", default=None)
    parser.add_argument("--data-port", type=int, default=None)
    parser.add_argument("--model-port", type=int, default=None)
    parser.add_argument("--decision-port", type=int, default=None)
    parser.add_argument("--gateway-port", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def _port(value, env_name, default):
    if value is not None:
        return value
    raw = os.getenv(env_name)
    return int(raw) if raw else default


def command_plan(args):
    if args.timeout <= 0:
        raise ValueError("timeout должен быть положительным")
    host = args.host or os.getenv("NEFTECODE_STACK_HOST", "127.0.0.1")
    ports = {
        "data": _port(args.data_port, "NEFTECODE_DATA_PORT", 8766),
        "model": _port(args.model_port, "NEFTECODE_MODEL_PORT", 8767),
        "decision": _port(args.decision_port, "NEFTECODE_DECISION_PORT", 8768),
        "gateway": _port(args.gateway_port, "NEFTECODE_GATEWAY_PORT", 8765),
    }
    root, artifacts = str(args.root.resolve()), str(args.artifacts.resolve())
    url_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    urls = {name: f"http://{url_host}:{port}" for name, port in ports.items()}
    return [
        [sys.executable, "-m", "neftecode.services.data_service", "--root", root,
         "--artifacts", artifacts, "--host", host, "--port", str(ports["data"])],
        [sys.executable, "-m", "neftecode.services.model_service", "--root", root,
         "--artifacts", artifacts, "--host", host, "--port", str(ports["model"])],
        [sys.executable, "-m", "neftecode.services.decision_service", "--root", root,
         "--artifacts", artifacts, "--host", host,
         "--port", str(ports["decision"]), "--data-url", urls["data"],
         "--model-url", urls["model"]],
        [sys.executable, "-m", "neftecode.services.gateway_service", "--root", root,
         "--artifacts", artifacts, "--host", host,
         "--port", str(ports["gateway"]), "--data-url", urls["data"],
         "--decision-url", urls["decision"]],
    ], urls


def run(args, popen=subprocess.Popen, client=None):
    commands, urls = command_plan(args)
    client = client or ServiceHTTPClient(timeout_s=1.0)
    processes = []

    def stop_signal(_signum, _frame):
        raise KeyboardInterrupt

    old_handlers = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        for command in commands:
            processes.append(popen(command, start_new_session=True))
        deadline = time.monotonic() + args.timeout
        for name in SERVICES:
            while time.monotonic() < deadline:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError("Сервис завершился во время запуска")
                try:
                    client.request("GET", urls[name] + "/healthz")
                    client.request("GET", urls[name] + "/readyz")
                    break
                except ServiceError:
                    time.sleep(.05)
            else:
                raise RuntimeError(f"Таймаут готовности сервиса {name}")
        print(f"Стек запущен: {urls['gateway']}")
        while True:
            if any(process.poll() is not None for process in processes):
                return 1
            time.sleep(.2)
    except KeyboardInterrupt:
        print("Стек остановлен.")
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"Ошибка запуска стека: {exc}", file=sys.stderr)
        return 1
    finally:
        for name, handler in old_handlers.items():
            signal.signal(name, handler)
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
