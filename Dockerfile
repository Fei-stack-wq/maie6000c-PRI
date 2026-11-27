FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ARG INSTALL_GROUPING=0

COPY pyproject.toml README.md /app/
COPY services /app/services
COPY scripts /app/scripts
COPY frontend /app/frontend
COPY docs/architecture.md docs/human-review.md docs/operations.md /app/docs/
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY data /app/data

RUN pip install --upgrade pip && pip install -e . \
    && if [ "$INSTALL_GROUPING" = "1" ]; then \
         pip install torch --index-url https://download.pytorch.org/whl/cpu \
         && pip install -e '.[grouping]' \
         && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"; \
       fi

CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
