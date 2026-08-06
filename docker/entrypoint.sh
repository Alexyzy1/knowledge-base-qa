#!/bin/bash
set -e

echo "=== 知识库问答系统 启动中 ==="

# Wait for MySQL
echo "--- 等待 MySQL 就绪 (mysql:3306) ---"
until python -c "import pymysql; pymysql.connect(host='mysql',port=3306,user='root',password='${MYSQL_ROOT_PASSWORD}',database='knowledge_base').close()" 2>/dev/null; do
    echo "MySQL 未就绪，等待..."
    sleep 3
done
echo "MySQL 已就绪"

# Wait for Milvus
echo "--- 等待 Milvus 就绪 (milvus-standalone:19530) ---"
until curl -sf http://milvus-standalone:9091/healthz >/dev/null 2>&1; do
    echo "Milvus 未就绪，等待..."
    sleep 3
done
echo "Milvus 已就绪"

# Initialize database and create admin user
echo "--- 初始化数据库 ---"
cd /app/backend/store
export ADMIN_PW="${ADMIN_PASSWORD}"
if [ -z "$ADMIN_PW" ]; then
    echo "错误: ADMIN_PASSWORD 未设置，请在 .env 中设置"
    exit 1
fi
python -c "
import os, sys
os.environ['ADMIN_PW'] = '${ADMIN_PW}'
os.environ['MYSQL_URL'] = 'mysql+pymysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/knowledge_base?charset=utf8mb4'
exec(open('init_auth.py').read())
"

echo "--- 启动应用 ---"
cd /app/backend
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000
