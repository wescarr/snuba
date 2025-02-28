from snuba.clickhouse.columns import (
    UUID,
    Array,
    ColumnSet,
    DateTime,
    IPv4,
    IPv6,
    Nested,
)
from snuba.clickhouse.columns import SchemaModifiers as Modifiers
from snuba.clickhouse.columns import String, UInt
from snuba.clusters.storage_sets import StorageSetKey
from snuba.datasets.plans.splitters.strategies import (
    ColumnSplitQueryStrategy,
    TimeSplitQueryStrategy,
)
from snuba.datasets.schemas.tables import TableSchema
from snuba.datasets.storage import ReadableTableStorage
from snuba.datasets.storages.errors import storage as error_storage
from snuba.datasets.storages.errors_common import mandatory_conditions
from snuba.datasets.storages.storage_key import StorageKey
from snuba.datasets.storages.transactions import storage as transactions_storage
from snuba.query.processors.physical.arrayjoin_keyvalue_optimizer import (
    ArrayJoinKeyValueOptimizer,
)
from snuba.query.processors.physical.empty_tag_condition_processor import (
    EmptyTagConditionProcessor,
)
from snuba.query.processors.physical.events_bool_contexts import (
    EventsBooleanContextsProcessor,
)
from snuba.query.processors.physical.hexint_column_processor import (
    HexIntColumnProcessor,
)
from snuba.query.processors.physical.mapping_optimizer import MappingOptimizer
from snuba.query.processors.physical.mapping_promoter import MappingColumnPromoter
from snuba.query.processors.physical.null_column_caster import NullColumnCaster
from snuba.query.processors.physical.prewhere import PrewhereProcessor
from snuba.query.processors.physical.table_rate_limit import TableRateLimit
from snuba.query.processors.physical.uuid_column_processor import UUIDColumnProcessor

columns = ColumnSet(
    [
        ("event_id", UUID()),
        ("project_id", UInt(64)),
        ("type", String()),
        ("timestamp", DateTime()),
        ("platform", String()),
        ("environment", String(Modifiers(nullable=True))),
        ("release", String(Modifiers(nullable=True))),
        ("dist", String(Modifiers(nullable=True))),
        ("transaction_name", String()),
        ("message", String()),
        ("title", String()),
        ("user", String()),
        ("user_hash", UInt(64)),
        ("user_id", String(Modifiers(nullable=True))),
        ("user_name", String(Modifiers(nullable=True))),
        ("user_email", String(Modifiers(nullable=True))),
        ("ip_address_v4", IPv4(Modifiers(nullable=True))),
        ("ip_address_v6", IPv6(Modifiers(nullable=True))),
        ("sdk_name", String(Modifiers(nullable=True))),
        ("sdk_version", String(Modifiers(nullable=True))),
        ("http_method", String(Modifiers(nullable=True))),
        ("http_referer", String(Modifiers(nullable=True))),
        ("tags", Nested([("key", String()), ("value", String())])),
        ("_tags_hash_map", Array(UInt(64))),
        ("contexts", Nested([("key", String()), ("value", String())])),
        ("trace_id", UUID(Modifiers(nullable=True))),
        ("span_id", UInt(64, Modifiers(nullable=True))),
        ("deleted", UInt(8)),
    ]
)

schema = TableSchema(
    columns=columns,
    local_table_name="discover_local",
    dist_table_name="discover_dist",
    storage_set_key=StorageSetKey.DISCOVER,
    mandatory_conditions=mandatory_conditions,
)

storage = ReadableTableStorage(
    storage_key=StorageKey.DISCOVER,
    storage_set_key=StorageSetKey.DISCOVER,
    schema=schema,
    query_processors=[
        MappingColumnPromoter(
            mapping_specs={
                "tags": {
                    "environment": "environment",
                    "sentry:release": "release",
                    "sentry:dist": "dist",
                    "sentry:user": "user",
                },
                "contexts": {"trace.trace_id": "trace_id", "trace.span_id": "span_id"},
            }
        ),
        MappingOptimizer("tags", "_tags_hash_map", "tags_hash_map_enabled"),
        EmptyTagConditionProcessor(),
        ArrayJoinKeyValueOptimizer("tags"),
        UUIDColumnProcessor(set(["event_id", "trace_id"])),
        HexIntColumnProcessor(set(["span_id"])),
        EventsBooleanContextsProcessor(),
        PrewhereProcessor(
            [
                "event_id",
                "release",
                "message",
                "transaction_name",
                "environment",
                "project_id",
            ]
        ),
        NullColumnCaster([transactions_storage, error_storage]),
        TableRateLimit(),
    ],
    query_splitters=[
        ColumnSplitQueryStrategy(
            id_column="event_id",
            project_column="project_id",
            timestamp_column="timestamp",
        ),
        TimeSplitQueryStrategy(timestamp_col="timestamp"),
    ],
)
