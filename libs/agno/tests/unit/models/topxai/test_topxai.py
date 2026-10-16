import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.topxai import Topxai
from agno.models.utils import get_model, get_model_from_dict


def test_topxai_initialization_with_api_key():
    model = Topxai(id="kimi-k3", api_key="test-api-key")
    assert model.id == "kimi-k3"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://ai.topxea.com/v1"


def test_topxai_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Topxai(id="kimi-k3")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_topxai_initialization_with_env_api_key():
    with patch.dict(os.environ, {"TOPXAI_API_KEY": "env-api-key"}):
        model = Topxai(id="kimi-k3")
        assert model.api_key == "env-api-key"


def test_topxai_client_params():
    model = Topxai(id="kimi-k3", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://ai.topxea.com/v1"


def test_topxai_default_values():
    model = Topxai(api_key="test-api-key")
    assert model.id == "kimi-k3"
    assert model.name == "Topxai"
    assert model.provider == "Topxai"


def test_topxai_resolves_from_string_syntax():
    model = get_model("topxai:kimi-k3")
    assert isinstance(model, Topxai)
    assert model.id == "kimi-k3"


def test_topxai_round_trips_through_dict():
    model = Topxai(id="claude-sonnet-5-5", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Topxai)
    assert rebuilt.id == "claude-sonnet-5-5"
