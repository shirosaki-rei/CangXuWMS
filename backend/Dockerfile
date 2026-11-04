FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

WORKDIR /srv

# mysqldump：每日备份用（app/tasks/backup.py）
RUN apt-get update  && apt-get install -y --no-install-recommends default-mysql-client  && rm -rf /var/lib/apt/lists/*

# 先装依赖再拷代码，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

# 非 root 运行
RUN useradd -r -u 10001 wms && chown -R wms:wms /srv
USER wms

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

# 默认起 API；worker 用同一个镜像换 entrypoint（见 docker-compose.yml）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "3"]
