FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir . && groupadd -g 10001 app && useradd -u 10001 -g app -M app
RUN mkdir /data && chown app:app /data
USER app
EXPOSE 8080/tcp 3702/udp
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('ONVIF_PORT','8080') + '/healthz', timeout=3)"
CMD ["tuya-onvif-local-bridge"]
