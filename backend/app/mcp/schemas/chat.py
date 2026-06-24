"""MCP create/update schemas for the chat domain."""

from pydantic import BaseModel


class MessageCreate(BaseModel):
    body: str
