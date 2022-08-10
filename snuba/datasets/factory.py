import importlib
import inspect
import os
from typing import Callable, List, MutableMapping, Sequence

from snuba.datasets.dataset import Dataset
from snuba.util import with_span
from snuba.utils.serializable_exception import SerializableException


class InvalidDatasetError(SerializableException):
    """Exception raised on invalid dataset access."""


def find_dataset_definitions_directory(root: str) -> List[str]:
    for path, _, files in os.walk(root):
        path_list = path.split("/")
        # Checks that top level root is snuba repo and directory name is dataset_definitions
        if (
            len(path_list) > 1
            and path_list[1] == "snuba"
            and path_list[-1] == "dataset_definitions"
        ):
            return [path + "/" + dataset_definition for dataset_definition in files]
    raise InvalidDatasetError("Unable to load dataset definitions file")


@with_span()
def get_dataset(name: str) -> Dataset:
    dataset_factories: MutableMapping[str, Callable[[], Dataset]] = {}
    dataset_definition_paths = find_dataset_definitions_directory(".")
    for p in dataset_definition_paths:
        p_without_ext = os.path.splitext(p)[0]
        package_import_path = ".".join(p_without_ext.split("/")[1:])
        module = importlib.import_module(package_import_path)

        # Only load the main dataset classes in each module
        # TODO: there's probably a better way to do this
        # Note: groupassignee and groupedmessage will be the keys since we're using filename as key names
        for class_name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and package_import_path in obj.__module__:
                dataset_factories[p_without_ext.split("/")[-1]] = getattr(
                    module, class_name
                )

    try:
        dataset = dataset_factories[name]()
    except KeyError as error:
        raise InvalidDatasetError(f"dataset {name!r} does not exist") from error

    return dataset


def change_case(str: str) -> str:
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
