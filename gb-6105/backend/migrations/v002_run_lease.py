"""Version 2: 批次执行租约与接管计数。

新库由 v001 的声明式建表直接包含这些列；旧库通过 v001 的幂等 ALTER 补齐。
本迁移保留独立版本入口，便于升级链留痕，并在历史库上再次幂等确认结构。
"""
from migrations.v001_workbench import upgrade as upgrade_v001


def upgrade(connection):
    upgrade_v001(connection)
