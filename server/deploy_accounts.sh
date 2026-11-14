#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo '请在云服务器root SSH终端运行此脚本。' >&2
  exit 1
fi
cd /opt/p4schedule
test -f server/migrate_accounts.py
test -x .venv/bin/python
systemctl stop p4schedule
umask 077
backup=$(mktemp --suffix=.sql /root/p4schedule-before-accounts-XXXXXXXX)
echo "正在备份数据库到 $backup"
if ! mysqldump --single-transaction --no-tablespaces p4schedule > "$backup"; then
  echo '备份失败，未执行迁移。API保持停止，请查看错误。' >&2
  exit 1
fi
echo '设置的是课表网站登录密码，不是SSH或MySQL密码。'
.venv/bin/python server/migrate_accounts.py --owner aiymsore
systemctl start p4schedule
sleep 2
systemctl is-active p4schedule
curl -fsS http://127.0.0.1:8000/api/health
printf '\n'
echo '后端已启动。请打开 https://api.aiymsore.com/ 登录验证；GitHub Pages尚未切换。'
