#!/usr/bin/env bash
# 每日备份 + 恢复演练（T-05-9 / 架构 10）。单机部署唯一的数据库保护手段，不可省。
#
#   ./tools/backup.sh                 备份到 volumes/backup/wms-YYYYmmdd-HHMM.sql.gz
#   ./tools/backup.sh restore <file>  恢复到当前库（会覆盖！）
#
# 依赖：本机 mysqldump / mysql 在 PATH，或设置 MYSQL_BIN 指向安装目录。
set -euo pipefail

BIN="${MYSQL_BIN:-/c/Program Files/MySQL/MySQL Server 8.0/bin}"
DUMP="$BIN/mysqldump.exe"
MYSQL="$BIN/mysql.exe"
DB="${DB_NAME:-wms}"
USER="${DB_USER:-wms}"
PASS="${DB_PASS:-wms123456}"
HOST="${DB_HOST:-127.0.0.1}"
DIR="${BACKUP_DIR:-./volumes/backup}"

if [[ "${1:-}" == "restore" ]]; then
  FILE="${2:?用法: backup.sh restore <file.sql.gz>}"
  echo "==> 恢复 $FILE 到 $DB（覆盖当前数据）"
  gunzip -c "$FILE" | "$MYSQL" -h"$HOST" -u"$USER" -p"$PASS" "$DB"
  echo "==> 完成。请立即跑 tools/gate_check.py 确认数据可用"
  exit 0
fi

mkdir -p "$DIR"
OUT="$DIR/wms-$(date +%Y%m%d-%H%M).sql.gz"
echo "==> 备份 $DB → $OUT"
"$DUMP" -h"$HOST" -u"$USER" -p"$PASS" \
  --single-transaction --quick --routines --triggers --set-gtid-purged=OFF "$DB" | gzip > "$OUT"

# 保留 7 天（架构 10）
find "$DIR" -name 'wms-*.sql.gz' -mtime +7 -delete
echo "==> 完成：$(du -h "$OUT" | cut -f1)"
echo "==> 演练要点：恢复到临时库后比对 inventory 行数与 txn 累计，10 分钟内能恢复才算通过"
