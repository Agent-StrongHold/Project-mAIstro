FROM python:3.12-slim

WORKDIR /app

COPY packages/maistro-core/src/maistro/ /app/packages/maistro-core/src/maistro/
COPY packages/hive-conductor/backend/ /app/packages/hive-conductor/backend/
COPY packages/hive-conductor/frontend/dist/ /app/packages/hive-conductor/frontend/dist/

RUN pip install --no-cache-dir -r /app/packages/hive-conductor/backend/requirements.txt 2>/dev/null || pip install --no-cache-dir fastapi uvicorn httpx pydantic bcrypt

WORKDIR /app/packages/hive-conductor/backend

EXPOSE 8101

# Run as a non-root user. The default data dir is ~/.conductor, so the user needs
# a writable home; /app is chowned so any build artifacts remain accessible.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8101"]
