"""
日志配置
"""
import sys
import os
from loguru import logger


def setup_logger():
    """配置日志"""
    logger.remove()
    
    # 控制台输出
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        enqueue=True
    )
    
    # 文件输出
    os.makedirs("./data/logs", exist_ok=True)
    logger.add(
        "./data/logs/orchestrator.log",
        rotation="10 MB",
        retention="30 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function} - {message}",
        enqueue=True
    )
    
    return logger


logger = setup_logger()
