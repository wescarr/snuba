from snuba.datasets.factory import get_dataset
from snuba.datasets.dataset_definitions.events import EventsDataset


def test_init_datasets() -> None:
    assert isinstance(get_dataset("events"), EventsDataset)
