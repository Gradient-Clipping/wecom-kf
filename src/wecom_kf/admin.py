"""Administrator console with authenticated service switches."""

import html
import time
import secrets
import re
from urllib.parse import parse_qs

from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from .store import Store


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
        return RedirectResponse("/admin", status_code=303)

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
        return RedirectResponse("/admin", status_code=303)

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
        return RedirectResponse("/admin", status_code=303)

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
        return RedirectResponse("/admin", status_code=303)

    def overview():
        with store.transaction() as cur:
            cur.execute("SELECT kind,status,COUNT(*) AS count FROM kf_jobs GROUP BY kind,status")
            counts = cur.fetchall()
            cur.execute("SELECT id,kind,status,created_at,updated_at FROM kf_jobs ORDER BY created_at DESC LIMIT 100")
            jobs = cur.fetchall()
            cur.execute("SELECT role,heartbeat FROM kf_workers ORDER BY role")
            workers = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS count FROM kf_bindings")
            bindings = cur.fetchone()["count"]
            cur.execute("SELECT status,COUNT(*) AS count FROM kf_outbox GROUP BY status")
            replies = cur.fetchall()
        return counts, jobs, workers, bindings, replies

    @app.get("/admin")
    async def admin(request: Request):
        session = request.session.get("admin", {})
        if session.get("until", 0) <= time.time():
            request.session.clear()
            try:
                return await client.authorize_redirect(request, settings.public_base_url + "/admin/auth/callback")
            except Exception:
                return PlainTextResponse("Identity service unavailable", status_code=503)
        try:
            counts, jobs, workers, bindings, replies = await run_in_threadpool(overview)
            service_states = await run_in_threadpool(store.service_states)
            human_enabled = await run_in_threadpool(store.human_support_enabled)
            query = request.query_params.get("binding", "").strip()
            if len(query) > 256:
                return PlainTextResponse("Search too long", status_code=400)
            binding_rows = await run_in_threadpool(store.bindings_for_admin, query)
        except Exception:
            return PlainTextResponse("Service data unavailable", status_code=503)
        esc = lambda value: html.escape(str(value), quote=True)
        csrf = request.session.setdefault("csrf", secrets.token_urlsafe(32))
        service_rows = "".join(
            f'<li><form method="post" action="/admin/services/{esc(s["code"])}">'
            f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
            f'<label><input type="checkbox" name="enabled" value="1" {"checked" if s["enabled"] else ""}> {esc(s["name"])} · {"已开启" if s["enabled"] else "已关闭"}</label> '
            '<button type="submit">保存</button></form></li>' for s in service_states)
        human_row = (f'<li><form method="post" action="/admin/human-support">'
                     f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
                     f'<label><input type="checkbox" name="enabled" value="1" {"checked" if human_enabled else ""}> '
                     f'0. 人工客服 · {"已开启" if human_enabled else "已关闭"}</label> '
                     '<button type="submit">保存</button></form></li>')
        binding_rows_html = "".join(
            f'<tr><td>{esc(b["external_userid"])}</td><td>{esc(b["login_no"])}</td>'
            f'<td>{esc(b["account"])}</td><td><form method="post" action="/admin/bindings/{esc(b["customer_id"])}/delete">'
            f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
            '<input name="login_no" aria-label="输入登录号确认解绑" placeholder="输入登录号确认" required maxlength="128">'
            '<button type="submit">解绑</button></form></td></tr>' for b in binding_rows)
        rows = "".join(f"<tr><td>{esc(j['id'][:12])}</td><td>{esc(j['kind'])}</td><td>{esc(j['status'])}</td><td>{esc(time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(j['updated_at'])))}</td></tr>" for j in jobs)
        worker_rows = "".join(f"<li>{esc(w['role'])}<strong>{'正常' if time.time()-w['heartbeat'] < 300 else '心跳延迟'}</strong></li>" for w in workers)
        reply_rows = "".join(f"<li>{esc(r['status'])}<strong>{r['count']}</strong></li>" for r in replies)
        active = sum(r["count"] for r in counts if r["status"] in {"pending", "running"})
        markup = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>客服管理 | LaZy</title><style>
*{{box-sizing:border-box;letter-spacing:0}}body{{margin:0;background:#f5f6f7;color:#232628;font:14px system-ui,sans-serif}}header{{background:white;border-bottom:1px solid #dfe3e6;padding:18px 28px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}}h1{{margin:0;font-size:20px}}main{{max-width:1200px;margin:auto;padding:24px}}h2{{font-size:16px;margin:0 0 16px}}section{{padding:20px 0;border-bottom:1px solid #dfe3e6}}.metrics{{display:flex;gap:60px;flex-wrap:wrap}}.metrics strong{{display:block;font-size:28px;margin-top:8px;color:#19704c}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:40px}}ul{{padding:0;list-style:none}}li{{display:flex;justify-content:space-between;gap:20px;padding:10px 0;border-bottom:1px solid #e4e7e9}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:12px 8px;text-align:left;border-bottom:1px solid #dfe3e6}}th{{background:#e9edef;font-weight:600}}.scroll{{overflow:auto}}a{{color:#176b4c}}@media(max-width:600px){{main{{padding:16px}}.columns{{grid-template-columns:1fr;gap:0}}.metrics{{gap:24px}}header{{padding:16px}}}}
</style><header><h1>LaZy 客服管理</h1><span>{esc(session['name'])} · <a href="/admin">刷新</a></span></header>
<main><section class="metrics"><div>已绑定账号<strong>{bindings}</strong></div><div>排队及执行中<strong>{active}</strong></div><div>已开启服务<strong>{sum(s['enabled'] for s in service_states)}</strong></div></section>
<section><h2>服务开关</h2><ul>{service_rows}{human_row}</ul></section>
<section><h2>账号绑定</h2><form method="get" action="/admin"><label>查找微信标识或头歌账号 <input name="binding" value="{esc(query)}" maxlength="256"></label> <button type="submit">查找</button></form><div class="scroll"><table><thead><tr><th>微信标识</th><th>头歌登录号</th><th>绑定账号</th><th>操作</th></tr></thead><tbody>{binding_rows_html or '<tr><td colspan="4">暂无匹配绑定</td></tr>'}</tbody></table></div></section>
<div class="columns"><section><h2>后台进程</h2><ul>{worker_rows or '<li>暂无心跳</li>'}</ul></section><section><h2>消息投递</h2><ul>{reply_rows or '<li>暂无消息</li>'}</ul></section></div>
<section><h2>最近任务</h2><div class="scroll"><table><thead><tr><th>任务号</th><th>类型</th><th>状态</th><th>更新时间（UTC）</th></tr></thead><tbody>{rows or '<tr><td colspan="4">暂无任务</td></tr>'}</tbody></table></div></section></main></html>'''
        return HTMLResponse(markup, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'", "Referrer-Policy": "no-referrer"})
