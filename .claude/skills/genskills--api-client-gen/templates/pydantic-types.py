# src/api/types.py - Pydantic models with strict typing
from pydantic import BaseModel, Field
from typing import Generic, TypeVar, Literal, NewType
from enum import Enum

UserId = NewType("UserId", str)
PostId = NewType("PostId", str)

T = TypeVar("T")

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    next_cursor: str | None = None
    has_more: bool

class ApiSuccess(BaseModel, Generic[T]):
    status: Literal["success"]
    data: T

class ApiFailure(BaseModel):
    status: Literal["error"]
    error: "ApiError"

ApiResponse = ApiSuccess[T] | ApiFailure
