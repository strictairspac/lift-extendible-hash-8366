from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Index, Integer, String, Table
from .base import metadata


runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("status", String(16), nullable=False, index=True),
    Column("parameter", Integer, nullable=False),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger, nullable=True),
    Column("result", JSON(none_as_null=True), nullable=True),
    Column("failure", String(320), nullable=True),
    Column("digest", String(64), nullable=True),
    # 执行租约：owner 为当前持有批次的进程标识，lease_expires_at 为租约到期的绝对时间。
    # running 且租约未过期的批次不会被别的进程领取；租约过期即可被接管。
    Column("owner", String(64), nullable=True),
    Column("lease_expires_at", BigInteger, nullable=True),
    # 累计领取次数（含接管），用于观察夜间中断与重试，不参与业务判定。
    Column("attempts", Integer, nullable=False, server_default="0"),
    Index("ix_runs_lease", "status", "lease_expires_at"),
)
