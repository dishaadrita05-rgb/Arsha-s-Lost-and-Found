# app/main.py
from __future__ import annotations

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
)

from .db import (
    init_db,
    create_user,
    get_user_by_phone,
    get_user_by_id,
    list_reports_for_user,
    list_claims_for_user,
    insert_report,
    get_report,
    list_reports,
    set_clarification,
    update_extracted_json,
    update_found_handover,
    close_report,
    create_claim,
    list_claims_for_found,
    list_claims_all,
    get_claim,
    get_claim_with_titles,
    set_claim_status,
    get_approved_claim,
    settle_claim,
    has_settled_claim_for_found,
    create_dispute,
    list_disputes_for_claim,
    list_disputes_all,
)

from .nlp import (
    extract,
    dumps_extracted,
    loads_extracted,
    mask_sensitive,
    apply_clarification,
)

from .matching import rank_matches, choose_clarifying_question, compute_match


app = FastAPI(title="Lost & Found Matcher")

SESSION_SECRET = "dev-session-secret-change-me"
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def _startup():
    init_db()


def current_user(request: Request):
    uid = session_user_id(request)
    if not uid:
        return None
    u = get_user_by_id(uid)
    if not u:
        return None
    if int(u.get("is_active") or 0) != 1:
        return None
    return u


def require_login_redirect(request: Request):
    return RedirectResponse(url="/login", status_code=303)


def require_office(user: dict) -> bool:
    return bool(user) and user.get("role") == "office"


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    u = current_user(request)
    if u:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "user": None},
    )


@app.post("/login")
def login_submit(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
):
    phone_norm = normalize_phone(phone)
    u = get_user_by_phone(phone_norm)
    if not u or int(u.get("is_active") or 0) != 1:
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
        {"request": request, "user": None},
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

    try:
        password_hash = hash_password(password)
    except Exception as e:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": str(e),
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


@app.get("/me", response_class=HTMLResponse)
def me(request: Request):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    my_lost = list_reports_for_user(int(u["id"]), kind="lost", include_closed=True)
    my_found = list_reports_for_user(int(u["id"]), kind="found", include_closed=True)
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


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    lost = list_reports("lost")[:10]
    found = list_reports("found")[:10]
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "user": u, "lost": lost, "found": found},
    )


@app.post("/submit")
def submit(
    request: Request,
    kind: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    location_text: str = Form(...),
    event_time: str = Form(None),
    handover_location: str = Form(""),
    contact_info: str = Form(""),
):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    kind = (kind or "").strip().lower()
    if kind not in ("lost", "found"):
        return HTMLResponse("Invalid kind.", status_code=400)

    title = (title or "").strip()
    description = (description or "").strip()
    location_text = (location_text or "").strip()
    event_time = (event_time.strip() if event_time else None)

    combined = f"{title}\n{description}\n{location_text}"
    ex = extract(combined)

    manage_token = None
    if kind == "found":
        manage_token = secrets.token_urlsafe(16)

    same_kind = list_reports(kind)
    duplicate_of = None
    if same_kind:
        recent = same_kind[:200]
        best_score = None
        best_id = None

        dummy_current = {
            "id": -1,
            "kind": kind,
            "title": title,
            "description": description,
            "location_text": location_text,
            "event_time": event_time,
            "extracted_json": dumps_extracted(ex),
        }

        for c in recent:
            m = compute_match(dummy_current, c)
            if best_score is None or m.score > best_score:
                best_score = m.score
                best_id = c["id"]

        if best_score is not None and best_score >= 0.85:
            duplicate_of = int(best_id)

    rid = insert_report(
        kind=kind,
        title=title,
        description=description,
        location_text=location_text,
        event_time=event_time,
        extracted_json=dumps_extracted(ex),
        duplicate_of=duplicate_of,
        owner_user_id=int(u["id"]),
    )

    if kind == "found":
        update_found_handover(
            found_id=rid,
            handover_location=(handover_location or "").strip() or "Public help desk/security point.",
            contact_info=(contact_info or "").strip(),
            manage_token=manage_token,
        )
        return RedirectResponse(url=f"/report/{rid}?created=1", status_code=303)

    return RedirectResponse(url=f"/report/{rid}", status_code=303)


@app.get("/report/{report_id}", response_class=HTMLResponse)
def view_report(request: Request, report_id: int):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    r = get_report(report_id)
    if not r:
        return HTMLResponse("Not found", status_code=404)

    created = (request.query_params.get("created") == "1")

    masked_title = mask_sensitive(r["title"])
    masked_desc = mask_sensitive(r["description"])
    masked_loc = mask_sensitive(r["location_text"])

    r_ex = loads_extracted(r["extracted_json"])

    opposite = "found" if r["kind"] == "lost" else "lost"
    candidates = list_reports(opposite)
    matches = rank_matches(r, candidates, k=5)

    ask_question = False
    if len(matches) >= 2:
        top1 = matches[0].score
        top2 = matches[1].score
        if (top1 < 0.55) or ((top1 - top2) < 0.08):
            ask_question = True
    elif len(matches) == 1:
        ask_question = matches[0].score < 0.55
    else:
        ask_question = True

    top_candidate_rows = []
    for m in matches:
        for c in candidates:
            if int(c["id"]) == int(m.other_id):
                top_candidate_rows.append(c)
                break

    question = None
    if ask_question and not r.get("clarify_key"):
        q = choose_clarifying_question(r, top_candidate_rows[:5])
        if q:
            question = {"key": q[0], "text": q[1]}

    approved_info = {}
    if r["kind"] == "lost":
        for m in matches:
            approved = get_approved_claim(int(r["id"]), int(m.other_id))
            if approved:
                found_rep = get_report(int(m.other_id))
                if found_rep:
                    approved_info[int(m.other_id)] = {
                        "handover_location": found_rep.get("handover_location") or "",
                        "contact_info": found_rep.get("contact_info") or "",
                        "found_is_closed": int(found_rep.get("is_closed") or 0),
                        "claim_id": approved["id"],
                    }

    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "user": u,
            "report": r,
            "report_extracted": r_ex,
            "matches": matches,
            "question": question,
            "masked_title": masked_title,
            "masked_desc": masked_desc,
            "masked_loc": masked_loc,
            "created": created,
            "approved_info": approved_info,
        },
    )


@app.post("/answer/{report_id}")
def answer(
    request: Request,
    report_id: int,
    key: str = Form(...),
    answer: str = Form(...),
):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    r = get_report(report_id)
    if not r:
        return RedirectResponse(url="/", status_code=303)

    ex = loads_extracted(r["extracted_json"])
    ex = apply_clarification(ex, key, answer)
    update_extracted_json(report_id, dumps_extracted(ex))

    set_clarification(report_id, key, (answer or "").strip())
    return RedirectResponse(url=f"/report/{report_id}", status_code=303)


@app.get("/claim/{lost_id}/{found_id}", response_class=HTMLResponse)
def claim_page(request: Request, lost_id: int, found_id: int):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    lost = get_report(lost_id)
    found = get_report(found_id)
    if not lost or not found:
        return HTMLResponse("Not found", status_code=404)

    if int(found.get("is_closed") or 0) == 1:
        return HTMLResponse("This found report is closed. Claims are disabled.", status_code=400)

    if has_settled_claim_for_found(found_id):
        return HTMLResponse("This found report is already settled. Claims are disabled.", status_code=400)

    return templates.TemplateResponse(
        "claim.html",
        {"request": request, "user": u, "lost": lost, "found": found},
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
        return require_login_redirect(request)

    found = get_report(found_id)
    if not found:
        return HTMLResponse("Not found", status_code=404)

    if int(found.get("is_closed") or 0) == 1 or has_settled_claim_for_found(found_id):
        return HTMLResponse("This found report is closed/settled. Claims are disabled.", status_code=400)

    proof_text = (proof_text or "").strip()
    if len(proof_text) < 10:
        return HTMLResponse("Please write a bit more proof detail (at least ~10 chars).", status_code=400)

    create_claim(
        lost_id,
        found_id,
        proof_text,
        claimer_user_id=int(u["id"]),
        claimer_name=u.get("name") or "",
        claimer_phone=u.get("phone") or "",
        claimer_nid=u.get("nid") or "",
    )
    return RedirectResponse(url=f"/report/{lost_id}", status_code=303)


@app.get("/manage/{found_id}", response_class=HTMLResponse)
def manage_claims(request: Request, found_id: int, token: str):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    found = get_report(found_id)
    if not found or not found.get("manage_token") or token != found["manage_token"]:
        return HTMLResponse("Unauthorized", status_code=403)

    claims = list_claims_for_found(found_id)
    # Mask proof text on non-office pages (prevents accidental phone/email leaks)
    for c in claims:
        c["proof_text_masked"] = mask_sensitive(c.get("proof_text") or "")

    lost_reports = {c["lost_report_id"]: get_report(c["lost_report_id"]) for c in claims}

    return templates.TemplateResponse(
        "claims.html",
        {
            "request": request,
            "user": u,
            "found": found,
            "claims": claims,
            "lost_reports": lost_reports,
            "token": token,
        },
    )


@app.post("/manage/claim/{claim_id}/approve")
def approve_claim(request: Request, claim_id: int, token: str = Form(...)):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    claim = get_claim(claim_id)
    if not claim:
        return HTMLResponse("Not found", status_code=404)

    found = get_report(claim["found_report_id"])
    if not found or token != found.get("manage_token"):
        return HTMLResponse("Unauthorized", status_code=403)

    if int(found.get("is_closed") or 0) == 1:
        return HTMLResponse("This report is closed.", status_code=400)

    set_claim_status(claim_id, "approved")
    return RedirectResponse(url=f"/manage/{found['id']}?token={token}", status_code=303)


@app.post("/manage/claim/{claim_id}/reject")
def reject_claim(request: Request, claim_id: int, token: str = Form(...)):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    claim = get_claim(claim_id)
    if not claim:
        return HTMLResponse("Not found", status_code=404)

    found = get_report(claim["found_report_id"])
    if not found or token != found.get("manage_token"):
        return HTMLResponse("Unauthorized", status_code=403)

    set_claim_status(claim_id, "rejected")
    return RedirectResponse(url=f"/manage/{found['id']}?token={token}", status_code=303)


@app.post("/manage/claim/{claim_id}/settle")
def settle_claim_route(request: Request, claim_id: int, token: str = Form(...)):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    claim = get_claim(claim_id)
    if not claim:
        return HTMLResponse("Not found", status_code=404)

    found = get_report(claim["found_report_id"])
    if not found or token != found.get("manage_token"):
        return HTMLResponse("Unauthorized", status_code=403)

    if claim.get("status") != "approved":
        return HTMLResponse("Only approved claims can be settled.", status_code=400)

    settle_claim(claim_id)
    close_report(int(claim["found_report_id"]), closed_claim_id=claim_id)
    close_report(int(claim["lost_report_id"]), closed_claim_id=claim_id)

    return RedirectResponse(url=f"/manage/{found['id']}?token={token}", status_code=303)


@app.get("/claims", response_class=HTMLResponse)
def all_claims(request: Request):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    q = (request.query_params.get("q") or "").strip()
    status = (request.query_params.get("status") or "").strip().lower()
    settled = (request.query_params.get("settled") or "").strip().lower()

    if status not in ("", "pending", "approved", "rejected"):
        status = ""
    if settled not in ("", "open", "settled"):
        settled = ""

    claims = list_claims_all(limit=500, q=q or None, status=status or None, settled=settled or None)

    return templates.TemplateResponse(
        "all_claims.html",
        {
            "request": request,
            "user": u,
            "claims": claims,
            "q": q,
            "status": status,
            "settled": settled,
        },
    )


@app.get("/claims/{claim_id}", response_class=HTMLResponse)
def claim_safe_view(request: Request, claim_id: int):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    claim = get_claim_with_titles(claim_id)
    if not claim:
        return HTMLResponse("Not found", status_code=404)

    masked_proof = mask_sensitive(claim.get("proof_text") or "")
    dispute_count = int(claim.get("dispute_count") or 0)

    return templates.TemplateResponse(
        "claim_safe.html",
        {
            "request": request,
            "user": u,
            "claim": claim,
            "masked_proof": masked_proof,
            "lost_title": claim.get("lost_title") or "",
            "found_title": claim.get("found_title") or "",
            "dispute_count": dispute_count,
        },
    )


@app.get("/dispute/{claim_id}", response_class=HTMLResponse)
def dispute_form(request: Request, claim_id: int):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    claim = get_claim_with_titles(claim_id)
    if not claim:
        return HTMLResponse("Not found", status_code=404)

    return templates.TemplateResponse(
        "dispute.html",
        {
            "request": request,
            "user": u,
            "claim": claim,
            "lost_title": claim.get("lost_title") or "",
            "found_title": claim.get("found_title") or "",
        },
    )


@app.post("/dispute/{claim_id}")
def dispute_submit(request: Request, claim_id: int, reason: str = Form(...)):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)

    claim = get_claim(claim_id)
    if not claim:
        return HTMLResponse("Not found", status_code=404)

    reason = (reason or "").strip()
    if len(reason) < 6:
        return HTMLResponse("Please write a bit more detail.", status_code=400)

    create_dispute(
        claim_id,
        reason,
        reporter_user_id=int(u["id"]),
        reporter_name=u.get("name") or "",
        reporter_phone=u.get("phone") or "",
    )
    return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)


@app.get("/office", response_class=HTMLResponse)
def office_dashboard(request: Request):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)
    if not require_office(u):
        return HTMLResponse("Unauthorized", status_code=403)

    disputes = list_disputes_all(limit=200)

    return templates.TemplateResponse(
        "office.html",
        {"request": request, "user": u, "disputes": disputes},
    )


@app.get("/office/claim/{claim_id}", response_class=HTMLResponse)
def office_view_claim(request: Request, claim_id: int):
    u = current_user(request)
    if not u:
        return require_login_redirect(request)
    if not require_office(u):
        return HTMLResponse("Unauthorized", status_code=403)

    claim = get_claim_with_titles(claim_id)
    if not claim:
        return HTMLResponse("Not found", status_code=404)

    disputes = list_disputes_for_claim(claim_id)

    return templates.TemplateResponse(
        "office_claim.html",
        {
            "request": request,
            "user": u,
            "claim": claim,
            "disputes": disputes,
        },
    )
