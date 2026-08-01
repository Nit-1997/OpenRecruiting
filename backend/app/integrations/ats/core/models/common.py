"""Provider-agnostic shared model primitives."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of a cursor-paginated ATS listing."""

    items: list[T]
    next_page_token: str | None = None
