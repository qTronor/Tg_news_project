from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    login: str = Field(description="Email or username")
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: UUID
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    email: EmailStr | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class MessageEdit(BaseModel):
    sentiment_score: float | None = Field(None, ge=-1.0, le=1.0)
    sentiment_label: str | None = Field(None, max_length=20)
    topic_label: str | None = Field(None, max_length=200)
    cluster_id: int | None = None
    entities: list[dict] | None = None


class ChannelVisibilityUpdate(BaseModel):
    is_visible: bool


class ChannelInfo(BaseModel):
    channel_name: str
    is_visible: bool
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ReactionRequest(BaseModel):
    reaction: str = Field(pattern=r"^(like|dislike)$")


class ReactionInfo(BaseModel):
    message_event_id: str
    likes: int = 0
    dislikes: int = 0
    user_reaction: str | None = None


class AuditLogEntry(BaseModel):
    id: UUID
    admin_id: UUID | None
    admin_username: str | None = None
    action: str
    target_type: str | None
    target_id: str | None
    old_value: dict | None
    new_value: dict | None
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
