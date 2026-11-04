FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

WORKDIR /srv

# 国内构建走镜像源：这台服务器到官方 PyPI 实测 19.9 KB/s，14 个包要等到天黑；
# apt 走 deb.debian.org 同样很慢。海外构建可用 --build-arg 覆盖回官方源。
ARG APT_MIRROR=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# mysqldump：每日备份用（app/tasks/backup.py）
RUN sed -i -e "s|deb.debian.org|${APT_MIRROR}|g" -e "s|security.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends default-mysql-client \
 && rm -rf /var/lib/apt/lists/*

# 先装依赖再拷代码，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

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
