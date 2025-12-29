# app/main.py
from pathlib import Path
import secrets

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware

from .auth import (
    normalize_phone,
    normalize_nid,
    validate_nid,
    hash_password,
    verify_password,
    session_login,
    session_logout,
    session_user_id,
    BCRYPT_MAX_BYTES,
)

from .db import (
    init_db,

    # users
    create_user,
    get_user_by_phone,
    get_user_by_id,
    list_reports_for_user,
    list_claims_for_user,

    # reports/claims existing
    insert_report,
    get_report,
    list_reports,
    set_clarification,
    update_extracted_json,
    update_found_handover,

    create_claim,
    list_claims_for_found,
    get_claim,
    set_claim_status,
    get_approved_claim,

    close_report,
    settle_claim,
    has_settled_claim_for_found,
    create_dispute,
    list_disputes_for_claim,
)

from .nlp import (
    extract,
    dumps_extracted,
)

from .matching import (
    rank_matches,
    explain_match,
)

app = FastAPI()

# IMPORTANT: change this in production
SESSION_SECRET = "dev-session-secret-change-me"
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def _startup():
    init_db()


# ----------------------------
# Helpers
# ----------------------------

def current_user(request: Request):
    uid = session_user_id(request)
    if not uid:
        return None
    return get_user_by_id(uid)


def require_login(request: Request):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)
    return u


def is_office(user: dict) -> bool:
    return bool(user) and (user.get("role") == "office")


def _mask_sensitive(text: str) -> str:
    """Light masking for UI; server still stores full data privately."""
    if not text:
        return ""
    # very simple masking
    out = text
    # emails
    out = out.replace("@", " [at] ")
    return out


# ----------------------------
# Auth routes
# ----------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    u = current_user(request)
    if u:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login_submit(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
):
    phone_norm = normalize_phone(phone)
    u = get_user_by_phone(phone_norm)
    if not u:
        return HTMLResponse("Invalid phone or password.", status_code=400)

    if not verify_password(password, u["password_hash"]):
        return HTMLResponse("Invalid phone or password.", status_code=400)

    session_login(request, int(u["id"]))
    return RedirectResponse(url="/", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    u = current_user(request)
    if u:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "error": None,
            "name": "",
            "phone": "",
            "nid": "",
        },
    )


@app.post("/register")
def register_submit(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    nid: str = Form(...),
    password: str = Form(...),
):
    name_clean = (name or "").strip()
    phone_norm = normalize_phone(phone)
    nid_digits = normalize_nid(nid)

    # bcrypt only supports the first 72 BYTES (not characters).
    # This prevents confusing errors when someone uses long passwords or emoji/Bangla letters.
    if len((password or "").encode("utf-8")) > BCRYPT_MAX_BYTES:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": "Password is too long for bcrypt (max 72 bytes). Please use a shorter password.",
                "name": name_clean,
                "phone": phone_norm,
                "nid": nid_digits,
            },
            status_code=400,
        )

    if not name_clean:
        return HTMLResponse("Name is required.", status_code=400)

    if len(phone_norm) < 8:
        return HTMLResponse("Phone looks invalid.", status_code=400)

    if not validate_nid(nid_digits):
        return HTMLResponse("NID must be 13 or 18 digits.", status_code=400)

    if len(password or "") < 6:
        return HTMLResponse("Password must be at least 6 characters.", status_code=400)

    if get_user_by_phone(phone_norm):
        return HTMLResponse("This phone number is already registered.", status_code=400)

    # ✅ Friendly error handling for bcrypt/passlib limits (and any other hash errors)
    try:
        password_hash = hash_password(password)
    except Exception as e:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": str(e),
                # optional: keep typed fields so the user doesn't retype everything
                "name": name_clean,
                "phone": phone_norm,
                "nid": nid_digits,
            },
            status_code=400,
        )

    uid = create_user(
        name=name_clean,
        phone=phone_norm,
        nid_digits=nid_digits,
        password_hash=password_hash,
        role="user",
    )

    session_login(request, uid)
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    session_logout(request)
    return RedirectResponse(url="/login", status_code=303)


# ----------------------------
# User dashboard
# ----------------------------

@app.get("/me", response_class=HTMLResponse)
def me(request: Request):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    my_lost, my_found = list_reports_for_user(int(u["id"]))
    my_claims = list_claims_for_user(int(u["id"]))

    return templates.TemplateResponse(
        "me.html",
        {
            "request": request,
            "user": u,
            "my_lost": my_lost,
            "my_found": my_found,
            "my_claims": my_claims,
        },
    )


# ----------------------------
# Home + submit reports
# ----------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    lost = list_reports(kind="lost", limit=10)
    found = list_reports(kind="found", limit=10)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": u,
            "lost": lost,
            "found": found,
        },
    )


@app.post("/submit")
def submit_report(
    request: Request,
    kind: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    location_text: str = Form(...),
    event_time: str = Form(None),
    handover_location: str = Form(None),
    contact_info: str = Form(None),
):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    kind = (kind or "").strip().lower()
    if kind not in ("lost", "found"):
        return HTMLResponse("Invalid report type.", status_code=400)

    title = (title or "").strip()
    description = (description or "").strip()
    location_text = (location_text or "").strip()
    event_time = (event_time or "").strip()

    if not title or not description or not location_text:
        return HTMLResponse("Title, description, and location are required.", status_code=400)

    # Extract NLP features
    extracted = extract(f"{title}\n{description}\n{location_text}")
    extracted_json = dumps_extracted(extracted)

    manage_token = None
    if kind == "found":
        manage_token = secrets.token_urlsafe(16)

    report_id = insert_report(
        user_id=int(u["id"]),
        kind=kind,
        title=title,
        description=description,
        location_text=location_text,
        event_time=event_time,
        extracted_json=extracted_json,
        handover_location=handover_location if kind == "found" else "",
        contact_info=contact_info if kind == "found" else "",
        manage_token=manage_token,
    )

    # After submit, redirect to report
    url = f"/report/{report_id}"
    if kind == "found":
        url += "?created=1"
    return RedirectResponse(url=url, status_code=303)


# ----------------------------
# Report view + matching
# ----------------------------

@app.get("/report/{rid}", response_class=HTMLResponse)
def report_view(request: Request, rid: int):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    r = get_report(rid)
    if not r:
        return HTMLResponse("Not found.", status_code=404)

    # Enforce access: allow viewing others too (public-ish but login required)
    # Sensitive fields are controlled in templates / logic.

    # Build matches for opposite kind
    if r["kind"] == "lost":
        candidates = list_reports(kind="found", limit=200)
    else:
        candidates = list_reports(kind="lost", limit=200)

    ranked = rank_matches(r, candidates)
    # Attach explanations
    matches = []
    for cand, score in ranked[:10]:
        matches.append(
            {
                "report": cand,
                "score": score,
                "reason": explain_match(r, cand),
            }
        )

    approved_claim = None
    if r["kind"] == "found":
        approved_claim = get_approved_claim(found_report_id=int(r["id"]))

    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "user": u,
            "report": r,
            "matches": matches,
            "approved_claim": approved_claim,
        },
    )


# ----------------------------
# Clarification
# ----------------------------

@app.post("/report/{rid}/clarify")
def report_clarify(
    request: Request,
    rid: int,
    key: str = Form(...),
    answer: str = Form(...),
):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    r = get_report(rid)
    if not r:
        return HTMLResponse("Not found.", status_code=404)

    if int(r["user_id"]) != int(u["id"]):
        return HTMLResponse("Forbidden.", status_code=403)

    set_clarification(rid, key, answer)
    return RedirectResponse(url=f"/report/{rid}", status_code=303)


# ----------------------------
# Claim flow
# ----------------------------

@app.get("/claim/{lost_id}/{found_id}", response_class=HTMLResponse)
def claim_form(request: Request, lost_id: int, found_id: int):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    lost_r = get_report(lost_id)
    found_r = get_report(found_id)
    if not lost_r or not found_r:
        return HTMLResponse("Not found.", status_code=404)

    # Must be lost->found pair
    if lost_r["kind"] != "lost" or found_r["kind"] != "found":
        return HTMLResponse("Invalid claim pairing.", status_code=400)

    # Do not allow claims on closed/settled found
    if found_r.get("is_closed"):
        return HTMLResponse("This found report is closed. No new claims allowed.", status_code=400)

    if has_settled_claim_for_found(found_id):
        return HTMLResponse("This found report is already settled.", status_code=400)

    return templates.TemplateResponse(
        "claim.html",
        {
            "request": request,
            "user": u,
            "lost": lost_r,
            "found": found_r,
            "error": None,
        },
    )


@app.post("/claim/{lost_id}/{found_id}")
def claim_submit(
    request: Request,
    lost_id: int,
    found_id: int,
    proof_text: str = Form(...),
):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    lost_r = get_report(lost_id)
    found_r = get_report(found_id)
    if not lost_r or not found_r:
        return HTMLResponse("Not found.", status_code=404)

    if lost_r["kind"] != "lost" or found_r["kind"] != "found":
        return HTMLResponse("Invalid claim pairing.", status_code=400)

    if found_r.get("is_closed"):
        return HTMLResponse("This found report is closed. No new claims allowed.", status_code=400)

    if has_settled_claim_for_found(found_id):
        return HTMLResponse("This found report is already settled.", status_code=400)

    proof = (proof_text or "").strip()
    if len(proof) < 10:
        return templates.TemplateResponse(
            "claim.html",
            {
                "request": request,
                "user": u,
                "lost": lost_r,
                "found": found_r,
                "error": "Please provide a bit more proof (at least 10 characters). Do not include phone/email in proof.",
            },
            status_code=400,
        )

    # Store claimant sensitive details from the logged-in user (office-only)
    claim_id = create_claim(
        lost_report_id=lost_id,
        found_report_id=found_id,
        proof_text=proof,
        claimer_name=u.get("name", ""),
        claimer_phone=u.get("phone", ""),
        claimer_nid=u.get("nid_digits", ""),
        claimer_user_id=int(u["id"]) if u.get("id") is not None else None,
    )

    return RedirectResponse(url=f"/report/{found_id}", status_code=303)


# ----------------------------
# Founder manage page
# ----------------------------

@app.get("/manage/{found_id}", response_class=HTMLResponse)
def manage_found(request: Request, found_id: int, token: str = ""):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    found_r = get_report(found_id)
    if not found_r:
        return HTMLResponse("Not found.", status_code=404)

    # Token required
    if not token or token != found_r.get("manage_token"):
        return HTMLResponse("Invalid manage token.", status_code=403)

    claims = list_claims_for_found(found_id)

    disputes_by_claim = {}
    for c in claims:
        disputes_by_claim[int(c["id"])] = list_disputes_for_claim(int(c["id"]))

    return templates.TemplateResponse(
        "claims.html",
        {
            "request": request,
            "user": u,
            "found": found_r,
            "claims": claims,
            "disputes_by_claim": disputes_by_claim,
            "token": token,
        },
    )


@app.post("/manage/{found_id}/approve")
def manage_approve(
    request: Request,
    found_id: int,
    token: str = Form(...),
    claim_id: int = Form(...),
):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    found_r = get_report(found_id)
    if not found_r:
        return HTMLResponse("Not found.", status_code=404)

    if token != found_r.get("manage_token"):
        return HTMLResponse("Invalid manage token.", status_code=403)

    set_claim_status(claim_id, "approved")
    return RedirectResponse(url=f"/manage/{found_id}?token={token}", status_code=303)


@app.post("/manage/{found_id}/reject")
def manage_reject(
    request: Request,
    found_id: int,
    token: str = Form(...),
    claim_id: int = Form(...),
):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    found_r = get_report(found_id)
    if not found_r:
        return HTMLResponse("Not found.", status_code=404)

    if token != found_r.get("manage_token"):
        return HTMLResponse("Invalid manage token.", status_code=403)

    set_claim_status(claim_id, "rejected")
    return RedirectResponse(url=f"/manage/{found_id}?token={token}", status_code=303)


@app.post("/manage/{found_id}/settle")
def manage_settle(
    request: Request,
    found_id: int,
    token: str = Form(...),
    claim_id: int = Form(...),
):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    found_r = get_report(found_id)
    if not found_r:
        return HTMLResponse("Not found.", status_code=404)

    if token != found_r.get("manage_token"):
        return HTMLResponse("Invalid manage token.", status_code=403)

    # Mark claim settled and close both reports
    settle_claim(claim_id)
    close_report(found_id, closed_claim_id=claim_id)
    c = get_claim(claim_id)
    if c:
        close_report(int(c["lost_report_id"]), closed_claim_id=claim_id)

    return RedirectResponse(url=f"/manage/{found_id}?token={token}", status_code=303)


# ----------------------------
# Disputes
# ----------------------------

@app.get("/dispute/{claim_id}", response_class=HTMLResponse)
def dispute_form(request: Request, claim_id: int):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    c = get_claim(claim_id)
    if not c:
        return HTMLResponse("Not found.", status_code=404)

    return templates.TemplateResponse(
        "dispute.html",
        {
            "request": request,
            "user": u,
            "claim": c,
            "error": None,
        },
    )


@app.post("/dispute/{claim_id}")
def dispute_submit(
    request: Request,
    claim_id: int,
    reason: str = Form(...),
):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    c = get_claim(claim_id)
    if not c:
        return HTMLResponse("Not found.", status_code=404)

    reason_clean = (reason or "").strip()
    if len(reason_clean) < 10:
        return templates.TemplateResponse(
            "dispute.html",
            {
                "request": request,
                "user": u,
                "claim": c,
                "error": "Please write a bit more detail (at least 10 characters).",
            },
            status_code=400,
        )

    create_dispute(
        claim_id=claim_id,
        reason=reason_clean,
        reporter_user_id=int(u["id"]),
        reporter_name=u.get("name", ""),
        reporter_phone=u.get("phone", ""),
    )

    # Redirect back to the found report page
    return RedirectResponse(url=f"/report/{c['found_report_id']}", status_code=303)


# ----------------------------
# Office-only: claim detail page
# ----------------------------

@app.get("/office/claim/{claim_id}", response_class=HTMLResponse)
def office_claim_detail(request: Request, claim_id: int):
    u = current_user(request)
    if not u:
        return RedirectResponse(url="/login", status_code=303)

    if not is_office(u):
        return HTMLResponse("Forbidden.", status_code=403)

    c = get_claim(claim_id)
    if not c:
        return HTMLResponse("Not found.", status_code=404)

    lost_r = get_report(int(c["lost_report_id"]))
    found_r = get_report(int(c["found_report_id"]))
    disputes = list_disputes_for_claim(claim_id)

    return templates.TemplateResponse(
        "office_claim.html",
        {
            "request": request,
            "user": u,
            "claim": c,
            "lost": lost_r,
            "found": found_r,
            "disputes": disputes,
        },
    )
