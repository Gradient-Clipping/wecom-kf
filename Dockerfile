FROM node:22-bookworm-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.10.9 AS uv
FROM python:3.13-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=0
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY --from=frontend-build /frontend/dist /opt/admin
COPY resources /opt/seed
COPY assets ./assets
RUN uv sync --frozen --no-dev --no-cache && useradd --uid 1000 --create-home app
ARG REVISION=development
ENV APP_REVISION=$REVISION ADMIN_STATIC_DIR=/opt/admin PATH=/app/.venv/bin:$PATH
USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "wecom_kf.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers", "--timeout-graceful-shutdown", "20"]
