from pydantic import BaseModel, ConfigDict, Field, field_validator


class GoogleSignInStartRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redirect_url: str = Field(default="", max_length=500)

    @field_validator("redirect_url", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()


class GoogleSignInExchangeRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auth_code: str = Field(min_length=1, max_length=4000)
    auth_flow: str = Field(default="", max_length=120)
    redirect_url: str = Field(default="", max_length=500)

    @field_validator("auth_code", "auth_flow", "redirect_url", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()
