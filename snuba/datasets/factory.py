from typing import Callable, MutableMapping, Sequence, Set

from snuba import settings
from snuba.datasets.dataset import Dataset
from snuba.util import with_span
from snuba.utils.serializable_exception import SerializableException
import importlib


class InvalidDatasetError(SerializableException):
    """Exception raised on invalid dataset access."""


@with_span()
def get_dataset(name: str) -> Dataset:
    from snuba.datasets.dataset_definitions.groupassignee import GroupAssigneeDataset
    from snuba.datasets.dataset_definitions.groupedmessage import GroupedMessageDataset
    from snuba.datasets.dataset_definitions.discover import DiscoverDataset
    from snuba.datasets.dataset_definitions.events import EventsDataset
    from snuba.datasets.dataset_definitions.functions import FunctionsDataset
    from snuba.datasets.dataset_definitions.generic_metrics import GenericMetricsDataset
    from snuba.datasets.dataset_definitions.metrics import MetricsDataset
    from snuba.datasets.dataset_definitions.outcomes import OutcomesDataset
    from snuba.datasets.dataset_definitions.outcomes_raw import OutcomesRawDataset
    from snuba.datasets.dataset_definitions.profiles import ProfilesDataset
    from snuba.datasets.dataset_definitions.replays import ReplaysDataset
    from snuba.datasets.dataset_definitions.sessions import SessionsDataset
    from snuba.datasets.dataset_definitions.transactions import TransactionsDataset

    dataset_factories: MutableMapping[str, Callable[[], Dataset]] = {
        "discover": DiscoverDataset,
        "events": EventsDataset,
        "groupassignee": GroupAssigneeDataset,
        "groupedmessage": GroupedMessageDataset,
        "metrics": MetricsDataset,
        "outcomes": OutcomesDataset,
        "outcomes_raw": OutcomesRawDataset,
        "sessions": SessionsDataset,
        "transactions": TransactionsDataset,
        "profiles": ProfilesDataset,
        "functions": FunctionsDataset,
        "generic_metrics": GenericMetricsDataset,
        "replays": ReplaysDataset,
    }

    try:
        dataset = dataset_factories[name]()
    except KeyError as error:
        raise InvalidDatasetError(f"dataset {name!r} does not exist") from error

    return dataset


def change_case(str) -> str:
    res = [str[0].lower()]
    for c in str[1:]:
        if c in ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            res.append("_")
            res.append(c.lower())
        else:
            res.append(c)

    return "".join(res)


def get_dataset_name(dataset: Dataset) -> str:
    # TODO: this breaks groupassignee
    return change_case(dataset.__class__.__name__.replace("Dataset", ""))


def get_enabled_dataset_names() -> Sequence[str]:
    # TOOO
    return []
    # return [name for name in DATASET_NAMES if name not in settings.DISABLED_DATASETS]
