"""Cache settings."""
from pydantic import BaseModel


class CacheSettings(BaseModel):
    enable_prefix_caching: bool = True
