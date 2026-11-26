from sqlalchemy import inspect, text

from src.models import audit, cases, reviews, runs, users  # Register the tables.
from src.models.base import metadata

# 增量字段：v001 建表后补齐执行租约与重试计数。
_ADDED_COLUMNS = {
    "runs": {
        "owner": "VARCHAR(64)",
        "lease_expires_at": "BIGINT",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
    },
}
_ADDED_INDEXES = {
    "runs": {
        "ix_runs_lease": ("status", "lease_expires_at"),
    },
}


def _has_index(inspector, table_name, index_name):
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade(connection):
    # Version 1 建立全部表（全新库直接带上新列）。
    metadata.create_all(connection)

    # 对已存在的旧库做幂等增量迁移。
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table_name, columns in _ADDED_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_type in columns.items():
            if column_name not in present:
                connection.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                ))
    for table_name, indexes in _ADDED_INDEXES.items():
        if table_name not in existing_tables:
            continue
        for index_name, columns in indexes.items():
            if not _has_index(inspector, table_name, index_name):
                connection.execute(text(
                    f"CREATE INDEX {index_name} ON {table_name} ({', '.join(columns)})"
                ))
