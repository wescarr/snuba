from abc import ABC, abstractmethod
from typing import Optional, Sequence

import sentry_sdk

from snuba.clickhouse.query_dsl.accessors import get_object_ids_in_query_ast
from snuba.clickhouse.translators.snuba.mapping import TranslationMappers
from snuba.clusters.cluster import ClickhouseCluster, get_cluster
from snuba.clusters.storage_sets import StorageSetKey
from snuba.datasets.partitioning import (
    is_storage_partitioned,
    map_logical_partition_to_slice,
    map_org_id_to_logical_partition,
)
from snuba.datasets.plans.query_plan import (
    ClickhouseQueryPlan,
    ClickhouseQueryPlanBuilder,
)
from snuba.datasets.plans.single_storage import (
    SimpleQueryPlanExecutionStrategy,
    get_query_data_source,
)
from snuba.datasets.plans.translator.query import QueryTranslator
from snuba.datasets.storage import ReadableStorage
from snuba.datasets.storages.storage_key import StorageKey
from snuba.query.logical import Query as LogicalQuery
from snuba.query.processors.physical import ClickhouseQueryProcessor
from snuba.query.processors.physical.conditions_enforcer import (
    MandatoryConditionEnforcer,
)
from snuba.query.processors.physical.mandatory_condition_applier import (
    MandatoryConditionApplier,
)
from snuba.query.query_settings import QuerySettings
from snuba.util import with_span


class StorageClusterSelector(ABC):
    """
    The component provided by a dataset and used at the beginning of the
    execution of a query to pick the storage set a query should be executed
    onto.
    """

    @abstractmethod
    def select_cluster(
        self, query: LogicalQuery, query_settings: QuerySettings
    ) -> ClickhouseCluster:
        raise NotImplementedError


class ColumnBasedStoragePartitionSelector(StorageClusterSelector):
    """
    Storage partition selector for the generic metrics storage. This is needed
    because the generic metrics storage can be partitioned and we would need to
    know which partition to use for a specific query.
    """

    def __init__(
        self,
        storage: StorageKey,
        storage_set: StorageSetKey,
        partition_key_column_name: str,
    ) -> None:
        self.storage = storage
        self.storage_set = storage_set
        self.partition_key_column_name = partition_key_column_name

    def select_cluster(
        self, query: LogicalQuery, query_settings: QuerySettings
    ) -> ClickhouseCluster:
        """
        Selects the cluster to use for a query if the storage set is partitioned.
        If the storage set is not partitioned, it returns the default cluster.
        """
        if not is_storage_partitioned(self.storage):
            return get_cluster(self.storage_set)

        org_ids = get_object_ids_in_query_ast(query, self.partition_key_column_name)
        assert org_ids is not None
        assert len(org_ids) == 1
        org_id = org_ids.pop()

        slice_id = map_logical_partition_to_slice(
            self.storage, map_org_id_to_logical_partition(org_id)
        )
        cluster = get_cluster(self.storage_set, slice_id)

        return cluster


class PartitionedStorageQueryPlanBuilder(ClickhouseQueryPlanBuilder):
    """
    Builds the Clickhouse Query Execution Plan for a dataset that is
    partitioned.
    """

    def __init__(
        self,
        storage: ReadableStorage,
        storage_cluster_selector: StorageClusterSelector,
        mappers: Optional[TranslationMappers] = None,
        post_processors: Optional[Sequence[ClickhouseQueryProcessor]] = None,
    ) -> None:
        self.__storage = storage
        self.__storage_cluster_selector = storage_cluster_selector
        self.__mappers = mappers if mappers is not None else TranslationMappers()
        self.__post_processors = post_processors or []

    @with_span()
    def build_and_rank_plans(
        self, query: LogicalQuery, settings: QuerySettings
    ) -> Sequence[ClickhouseQueryPlan]:
        with sentry_sdk.start_span(
            op="build_plan.partitioned_storage", description="select_storage"
        ):
            cluster = self.__storage_cluster_selector.select_cluster(query, settings)

        with sentry_sdk.start_span(
            op="build_plan.partitioned_storage", description="translate"
        ):
            # The QueryTranslator class should be instantiated once for each call to build_plan,
            # to avoid cache conflicts.
            clickhouse_query = QueryTranslator(self.__mappers).translate(query)

        with sentry_sdk.start_span(
            op="build_plan.partitioned_storage", description="set_from_clause"
        ):
            clickhouse_query.set_from_clause(
                get_query_data_source(
                    self.__storage.get_schema().get_data_source(),
                    final=query.get_final(),
                    sampling_rate=query.get_sample(),
                )
            )

        db_query_processors = [
            *self.__storage.get_query_processors(),
            *self.__post_processors,
            MandatoryConditionApplier(),
            MandatoryConditionEnforcer(
                self.__storage.get_mandatory_condition_checkers()
            ),
        ]

        return [
            ClickhouseQueryPlan(
                query=clickhouse_query,
                plan_query_processors=[],
                db_query_processors=db_query_processors,
                storage_set_key=self.__storage.get_storage_set_key(),
                execution_strategy=SimpleQueryPlanExecutionStrategy(
                    cluster=cluster,
                    db_query_processors=db_query_processors,
                    splitters=self.__storage.get_query_splitters(),
                ),
            )
        ]
