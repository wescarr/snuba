from snuba.admin.clickhouse.common import (
    InvalidCustomQuery,
    get_ro_query_node_connection,
    validate_ro_query,
)
from snuba.clickhouse.native import ClickhouseResult
from snuba.clusters.cluster import ClickhouseClientSettings
from snuba.datasets.schemas.tables import TableSchema
from snuba.datasets.storages.factory import get_storage
from snuba.datasets.storages.storage_key import StorageKey
from snuba.state import get_config

ENABLE_QUERYLOG_API_CONFIG = "enable_clickhouse_querylog_api"


def run_querylog_query(query: str, user: str) -> ClickhouseResult:
    querylog_storage_key = StorageKey.QUERYLOG
    schema = get_storage(querylog_storage_key).get_schema()
    assert isinstance(schema, TableSchema)

    allowed_tables = [schema.get_table_name()]
    validate_ro_query(query, allowed_tables)

    connection = get_ro_query_node_connection(
        querylog_storage_key.value, ClickhouseClientSettings.QUERY
    )

    if get_config(ENABLE_QUERYLOG_API_CONFIG, 0):
        audit_log_query(query, user)
        query_result = connection.execute(query=query, with_column_types=True)
        return query_result

    raise InvalidCustomQuery("Production ClickHouse querylog access is not yet ready.")


def audit_log_query(query: str, user: str) -> None:
    """
    Log query and user to GCP logs for auditlog
    """
    pass
