FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY studio ./studio
COPY engines ./engines
RUN pip install --no-cache-dir .
ENV STUDIO_DATA_DIR=/data STUDIO_DEV_MODE=false STUDIO_ENGINES_DIR=/app/engines
RUN useradd -m studio && mkdir -p /data && chown studio /data
USER studio
EXPOSE 8000
CMD ["python", "-m", "studio", "serve", "--host", "0.0.0.0", "--port", "8000"]
