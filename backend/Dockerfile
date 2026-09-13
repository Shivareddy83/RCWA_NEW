FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app
WORKDIR /app

RUN groupadd --system --gid 10001 rcaa \
    && useradd --system --uid 10001 --gid rcaa --home-dir /app --shell /usr/sbin/nologin rcaa

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=rcaa:rcaa . .
RUN chmod 0755 /app/docker-entrypoint.sh

USER rcaa
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
