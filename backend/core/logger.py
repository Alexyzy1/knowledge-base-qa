import logging
import sys
from pathlib import Path
from loguru import logger

# 日志目录 = 项目根/logs （logger.py 在 backend/core/ 下，往上两级是项目根）
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class InterceptHandler(logging.Handler):
    """把标准库 logging（uvicorn、sqlalchemy 等）的日志也转给 loguru。"""
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logger():
    logger.remove()  # 清掉默认 handler，自己接管

    # 控制台：带颜色，DEBUG 起
    logger.add(
        sys.stderr, level="DEBUG",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # 文件：每天 0 点轮转、保留 7 天，INFO 起
    logger.add(
        LOG_DIR / "app_{time:YYYY-MM-DD}.log",
        level="INFO", rotation="00:00", retention="7 days", encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    logger.info("logger 初始化完成，日志目录: {}", LOG_DIR)
    return logger
