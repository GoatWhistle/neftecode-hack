import socket
import urllib.request

import pytest


def _no_network(*args, **kwargs):
    raise AssertionError("network call in tests: agent tests must use ScriptedLLM, PolicyLLM or a mock")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    yield
