"""Request and response contracts shared by protected backtest routes."""

from pydantic import BaseModel, Field


class BacktestCsrfResponse(BaseModel):
    csrf_token: str = Field(min_length=20)


class BacktestLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class BacktestLoginResponse(BaseModel):
    csrf_token: str = Field(min_length=20)


class BacktestLogoutResponse(BaseModel):
    status: str = "logged_out"
