"""持久队列的执行服务。

并发模型（PostgreSQL 行锁 + 租约 + 终态 CAS）：

1. ``claim`` 在一个事务里用 ``FOR UPDATE SKIP LOCKED`` 挑出「排队中」或
   「运行中但租约已过期」的最早批次，原子地写入本进程租约。同一批次同一时刻
   只会被一个进程领取；原进程超时但仍连着库时，租约过期后别的进程也能接管。
2. 计算在事务外完成，后台线程按固定节奏续租，健康进程不会因单批耗时较长而被误接管。
3. 收尾用带 ``status=running AND owner=自己`` 条件的 UPDATE 做 compare-and-swap：
   只有租约仍属于自己、且批次尚未进入终态时才能落库（``lease_expires_at`` 只决定能否被
   接管，不参与收尾判据，故正常续租不会误伤收尾）。原进程晚到的成功或报错因此无法改动
   已被接管并收尾的批次。
4. 审计里的完工事件与终态写入在同一事务、受同一个 CAS 保护，重试不会重复登记完工。
"""
import logging
import threading
from time import time

from sqlalchemy import and_, or_, select, update

from src.config.resources import engine
from src.config.settings import LEASE_RENEW_INTERVAL, LEASE_SECONDS
from src.constants.job_state import JobState
from src.domain import scenario
from src.models.cases import cases
from src.models.runs import runs
from src.services.audit import record
from src.utils.serial import content_digest

logger = logging.getLogger(__name__)


class JobFailure(Exception):
    """业务/计算阶段的失败，携带当时的租约 owner，交由 worker 落库。"""

    def __init__(self, run_id, owner, cause):
        super().__init__(str(cause))
        self.run_id = run_id
        self.owner = owner
        self.cause = cause


class Lease:
    """可续租的执行租约。续租只在仍由本进程持有时推进到期时间。"""

    def __init__(self, db_engine, run_id, owner, expires_at):
        self._engine = db_engine
        self.run_id = run_id
        self.owner = owner
        self._expires_at = expires_at
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._renew_loop, name=f"lease-{run_id}", daemon=True)

    @property
    def expires_at(self):
        return self._expires_at

    def alive(self):
        """本进程是否仍持有租约（未被接管、未停止续租）。"""
        return not self._stop.is_set()

    def start(self):
        self._thread.start()

    def stop(self):
        """停止续租并等待续租线程退出，避免高吞吐下线程堆积。"""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=LEASE_SECONDS)

    def _renew_loop(self):
        while not self._stop.wait(LEASE_RENEW_INTERVAL):
            try:
                with self._engine.begin() as db:
                    deadline = int(time()) + LEASE_SECONDS
                    updated = db.execute(
                        update(runs)
                        .where(
                            runs.c.id == self.run_id,
                            runs.c.owner == self.owner,
                            runs.c.status == JobState.RUNNING,
                        )
                        .values(lease_expires_at=deadline)
                    ).rowcount
                if updated == 1:
                    self._expires_at = deadline
                else:
                    # 租约已被接管或批次已收尾：停止续租，让收尾 CAS 自然失败。
                    self._stop.set()
                    logger.warning("Run %s lease lost for owner %s", self.run_id, self.owner)
            except Exception:  # 续租失败不杀 worker，下一拍再试；租约到期会触发接管。
                logger.exception("Run %s lease renewal failed", self.run_id)


class _StaticLease:
    """失败路径不需要续租，只复用 owner 做 CAS 条件。"""

    def __init__(self, run_id, owner):
        self.run_id = run_id
        self.owner = owner
        self.expires_at = None

    def alive(self):
        return True

    def stop(self):
        pass


def _supports_skip_locked(db):
    return db.dialect.name in ("postgresql", "mysql", "oracle")


def claim(db, owner):
    """领取一个可执行批次并写入租约；没有可领取批次时返回 None。

    可领取 = 排队中，或运行中但租约已过期（上一进程超时/失联）。
    """
    now = int(time())
    reclaimable = and_(runs.c.status == JobState.RUNNING, runs.c.lease_expires_at < now)
    statement = (
        select(runs)
        .where(or_(runs.c.status == JobState.QUEUED, reclaimable))
        .order_by(runs.c.id)
        .limit(1)
    )
    statement = statement.with_for_update(skip_locked=_supports_skip_locked(db))
    task = db.execute(statement).mappings().first()
    if task is None:
        return None

    is_reclaim = task["status"] == JobState.RUNNING
    deadline = now + LEASE_SECONDS
    db.execute(
        update(runs)
        .where(runs.c.id == task["id"])
        .values(
            status=JobState.RUNNING,
            owner=owner,
            lease_expires_at=deadline,
            attempts=runs.c.attempts + 1,
            # 接管时清掉上一进程残留的半成品字段，终态只由本次收尾写入。
            result=None,
            digest=None,
            failure=None,
            finished_at=None,
        )
    )
    record(db, "reclaim" if is_reclaim else "claim", owner, "run", task["id"])
    lease = Lease(engine, task["id"], owner, deadline)
    logger.info(
        "Run %s %s by %s (attempt %s)",
        task["id"], "reclaimed" if is_reclaim else "claimed", owner, task["attempts"] + 1,
    )
    return task["id"], lease, is_reclaim


def service_one(owner):
    """领取并执行一个批次。True 表示处理过一个批次，False 表示当前没有可领取批次。"""
    with engine.begin() as db:
        claimed = claim(db, owner)
    if claimed is None:
        return False
    run_id, lease, _ = claimed
    lease.start()
    try:
        with engine.begin() as db:
            payload, parameter = db.execute(
                select(cases.c.payload, runs.c.parameter)
                .select_from(runs.join(cases, cases.c.id == runs.c.case_id))
                .where(runs.c.id == run_id)
            ).one()
        # 计算在事务外执行，长任务不占用事务和行锁；期间由租约保活。
        result = scenario.run(payload, parameter)
        output = {
            "status": JobState.DONE,
            "result": result,
            # 证据与校验摘要在同一条 UPDATE 落库：要么同时可见，要么都不可见。
            "digest": content_digest(result),
            "failure": None,
        }
    except Exception as exc:
        # 让可能已回滚的事务结束，再由 worker 在新事务里按 CAS 落失败。
        raise JobFailure(run_id, lease.owner, exc) from exc
    finally:
        lease.stop()
    _commit(run_id, lease, output)
    return True


def fail(job_failure):
    """落库失败批次；仅当租约仍属于本进程且批次未收尾时生效，重复调用安全。"""
    cause = job_failure.cause
    if isinstance(cause, (ValueError, TypeError, KeyError, OverflowError)):
        reason = str(cause) or "输入资料或批次参数不符合要求"
    else:
        logger.exception("Run %s processing failed", job_failure.run_id)
        reason = "处理失败，请检查 worker 日志"
    lease = _StaticLease(job_failure.run_id, job_failure.owner)
    _commit(job_failure.run_id, lease, {
        "status": JobState.FAILED,
        "failure": reason[:320],
        "result": None,
        "digest": None,
    })


def _commit(run_id, lease, output):
    """终态 compare-and-swap 落库。

    所有权判据是 ``status=running AND owner=自己``：
      * owner 一旦被接管方覆盖，原进程的收尾即命中 0 行；
      * 批次一旦进入终态，status 不再是 running，任何迟到写入也命中 0 行。
    ``lease_expires_at`` 只用于判定「能否被接管」，不参与收尾判据，因此正常续租
    推进到期时间不会误伤本次收尾。
    终态字段、finished_at 与审计事件在同一事务提交，重试不会重复登记完工。
    """
    now = int(time())
    with engine.begin() as db:
        updated = db.execute(
            update(runs)
            .where(
                runs.c.id == run_id,
                runs.c.status == JobState.RUNNING,
                runs.c.owner == lease.owner,
            )
            .values(finished_at=now, owner=None, lease_expires_at=None, **output)
        ).rowcount
        if updated == 0:
            logger.warning(
                "Run %s late %s from %s discarded: lease lost or already finished",
                run_id, output["status"], lease.owner,
            )
            return
        record(db, str(output["status"]), lease.owner, "run", run_id)
