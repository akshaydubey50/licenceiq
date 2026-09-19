"""Public authentication request, response, and identity contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class LoginRequest(BaseModel):
    """Credentials for the single server-configured bootstrap account."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    password: SecretStr


class AccessTokenResponse(BaseModel):
    """A short-lived bearer token without account or credential details."""

    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(min_length=1)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)


class AuthenticatedUser(BaseModel):
    """The validated JWT identity passed to protected application operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=200)
