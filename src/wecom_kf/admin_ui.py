"""HTML shell for the authenticated customer-service administrator console."""
from html import escape
from fastapi.responses import HTMLResponse


def render_admin(username: str, csrf: str) -> HTMLResponse:
    """Render the data-free console shell; console.js populates it from admin APIs."""
    user = escape(str(username or "管理员"), quote=True)
    token = escape(str(csrf or ""), quote=True)
    markup = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="admin-user" content="{user}"><meta name="csrf-token" content="{token}">
<title>LaZy · 客服运营台</title><link rel="stylesheet" href="/admin/assets/console.css">
</head><body>
<canvas id="nebula-canvas" class="nebula-canvas" aria-hidden="true"></canvas>
<div class="app-shell">
 <aside class="sidebar"><div class="brand"><span class="brand-mark">L</span><span>LaZy</span></div>
  <nav aria-label="主导航"><a class="nav-item active" data-page="overview" aria-current="page" href="#overview">总览</a><a class="nav-item" data-page="jobs" href="#jobs">任务中心</a><a class="nav-item" data-page="bindings" href="#bindings">账号绑定</a><a class="nav-item" data-page="settings" href="#settings">服务设置</a></nav>
  <div class="sidebar-foot"><span class="status-dot"></span><span id="system-health">运行状态待同步</span></div>
 </aside>
 <div class="workspace"><header class="topbar"><button class="menu-toggle" type="button" aria-label="打开导航">☰</button><div><h1>客服运营台</h1><p class="eyebrow">WECHAT CUSTOMER SERVICE</p></div><div class="top-actions"><span class="sync-label" id="sync-status">等待同步</span><button class="btn btn-ghost" id="refresh-btn" type="button">↻ 刷新</button><span class="user-pill">{user}</span></div></header>
 <main id="main-content" tabindex="-1">
  <div id="alert" class="alert" role="status" hidden></div>
  <section id="overview" class="view-section app-page" data-page="overview"><div class="section-heading"><div><p class="eyebrow">实时概况</p><h2>运营总览</h2></div><span class="muted" id="last-success">尚未同步</span></div>
   <div class="metric-grid" id="metric-grid"><div class="metric-card skeleton"></div><div class="metric-card skeleton"></div><div class="metric-card skeleton"></div><div class="metric-card skeleton"></div></div>
   <div class="overview-grid"><article class="panel"><div class="panel-title"><h3>任务状态</h3><span class="muted">全库口径</span></div><div id="status-summary" class="status-summary"></div></article><article class="panel"><div class="panel-title"><h3>运行进程</h3><span class="muted">心跳监控</span></div><div id="workers" class="worker-list"></div></article><article class="panel"><div class="panel-title"><h3>消息投递</h3><span class="muted">当前队列</span></div><div id="replies" class="reply-list"></div></article></div>
  </section>
  <section id="jobs" class="view-section app-page" data-page="jobs" hidden><div class="section-heading"><div><p class="eyebrow">执行记录</p><h2>任务中心</h2></div><button class="btn btn-ghost" id="clear-filters" type="button">清空筛选</button></div>
   <form class="filters" id="job-filters"><label>关键词<input name="q" maxlength="128" placeholder="任务 ID、客户 ID、账号或微信标识"></label><label>状态<select name="status" disabled><option value="">全部状态</option></select></label><label>类型<select name="kind" disabled><option value="">全部类型</option></select></label><label>开始日期<input type="date" name="from"></label><label>结束日期<input type="date" name="to"></label><button class="btn btn-primary" type="submit">查询</button></form>
   <div class="table-wrap"><table><thead><tr><th>任务</th><th>客户</th><th>类型</th><th>状态</th><th>用户进度</th><th>更新时间</th><th></th></tr></thead><tbody id="jobs-body"><tr><td colspan="7" class="empty">正在加载任务…</td></tr></tbody></table></div><div class="pager" id="pager"></div>
  </section>
  <section id="bindings" class="view-section app-page" data-page="bindings" hidden><div class="section-heading"><div><p class="eyebrow">身份关联</p><h2>账号绑定</h2></div><span class="muted">精确匹配，最多显示 50 条</span></div><form class="binding-search" id="binding-form"><input name="q" maxlength="128" placeholder="搜索账号、微信标识或登录号"><button class="btn btn-primary" type="submit">查找</button></form><div class="table-wrap"><table><thead><tr><th>客户</th><th>账号</th><th>登录号</th><th>微信标识</th><th>绑定时间</th><th>操作</th></tr></thead><tbody id="bindings-body"><tr><td colspan="6" class="empty">输入关键词查找绑定</td></tr></tbody></table></div></section>
  <section id="settings" class="view-section app-page" data-page="settings" hidden><div class="section-heading"><div><p class="eyebrow">运营配置</p><h2>服务设置</h2></div></div><div class="settings-grid" id="services"><div class="empty">正在加载设置…</div></div></section>
 </main><footer class="footer">数据仅展示已授权运营信息 · 自动同步每 15 秒 <span id="sync-note"></span></footer></div>
</div><aside class="drawer" id="job-drawer" aria-hidden="true"><div class="drawer-head"><h2>任务详情</h2><button class="icon-btn" id="drawer-close" type="button" aria-label="关闭">×</button></div><div id="drawer-body"></div></aside><div class="drawer-backdrop" id="drawer-backdrop"></div>
<script src="/admin/assets/console.js" defer></script></body></html>'''
    return HTMLResponse(markup, headers={"Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
