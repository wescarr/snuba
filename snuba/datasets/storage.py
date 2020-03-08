from abc import ABC
from typing import Optional, Sequence


from snuba.datasets.dataset_schemas import StorageSchemas
from snuba.datasets.table_storage import TableWriter
from snuba.query.query import Query
from snuba.query.query_processor import QueryProcessor
from snuba.request.request_settings import RequestSettings


class Storage(ABC):
    def get_schemas(self) -> StorageSchemas:
        """
        Returns the collections of schemas for DDL operations and for
        query.
        See TableWriter to get a write schema.
        """
        raise NotImplementedError

    def can_write(self) -> bool:
        """
        Returns True if this dataset has write capabilities
        """
        return self.get_table_writer() is not None

    def get_table_writer(self) -> Optional[TableWriter]:
        """
        Returns the TableWriter or throws if the dataaset is a readonly one.

        Once we will have a full TableStorage implementation this method will
        disappear since we will have a table storage factory that will return
        only writable ones, scripts will depend on table storage instead of
        going through datasets.
        """
        raise NotImplementedError

    def get_query_processors(self) -> Sequence[QueryProcessor]:
        """
        Returns a series of transformation functions (in the form of QueryProcessor objects)
        that are applied to queries after parsing and before running them on Clickhouse.
        These are applied in sequence in the same order as they are defined and are supposed
        to be stateless.
        """
        raise NotImplementedError


class TableStorage(Storage):
    def __init__(
        self,
        schemas: StorageSchemas,
        table_writer: Optional[TableWriter] = None,
        query_processors: Optional[Sequence[QueryProcessor]] = None,
    ) -> None:
        self.__schemas = schemas
        self.__table_writer = table_writer
        self.__query_processors = query_processors or []

    def get_schemas(self) -> StorageSchemas:
        return self.__schemas

    def get_table_writer(self) -> Optional[TableWriter]:
        return self.__table_writer

    def get_query_processors(self) -> Sequence[QueryProcessor]:
        return self.__query_processors


class QueryStorageSelector(ABC):
    """
    The component provided by a dataset and used at the beginning of the
    execution of a query to pick the storage query should be executed onto.
    """

    def select_storage(
        self, query: Query, request_settings: RequestSettings
    ) -> Storage:
        raise NotImplementedError


class SingleTableQueryStorageSelector(QueryStorageSelector):
    def __init__(self, storage: TableStorage) -> None:
        self.__storage = storage

    def select_storage(
        self, query: Query, request_settings: RequestSettings
    ) -> Storage:
        return self.__storage
