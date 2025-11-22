"""
Database Schemas for Citizen Hub

Each Pydantic model represents a collection (lowercased class name).
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal, List
from datetime import datetime

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    preferred_language: Literal["en", "hi"] = Field("en", description="User's preferred language")
    is_active: bool = Field(True, description="Active user")

class Session(BaseModel):
    user_email: EmailStr = Field(...)
    token: str = Field(..., description="Session token (opaque)")
    expires_at: datetime = Field(..., description="Expiry timestamp (UTC)")

class Application(BaseModel):
    user_email: EmailStr
    doc_type: Literal["aadhaar", "pan", "dl", "voter", "passport"]
    status: Literal["draft", "submitted", "in_review", "approved", "rejected"] = "draft"
    reference_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

class Payment(BaseModel):
    user_email: EmailStr
    purpose: str
    amount: float = Field(..., ge=0)
    currency: Literal["INR"] = "INR"
    status: Literal["initiated", "successful", "failed", "refunded"] = "initiated"
    application_ref: Optional[str] = None
    provider_ref: Optional[str] = None

# Search index document for predictive search suggestions
class SearchItem(BaseModel):
    key: str
    label: str
    category: str
    url: str
    keywords: List[str] = Field(default_factory=list)
