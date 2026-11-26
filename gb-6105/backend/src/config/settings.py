import os

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
JWT_SECRET = os.environ["JWT_SECRET"]
DEMO_PASSWORD = os.environ["DEMO_PASSWORD"]
SEED_DEMO = os.environ.get("SEED_DEMO", "true").lower() == "true"

# 单次执行租约时长（秒）：租约过期后，其他进程可接管同一批次。
# 健康进程会在执行期间持续续租，只有失联/超时的进程才会让租约过期。
LEASE_SECONDS = max(5, int(os.environ.get("LEASE_SECONDS", "30")))
# 续租间隔，约为租约时长的三分之一，保证网络抖动下仍有续租余量。
LEASE_RENEW_INTERVAL = max(1, LEASE_SECONDS // 3)
