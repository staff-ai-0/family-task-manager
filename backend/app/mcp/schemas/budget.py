from pydantic import BaseModel
from typing import Optional


class AccountCreate(BaseModel):
    name: str
    account_type: str
    starting_balance: int = 0


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None
