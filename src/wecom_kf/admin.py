"""Administrator console with authenticated service switches."""

import os
import re
import secrets
import time
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from .store import Store
from .admin_queries import AdminQueries, QueryValidationError, parse_job_filters
from .admin_metadata import admin_metadata


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class UnbindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_no: str = Field(min_length=1, max_length=128)


def install_admin(app, settings):
    if len(settings.session_secret) < 32:
        raise ValueError("Strong ADMIN_SESSION_SECRET required")
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                       session_cookie="__Host-kf-admin", https_only=True,
                       same_site="lax", max_age=600)
    oauth = OAuth()
    client = oauth.register("sso", client_id=settings.oidc_client_id, client_secret=settings.oidc_secret,
                            server_metadata_url=settings.oidc_issuer + "/.well-known/openid-configuration",
                            client_kwargs={"scope": "openid profile", "code_challenge_method": "S256"})
    store = Store(settings)
    queries = AdminQueries(store)

    # The Vue application is built independently and can be served by a CDN,
    # reverse proxy, or this API process in the container image. Keeping the
    # directory configurable lets local Vite development and production use
    # the same API contract without embedding templates in the backend.
    static_dir = Path(os.getenv("ADMIN_STATIC_DIR", "")) if os.getenv("ADMIN_STATIC_DIR") else (
        Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    index_file = static_dir / "index.html"
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/admin/assets", StaticFiles(directory=assets_dir), name="admin-assets")

    def api_session(request):
        session = request.session.get("admin", {})
        if session.get("until", 0) <= time.time():
            request.session.clear()
            return None
        return session

    def api_error(status, code):
        return JSONResponse({"error": code}, status_code=status, headers={"Cache-Control": "no-store"})

    def api_ok(value):
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @app.get("/admin/api/session")
    async def admin_api_session(request: Request):
        session = api_session(request)
        if not session:
            return api_error(401, "session_expired")
        csrf = request.session.setdefault("csrf", secrets.token_urlsafe(32))
        return api_ok({"name": session.get("name", "管理员"), "csrf": csrf,
                       "expires_at": session["until"]})

    def mutation_session(request):
        session = api_session(request)
        if not session:
            return None, api_error(401, "session_expired")
        origin = request.headers.get("origin")
        if origin and origin != settings.public_base_url.rstrip("/"):
            return None, api_error(403, "invalid_origin")
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not secrets.compare_digest(csrf, request.session.get("csrf", "")):
            return None, api_error(403, "invalid_csrf")
        return session, None

    @app.put("/admin/api/services/{code}")
    async def update_service(code: str, value: ServiceUpdate, request: Request):
        session, error = mutation_session(request)
        if error is not None:
            return error
        try:
            await run_in_threadpool(store.set_service_enabled, code, value.enabled, session["name"])
        except ValueError:
            return api_error(404, "not_found")
        except Exception:
            return api_error(503, "data_unavailable")
        return api_ok({"code": code, "enabled": value.enabled})

    @app.put("/admin/api/human-support")
    async def update_human(value: ServiceUpdate, request: Request):
        session, error = mutation_session(request)
        if error is not None:
            return error
        try:
            await run_in_threadpool(store.set_human_support_enabled, value.enabled, session["name"])
        except Exception:
            return api_error(503, "data_unavailable")
        return api_ok({"enabled": value.enabled})

    @app.post("/admin/api/bindings/{customer_id}/unbind")
    async def unbind_api(customer_id: str, value: UnbindRequest, request: Request):
        _, error = mutation_session(request)
        if error is not None:
            return error
        if not re.fullmatch(r"[0-9a-f]{64}", customer_id):
            return api_error(400, "invalid_customer")
        try:
            await run_in_threadpool(store.unbind, customer_id, value.login_no)
        except ValueError:
            return api_error(409, "binding_mismatch")
        except RuntimeError:
            return api_error(409, "binding_busy")
        except Exception:
            return api_error(503, "data_unavailable")
        return api_ok({"unbound": True})

    @app.get("/admin/api/metadata")
    async def admin_api_metadata(request: Request):
        if not api_session(request):
            return api_error(401, "session_expired")
        return api_ok(admin_metadata())

    @app.get("/admin/api/overview")
    async def admin_api_overview(request: Request):
        if not api_session(request):
            return api_error(401, "session_expired")
        try:
            counts, bindings, workers, replies = await run_in_threadpool(queries.overview)
            services = await run_in_threadpool(store.service_states)
            human = await run_in_threadpool(store.human_support_enabled)
        except Exception:
            return api_error(503, "data_unavailable")
        return api_ok({"generated_at": int(time.time()), "counts": counts, "bindings": bindings,
                       "workers": workers, "replies": replies, "services": services,
                       "human_support_enabled": bool(human)})

    @app.get("/admin/api/jobs")
    async def admin_api_jobs(request: Request):
        if not api_session(request):
            return api_error(401, "session_expired")
        try:
            filters = parse_job_filters(request.query_params)
            items, total = await run_in_threadpool(queries.jobs, filters)
        except QueryValidationError:
            return api_error(400, "invalid_query")
        except Exception:
            return api_error(503, "data_unavailable")
        page_size = filters["page_size"]
        return api_ok({"generated_at": int(time.time()), "items": items, "page": filters["page"],
                       "page_size": page_size, "total": total,
                       "pages": (total + page_size - 1) // page_size})

    @app.get("/admin/api/jobs/{job_id}")
    async def admin_api_job(job_id: str, request: Request):
        if not api_session(request):
            return api_error(401, "session_expired")
        try:
            job = await run_in_threadpool(queries.job, job_id)
        except QueryValidationError:
            return api_error(400, "invalid_query")
        except Exception:
            return api_error(503, "data_unavailable")
        if job is None:
            return api_error(404, "not_found")
        return api_ok({"generated_at": int(time.time()), "job": job})

    @app.get("/admin/api/bindings")
    async def admin_api_bindings(request: Request):
        if not api_session(request):
            return api_error(401, "session_expired")
        try:
            if any(key != "q" for key in request.query_params.keys()):
                raise QueryValidationError("unknown query field")
            values = request.query_params.getlist("q")
            if len(values) > 1:
                raise QueryValidationError("duplicate q")
            query = values[0] if values else ""
            rows = await run_in_threadpool(queries.bindings, query)
        except QueryValidationError:
            return api_error(400, "invalid_query")
        except Exception:
            return api_error(503, "data_unavailable")
        items = [{"customer_id": row["customer_id"], "account": row["account"],
                  "login_no": row["login_no"], "external_userid": row["external_userid"],
                  "created_at": row["created_at"]} for row in rows]
        return api_ok({"generated_at": int(time.time()), "items": items})

    @app.get("/admin/auth/callback")
    async def callback(request: Request):
        try:
            token = await client.authorize_access_token(request)
            user = token.get("userinfo") or {}
            roles = user.get("realm_access", {}).get("roles", [])
            if "platform-admin" not in roles or not user.get("sub"):
                request.session.clear()
                return PlainTextResponse("Administrator access required", status_code=403)
            request.session.clear()
            # Never put access/refresh tokens or customer credentials into cookies.
            request.session["admin"] = {"name": user.get("preferred_username", "admin"),
                                        "until": min(time.time() + 300, user["exp"])}
        except Exception:
            request.session.clear()
            return PlainTextResponse("SSO verification failed", status_code=403)
        return RedirectResponse("/", status_code=303)

    @app.get("/admin/auth/login")
    async def login(request: Request):
        if api_session(request):
            return RedirectResponse("/", status_code=303)
        request.session.clear()
        try:
            return await client.authorize_redirect(request, settings.public_base_url + "/admin/auth/callback")
        except Exception:
            return PlainTextResponse("Identity service unavailable", status_code=503)

    @app.get("/")
    async def admin_frontend():
        if not index_file.is_file():
            return PlainTextResponse(
                "Admin frontend is not built. Run `cd frontend && npm install && npm run build`, "
                "or start the Vite dev server on port 5173.",
                status_code=503,
            )
        return FileResponse(index_file, media_type="text/html",
                            headers={"Cache-Control": "no-store"})

    # Page rendering belongs to the separately built Vue frontend. Keep old
    # bookmarks working while all data access remains under /admin/api.
    @app.get("/admin")
    @app.get("/admin/")
    async def legacy_entry():
        return RedirectResponse("/", status_code=307)
