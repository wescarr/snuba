import pytest

from snuba.datasets.storages import StorageKey, are_writes_identical


@pytest.mark.parametrize(
    "first_storage, second_storage, expected",
    [
        (StorageKey.ERRORS, StorageKey.ERRORS_V2, True),
        (StorageKey.TRANSACTIONS, StorageKey.TRANSACTIONS_V2, True),
        (StorageKey.ERRORS, StorageKey.TRANSACTIONS, False),
        (StorageKey.METRICS_SETS, StorageKey.METRICS_BUCKETS, False),
    ],
)
def test_storage_keys_same_writes(
    first_storage: StorageKey, second_storage: StorageKey, expected: bool
) -> None:
    assert are_writes_identical(first_storage, second_storage) == expected
