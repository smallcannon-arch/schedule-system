# -*- coding: utf-8 -*-
"""Google identity verification and schedule-role authorization."""
from dataclasses import dataclass


class AuthenticationError(RuntimeError):
    pass


class AuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str
    hosted_domain: str = ""


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str
    name: str
    role: str
    class_codes: tuple[str, ...]
    school_id: str = ""
    school_name: str = ""
    hosted_domain: str = ""
    is_super_admin: bool = False

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def can_edit_classes(self):
        return self.role in {"admin", "homeroom_teacher"}


def normalize_email(value):
    return str(value or "").strip().lower()


def bearer_token(authorization):
    scheme, separator, token = str(authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("請先使用學校 Google 帳號登入")
    return token.strip()


def verify_google_token(token, client_id, workspace_domain=""):
    if not client_id:
        raise AuthenticationError("Google 登入尚未完成設定")
    try:
        from google.auth.transport import requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(token, requests.Request(), client_id)
    except Exception as exc:
        raise AuthenticationError("Google 登入憑證無效或已過期") from exc

    email = normalize_email(claims.get("email"))
    subject = str(claims.get("sub") or "").strip()
    if not subject or not email or claims.get("email_verified") is not True:
        raise AuthenticationError("Google 帳號未完成電子郵件驗證")

    required_domain = str(workspace_domain or "").strip().lower().lstrip("@")
    hosted_domain = str(claims.get("hd") or "").strip().lower()
    if required_domain and hosted_domain != required_domain:
        raise AuthorizationError("請使用學校配發的 Google Workspace 帳號")

    return GoogleIdentity(
        subject=subject,
        email=email,
        name=str(claims.get("name") or "").strip(),
        hosted_domain=hosted_domain,
    )


def authorize_identity(identity, store, admin_emails=(), school=None, is_super_admin=False):
    email = normalize_email(identity.email)
    normalized_admins = {normalize_email(item) for item in admin_emails if item}
    record = store.get_teacher(email)
    school = school or {}
    principal_context = {
        "school_id": str(school.get("school_id") or ""),
        "school_name": str(school.get("name") or ""),
        "hosted_domain": identity.hosted_domain,
        "is_super_admin": bool(is_super_admin),
    }

    if email in normalized_admins:
        bound_subject = str((school.get("admin_subjects") or {}).get(email) or "").strip()
        if bound_subject and bound_subject != identity.subject:
            raise AuthorizationError("此管理員帳號已綁定其他 Google 身分，請洽平台管理員")
        name = (record or {}).get("name") or identity.name or email
        class_codes = tuple((record or {}).get("class_codes") or ())
        return Principal(identity.subject, email, name, "admin", class_codes, **principal_context)

    if not record or not record.get("active", True):
        raise AuthorizationError("此帳號不在目前啟用的教師名單中")

    bound_subject = str(record.get("google_sub") or "").strip()
    if bound_subject and bound_subject != identity.subject:
        raise AuthorizationError("此教師帳號已綁定其他 Google 身分，請洽排課管理員")
    if not bound_subject:
        store.bind_google_subject(email, identity.subject)

    role = str(record.get("role") or "subject_teacher")
    if role == "admin":
        raise AuthorizationError("管理員權限必須由平台的學校管理員名單授予")
    return Principal(
        subject=identity.subject,
        email=email,
        name=str(record.get("name") or identity.name or email),
        role=role,
        class_codes=tuple(str(code) for code in record.get("class_codes") or ()),
        **principal_context,
    )
