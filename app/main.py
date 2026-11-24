from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .db import SessionLocal, init_db
from .errors import AppError, AuthRequired
from .models import User
from .routers import admin, auth, dashboard, groups, messages, topics
from .security import safe_next_url
from .service_errors import ServiceError
from .web import render

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def _session_user(request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        with SessionLocal() as db:
            user = db.get(User, int(user_id))
            if user is not None and user.is_active:
                return user
    except (TypeError, ValueError):
        return None
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db()
    if not settings.mock_aliyun and not settings.instance_ids:
        raise RuntimeError(
            "ALLOWED_INSTANCE_IDS 未配置：必须显式指定允许管理的实例，避免面板操作整个账号。"
        )
    if not settings.mock_aliyun:
        if settings.secret_key.startswith("dev-only") or len(settings.secret_key) < 32:
            raise RuntimeError(
                "SECRET_KEY 未配置或长度不足 32 字符：请生成随机密钥后再启动。"
            )
        if not settings.cookie_secure:
            logger.warning(
                "COOKIE_SECURE=false：如果面板通过 HTTPS 访问，请务必设为 true"
            )
    if settings.mock_aliyun:
        logger.warning("MOCK_ALIYUN=1：使用内存 Mock 数据，不会访问阿里云")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="rmq_session",
        max_age=settings.session_ttl_hours * 3600,
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'self'",
        )
        if "text/html" in response.headers.get("content-type", ""):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(topics.router)
    app.include_router(groups.router)
    app.include_router(messages.router)
    app.include_router(admin.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return JSONResponse({"status": "ok", "mock": settings.mock_aliyun})

    @app.exception_handler(AuthRequired)
    async def auth_required_handler(request: Request, exc: AuthRequired):
        target = safe_next_url(exc.next_url)
        return RedirectResponse(
            f"/login?next={quote(target, safe='')}",
            status_code=303,
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return render(
            request,
            "error.html",
            user=_session_user(request),
            status_code=exc.status_code,
            message=exc.message,
            hint=exc.hint,
        )

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return render(
            request,
            "error.html",
            user=_session_user(request),
            status_code=exc.status_code,
            message=exc.message,
            hint=f"错误码：{exc.code}",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        default_messages = {
            400: "请求不合法",
            401: "请先登录",
            403: "没有权限执行该操作",
            404: "页面不存在",
            405: "请求方法不允许",
        }
        detail = exc.detail if isinstance(exc.detail, str) else None
        if detail in {"Not Found", "Bad Request", "Method Not Allowed"}:
            detail = None
        return render(
            request,
            "error.html",
            user=_session_user(request),
            status_code=exc.status_code,
            message=detail or default_messages.get(exc.status_code, "请求失败"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        logger.info("validation error on %s: %s", request.url.path, exc.errors())
        return render(
            request,
            "error.html",
            user=_session_user(request),
            status_code=400,
            message="请求参数不合法",
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("unhandled error on %s", request.url.path)
        return render(
            request,
            "error.html",
            user=_session_user(request),
            status_code=500,
            message="服务器内部错误",
            hint="请查看服务端日志，或联系面板管理员。",
        )

    return app


app = create_app()
