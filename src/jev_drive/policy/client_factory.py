"""Explicit provider selection; environment keys never select a provider."""

from .jev_client import JevClient
from .vercel_client import VercelJevClient


def create_client(config, on_event=None):
    clients = {"typesafe": JevClient, "vercel": VercelJevClient}
    return clients[config.backend](config, on_event=on_event)
