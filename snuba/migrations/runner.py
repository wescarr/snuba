import logging
from datetime import datetime
from functools import partial
from typing import List, Mapping, MutableMapping, NamedTuple, Optional, Sequence, Tuple

from clickhouse_driver import errors

from snuba import settings
from snuba.clickhouse.errors import ClickhouseError
from snuba.clickhouse.escaping import escape_string
from snuba.clickhouse.native import ClickhousePool
from snuba.clusters.cluster import (
    ClickhouseClientSettings,
    ClickhouseNodeType,
    get_cluster,
)
from snuba.clusters.storage_sets import StorageSetKey
from snuba.migrations.context import Context
from snuba.migrations.errors import (
    InvalidMigrationState,
    MigrationError,
    MigrationInProgress,
)
from snuba.migrations.groups import (
    OPTIONAL_GROUPS,
    REGISTERED_GROUPS_LOOKUP,
    MigrationGroup,
    get_group_loader,
)
from snuba.migrations.migration import ClickhouseNodeMigration, CodeMigration, Migration
from snuba.migrations.operations import SqlOperation
from snuba.migrations.status import Status

logger = logging.getLogger("snuba.migrations")

LOCAL_TABLE_NAME = "migrations_local"
DIST_TABLE_NAME = "migrations_dist"


def get_active_migration_groups() -> Sequence[MigrationGroup]:
    return [
        group
        for group in REGISTERED_GROUPS_LOOKUP
        if not (group in OPTIONAL_GROUPS and group in settings.SKIPPED_MIGRATION_GROUPS)
    ]


class MigrationKey(NamedTuple):
    group: MigrationGroup
    migration_id: str

    def __str__(self) -> str:
        return f"{self.group}: {self.migration_id}"


class MigrationDetails(NamedTuple):
    migration_id: str
    status: Status
    blocking: bool


class Runner:
    def __init__(self) -> None:
        migrations_cluster = get_cluster(StorageSetKey.MIGRATIONS)
        self.__table_name = (
            LOCAL_TABLE_NAME if migrations_cluster.is_single_node() else DIST_TABLE_NAME
        )

        self.__connection = migrations_cluster.get_query_connection(
            ClickhouseClientSettings.MIGRATE
        )

        self.__status: MutableMapping[
            MigrationKey, Tuple[Status, Optional[datetime]]
        ] = {}

    def get_status(
        self, migration_key: MigrationKey
    ) -> Tuple[Status, Optional[datetime]]:
        """
        Returns the status and timestamp of a migration.
        """

        if migration_key in self.__status:
            return self.__status[migration_key]

        try:
            data = self.__connection.execute(
                f"SELECT status, timestamp FROM {self.__table_name} FINAL WHERE group = %(group)s AND migration_id = %(migration_id)s",
                {
                    "group": migration_key.group,
                    "migration_id": migration_key.migration_id,
                },
            ).results

            if data:
                status, timestamp = data[0]
                self.__status[migration_key] = (Status(status), timestamp)
            else:
                self.__status[migration_key] = (Status.NOT_STARTED, None)

            return self.__status[migration_key]

        except ClickhouseError as e:
            # If the table wasn't created yet, no migrations have started.
            if e.code != errors.ErrorCodes.UNKNOWN_TABLE:
                raise e

        return Status.NOT_STARTED, None

    def show_all(self) -> List[Tuple[MigrationGroup, List[MigrationDetails]]]:
        """
        Returns the list of migrations and their statuses for each group.
        """
        migrations: List[Tuple[MigrationGroup, List[MigrationDetails]]] = []

        migration_status = self._get_migration_status()

        def get_status(migration_key: MigrationKey) -> Status:
            return migration_status.get(migration_key, Status.NOT_STARTED)

        for group in get_active_migration_groups():
            group_migrations: List[MigrationDetails] = []
            group_loader = get_group_loader(group)

            for migration_id in group_loader.get_migrations():
                migration_key = MigrationKey(group, migration_id)
                migration = group_loader.load_migration(migration_id)
                group_migrations.append(
                    MigrationDetails(
                        migration_id, get_status(migration_key), migration.blocking
                    )
                )

            migrations.append((group, group_migrations))

        return migrations

    def run_all(self, *, force: bool = False, group: Optional[str] = None) -> None:
        """
        If group is specified, runs all pending migrations for that specific group. Makes
        sure to run any pending system migrations first so that the migrations table is
        created before running migrations for other groups. Throw an error if any migration
        is in progress.

        If no group is specified, run all pending migrations. Throws an error if any
        migration is in progress.

        Requires force to run blocking migrations.
        """

        if not group:
            pending_migrations = self._get_pending_migrations()
        else:
            pending_migrations = self._get_pending_migrations_for_group(
                "system"
            ) + self._get_pending_migrations_for_group(group)

        # Do not run migrations if any are blocking
        if not force:
            for migration_key in pending_migrations:
                migration = get_group_loader(migration_key.group).load_migration(
                    migration_key.migration_id
                )
                if migration.blocking:
                    raise MigrationError("Requires force to run blocking migrations")

        for migration_key in pending_migrations:
            self._run_migration_impl(migration_key, force=force)

    def run_migration(
        self,
        migration_key: MigrationKey,
        *,
        force: bool = False,
        fake: bool = False,
        dry_run: bool = False,
    ) -> None:
        """
        Run a single migration given its migration key and marks the migration as complete.

        Blocking migrations must be run with force.
        """

        migration_group, migration_id = migration_key

        group_migrations = get_group_loader(migration_group).get_migrations()

        if migration_id not in group_migrations:
            raise MigrationError("Could not find migration in group")

        if dry_run:
            self._run_migration_impl(migration_key, dry_run=True)
            return

        migration_status = self._get_migration_status()

        def get_status(migration_key: MigrationKey) -> Status:
            return migration_status.get(migration_key, Status.NOT_STARTED)

        if get_status(migration_key) != Status.NOT_STARTED:
            status_text = get_status(migration_key).value
            raise MigrationError(f"Migration is already {status_text}")

        for m in group_migrations[: group_migrations.index(migration_id)]:
            if get_status(MigrationKey(migration_group, m)) != Status.COMPLETED:
                raise MigrationError("Earlier migrations ned to be completed first")

        if fake:
            self._update_migration_status(migration_key, Status.COMPLETED)
        else:
            self._run_migration_impl(migration_key, force=force)

    def _run_migration_impl(
        self, migration_key: MigrationKey, *, force: bool = False, dry_run: bool = False
    ) -> None:
        migration_id = migration_key.migration_id

        context = Context(
            migration_id,
            logger,
            partial(self._update_migration_status, migration_key),
        )
        migration = get_group_loader(migration_key.group).load_migration(migration_id)

        if migration.blocking and not dry_run and not force:
            raise MigrationError("Blocking migrations must be run with force")

        migration.forwards(context, dry_run)

    def reverse_migration(
        self,
        migration_key: MigrationKey,
        *,
        force: bool = False,
        fake: bool = False,
        dry_run: bool = False,
    ) -> None:
        """
        Reverses a migration.
        """

        migration_group, migration_id = migration_key

        group_migrations = get_group_loader(migration_group).get_migrations()

        if migration_id not in group_migrations:
            raise MigrationError("Invalid migration")

        if dry_run:
            self._reverse_migration_impl(migration_key, dry_run=True)
            return

        migration_status = self._get_migration_status()

        def get_status(migration_key: MigrationKey) -> Status:
            return migration_status.get(migration_key, Status.NOT_STARTED)

        if get_status(migration_key) == Status.NOT_STARTED:
            raise MigrationError("You cannot reverse a migration that has not been run")

        if get_status(migration_key) == Status.COMPLETED and not force and not fake:
            raise MigrationError(
                "You must use force to revert an already completed migration"
            )

        for m in group_migrations[group_migrations.index(migration_id) + 1 :]:
            if get_status(MigrationKey(migration_group, m)) != Status.NOT_STARTED:
                raise MigrationError("Subsequent migrations must be reversed first")

        if fake:
            self._update_migration_status(migration_key, Status.NOT_STARTED)
        else:
            self._reverse_migration_impl(migration_key)

    def _reverse_migration_impl(
        self, migration_key: MigrationKey, *, dry_run: bool = False
    ) -> None:
        migration_id = migration_key.migration_id

        context = Context(
            migration_id,
            logger,
            partial(self._update_migration_status, migration_key),
        )
        migration = get_group_loader(migration_key.group).load_migration(migration_id)

        migration.backwards(context, dry_run)

    def _get_pending_migrations(self) -> List[MigrationKey]:
        """
        Gets pending migration list.
        """
        migrations: List[MigrationKey] = []

        for group in get_active_migration_groups():
            group_migrations = self._get_pending_migrations_for_group(group)
            migrations.extend(group_migrations)

        return migrations

    def _get_pending_migrations_for_group(self, group: str) -> List[MigrationKey]:
        """
        Gets pending migrations list for a specific group
        """
        migration_status = self._get_migration_status()

        def get_status(migration_key: MigrationKey) -> Status:
            return migration_status.get(migration_key, Status.NOT_STARTED)

        group_loader = get_group_loader(group)
        group_migrations: List[MigrationKey] = []

        for migration_id in group_loader.get_migrations():
            migration_key = MigrationKey(group, migration_id)
            status = get_status(migration_key)
            if status == Status.IN_PROGRESS:
                raise MigrationInProgress(str(migration_key))
            if status == Status.NOT_STARTED:
                group_migrations.append(migration_key)
            elif status == Status.COMPLETED and len(group_migrations):
                # We should never have a completed migration after a pending one for that group
                missing_migrations = ", ".join(
                    [m.migration_id for m in group_migrations]
                )
                raise InvalidMigrationState(f"Missing migrations: {missing_migrations}")

        return group_migrations

    def _update_migration_status(
        self, migration_key: MigrationKey, status: Status
    ) -> None:
        self.__status = {}
        next_version = self._get_next_version(migration_key)

        statement = f"INSERT INTO {self.__table_name} FORMAT JSONEachRow"
        data = [
            {
                "group": migration_key.group,
                "migration_id": migration_key.migration_id,
                "timestamp": datetime.now(),
                "status": status.value,
                "version": next_version,
            }
        ]
        self.__connection.execute(statement, data)

    def _get_next_version(self, migration_key: MigrationKey) -> int:
        result = self.__connection.execute(
            f"SELECT version FROM {self.__table_name} FINAL WHERE group = %(group)s AND migration_id = %(migration_id)s;",
            {
                "group": migration_key.group,
                "migration_id": migration_key.migration_id,
            },
        ).results
        if result:
            (version,) = result[0]
            return int(version) + 1

        return 1

    def _get_migration_status(self) -> Mapping[MigrationKey, Status]:
        data: MutableMapping[MigrationKey, Status] = {}
        migration_groups = (
            "("
            + (
                ", ".join(
                    [escape_string(group) for group in get_active_migration_groups()]
                )
            )
            + ")"
        )

        try:
            for row in self.__connection.execute(
                f"SELECT group, migration_id, status FROM {self.__table_name} FINAL WHERE group IN {migration_groups}"
            ).results:
                group_name, migration_id, status_name = row
                data[MigrationKey(MigrationGroup(group_name), migration_id)] = Status(
                    status_name
                )
        except ClickhouseError as e:
            # If the table wasn't created yet, no migrations have started.
            if e.code != errors.ErrorCodes.UNKNOWN_TABLE:
                raise e

        return data

    @classmethod
    def add_node(
        self,
        node_type: ClickhouseNodeType,
        storage_sets: Sequence[StorageSetKey],
        host_name: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ) -> None:
        client_settings = ClickhouseClientSettings.MIGRATE.value
        clickhouse = ClickhousePool(
            host_name,
            port,
            user,
            password,
            database,
            client_settings=client_settings.settings,
            send_receive_timeout=client_settings.timeout,
        )

        migrations: List[Migration] = []

        for group in get_active_migration_groups():
            group_loader = get_group_loader(group)

            for migration_id in group_loader.get_migrations():
                migration = group_loader.load_migration(migration_id)
                migrations.append(migration)

        for migration in migrations:
            if isinstance(migration, ClickhouseNodeMigration):
                operations = (
                    migration.forwards_local()
                    if node_type == ClickhouseNodeType.LOCAL
                    else migration.forwards_dist()
                )

                for sql_op in operations:
                    if isinstance(sql_op, SqlOperation):
                        if sql_op._storage_set in storage_sets:
                            sql = sql_op.format_sql()
                            logger.info(f"Executing {sql}")
                            clickhouse.execute(sql)
            elif isinstance(migration, CodeMigration):
                for python_op in migration.forwards_global():
                    python_op.execute_new_node(storage_sets)
