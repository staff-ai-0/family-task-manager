"""MCP create schema for the jarvis (scheduled prompts) domain."""

from pydantic import BaseModel


class ScheduleCreate(BaseModel):
    name: str
    prompt: str
    cron_expr: str
    channel: str = "notification"
