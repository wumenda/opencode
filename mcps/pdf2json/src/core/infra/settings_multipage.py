"""Multi-page extraction settings."""
from pydantic import BaseModel


class MultipageSettings(BaseModel):
    multi_page_dpi: int = 300
    multi_page_accept_threshold: float = 0.85
    multi_page_review_threshold: float = 0.6
