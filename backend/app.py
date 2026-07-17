# -*- coding: utf-8 -*-
"""排課引擎 API（Cloud Run 用）。"""
import asyncio
import base64
import csv
import hmac
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
import zipfile
from collections import deque

from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import auth_service
import engine
import openai_advisor
import schedule_store
import teacher_portal
import schedule_policy
import usage_tracker

LOGGER = logging.getLogger("schedule-api")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
MAX_UNCOMPRESSED_BYTES = int(os.getenv("MAX_UNCOMPRESSED_BYTES", str(100 * 1024 * 1024)))
MAX_ZIP_ENTRIES = int(os.getenv("MAX_ZIP_ENTRIES", "250"))
API_KEY = os.getenv("SCHEDULE_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
OPENAI_ENABLED = bool(os.getenv("OPENAI_API_KEY", "").strip())
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_WORKSPACE_DOMAIN = os.getenv("GOOGLE_WORKSPACE_DOMAIN", "").strip().lower().lstrip("@")
ADMIN_EMAILS = tuple(email.strip().lower() for email in os.getenv(
    "SCHEDULE_ADMIN_EMAILS", "").split(",") if email.strip())
SUPER_ADMIN_EMAILS = tuple(email.strip().lower() for email in os.getenv(
    "SCHEDULE_SUPER_ADMIN_EMAILS", "").split(",") if email.strip())
DEFAULT_SCHOOL_ID = os.getenv("SCHEDULE_SCHOOL_ID", "default-school").strip().lower()
DEFAULT_SCHOOL_NAME = os.getenv("SCHEDULE_SCHOOL_NAME", "預設學校").strip()
DEFAULT_MOE_SCHOOL_CODE = os.getenv("SCHEDULE_MOE_SCHOOL_CODE", "").strip()
MULTI_TENANT_ENABLED = os.getenv("SCHEDULE_MULTI_TENANT", "true").strip().lower() not in {
    "0", "false", "no", "off",
}
MAX_PUBLISHED_SNAPSHOT_BYTES = int(os.getenv("MAX_PUBLISHED_SNAPSHOT_BYTES", str(800 * 1024)))
STORE = schedule_store.create_store()
TENANT_DIRECTORY = schedule_store.create_tenant_directory(DEFAULT_SCHOOL_ID, STORE)
USAGE_TRACKER = usage_tracker.create_usage_tracker()
if GOOGLE_WORKSPACE_DOMAIN:
    default_school = TENANT_DIRECTORY.ensure_school({
        "school_id": DEFAULT_SCHOOL_ID,
        "moe_code": DEFAULT_MOE_SCHOOL_CODE,
        "name": DEFAULT_SCHOOL_NAME,
        "domains": [GOOGLE_WORKSPACE_DOMAIN],
        "admin_emails": list(ADMIN_EMAILS),
        "active": True,
    })
    if DEFAULT_MOE_SCHOOL_CODE and default_school.get("moe_code") != DEFAULT_MOE_SCHOOL_CODE:
        TENANT_DIRECTORY.upsert_school({**default_school, "moe_code": DEFAULT_MOE_SCHOOL_CODE})
SOLVE_GATE = asyncio.Semaphore(max(1, int(os.getenv("MAX_CONCURRENT_SOLVES", "1"))))
RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("RATE_LIMIT_PER_MINUTE", "30")))
SOLVE_REQUESTS = deque()
RATE_LOCK = threading.Lock()
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "false").strip().lower() in {"1", "true", "yes", "on"}
app = FastAPI(
    title="排課引擎 API", version="1.28",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv(
    "ALLOWED_ORIGINS",
    "http://127.0.0.1:8765,http://localhost:8765,http://127.0.0.1:8768,http://localhost:8768,https://smallcannon-arch.github.io",
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["Content-Disposition", "X-Solve-Status", "X-Penalty", "X-Violations",
                    "X-Schedule-Completeness", "X-Missing-Lessons", "X-Tutor-Pool",
                    "X-Weekly-Cap-Issues", "X-Compliance-Issues",
                    "X-OpenAI-Status", "X-OpenAI-Model"],
)


def _request_body_limit(path):
    if path == "/admin/teachers/import-csv":
        return 1024 * 1024 + 64 * 1024
    if path in {"/admin/publish", "/admin/draft"}:
        return MAX_PUBLISHED_SNAPSHOT_BYTES + 64 * 1024
    if path in {"/solve", "/solve-data"}:
        return MAX_UPLOAD_BYTES + 1024 * 1024
    if path.startswith("/teacher/classes/"):
        return 64 * 1024
    if path.startswith("/admin/teacher-updates"):
        return 64 * 1024
    if path.startswith("/admin/published-versions/"):
        return 64 * 1024
    if path.startswith("/platform/schools/"):
        return 64 * 1024
    return 0


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    limit = _request_body_limit(request.url.path)
    content_length = request.headers.get("content-length")
    if limit and content_length:
        try:
            too_large = int(content_length) > limit
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Content-Length 格式不正確"})
        if too_large:
            return JSONResponse(status_code=413, content={"error": "請求資料超過大小上限"})

    protected_write = request.method in {"POST", "PUT", "DELETE"} and (
        request.url.path.startswith(("/admin/", "/teacher/", "/platform/"))
        or request.url.path in {"/solve", "/solve-data"}
    )
    if (protected_write and GOOGLE_CLIENT_ID
            and not request.headers.get("authorization")
            and not request.headers.get("x-api-key")):
        return JSONResponse(
            status_code=401, content={"error": "請先使用學校 Google 帳號登入"},
            headers={"WWW-Authenticate": "Bearer, ApiKey"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith(("/auth/", "/admin/", "/teacher/", "/platform/")):
        response.headers["Cache-Control"] = "no-store"
    return response

KEY_FIELD = ("API 金鑰 <input type=\"password\" name=\"api_key\" autocomplete=\"current-password\" required><br>"
             if API_KEY else "")
PAGE = """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CP-SAT 排課引擎</title>
<style>body{font-family:'Microsoft JhengHei',sans-serif;background:#fdf8f4;display:grid;place-items:center;min-height:100vh;margin:0;color:#4a4458}
.card{background:#fff;border-radius:8px;box-shadow:0 10px 28px rgba(120,90,110,.12);padding:32px;max-width:560px;text-align:center;margin:16px}
h1{font-size:22px}p{color:#756b82;font-size:14px;line-height:1.8}input,textarea{margin:9px 0;font-size:14px;padding:7px;border:2px solid #efe8ea;border-radius:6px}
input[type=number]{width:70px}button{background:#a93f68;color:#fff;border:0;border-radius:6px;padding:13px 28px;font-size:16px;font-weight:900;cursor:pointer;margin-top:10px}
fieldset{border:1px solid #ded5e4;border-radius:8px;margin:14px 0;padding:12px;text-align:left}legend{font-weight:700}textarea{display:block;width:100%;min-height:76px;box-sizing:border-box;font-family:inherit}small{display:block;color:#756b82;line-height:1.5}.ai-off{background:#fff4d6;padding:9px;border-radius:6px}
button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #3878a8;outline-offset:2px}</style></head><body><main class="card">
<h1>CP-SAT 排課引擎</h1>
<p>不需要 AI 或模型 API。CP-SAT 負責實際求解，並通過獨立硬規則檢核後才會下載課表。</p>
<form action="/solve" method="post" enctype="multipart/form-data">
<input type="file" name="file" accept=".xlsx" required><br>
{{API_KEY_FIELD}}
求解秒數上限 <input type="number" name="time_limit" value="120" min="10" max="600"><br>
<label><input type="checkbox" name="auto_schedule_tutor" value="true"> 由 CP-SAT 一併排完導師課（預設保留給導師自行安排）</label><br>
<label><input type="checkbox" name="strict_complete" value="true"> 要求本次直接產生完整課表</label><br>
<button>開始排課</button></form>
<p>檔案只在求解期間暫存，完成即回收。上傳上限由服務端設定。</p>
</main></body></html>""".replace("{{API_KEY_FIELD}}", KEY_FIELD)


class ResultValidationError(RuntimeError):
    pass


def _infeasible_response(exc):
    return JSONResponse(status_code=422, content={
        "error": str(exc),
        "status": getattr(exc, "status", "INFEASIBLE"),
        "diagnostics": getattr(exc, "diagnostics", []),
        "diagnostic_engine": "cp-sat-rules",
    })


class PlacementUpdate(BaseModel):
    revision: str = Field(min_length=1, max_length=100)
    placements: dict[str, str]


class TeacherUpdateApproval(BaseModel):
    revision: str = Field(min_length=1, max_length=100)
    updates: dict[str, int]


class SchoolUpsert(BaseModel):
    moe_code: str = Field(default="", max_length=6)
    name: str = Field(min_length=1, max_length=120)
    domains: list[str]
    admin_emails: list[str]
    active: bool = True


class SolveDataRequest(BaseModel):
    data: dict
    limits: list = Field(default_factory=list)
    rules: list = Field(default_factory=list)
    time_limit: int = 120
    use_openai: bool = False
    ai_goal: str = Field(default="", max_length=1200)
    auto_schedule_tutor: bool = False
    strict_complete: bool = False


ROLE_ALIASES = {
    "homeroom_teacher": "homeroom_teacher", "導師": "homeroom_teacher",
    "subject_teacher": "subject_teacher", "科任": "subject_teacher",
    "教支人員": "subject_teacher", "鐘點教師": "subject_teacher",
    "組長": "subject_teacher", "主任": "subject_teacher",
    "resource_teacher": "resource_teacher", "資源班": "resource_teacher",
    "資源班教師": "resource_teacher",
}


def _verified_identity(authorization):
    token = auth_service.bearer_token(authorization)
    return auth_service.verify_google_token(token, GOOGLE_CLIENT_ID)


def _school_store(school):
    school_id = str(school.get("school_id") or "")
    if school_id == DEFAULT_SCHOOL_ID:
        return STORE
    return TENANT_DIRECTORY.get_store(school_id)


def _school_for_identity(identity, super_admin=False):
    schools = (TENANT_DIRECTORY.get_schools_by_domain(identity.hosted_domain)
               if identity.hosted_domain else [])
    eligible = []
    for school in schools:
        if not school.get("active", True):
            continue
        if identity.email in set(school.get("admin_emails") or ()):
            eligible.append(school)
            continue
        record = _school_store(school).get_teacher(identity.email)
        if record and record.get("active", True):
            eligible.append(school)
    if len(eligible) == 1:
        return eligible[0]
    if len(eligible) > 1:
        names = "、".join(str(item.get("name") or item.get("school_id")) for item in eligible[:4])
        raise auth_service.AuthorizationError(
            f"此帳號同時屬於多所學校（{names}），請洽平台管理員設定主要學校")
    if super_admin:
        return None
    if len(schools) == 1:
        return schools[0]
    if schools:
        raise auth_service.AuthorizationError("此帳號不在該 Workspace 網域已開通學校的名單中")
    return None


def _current_session(authorization):
    try:
        identity = _verified_identity(authorization)
        super_admin = identity.email in set(SUPER_ADMIN_EMAILS)
        school = _school_for_identity(identity, super_admin=super_admin)
        if not school:
            if super_admin:
                principal = auth_service.Principal(
                    identity.subject, identity.email, identity.name or identity.email,
                    "platform_admin", (), hosted_domain=identity.hosted_domain,
                    is_super_admin=True)
                return principal, None
            raise auth_service.AuthorizationError("此 Google Workspace 網域尚未加入系統")
        if not school.get("active", True):
            raise auth_service.AuthorizationError("此學校目前已停用")
        store = _school_store(school)
        school_admins = set(school.get("admin_emails") or ())
        if identity.email in school_admins:
            TENANT_DIRECTORY.bind_admin_subject(
                school.get("school_id"), identity.email, identity.subject)
            school = TENANT_DIRECTORY.get_school(school.get("school_id")) or school
        try:
            principal = auth_service.authorize_identity(
                identity, store, school_admins, school=school, is_super_admin=super_admin)
        except auth_service.AuthorizationError:
            if not super_admin:
                raise
            principal = auth_service.Principal(
                identity.subject, identity.email, identity.name or identity.email,
                "platform_admin", (), hosted_domain=identity.hosted_domain,
                is_super_admin=True)
            return principal, None
        return principal, store
    except auth_service.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc),
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    except (auth_service.AuthorizationError, schedule_store.StoreConflictError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _current_principal(authorization):
    return _current_session(authorization)[0]


def _current_school_session(authorization):
    principal, store = _current_session(authorization)
    if store is None:
        raise HTTPException(status_code=403, detail="平台總管理員尚未進入學校租戶")
    return principal, store


def _require_admin(authorization):
    principal, store = _current_school_session(authorization)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="只有排課管理員可以執行此操作")
    return principal, store


def _require_super_admin(authorization):
    try:
        identity = _verified_identity(authorization)
    except auth_service.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc),
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    if identity.email not in set(SUPER_ADMIN_EMAILS):
        raise HTTPException(status_code=403, detail="只有平台總管理員可以管理學校")
    return identity


def _record_usage(principal, event):
    if not principal or not principal.school_id:
        return
    try:
        USAGE_TRACKER.record(principal.school_id, event, principal.role)
    except Exception:
        LOGGER.exception("Aggregate usage tracking failed")


def _usage_principal(authorization):
    if not authorization:
        return None
    try:
        principal = _current_principal(authorization)
        return principal if principal.is_admin else None
    except HTTPException:
        return None


def _csv_value(row, *names):
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_teacher_rows(rows):
    records = []
    seen = set()
    for index, row in enumerate(rows, start=2):
        name = _csv_value(row, "教師姓名", "姓名", "name")
        email = auth_service.normalize_email(_csv_value(
            row, "學校Google帳號", "學校 Google 帳號", "學校信箱", "電子郵件", "email"))
        role_text = _csv_value(row, "角色", "身分", "role") or "科任"
        role = ROLE_ALIASES.get(role_text)
        class_text = _csv_value(row, "負責班級", "導師班級", "班級", "classes")
        class_codes = [value for value in re.split(r"[\s,，、;；]+", class_text) if value]
        active_text = _csv_value(row, "啟用", "active").lower()
        active = active_text not in {"否", "停用", "false", "0", "no"}
        if not name or not email or "@" not in email:
            raise ValueError(f"第 {index} 列缺少有效的教師姓名或 Google 帳號")
        if role is None:
            raise ValueError(f"第 {index} 列的角色「{role_text}」不支援")
        if role == "homeroom_teacher" and not class_codes:
            raise ValueError(f"第 {index} 列導師未填負責班級")
        if email in seen:
            raise ValueError(f"第 {index} 列 Google 帳號重複：{email}")
        seen.add(email)
        records.append({
            "email": email, "name": name, "role": role,
            "class_codes": class_codes, "active": active,
        })
    if not records:
        raise ValueError("教師帳號表沒有可匯入的資料")
    if len(records) > 500:
        raise ValueError("單次最多匯入 500 位教師")
    return records


def _normalize_schedule_snapshot(payload, require_schedule):
    snapshot = {
        "data": payload.get("data"),
        "schedule": payload.get("schedule") if "schedule" in payload else payload.get("sol"),
        "tutor_placements": payload.get("tutor_placements") if "tutor_placements" in payload else payload.get("tp"),
        "overlay": payload.get("overlay") if "overlay" in payload else payload.get("ovl"),
        "limits": payload.get("limits") or [],
        "rules": payload.get("rules") or [],
        "label": str(payload.get("label") or "排課暫存")[:120],
        "formal_auto_tutor": bool(payload.get("formal_auto_tutor", payload.get("formalAutoTutor", False))),
        "schedule_ready": bool(payload.get("schedule_ready", payload.get("scheduleReady", False))),
    }
    if snapshot["tutor_placements"] is None:
        snapshot["tutor_placements"] = {}
    if snapshot["overlay"] is None:
        snapshot["overlay"] = []
    if snapshot["schedule"] is None and not require_schedule:
        snapshot["schedule"] = {}
    if not isinstance(snapshot["data"], dict) or not isinstance(snapshot["schedule"], dict):
        raise ValueError("請先載入有效的學校排課資料")
    if snapshot["schedule"] or snapshot["overlay"]:
        snapshot["schedule_ready"] = True
    if require_schedule and not snapshot["schedule_ready"]:
        raise ValueError("請先完成排課，再發布正式教師課表")
    if not (snapshot["data"].get("classes") and snapshot["data"].get("subjects")):
        raise ValueError("課表缺少班級或科目設定")
    policy_result = schedule_policy.validate_case(
        snapshot["data"], require_approval=require_schedule)
    if require_schedule and policy_result["blocking"]:
        raise ValueError("正式發布前的學校自訂規則檢核未通過：" +
                         "；".join(policy_result["blocking"][:5]))
    snapshot["policy_compliance"] = policy_result
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_PUBLISHED_SNAPSHOT_BYTES:
        raise OverflowError("排課資料過大，請改用分班儲存模式")
    return snapshot


def _check_api_key(form_key, header_key):
    if not API_KEY:
        return True
    supplied = header_key or form_key or ""
    return hmac.compare_digest(supplied.encode("utf-8"), API_KEY.encode("utf-8"))


def _check_solve_access(form_key, header_key, authorization):
    if API_KEY and _check_api_key(form_key, header_key):
        return True
    if authorization:
        try:
            return _current_principal(authorization).is_admin
        except HTTPException:
            return False
    return not API_KEY and not GOOGLE_CLIENT_ID


def _claim_rate_limit():
    now = time.monotonic()
    with RATE_LOCK:
        while SOLVE_REQUESTS and now - SOLVE_REQUESTS[0] >= 60:
            SOLVE_REQUESTS.popleft()
        if len(SOLVE_REQUESTS) >= RATE_LIMIT_PER_MINUTE:
            return False
        SOLVE_REQUESTS.append(now)
        return True


def _validate_xlsx(data):
    if not data.startswith(b"PK\x03\x04"):
        raise ValueError("檔案不是有效的 xlsx")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise ValueError("檔案不是有效的 Excel 活頁簿")
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ValueError("Excel 內部檔案數量過多")
            expanded = sum(item.file_size for item in infos)
            if expanded > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Excel 解壓後資料量超過限制")
            for item in infos:
                if item.file_size > 1024 * 1024 and item.file_size > max(1, item.compress_size) * 200:
                    raise ValueError("Excel 壓縮比例異常")
    except zipfile.BadZipFile as exc:
        raise ValueError("檔案不是有效的 xlsx") from exc


def _solve_loaded_data(schedule_data, time_limit, use_openai=False, ai_goal="",
                       auto_schedule_tutor=False):
    with tempfile.TemporaryDirectory() as td:
        dst = os.path.join(td, "課表輸出.xlsx")
        ai_status, ai_plan, ai_audit = "disabled", None, []
        if use_openai:
            try:
                ai_plan = openai_advisor.plan_soft_rules(schedule_data, ai_goal, OPENAI_MODEL)
                ai_audit = openai_advisor.apply_plan(schedule_data, ai_plan)
                ai_status = "applied"
            except Exception:
                LOGGER.exception("OpenAI soft-rule planning failed")
                ai_status = "failed"
        sched, tasks, warn, meta, overlay = engine.solve(
            schedule_data, time_limit=time_limit, auto_schedule_tutor=auto_schedule_tutor)
        errs = engine.validate(schedule_data, sched, tasks, overlay)
        if errs:
            detail = "；".join(errs[:5])
            raise ResultValidationError(f"排課結果未通過硬規則檢核（{len(errs)} 項）：{detail}")
        engine.write_output(dst, schedule_data, sched, tasks, warn, meta, errs, overlay)
        if use_openai:
            openai_advisor.append_plan_sheet(
                dst, OPENAI_MODEL, ai_status, plan=ai_plan, audit_rows=ai_audit,
                error_message="OpenAI 規劃失敗，本次已自動改用母版原始軟規則；課表仍通過 CP-SAT 硬規則檢核。",
            )
        with open(dst, "rb") as stream:
            output = stream.read()
    schedule_rows = [
        {"code": code, "day": day, "period": period, "subject": subject,
         "teacher": teacher, "room": room}
        for (code, day, period), (subject, teacher, room) in sorted(
            sched.items(), key=lambda item: (
                item[0][0], engine.DAYS.index(item[0][1]), item[0][2]))
    ]
    overlay_rows = [
        {"group_id": group_id, "group": group, "code": code,
         "subject": subject, "pull_subject": pull_subject, "teacher": teacher,
         "day": day, "period": period}
        for group_id, group, code, subject, pull_subject, teacher, day, period in overlay
    ]
    return output, meta, ai_status, schedule_rows, overlay_rows


def _run_solver(data, time_limit, use_openai=False, ai_goal="", auto_schedule_tutor=False):
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.xlsx")
        with open(src, "wb") as stream:
            stream.write(data)
        schedule_data = engine.load_data(src)
    return _solve_loaded_data(
        schedule_data, time_limit, use_openai, ai_goal, auto_schedule_tutor)


def _run_solver_data(payload, limits, rules, time_limit, use_openai=False, ai_goal="",
                     auto_schedule_tutor=False):
    schedule_data = engine.load_frontend_data(payload, limits, rules)
    return _solve_loaded_data(
        schedule_data, time_limit, use_openai, ai_goal, auto_schedule_tutor)


@app.get("/auth/config")
def auth_config():
    return {
        "enabled": bool(GOOGLE_CLIENT_ID),
        "client_id": GOOGLE_CLIENT_ID,
        "workspace_domain": "" if MULTI_TENANT_ENABLED else GOOGLE_WORKSPACE_DOMAIN,
        "multi_tenant": MULTI_TENANT_ENABLED,
        "provider": "google",
    }


@app.get("/auth/me")
def auth_me(authorization: str = Header("")):
    principal = _current_principal(authorization)
    _record_usage(principal, "login")
    school = TENANT_DIRECTORY.get_school(principal.school_id) if principal.school_id else {}
    return {
        "email": principal.email, "name": principal.name, "role": principal.role,
        "class_codes": list(principal.class_codes), "is_admin": principal.is_admin,
        "is_super_admin": principal.is_super_admin,
        "school_id": principal.school_id, "school_name": principal.school_name,
        "moe_code": (school or {}).get("moe_code", ""),
        "workspace_domain": principal.hosted_domain,
    }


@app.get("/platform/schools")
def list_schools(authorization: str = Header("")):
    _require_super_admin(authorization)
    return {"schools": TENANT_DIRECTORY.list_schools()}


@app.get("/platform/usage")
def platform_usage(days: int = 30, authorization: str = Header("")):
    _require_super_admin(authorization)
    overview = USAGE_TRACKER.get_overview(
        TENANT_DIRECTORY.list_schools(), days=min(max(days, 1), 90))
    case_overviews = {}
    for school in overview.get("schools") or []:
        if not school.get("active", True):
            continue
        school_id = usage_tracker.normalize_school_id(school.get("school_id"))
        if not school_id:
            continue
        try:
            case_overviews[school_id] = TENANT_DIRECTORY.get_store(school_id).get_case_overview()
        except Exception:  # pragma: no cover - defensive isolation for the platform view
            LOGGER.exception("Unable to read usage case overview for %s", school_id)
            case_overviews[school_id] = {"metadata_unavailable": True}
    return usage_tracker.enrich_overview(overview, case_overviews)


@app.put("/platform/schools/{school_id}")
def upsert_school(school_id: str, payload: SchoolUpsert,
                  authorization: str = Header("")):
    identity = _require_super_admin(authorization)
    try:
        normalized_id = schedule_store.normalize_school_id(school_id)
        moe_code = schedule_store.normalize_moe_school_code(
            payload.moe_code, school_id=normalized_id)
        existing = TENANT_DIRECTORY.get_school(normalized_id)
        existing_moe_code = str((existing or {}).get("moe_code") or "").strip()
        if existing_moe_code and moe_code != existing_moe_code:
            raise schedule_store.StoreConflictError(
                f"既有學校的教育部代碼不可由 {existing_moe_code} 改為 {moe_code}；"
                "若要建立另一間學校，請先按「新增學校」")
        duplicate = next((item for item in TENANT_DIRECTORY.list_schools()
                          if item.get("school_id") != normalized_id
                          and item.get("moe_code") == moe_code and moe_code), None)
        if duplicate:
            raise schedule_store.StoreConflictError(
                f"教育部學校代碼 {moe_code} 已由 {duplicate.get('name', '其他學校')} 使用")
        school = TENANT_DIRECTORY.upsert_school({
            "school_id": normalized_id,
            "moe_code": moe_code,
            "name": payload.name,
            "domains": payload.domains,
            "admin_emails": payload.admin_emails,
            "active": payload.active,
        })
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except schedule_store.StoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"school": school, "updated_by": identity.email}


@app.post("/admin/teachers/import-csv")
async def import_teacher_csv(file: UploadFile = File(...), replace: bool = Form(True),
                             authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    data = await file.read(1024 * 1024 + 1)
    await file.close()
    if len(data) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="教師帳號表不可超過 1 MB")
    try:
        text = data.decode("utf-8-sig")
        records = _normalize_teacher_rows(csv.DictReader(io.StringIO(text)))
        school = TENANT_DIRECTORY.get_school(principal.school_id) or {}
        allowed_domains = set(school.get("domains") or ())
        invalid_emails = [record["email"] for record in records
                          if record["email"].rsplit("@", 1)[-1] not in allowed_domains]
        if invalid_emails:
            raise ValueError(f"教師帳號不屬於本校 Workspace 網域：{invalid_emails[0]}")
        count = store.import_teachers(records, replace=replace)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV 請使用 UTF-8 編碼") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _record_usage(principal, "teacher_import")
    return {"imported": count, "replace": replace, "imported_by": principal.email}


@app.post("/admin/publish")
def publish_schedule(payload: dict = Body(...), authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    try:
        snapshot = _normalize_schedule_snapshot(payload, require_schedule=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    state = store.publish_snapshot(snapshot, principal.email)
    _record_usage(principal, "publish")
    return {"revision": state["revision"], "published_at": state["published_at"],
            "update_sequence": state["update_sequence"]}


@app.put("/admin/draft")
def save_admin_draft(payload: dict = Body(...), authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    expected_draft_revision = str(payload.get("expected_draft_revision") or "")[:100]
    try:
        snapshot = _normalize_schedule_snapshot(payload, require_schedule=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    active_revision = str(payload.get("active_revision") or "")[:100]
    try:
        draft = store.save_draft(
            snapshot, principal.email, active_revision, expected_draft_revision)
    except schedule_store.StoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if str(payload.get("save_mode") or "").strip().lower() == "manual":
        _record_usage(principal, "draft_save")
    return {"draft_revision": draft["draft_revision"], "saved_at": draft["saved_at"],
            "saved_by": draft["saved_by"], "active_revision": draft["active_revision"]}


@app.get("/admin/draft")
def get_admin_draft(authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    draft = store.get_draft(principal.email)
    if not draft:
        raise HTTPException(status_code=404, detail="目前沒有雲端暫存")
    return draft


@app.delete("/admin/draft")
def delete_admin_draft(expected_draft_revision: str = "",
                       authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    try:
        deleted = store.delete_draft(str(expected_draft_revision or "")[:100])
    except schedule_store.StoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if deleted:
        _record_usage(principal, "draft_delete")
    return {"deleted": deleted, "published_schedule_preserved": True}


@app.post("/admin/backups")
def create_admin_backup(authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    draft = store.get_draft(principal.email)
    if not draft:
        raise HTTPException(status_code=404, detail="目前沒有可建立還原點的雲端案件")
    backup = store.create_backup(
        draft["snapshot"], principal.email, draft.get("active_revision", ""),
        draft.get("draft_revision", ""))
    _record_usage(principal, "backup_create")
    return {key: backup[key] for key in (
        "backup_id", "created_at", "created_by", "active_revision",
        "source_draft_revision", "summary")}


@app.get("/admin/backups")
def list_admin_backups(limit: int = 10, authorization: str = Header("")):
    _, store = _require_admin(authorization)
    return {"backups": store.list_backups(min(max(limit, 1), 10))}


@app.post("/admin/backups/{backup_id}/restore")
def restore_admin_backup(backup_id: str, payload: dict = Body(...),
                         authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    backup = store.get_backup(backup_id[:100])
    if not backup:
        raise HTTPException(status_code=404, detail="找不到指定的案件還原點")
    expected_draft_revision = str(payload.get("expected_draft_revision") or "")[:100]
    active_state = store.get_active_state() or {}
    active_revision = str(active_state.get("revision") or "")[:100]
    try:
        draft = store.save_draft(
            backup["snapshot"], principal.email,
            active_revision,
            expected_draft_revision)
    except schedule_store.StoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _record_usage(principal, "backup_restore")
    return {
        "backup_id": backup["backup_id"],
        "restored_at": draft["saved_at"],
        "restored_by": principal.email,
        "draft_revision": draft["draft_revision"],
        "active_revision": draft["active_revision"],
        "snapshot": draft["snapshot"],
    }


@app.get("/admin/teacher-updates")
def get_teacher_updates(revision: str = "", after: int = 0,
                        authorization: str = Header("")):
    _, store = _require_admin(authorization)
    state = store.get_active_state()
    if not state:
        raise HTTPException(status_code=404, detail="目前沒有已發布的正式課表")
    if revision and revision != state.get("revision"):
        raise HTTPException(status_code=409, detail="正式課表版本已更新，請重新發布或載入雲端暫存")
    updates = {}
    placements = {}
    for code, metadata in (state.get("pending_teacher_updates") or {}).items():
        if int(metadata.get("sequence") or 0) <= max(0, after):
            continue
        updates[code] = {key: metadata.get(key) for key in (
            "submitted_at", "submitted_by", "sequence")}
        placements[code] = metadata.get("placements") or {}
    return {
        "revision": state["revision"], "updated_at": state.get("updated_at"),
        "update_sequence": int(state.get("update_sequence") or 0),
        "updates": updates, "placements": placements,
    }


@app.post("/admin/teacher-updates/approve")
def approve_teacher_updates(approval: TeacherUpdateApproval,
                            authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    try:
        state = store.approve_teacher_updates(
            approval.revision, approval.updates, principal.email)
    except schedule_store.StoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    approved_codes = sorted(str(code) for code in approval.updates)
    return {
        "ok": True,
        "revision": state["revision"],
        "approved_codes": approved_codes,
        "update_sequence": int(state.get("update_sequence") or 0),
        "updated_at": state.get("updated_at"),
    }


@app.get("/admin/published-versions")
def list_published_versions(limit: int = 20, authorization: str = Header("")):
    _, store = _require_admin(authorization)
    state = store.get_active_state()
    return {
        "active_revision": str((state or {}).get("revision") or ""),
        "versions": store.list_published_versions(min(max(limit, 1), 50)),
    }


@app.post("/admin/published-versions/{revision}/restore")
def restore_published_version(revision: str, authorization: str = Header("")):
    principal, store = _require_admin(authorization)
    try:
        state = store.restore_published_version(revision[:100], principal.email)
    except schedule_store.StoreConflictError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _record_usage(principal, "publish")
    return {
        "revision": state["revision"],
        "published_at": state["published_at"],
        "restored_from": state.get("restored_from") or "",
        "snapshot": state["snapshot"],
    }


@app.get("/teacher/workspace")
def teacher_workspace(authorization: str = Header("")):
    principal, store = _current_school_session(authorization)
    try:
        workspace = teacher_portal.build_teacher_workspace(store.get_active_state(), principal)
        _record_usage(principal, "teacher_open")
        return workspace
    except teacher_portal.TeacherChangeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/teacher/classes/{class_code}/placements")
def update_teacher_placements(class_code: str, update: PlacementUpdate,
                              authorization: str = Header("")):
    principal, store = _current_school_session(authorization)
    state = store.get_active_state()
    if state and state.get("revision") != update.revision:
        raise HTTPException(status_code=409, detail="正式課表已更新，請重新載入後再調整")
    try:
        placements = teacher_portal.validate_teacher_placements(
            state, principal, class_code, update.placements)
        updated_state = store.submit_teacher_placements(
            class_code, placements, update.revision, principal.email)
    except teacher_portal.TeacherChangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except schedule_store.StoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _record_usage(principal, "teacher_save")
    return {"ok": True, "pending_review": True, "class_code": class_code, "placements": placements,
            "update_sequence": updated_state["update_sequence"],
            "updated_at": updated_state["updated_at"]}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.post("/solve-data")
async def solve_data(request: SolveDataRequest, x_api_key: str = Header(""),
                     authorization: str = Header("")):
    if not _check_solve_access("", x_api_key, authorization):
        return JSONResponse(status_code=401, content={"error": "請使用排課管理員 Google 帳號登入"},
                            headers={"WWW-Authenticate": "Bearer, ApiKey"})
    solve_principal = _usage_principal(authorization)
    if not _claim_rate_limit():
        return JSONResponse(status_code=429, content={"error": "排課請求過於頻繁，請稍後再試"},
                            headers={"Retry-After": "60"})
    encoded = json.dumps(request.data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"error": "系統案件資料超過大小上限"})
    if request.use_openai and not OPENAI_ENABLED:
        return JSONResponse(status_code=503, content={"error": "OpenAI 尚未設定，請先配置 OPENAI_API_KEY"})
    try:
        seconds = min(max(int(request.time_limit), 10), 600)
        async with SOLVE_GATE:
            output, meta, ai_status, schedule_rows, overlay_rows = await run_in_threadpool(
                _run_solver_data, request.data, request.limits, request.rules, seconds,
                request.use_openai, request.ai_goal.strip(), request.auto_schedule_tutor)
        compliance_issues = list(meta.get("compliance_blocking_issues", []))
        blocking_issues = compliance_issues + list(meta.get("weekly_cap_violations", []))
        if meta.get("completion") != "complete":
            blocking_issues.append(
                f"尚有 {meta.get('remaining_total', 0)} 節未完成，其中未配教師 {meta.get('missing_total', 0)} 節、導師自排池 {meta.get('pool_total', 0)} 節")
        if request.strict_complete and blocking_issues:
            _record_usage(solve_principal, "solve_failed")
            return JSONResponse(status_code=409, content={
                "error": "課表尚未達到正式完成標準",
                "completion": meta.get("completion", "partial"),
                "required_total": meta.get("required_total", 0),
                "scheduled_total": meta.get("scheduled_total", 0),
                "missing_total": meta.get("missing_total", 0),
                "tutor_pool": meta.get("pool_total", 0),
                "weekly_cap_issues": meta.get("weekly_cap_violations", []),
                "compliance_issues": compliance_issues,
                "compliance_warnings": meta.get("compliance_warnings", []),
                "issues": blocking_issues[:10],
            })
        filename = "schedule_output.xlsx" if meta.get("completion") == "complete" and not blocking_issues else "schedule_partial.xlsx"
        headers = {"Content-Disposition": f"attachment; filename={filename}",
                   "X-Solve-Status": meta["status"],
                   "X-Penalty": str(meta["penalty"]),
                   "X-Violations": "0",
                   "X-Schedule-Completeness": meta.get("completion", "partial"),
                   "X-Missing-Lessons": str(meta.get("missing_total", 0)),
                   "X-Tutor-Pool": str(meta.get("pool_total", 0)),
                   "X-Weekly-Cap-Issues": str(len(meta.get("weekly_cap_violations", []))),
                   "X-Compliance-Issues": str(len(compliance_issues)),
                   "X-OpenAI-Status": ai_status,
                   "X-OpenAI-Model": OPENAI_MODEL if request.use_openai else "none"}
        public_meta = {key: meta.get(key) for key in (
            "status", "penalty", "best_bound", "relative_gap", "wall", "conflicts",
            "branches", "required_total", "scheduled_total", "remaining_total",
            "pool_total", "missing_total", "completion", "weekly_cap_violations",
            "compliance_blocking_issues", "compliance_warnings", "policy",
            "auto_schedule_tutor")}
        _record_usage(solve_principal, "solve_success")
        return JSONResponse(content={
            "filename": filename,
            "workbook_base64": base64.b64encode(output).decode("ascii"),
            "meta": public_meta,
            "schedule": schedule_rows,
            "overlay": overlay_rows,
        }, headers=headers)
    except engine.InfeasibleScheduleError as exc:
        _record_usage(solve_principal, "solve_failed")
        return _infeasible_response(exc)
    except (ValueError, RuntimeError) as exc:
        _record_usage(solve_principal, "solve_failed")
        return JSONResponse(status_code=422, content={"error": str(exc)})
    except Exception:
        _record_usage(solve_principal, "solve_failed")
        LOGGER.exception("Unexpected data solve failure")
        return JSONResponse(status_code=500, content={"error": "排課服務發生未預期錯誤，請聯絡系統管理者"})


@app.post("/solve")
async def solve(file: UploadFile = File(...), time_limit: int = Form(120),
                api_key: str = Form(""), x_api_key: str = Header(""),
                authorization: str = Header(""),
                use_openai: bool = Form(False), ai_goal: str = Form(""),
                auto_schedule_tutor: bool = Form(False), strict_complete: bool = Form(False),
                return_json: bool = Form(False)):
    if not _check_solve_access(api_key, x_api_key, authorization):
        return JSONResponse(status_code=401, content={"error": "請使用排課管理員 Google 帳號登入"},
                            headers={"WWW-Authenticate": "Bearer, ApiKey"})
    solve_principal = _usage_principal(authorization)
    if not _claim_rate_limit():
        return JSONResponse(status_code=429, content={"error": "排課請求過於頻繁，請稍後再試"},
                            headers={"Retry-After": "60"})
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        return JSONResponse(status_code=415, content={"error": "只接受 .xlsx 檔案"})
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not data:
        return JSONResponse(status_code=400, content={"error": "上傳檔案是空的"})
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"error": f"檔案超過 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限"})
    if use_openai and not OPENAI_ENABLED:
        return JSONResponse(status_code=503, content={"error": "OpenAI 尚未設定，請先配置 OPENAI_API_KEY"})
    if len(ai_goal) > 1200:
        return JSONResponse(status_code=422, content={"error": "OpenAI 排課目標不可超過 1200 字"})
    try:
        _validate_xlsx(data)
        seconds = min(max(int(time_limit), 10), 600)
        async with SOLVE_GATE:
            output, meta, ai_status, schedule_rows, overlay_rows = await run_in_threadpool(
                _run_solver, data, seconds, use_openai, ai_goal.strip(), auto_schedule_tutor)
        compliance_issues = list(meta.get("compliance_blocking_issues", []))
        blocking_issues = compliance_issues + list(meta.get("weekly_cap_violations", []))
        if meta.get("completion") != "complete":
            blocking_issues.append(
                f"尚有 {meta.get('remaining_total', 0)} 節未完成，其中未配教師 {meta.get('missing_total', 0)} 節、導師自排池 {meta.get('pool_total', 0)} 節")
        if strict_complete and blocking_issues:
            _record_usage(solve_principal, "solve_failed")
            return JSONResponse(status_code=409, content={
                "error": "課表尚未達到正式完成標準",
                "completion": meta.get("completion", "partial"),
                "required_total": meta.get("required_total", 0),
                "scheduled_total": meta.get("scheduled_total", 0),
                "missing_total": meta.get("missing_total", 0),
                "tutor_pool": meta.get("pool_total", 0),
                "weekly_cap_issues": meta.get("weekly_cap_violations", []),
                "compliance_issues": compliance_issues,
                "compliance_warnings": meta.get("compliance_warnings", []),
                "issues": blocking_issues[:10],
            })
        filename = "schedule_output.xlsx" if meta.get("completion") == "complete" and not blocking_issues else "schedule_partial.xlsx"
        headers = {"Content-Disposition": f"attachment; filename={filename}",
                   "X-Solve-Status": meta["status"],
                   "X-Penalty": str(meta["penalty"]),
                   "X-Violations": "0",
                   "X-Schedule-Completeness": meta.get("completion", "partial"),
                   "X-Missing-Lessons": str(meta.get("missing_total", 0)),
                   "X-Tutor-Pool": str(meta.get("pool_total", 0)),
                   "X-Weekly-Cap-Issues": str(len(meta.get("weekly_cap_violations", []))),
                   "X-Compliance-Issues": str(len(compliance_issues)),
                   "X-OpenAI-Status": ai_status,
                   "X-OpenAI-Model": OPENAI_MODEL if use_openai else "none"}
        if return_json:
            public_meta = {key: meta.get(key) for key in (
                "status", "penalty", "best_bound", "relative_gap", "wall", "conflicts",
                "branches", "required_total", "scheduled_total", "remaining_total",
                "pool_total", "missing_total", "completion", "weekly_cap_violations",
                "compliance_blocking_issues", "compliance_warnings", "policy",
                "auto_schedule_tutor")}
            _record_usage(solve_principal, "solve_success")
            return JSONResponse(content={
                "filename": filename,
                "workbook_base64": base64.b64encode(output).decode("ascii"),
                "meta": public_meta,
                "schedule": schedule_rows,
                "overlay": overlay_rows,
            }, headers=headers)
        _record_usage(solve_principal, "solve_success")
        return Response(content=output, media_type=XLSX_MIME, headers=headers)
    except engine.InfeasibleScheduleError as exc:
        _record_usage(solve_principal, "solve_failed")
        return _infeasible_response(exc)
    except (ValueError, RuntimeError) as exc:
        _record_usage(solve_principal, "solve_failed")
        return JSONResponse(status_code=422, content={"error": str(exc)})
    except Exception:
        _record_usage(solve_principal, "solve_failed")
        LOGGER.exception("Unexpected solve failure")
        return JSONResponse(status_code=500, content={"error": "排課服務發生未預期錯誤，請聯絡系統管理者"})


@app.get("/health")
def health():
    return {"ok": True, "version": app.version}


@app.get("/ai/status")
def ai_status(authorization: str = Header("")):
    _require_admin(authorization)
    return {"configured": OPENAI_ENABLED, "model": OPENAI_MODEL,
            "role": "soft-rule-planner", "solver": "CP-SAT"}
