FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# libgomp1: LightGBM's OpenMP runtime. libexpat1: required by the GDAL bundled in the rasterio wheel.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# Images default to production so a deployment that forgets ENVIRONMENT fails closed (the API refuses to start
# without a real SECRET_KEY, database password and CORS origins). docker-compose sets development explicitly.
ENV ENVIRONMENT=production
COPY . .
RUN mkdir -p /app/var && chown -R app:app /app/var
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
