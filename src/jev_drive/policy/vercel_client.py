"""Optional local-development transport; never selected as a fallback."""

from .http_client import HttpJevClient


class VercelJevClient(HttpJevClient):
    backend = "vercel"
    key_env = "AI_GATEWAY_API_KEY"
    source_label = "vercel_ai_gateway"
    extra_diagnostic_headers = ("x-vercel-id",)
