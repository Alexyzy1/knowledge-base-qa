"""共享数据库 Engine — 全局唯一连接池。

mysql_store 和 auth_store 共用此 engine，避免双池浪费、保证跨模块
可在一个事务内操作（需要时可通过 sessionmaker 获取同一 Session）。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import config

engine = create_engine(
    config.MYSQL_URL,
    pool_size=8,
    max_overflow=12,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
