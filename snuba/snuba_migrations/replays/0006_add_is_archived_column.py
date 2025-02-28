from typing import List, Sequence, Tuple

from snuba.clickhouse.columns import Column, UInt
from snuba.clusters.storage_sets import StorageSetKey
from snuba.migrations import migration, operations
from snuba.migrations.columns import MigrationModifiers as Modifiers

new_columns: Sequence[Tuple[Column[Modifiers], str]] = [
    (Column("is_archived", UInt(8, Modifiers(nullable=True))), "urls")
]


class Migration(migration.ClickhouseNodeMigration):
    blocking = False

    def forwards_local(self) -> Sequence[operations.SqlOperation]:
        ops: List[operations.SqlOperation] = []

        for column, after in new_columns:
            ops.append(
                operations.AddColumn(
                    storage_set=StorageSetKey.REPLAYS,
                    table_name="replays_local",
                    column=column,
                    after=after,
                )
            )

        return ops

    def backwards_local(self) -> Sequence[operations.SqlOperation]:
        ops: List[operations.SqlOperation] = []

        for column, _ in reversed(new_columns):
            ops.append(
                operations.DropColumn(
                    StorageSetKey.REPLAYS, "replays_local", column.name
                )
            )

        return ops

    def forwards_dist(self) -> Sequence[operations.SqlOperation]:
        ops: List[operations.SqlOperation] = []

        for column, after in new_columns:
            ops.append(
                operations.AddColumn(
                    storage_set=StorageSetKey.REPLAYS,
                    table_name="replays_dist",
                    column=column,
                    after=after,
                )
            )

        return ops

    def backwards_dist(self) -> Sequence[operations.SqlOperation]:
        ops: List[operations.SqlOperation] = []

        for column, _ in reversed(new_columns):
            ops.append(
                operations.DropColumn(
                    StorageSetKey.REPLAYS, "replays_dist", column.name
                )
            )

        return ops
