FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/cestos
RUN pip install --no-cache-dir uv==0.10.9
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev --no-cache
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY frontend ./frontend
RUN useradd --create-home --uid 10001 cestos
USER cestos
EXPOSE 8000
CMD ["/srv/cestos/.venv/bin/python", "-m", "scripts.start"]
