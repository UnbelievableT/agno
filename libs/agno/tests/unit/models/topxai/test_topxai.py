import asyncio
import os
import runpy
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.topxai import Topxai
from agno.models.utils import get_model, get_model_from_dict


def test_topxai_initialization_with_api_key():
    model = Topxai(id="kimi-k3.1-pro", api_key="test-api-key")
    assert model.id == "kimi-k3.1-pro"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://ai.topxea.com/v1"


def test_topxai_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Topxai(id="kimi-k3.1-pro")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_topxai_initialization_with_env_api_key():
    with patch.dict(os.environ, {"TOPXAI_API_KEY": "env-api-key"}):
        model = Topxai(id="kimi-k3.1-pro")
        assert model.api_key == "env-api-key"


def test_topxai_client_params():
    model = Topxai(id="kimi-k3.1-pro", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://ai.topxea.com/v1"


def test_topxai_default_values():
    model = Topxai(api_key="test-api-key")
    assert model.id == "kimi-k3.1-pro"
    assert model.name == "Topxai"
    assert model.provider == "Topxai"


def test_topxai_resolves_from_string_syntax():
    model = get_model("topxai:kimi-k3.1-pro")
    assert isinstance(model, Topxai)
    assert model.id == "kimi-k3.1-pro"


def test_topxai_round_trips_through_dict():
    model = Topxai(id="claude-sonnet-5-5", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Topxai)
    assert rebuilt.id == "claude-sonnet-5-5"


@pytest.mark.parametrize("example", ["basic.py", "tool_use.py"])
def test_cookbook_reuses_one_async_event_loop(monkeypatch, example):
    calls = []
    async_loops = []

    class ExampleAgent:
        def __init__(self, **kwargs):
            pass

        def print_response(self, prompt, stream=False):
            calls.append(("sync", stream))

        async def aprint_response(self, prompt, stream=False):
            loop = asyncio.get_running_loop()
            if async_loops:
                assert loop is async_loops[0]
            async_loops.append(loop)
            calls.append(("async", stream))

    monkeypatch.setattr("agno.agent.Agent", ExampleAgent)
    path = Path(__file__).resolve().parents[6] / "cookbook" / "90_models" / "topxai" / example
    runpy.run_path(str(path), run_name="__main__")
    assert calls == [("sync", False), ("sync", True), ("async", False), ("async", True)]
