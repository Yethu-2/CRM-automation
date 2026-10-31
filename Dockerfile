FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ROOT=/app DATA_DIR=/app/data
WORKDIR /app
COPY backend/requirements.txt backend/requirements-dev.txt backend/
ARG DEV=0
RUN pip install --no-cache-dir -r backend/requirements$( [ "$DEV" = 1 ] && echo -dev ).txt
COPY backend backend
COPY skills skills
COPY skills-local skills-local
COPY prices.json .
RUN useradd --uid 1000 --create-home app && mkdir -p data && chown app data
USER app
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
