"""Administrator console with authenticated service switches."""

import time
import secrets
import re
from importlib import resources
from urllib.parse import parse_qs

from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from .store import Store
from .admin_queries import AdminQueries, QueryValidationError, parse_job_filters
from .admin_ui import render_admin
from .admin_metadata import admin_metadata


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

    @app.get("/admin/assets/{name}")
    async def admin_asset(name: str, request: Request):
        if name not in {"console.css", "console.js"}:
            return PlainTextResponse("Not found", status_code=404)
        # Assets are public and contain no account/session data; resolve only the two names above.
        try:
            data = resources.files("wecom_kf.admin_assets").joinpath(name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError):
            return PlainTextResponse("Not found", status_code=404)
        media = "text/css; charset=utf-8" if name.endswith(".css") else "application/javascript; charset=utf-8"
        return Response(data, media_type=media, headers={"Cache-Control": "no-store"})

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

    async def admin_form(request):
        session = request.session.get("admin", {})
        if session.get("until", 0) <= time.time():
            return None, PlainTextResponse("Administrator access required", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != "null" and origin != settings.public_base_url.rstrip("/"):
            return None, PlainTextResponse("Invalid origin", status_code=403)
        body = await request.body()
        if len(body) > 4096:
            return None, PlainTextResponse("Invalid request", status_code=400)
        form = parse_qs(body.decode("utf-8", errors="replace"))
        token = form.get("csrf", [""])[0]
        if not token or not secrets.compare_digest(token, request.session.get("csrf", "")):
            return None, PlainTextResponse("Invalid CSRF token", status_code=403)
        return (session, form), None

    @app.post("/admin/services/{code}")
    async def set_service(code: str, request: Request):
        data, error = await admin_form(request)
        if error:
            return error
        session, form = data
        try:
            await run_in_threadpool(store.set_service_enabled, code, form.get("enabled") == ["1"], session.get("name", "admin"))
        except ValueError:
            return PlainTextResponse("Unknown service", status_code=404)
        except Exception:
            return PlainTextResponse("Service settings unavailable", status_code=503)
        return RedirectResponse("/#settings", status_code=303)

    @app.post("/admin/human-support")
    async def set_human_support(request: Request):
        data, error = await admin_form(request)
        if error:
            return error
        session, form = data
        try:
            await run_in_threadpool(store.set_human_support_enabled, form.get("enabled") == ["1"], session.get("name", "admin"))
        except Exception:
            return PlainTextResponse("Human support settings unavailable", status_code=503)
        return RedirectResponse("/#settings", status_code=303)

    @app.post("/admin/bindings/{customer_id}/delete")
    async def delete_binding(customer_id: str, request: Request):
        data, error = await admin_form(request)
        if error:
            return error
        if not re.fullmatch(r"[0-9a-f]{64}", customer_id):
            return PlainTextResponse("Invalid customer", status_code=400)
        _, form = data
        login_no = form.get("login_no", [""])[0]
        if not login_no or len(login_no) > 128:
            return PlainTextResponse("Login number required", status_code=400)
        try:
            await run_in_threadpool(store.unbind, customer_id, login_no)
        except ValueError:
            return PlainTextResponse("Binding changed or login number mismatched", status_code=409)
        except RuntimeError:
            return PlainTextResponse("Active task or unsettled order: cannot unbind", status_code=409)
        except Exception:
            return PlainTextResponse("Binding unavailable", status_code=503)
        return RedirectResponse("/#bindings", status_code=303)

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

    # The public domain root is the console; keep old bookmarks and callback
    # URLs working without broad catch-all routes or proxy rewrites.
    @app.get("/")
    @app.get("/admin/")
    @app.get("/admin")
    async def admin(request: Request):
        session = request.session.get("admin", {})
        if session.get("until", 0) <= time.time():
            request.session.clear()
            try:
                return await client.authorize_redirect(request, settings.public_base_url + "/admin/auth/callback")
            except Exception:
                return PlainTextResponse("Identity service unavailable", status_code=503)
        csrf = request.session.setdefault("csrf", secrets.token_urlsafe(32))
        return render_admin(session.get("name", "管理员"), csrf)
