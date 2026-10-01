"""Typed request contracts shared by simulator services and adapters."""

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    """One requested stock item."""

    sku: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    quantity: int = Field(ge=1, le=100)


class CheckoutRequest(BaseModel):
    """Deterministic checkout input shared by Gateway and Order."""

    order_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    items: tuple[LineItem, ...] = Field(min_length=1, max_length=20)
    amount_minor: int = Field(ge=1, le=10_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
