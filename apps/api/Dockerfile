FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 agrayian
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && python -c 'import tomllib,subprocess; deps=tomllib.load(open("pyproject.toml","rb"))["project"]["dependencies"]; subprocess.check_call(["pip","install",*deps])'
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-deps --no-cache-dir -e . \
    && chown -R agrayian:agrayian /app
USER agrayian
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python -m app.workers.health
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
