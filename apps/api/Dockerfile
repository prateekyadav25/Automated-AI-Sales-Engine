FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 agrayian
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir -e . && chown -R agrayian:agrayian /app
USER agrayian
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
