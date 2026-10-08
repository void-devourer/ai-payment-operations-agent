FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend backend
COPY scripts scripts
COPY infra/migrations infra/migrations
COPY tests tests
RUN useradd --uid 10001 --create-home app
USER app
CMD ["uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
