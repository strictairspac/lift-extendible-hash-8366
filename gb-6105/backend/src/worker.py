import logging
import os
import socket
import time
import uuid

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.config.resources import cache, engine
from src.services.execution import JobFailure, fail, service_one

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

# 进程级唯一标识：写入 runs.owner，用于租约归属与终态 CAS。
# 容器名 + 随机后缀，保证同一镜像多副本/重启后的进程标识都不同。
WORKER_ID = f"{os.environ.get('HOSTNAME') or socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def check():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    heartbeat = cache.get("workbench:heartbeat")
    return heartbeat is not None and time.time() - float(heartbeat) < 90


def work():
    logger.info("Worker %s started", WORKER_ID)
    while True:
        try:
            cache.set("workbench:heartbeat", time.time(), ex=90)
            try:
                if service_one(WORKER_ID):
                    continue
            except JobFailure as exc:
                logger.exception("Run %s failed", exc.run_id)
                fail(exc)
                continue
            # 没有批次时阻塞等待唤醒；每秒也会回到循环，使过期租约最迟 1 秒后被接管。
            cache.blpop("workbench:wake", timeout=1)
        except (RedisError, SQLAlchemyError):
            logger.exception("Worker connection unavailable")
            time.sleep(2)


if __name__ == "__main__":
    work()
