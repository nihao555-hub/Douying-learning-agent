"""
数据库连接
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.models.models import Base
from app.core.config import settings
import os

# 确保目录存在
db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
db_dir = os.path.dirname(db_path)
if db_dir and db_dir != ".":
    os.makedirs(db_dir, exist_ok=True)

# SQLite 并发写入需要更长 timeout；WAL 在首次连接后启用
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"timeout": 60},
)


async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """初始化数据库"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # WAL 模式提升并发读写能力（配合高并发视频处理）
        if settings.DATABASE_URL.startswith("sqlite"):
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=60000")


async def get_db() -> AsyncSession:
    """获取数据库会话"""
    async with async_session() as session:
        yield session
