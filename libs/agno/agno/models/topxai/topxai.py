from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Topxai(OpenAILike):
    """
    A class for interacting with TopxAI, an LLM API gateway with an OpenAI-compatible
    Chat Completions endpoint.

    Attributes:
        id (str): The id of the TopxAI model to use. Default is "kimi-k3.1-pro".
        name (str): The name of this chat model instance. Default is "Topxai".
        provider (str): The provider of the model. Default is "Topxai".
        api_key (str): The api key to authorize request to TopxAI.
        base_url (str): The base url to which the requests are sent.
            Defaults to "https://ai.topxea.com/v1".
    """

    id: str = "kimi-k3.1-pro"
    name: str = "Topxai"
    provider: str = "Topxai"
    api_key: Optional[str] = field(default_factory=lambda: getenv("TOPXAI_API_KEY"))
    base_url: str = "https://ai.topxea.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for TOPXAI_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("TOPXAI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="TOPXAI_API_KEY not set. Please set the TOPXAI_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
