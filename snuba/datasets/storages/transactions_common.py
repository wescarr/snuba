from snuba.clickhouse.columns import (
    UUID,
    Array,
    ColumnSet,
    DateTime,
    Float,
    IPv4,
    IPv6,
    Nested,
)
from snuba.clickhouse.columns import SchemaModifiers as Modifiers
from snuba.clickhouse.columns import String, UInt
from snuba.datasets.plans.splitters.strategies import TimeSplitQueryStrategy
from snuba.query.processors.condition_checkers.checkers import ProjectIdEnforcer
from snuba.query.processors.physical.array_has_optimizer import ArrayHasOptimizer
from snuba.query.processors.physical.arrayjoin_keyvalue_optimizer import (
    ArrayJoinKeyValueOptimizer,
)
from snuba.query.processors.physical.arrayjoin_optimizer import ArrayJoinOptimizer
from snuba.query.processors.physical.bloom_filter_optimizer import BloomFilterOptimizer
from snuba.query.processors.physical.empty_tag_condition_processor import (
    EmptyTagConditionProcessor,
)
from snuba.query.processors.physical.events_bool_contexts import (
    EventsBooleanContextsProcessor,
)
from snuba.query.processors.physical.hexint_column_processor import (
    HexIntArrayColumnProcessor,
    HexIntColumnProcessor,
)
from snuba.query.processors.physical.mapping_optimizer import MappingOptimizer
from snuba.query.processors.physical.mapping_promoter import MappingColumnPromoter
from snuba.query.processors.physical.prewhere import PrewhereProcessor
from snuba.query.processors.physical.table_rate_limit import TableRateLimit
from snuba.query.processors.physical.tuple_unaliaser import TupleUnaliaser
from snuba.query.processors.physical.uniq_in_select_and_having import (
    UniqInSelectAndHavingProcessor,
)
from snuba.query.processors.physical.uuid_column_processor import UUIDColumnProcessor

columns = ColumnSet(
    [
        ("project_id", UInt(64)),
        ("event_id", UUID()),
        ("trace_id", UUID(Modifiers(nullable=True))),
        ("span_id", UInt(64)),
        ("transaction_name", String()),
        ("transaction_hash", UInt(64, Modifiers(readonly=True))),
        ("transaction_op", String()),
        ("transaction_status", UInt(8)),
        ("start_ts", DateTime()),
        ("start_ms", UInt(16)),
        ("finish_ts", DateTime()),
        ("finish_ms", UInt(16)),
        ("duration", UInt(32)),
        ("platform", String()),
        ("environment", String(Modifiers(nullable=True))),
        ("release", String(Modifiers(nullable=True))),
        ("dist", String(Modifiers(nullable=True))),
        ("ip_address_v4", IPv4(Modifiers(nullable=True))),
        ("ip_address_v6", IPv6(Modifiers(nullable=True))),
        ("user", String()),
        ("user_hash", UInt(64, Modifiers(readonly=True))),
        ("user_id", String(Modifiers(nullable=True))),
        ("user_name", String(Modifiers(nullable=True))),
        ("user_email", String(Modifiers(nullable=True))),
        ("sdk_name", String()),
        ("sdk_version", String()),
        ("http_method", String(Modifiers(nullable=True))),
        ("http_referer", String(Modifiers(nullable=True))),
        ("tags", Nested([("key", String()), ("value", String())])),
        ("_tags_hash_map", Array(UInt(64), Modifiers(readonly=True))),
        ("contexts", Nested([("key", String()), ("value", String())])),
        (
            "measurements",
            Nested([("key", String()), ("value", Float(64))]),
        ),
        (
            "span_op_breakdowns",
            Nested([("key", String()), ("value", Float(64))]),
        ),
        (
            "spans",
            Nested(
                [
                    ("op", String()),
                    ("group", UInt(64)),
                    ("exclusive_time", Float(64)),
                    ("exclusive_time_32", Float(32)),
                ]
            ),
        ),
        ("partition", UInt(16)),
        ("offset", UInt(64)),
        ("message_timestamp", DateTime()),
        ("retention_days", UInt(16)),
        ("deleted", UInt(8)),
        ("type", String(Modifiers(readonly=True))),
        ("message", String(Modifiers(readonly=True))),
        ("title", String(Modifiers(readonly=True))),
        ("transaction_source", String()),
        ("timestamp", DateTime(Modifiers(readonly=True))),
        ("group_ids", Array(UInt(64))),
        ("app_start_type", String()),
    ]
)

query_processors = [
    UniqInSelectAndHavingProcessor(),
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
    UUIDColumnProcessor(set(["event_id", "trace_id"])),
    HexIntColumnProcessor({"span_id"}),
    EventsBooleanContextsProcessor(),
    MappingOptimizer("tags", "_tags_hash_map", "tags_hash_map_enabled"),
    EmptyTagConditionProcessor(),
    ArrayJoinKeyValueOptimizer("tags"),
    ArrayJoinKeyValueOptimizer("measurements"),
    ArrayJoinKeyValueOptimizer("span_op_breakdowns"),
    # the bloom filter optimizer should occur before the array join optimizer
    # on the span columns because the array join optimizer will rewrite the
    # same conditions the bloom filter optimizer is looking for
    BloomFilterOptimizer("spans", ["op", "group"], ["exclusive_time_32"]),
    ArrayJoinOptimizer("spans", ["op", "group"], ["exclusive_time_32"]),
    ArrayHasOptimizer(["spans.op", "spans.group"]),
    HexIntArrayColumnProcessor({"spans.group"}),
    PrewhereProcessor(
        ["event_id", "trace_id", "span_id", "transaction_name", "transaction", "title"]
    ),
    TableRateLimit(),
    TupleUnaliaser(),
]

query_splitters = [TimeSplitQueryStrategy(timestamp_col="finish_ts")]

mandatory_condition_checkers = [ProjectIdEnforcer()]
