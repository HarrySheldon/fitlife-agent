FROM python:3.12-slim

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120
ARG PIP_RETRIES=5

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir \
    --index-url "$PIP_INDEX_URL" \
    --timeout "$PIP_DEFAULT_TIMEOUT" \
    --retries "$PIP_RETRIES" \
    -r /app/requirements.txt

COPY backend /app/backend
COPY scripts /app/scripts

RUN python /app/scripts/generate_sample_data.py

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
