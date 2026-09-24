# pyright: basic, reportMissingImports=false
"""Public API request and response models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    account: str = Field(min_length=1, max_length=120)
    password: SecretStr


class IdentityResponse(BaseModel):
    user_id: uuid.UUID
    account: str
    role: str
    class_id: uuid.UUID
    csrf_token: str
    expires_at: datetime


class MaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    content_type: str
    byte_size: int
    sha256: str
    uploader_id: uuid.UUID
    created_at: datetime
