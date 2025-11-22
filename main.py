import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from uuid import uuid4

from database import db, create_document, get_documents
from schemas import User, Session, Application, Payment, SearchItem

app = FastAPI(title="Citizen Hub API", description="Public service platform for Indian ID applications")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    preferred_language: Optional[str] = "en"

class LoginResponse(BaseModel):
    token: str
    email: EmailStr
    name: Optional[str] = None

class ApplicationCreate(BaseModel):
    doc_type: str
    metadata: dict = {}

class PaymentInit(BaseModel):
    purpose: str
    amount: float
    application_ref: Optional[str] = None

# Simple in-memory token check is NOT allowed; persist sessions instead

def _collection(name: str):
    return db[name]

@app.get("/")
def root():
    return {"message": "Citizen Hub API running"}

@app.get("/test")
def test_database():
    info = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "collections": []
    }
    try:
        info["database"] = "✅ Connected" if db is not None else "❌ Not Available"
        if db:
            info["collections"] = db.list_collection_names()
    except Exception as e:
        info["database"] = f"⚠️ {str(e)[:80]}"
    return info

# Auth: passwordless email login (demo). In real deployments, integrate OTP/OAuth.
@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Upsert user
    _collection("user").update_one({"email": req.email}, {"$setOnInsert": {"name": req.name or "Citizen", "email": req.email, "preferred_language": req.preferred_language or "en", "is_active": True}}, upsert=True)

    token = uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    create_document("session", Session(user_email=req.email, token=token, expires_at=expires))
    return LoginResponse(token=token, email=req.email, name=req.name)

# Middleware-like dependency to fetch session
class AuthToken(BaseModel):
    token: str

async def get_user_from_token(token: str) -> str:
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    sess = _collection("session").find_one({"token": token, "expires_at": {"$gt": datetime.now(timezone.utc)}})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return sess["user_email"]

# Applications
@app.post("/applications", response_model=dict)
def create_application(payload: ApplicationCreate, token: str):
    user_email = awaitable_get_user(token)
    app_doc = Application(user_email=user_email, doc_type=payload.doc_type, metadata=payload.metadata)
    ref = create_document("application", app_doc)
    return {"reference": ref, "status": app_doc.status}

@app.get("/applications", response_model=List[dict])
def list_applications(token: str):
    user_email = awaitable_get_user(token)
    items = get_documents("application", {"user_email": user_email}, limit=50)
    # Convert ObjectId to string
    for it in items:
        it["_id"] = str(it["_id"])
    return items

# Payments (mock init)
@app.post("/payments/init", response_model=dict)
def init_payment(payload: PaymentInit, token: str):
    user_email = awaitable_get_user(token)
    pay = Payment(user_email=user_email, purpose=payload.purpose, amount=payload.amount, application_ref=payload.application_ref)
    pid = create_document("payment", pay)
    return {"payment_id": pid, "status": "initiated"}

# Predictive search: seed static items and allow prefix search over keywords/label
SEARCH_ITEMS: List[SearchItem] = [
    SearchItem(key="aadhaar", label="Apply for Aadhaar", category="Identity", url="/guide/aadhaar", keywords=["uidai", "uid", "identity", "proof"]),
    SearchItem(key="pan", label="Apply for PAN", category="Tax", url="/guide/pan", keywords=["income tax", "form 49a", "epan"]),
    SearchItem(key="dl", label="Apply for Driving Licence", category="Transport", url="/guide/driving-licence", keywords=["sarathi", "rto", "learner", "dl"]),
    SearchItem(key="voter", label="Register Voter ID", category="Elections", url="/guide/voter", keywords=["epic", "eci", "form 6"]),
    SearchItem(key="passport", label="Apply for Passport", category="Travel", url="/guide/passport", keywords=["psk", "tatkaal", "seva"]),
]

@app.get("/search")
def predictive_search(q: str):
    ql = q.lower().strip()
    results = []
    for item in SEARCH_ITEMS:
        hay = " ".join([item.label, item.category] + item.keywords).lower()
        if ql in hay or any(k.startswith(ql) for k in [item.key] + item.keywords):
            results.append(item.model_dump())
    return {"results": results[:8]}

# Static content endpoints for guides (Plain Language)
GUIDES = {}
GUIDES["aadhaar"] = {
    "title": "Get your Aadhaar Number",
    "summary": "A step-by-step guide to enrol for Aadhaar.",
    "cost": "Free for first-time enrolment",
    "time": "Usually a few weeks; up to 180 days",
    "official": "https://myaadhaar.uidai.gov.in/",
    "steps": [
        "Find a nearby Aadhaar Enrolment Centre.",
        "Fill the enrolment form.",
        "Show original ID and address proofs. They will be scanned and returned.",
        "Give photo, fingerprints, and iris scans.",
        "Check your details on the screen.",
        "Keep the acknowledgement slip with EID to track.",
        "Download e-Aadhaar when ready.",
    ],
}
GUIDES["pan"] = {
    "title": "Get your PAN",
    "summary": "Apply online for a Permanent Account Number (PAN).",
    "cost": "Instant e-PAN: Free; Regular: ~₹101–₹107",
    "time": "Instant in minutes (e-PAN) or ~15–20 days",
    "official": "https://www.incometax.gov.in/",
    "steps": [
        "Choose Instant e-PAN or Regular PAN.",
        "Fill Form 49A (online).",
        "Pay the fee if required.",
        "Use Aadhaar e-KYC if possible (no paperwork).",
        "If not e-KYC, print, sign, and post the form.",
        "Get e-PAN by email; physical card comes by post.",
    ],
}
GUIDES["dl"] = {
    "title": "Get a Driving Licence",
    "summary": "Apply for a Learner's Licence, then take a driving test.",
    "cost": "Varies by State; ~₹200–₹500 for LL; ₹700–₹1,500 for DL",
    "time": "LL: same day after test; DL: after road test",
    "official": "https://sarathi.parivahan.gov.in/",
    "steps": [
        "Apply online for Learner's Licence.",
        "Upload documents and pay the fee.",
        "Book and pass the online test.",
        "Wait 30 days or more.",
        "Apply for Driving Licence and book road test.",
        "Take the test at the RTO. Bring originals.",
    ],
}
GUIDES["voter"] = {
    "title": "Register for Voter ID",
    "summary": "Add your name to the electoral roll (Form 6).",
    "cost": "Free",
    "time": "~30 days to 2 months",
    "official": "https://voters.eci.gov.in/",
    "steps": [
        "Log in to the Voter Services Portal.",
        "Choose Form 6 and fill your details.",
        "Upload photo, ID, address and age proof.",
        "Submit and keep the reference number.",
        "BLO may visit your home for verification.",
        "Get your EPIC after approval.",
    ],
}
GUIDES["passport"] = {
    "title": "Get a Passport",
    "summary": "Create an account and book an appointment at a PSK.",
    "cost": "Normal: ₹1,500 (36 pages); Tatkaal: ₹3,500",
    "time": "Normal: 15–30 days; Tatkaal: 7–14 days",
    "official": "https://passportindia.gov.in/",
    "steps": [
        "Create account at Passport Seva.",
        "Fill application and pay the fee.",
        "Book appointment at PSK/POPSK.",
        "Visit with originals. Biometrics will be taken.",
        "Police Verification will happen.",
        "Passport will be printed and sent by post.",
    ],
}

@app.get("/guides/{key}")
def get_guide(key: str):
    if key not in GUIDES:
        raise HTTPException(status_code=404, detail="Guide not found")
    return GUIDES[key]

# Helper to use dependency-style auth without FastAPI Depends for simplicity in this environment

def awaitable_get_user(token: str) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    sess = _collection("session").find_one({"token": token, "expires_at": {"$gt": datetime.now(timezone.utc)}})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return sess["user_email"]

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
