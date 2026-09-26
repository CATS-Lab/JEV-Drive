"""Official TypeSafe JEV adapter; the default public interface.

POST /v1/systemone with TYPESAFE_API_KEY bearer authentication.
See https://docs.typesafe.ai/introduction/quickstart.
"""

from .http_client import HttpJevClient, JevAPIError  # re-export shared error

__all__ = ["JevClient", "JevAPIError"]


class JevClient(HttpJevClient):
    backend = "typesafe"
    key_env = "TYPESAFE_API_KEY"
    source_label = "typesafe_official"
