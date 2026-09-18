"""Read-only, redacted queries used by the administrator console."""

import json
import re
import time
import math

from .admin_metadata import JOB_KINDS, JOB_STATUSES
SAFE_PROGRESS = ("passed_homeworks", "total_homeworks", "passed_challenges",
                 "total_challenges", "passed_units", "total_units", "current_step",
                 "total_steps", "current", "failures", "unknown", "has_error")


class QueryValidationError(ValueError):
    pass


def _one(params, key, default=""):
    values = params.getlist(key)
    if len(values) > 1:
        raise QueryValidationError(f"duplicate {key}")
    return values[0] if values else default


def parse_job_filters(params):
    allowed = {"page", "page_size", "status", "kind", "q", "from", "to"}
    if any(key not in allowed for key in params.keys()):
        raise QueryValidationError("unknown query field")
    raw_page = _one(params, "page", "1")
    raw_size = _one(params, "page_size", "20")
    if not re.fullmatch(r"[0-9]{1,7}", raw_page) or not re.fullmatch(r"[0-9]{1,3}", raw_size):
        raise QueryValidationError("invalid page")
    try:
        page, page_size = int(raw_page), int(raw_size)
    except (TypeError, ValueError):
        raise QueryValidationError("invalid page")
    if not 1 <= page <= 1000000 or page_size not in (20, 50, 100):
        raise QueryValidationError("invalid page")
    status, kind, q = _one(params, "status"), _one(params, "kind"), _one(params, "q")
    if status and status not in JOB_STATUSES:
        raise QueryValidationError("invalid status")
    if kind and kind not in JOB_KINDS:
        raise QueryValidationError("invalid kind")
    if len(q) > 128:
        raise QueryValidationError("query too long")
    result = {"page": page, "page_size": page_size, "status": status, "kind": kind, "q": q}
    for key in ("from", "to"):
        value = _one(params, key)
        if not value:
            result[key] = None
            continue
        if not re.fullmatch(r"[0-9]{1,12}", value):
            raise QueryValidationError(f"invalid {key}")
        try:
            parsed = int(value)
        except ValueError:
            raise QueryValidationError(f"invalid {key}")
        if not 0 <= parsed <= 253402300799:
            raise QueryValidationError(f"invalid {key}")
        result[key] = parsed
    if result["from"] is not None and result["to"] is not None and result["from"] > result["to"]:
        raise QueryValidationError("invalid range")
    return result


def _progress(kind, result):
    if kind != "solve" or not result:
        return None
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            return None
    if not isinstance(result, dict):
        return None
    # Educoder calls challenge progress `passed_units`; expose a neutral name.
    aliases = {"passed_challenges": "passed_units"}
    output = {key: result.get(aliases.get(key, key)) for key in SAFE_PROGRESS}
    for key in SAFE_PROGRESS[:8]:
        value = output[key]
        valid_number = (type(value) in (int, float) and 0 <= value <= 2147483647
                        and math.isfinite(value))
        output[key] = value if valid_number else None
    if isinstance(output["current"], str):
        output["current"] = output["current"][:256]
    elif output["current"] is not None:
        output["current"] = None
    failures = output["failures"]
    output["failures"] = ([item[:256] for item in failures[:50] if isinstance(item, str)]
                           if isinstance(failures, list) else None)
    for key in ("unknown", "has_error"):
        output[key] = output[key] if type(output[key]) is bool else None
    return output


class AdminQueries:
    def __init__(self, store):
        self.store = store

    def overview(self):
        with self.store.transaction() as cur:
            cur.execute("SELECT kind,status,COUNT(*) AS count FROM kf_jobs GROUP BY kind,status ORDER BY kind,status")
            counts = cur.fetchall()
            cur.execute("SELECT role,heartbeat FROM kf_workers ORDER BY role")
            workers = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS count FROM kf_bindings")
            bindings = int(cur.fetchone()["count"])
            cur.execute("SELECT status,COUNT(*) AS count FROM kf_outbox GROUP BY status ORDER BY status")
            replies = cur.fetchall()
        now = time.time()
        workers = [{"role": row["role"], "heartbeat": row.get("heartbeat"),
                    "healthy": (row.get("heartbeat") is not None and now - float(row["heartbeat"]) < 300)}
                   for row in workers]
        return counts, bindings, workers, replies

    def jobs(self, filters):
        where, args = [], []
        if filters["status"]:
            where.append("j.status=%s"); args.append(filters["status"])
        if filters["kind"]:
            where.append("j.kind=%s"); args.append(filters["kind"])
        if filters["q"]:
            where.append("(j.id=%s OR j.customer_id=%s OR b.account=%s OR b.login_no=%s OR c.external_userid=%s)")
            args.extend([filters["q"]] * 5)
        if filters["from"] is not None:
            where.append("j.created_at>=%s"); args.append(filters["from"])
        if filters["to"] is not None:
            where.append("j.created_at<=%s"); args.append(filters["to"])
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self.store.transaction() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM kf_jobs j LEFT JOIN kf_job_context b ON b.job_id=j.id LEFT JOIN kf_customers c ON c.id=j.customer_id" + clause, tuple(args))
            total = int(cur.fetchone()["count"])
            offset = (filters["page"] - 1) * filters["page_size"]
            cur.execute("SELECT j.id,j.customer_id,j.kind,j.status,j.created_at,j.updated_at,b.account,b.service,j.result FROM kf_jobs j LEFT JOIN kf_job_context b ON b.job_id=j.id LEFT JOIN kf_customers c ON c.id=j.customer_id" + clause + " ORDER BY j.created_at DESC,j.id DESC LIMIT %s OFFSET %s", tuple(args + [filters["page_size"], offset]))
            rows = cur.fetchall()
        items = [{"id": r["id"], "customer_id": r["customer_id"], "kind": r["kind"], "status": r["status"], "created_at": r["created_at"], "updated_at": r["updated_at"], "account": r.get("account"), "service": r.get("service"), "progress": _progress(r["kind"], r.get("result"))} for r in rows]
        return items, total

    def job(self, job_id):
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise QueryValidationError("invalid id")
        with self.store.transaction() as cur:
            cur.execute("SELECT j.id,j.customer_id,j.kind,j.status,j.created_at,j.updated_at,b.account,b.service,j.result FROM kf_jobs j LEFT JOIN kf_job_context b ON b.job_id=j.id WHERE j.id=%s", (job_id,))
            row = cur.fetchone()
        if not row:
            return None
        return {"id": row["id"], "customer_id": row["customer_id"], "kind": row["kind"], "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"], "account": row.get("account"), "service": row.get("service"), "progress": _progress(row["kind"], row.get("result"))}

    def bindings(self, query):
        if len(query) > 128:
            raise QueryValidationError("query too long")
        return self.store.bindings_for_admin(query)
