#!/bin/bash

# 确保脚本在任何命令失败时退出
set -e

# 1. 数据库迁移
echo "Applying database migrations..."
python manage.py migrate --noinput

# 2. 创建默认管理员用户
echo "Creating default admin user if it does not exist..."
python manage.py init_admin

# 3. 同步预置 Skills，修复数据库记录存在但媒体目录缺失导致的不可用问题
echo "Syncing bundled skills..."
python manage.py init_skills

# 4. 启动 supervisord 来管理所有服务
echo "Starting supervisord..."
exec supervisord -c /app/supervisord.conf
