import copy
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

from snuba import environment, settings
from snuba.consumers.types import KafkaMessageMetadata
from snuba.datasets.events_format import (
    EventTooOld,
    enforce_retention,
    extract_base,
    extract_extra_tags,
    extract_user,
)
from snuba.processor import (
    InsertBatch,
    MessageProcessor,
    ProcessedMessage,
    _as_dict_safe,
    _ensure_valid_date,
    _ensure_valid_ip,
    _unicodify,
)
from snuba.utils.metrics.wrapper import MetricsWrapper

logger = logging.getLogger(__name__)

metrics = MetricsWrapper(environment.metrics, "transactions.processor")


UNKNOWN_SPAN_STATUS = 2


EventDict = Dict[str, Any]
SpanDict = Dict[str, Any]
RetentionDays = int


class ReplaysProcessor(MessageProcessor):
    PROMOTED_TAGS = {
        "environment",
        "sentry:release",
        "sentry:user",
        "sentry:dist",
    }

    def __extract_timestamp(self, field: int) -> Tuple[datetime, int]:
        # We are purposely using a naive datetime here to work with the rest of the codebase.
        # We can be confident that clients are only sending UTC dates.
        timestamp = _ensure_valid_date(datetime.utcfromtimestamp(field))
        if timestamp is None:
            timestamp = datetime.utcnow()
        milliseconds = int(timestamp.microsecond / 1000)
        return (timestamp, milliseconds)

    def _structure_and_validate_message(
        self, message: Dict[str, Any]
    ) -> Optional[Tuple[EventDict, RetentionDays]]:
        event = message

        data = event["data"]
        event_type = data.get("type")
        if event_type != "replayevent":
            return None

        try:
            # We are purposely using a naive datetime here to work with the
            # rest of the codebase. We can be confident that clients are only
            # sending UTC dates.
            retention_days = enforce_retention(
                event, datetime.utcfromtimestamp(data["timestamp"])
            )
        except EventTooOld:
            return None

        return event, retention_days

    def _process_base_event_values(
        self, processed: MutableMapping[str, Any], event_dict: EventDict
    ) -> MutableMapping[str, Any]:

        extract_base(processed, event_dict)

        # transaction_ctx = event_dict["data"]["contexts"]["trace"]
        # trace_id = transaction_ctx["trace_id"]
        processed["event_id"] = str(uuid.UUID(processed["event_id"]))
        # processed["trace_id"] = str(uuid.UUID(trace_id))
        # processed["span_id"] = int(transaction_ctx["span_id"], 16)
        # processed["transaction_op"] = _unicodify(transaction_ctx.get("op") or "")
        # processed["transaction_name"] = _unicodify(
        #     event_dict["data"].get("transaction") or ""
        # )
        processed["start_ts"], processed["start_ms"] = self.__extract_timestamp(
            event_dict["data"]["start_timestamp"],
        )

        if event_dict["data"]["timestamp"] - event_dict["data"]["start_timestamp"] < 0:
            # Seems we have some negative durations in the DB
            metrics.increment("negative_duration")

        processed["finish_ts"], processed["finish_ms"] = self.__extract_timestamp(
            event_dict["data"]["timestamp"],
        )

        duration_secs = (processed["finish_ts"] - processed["start_ts"]).total_seconds()
        processed["duration"] = max(int(duration_secs * 1000), 0)

        processed["platform"] = _unicodify(event_dict["platform"])
        return processed

    def _process_tags(
        self, processed: MutableMapping[str, Any], event_dict: EventDict,
    ) -> None:

        tags: Mapping[str, Any] = _as_dict_safe(event_dict["data"].get("tags", None))
        processed["tags.key"], processed["tags.value"] = extract_extra_tags(tags)
        promoted_tags = {col: tags[col] for col in self.PROMOTED_TAGS if col in tags}
        processed["release"] = promoted_tags.get(
            "sentry:release", event_dict.get("release"),
        )
        processed["environment"] = promoted_tags.get("environment")
        processed["user"] = promoted_tags.get("sentry:user", "")
        processed["dist"] = _unicodify(
            promoted_tags.get("sentry:dist", event_dict["data"].get("dist")),
        )

    def _process_contexts_and_user(
        self, processed: MutableMapping[str, Any], event_dict: EventDict,
    ) -> None:
        contexts: MutableMapping[str, Any] = _as_dict_safe(
            event_dict["data"].get("contexts", None)
        )
        user_dict = (
            event_dict["data"].get(
                "user", event_dict["data"].get("sentry.interfaces.User", None)
            )
            or {}
        )
        geo = user_dict.get("geo", None) or {}

        if "geo" not in contexts and isinstance(geo, dict):
            contexts["geo"] = geo

        skipped_contexts = settings.TRANSACT_SKIP_CONTEXT_STORE.get(
            processed["project_id"], set()
        )
        for context in skipped_contexts:
            if context in contexts:
                del contexts[context]

        # sanitized_contexts = self._sanitize_contexts(processed, event_dict)
        # processed["contexts.key"], processed["contexts.value"] = extract_extra_contexts(
        #     sanitized_contexts
        # )

        user_data: MutableMapping[str, Any] = {}
        extract_user(user_data, user_dict)
        processed["user_name"] = user_data["username"]
        processed["user_id"] = user_data["user_id"]
        processed["user_email"] = user_data["email"]
        ip_address = _ensure_valid_ip(user_data["ip_address"])
        if ip_address:
            if ip_address.version == 4:
                processed["ip_address_v4"] = str(ip_address)
            elif ip_address.version == 6:
                processed["ip_address_v6"] = str(ip_address)

    def _process_sdk_data(
        self, processed: MutableMapping[str, Any], event_dict: EventDict,
    ) -> None:
        sdk = event_dict["data"].get("sdk", None) or {}
        processed["sdk_name"] = _unicodify(sdk.get("name") or "")
        processed["sdk_version"] = _unicodify(sdk.get("version") or "")

        if processed["sdk_name"] == "":
            metrics.increment("missing_sdk_name")
        if processed["sdk_version"] == "":
            metrics.increment("missing_sdk_version")

    def _sanitize_contexts(
        self, processed: MutableMapping[str, Any], event_dict: EventDict,
    ) -> MutableMapping[str, Any]:
        """
        Contexts can store a lot of data. We don't want to store all the data in
        the database. This api removes elements from contexts which are not required
        to be stored. It does that by creating a deepcopy of the contexts and working
        with the deepcopy so that the contexts in the original message are not
        mutated. It returns the new modified context object which can be used to fill
        in the processed object.
        """
        contexts: MutableMapping[str, Any] = _as_dict_safe(
            event_dict["data"].get("contexts", None)
        )
        if not contexts:
            return {}

        sanitized_context = copy.deepcopy(contexts)
        # We store trace_id and span_id as promoted columns and on the query level
        # we make sure that all queries on contexts[trace.trace_id/span_id] use those promoted
        # columns instead. So we don't need to store them in the contexts array as well
        transaction_ctx = sanitized_context.get("trace", {})
        transaction_ctx.pop("trace_id", None)
        transaction_ctx.pop("span_id", None)

        # The hash and exclusive_time is being stored in the spans columns
        # so there is no need to store it again in the context array.
        transaction_ctx.pop("hash", None)
        transaction_ctx.pop("exclusive_time", None)

        skipped_contexts = settings.TRANSACT_SKIP_CONTEXT_STORE.get(
            processed["project_id"], set()
        )
        for context in skipped_contexts:
            if context in sanitized_context:
                del sanitized_context[context]

        return sanitized_context

    def process_message(
        self, message: Dict[Any, Any], metadata: KafkaMessageMetadata
    ) -> Optional[ProcessedMessage]:
        event_dict, retention_days = self._structure_and_validate_message(message) or (
            None,
            None,
        )
        if not event_dict:
            return None
        processed: MutableMapping[str, Any] = {
            "deleted": 0,
            "retention_days": retention_days,
        }
        # The following helper functions should be able to be applied in any order.
        # At time of writing, there are no reads of the values in the `processed`
        # dictionary to inform values in other functions.
        # Ideally we keep continue that rule
        self._process_base_event_values(processed, event_dict)
        self._process_tags(processed, event_dict)
        self._process_sdk_data(processed, event_dict)
        # processed["partition"] = metadata.partition
        # processed["offset"] = metadata.offset

        # the following operation modifies the event_dict and is therefore *not* order-independent
        self._process_contexts_and_user(processed, event_dict)
        print("processed")
        print(processed)
        return InsertBatch([processed], None)
