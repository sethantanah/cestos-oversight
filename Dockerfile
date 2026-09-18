FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/cestos
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.10.9
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --locked --no-dev --no-cache
RUN uv pip check --python .venv/bin/python
RUN .venv/bin/python -c "import numpy, faiss, fastembed, rapidocr_onnxruntime, pypdf, pypdfium2, docx, openpyxl, pptx, PIL, bs4, striprtf, xlrd; from app.main import create_app"
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY frontend ./frontend
ENV DOCUMENT_INDEX_DIR=/home/cestos/document-index
RUN useradd --create-home --uid 10001 cestos
USER cestos
RUN mkdir -p /home/cestos/document-index/models \
    && .venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/home/cestos/document-index/models')"
EXPOSE 8000
CMD ["/srv/cestos/.venv/bin/python", "-m", "scripts.start"]
