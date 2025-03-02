import base64
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Callable, Dict, List

import graphene
from django.core.cache import cache
from django.db.models import QuerySet
from prices import Money

from ...shipping.interface import ShippingMethodData
from ..base_plugin import ExcludedShippingMethod
from .const import CACHE_EXCLUDED_SHIPPING_TIME, EXCLUDED_SHIPPING_REQUEST_TIMEOUT
from .tasks import _get_webhooks_for_event, trigger_webhook_sync
from .utils import APP_ID_PREFIX

if TYPE_CHECKING:
    from ...app.models import App


logger = logging.getLogger(__name__)


def to_shipping_app_id(app: "App", shipping_method_id: str) -> "str":
    return base64.b64encode(
        str.encode(f"{APP_ID_PREFIX}:{app.pk}:{shipping_method_id}")
    ).decode("utf-8")


def parse_list_shipping_methods_response(
    response_data: Any, app: "App"
) -> List["ShippingMethodData"]:
    shipping_methods = []
    for shipping_method_data in response_data:
        method_id = shipping_method_data.get("id")
        method_name = shipping_method_data.get("name")
        method_amount = shipping_method_data.get("amount")
        method_currency = shipping_method_data.get("currency")
        method_maximum_delivery_days = shipping_method_data.get("maximum_delivery_days")

        shipping_methods.append(
            ShippingMethodData(
                id=to_shipping_app_id(app, method_id),
                name=method_name,
                price=Money(method_amount, method_currency),
                maximum_delivery_days=method_maximum_delivery_days,
            )
        )
    return shipping_methods


def get_excluded_shipping_methods_or_fetch(
    webhooks: QuerySet, event_type: str, payload: str, cache_key: str
) -> Dict[str, List[ExcludedShippingMethod]]:
    """Return data of all excluded shipping methods.

    The data will be fetched from the cache. If missing it will fetch it from all
    defined webhooks by calling a request to each of them one by one.
    """
    cached_data = cache.get(cache_key)
    if cached_data:
        cached_payload, excluded_shipping_methods = cached_data
        if payload == cached_payload:
            return parse_excluded_shipping_methods(excluded_shipping_methods)

    excluded_methods = []
    # Gather responses from webhooks
    for webhook in webhooks:
        response_data = trigger_webhook_sync(
            event_type,
            payload,
            webhook.app,
            EXCLUDED_SHIPPING_REQUEST_TIMEOUT,
        )
        if response_data:
            excluded_methods.extend(
                get_excluded_shipping_methods_from_response(response_data)
            )
    cache.set(cache_key, (payload, excluded_methods), CACHE_EXCLUDED_SHIPPING_TIME)
    return parse_excluded_shipping_methods(excluded_methods)


def get_excluded_shipping_data(
    event_type: str,
    previous_value: List[ExcludedShippingMethod],
    payload_fun: Callable[[], str],
    cache_key: str,
) -> List[ExcludedShippingMethod]:
    """Exclude not allowed shipping methods by sync webhook.

    Fetch excluded shipping methods from sync webhooks and return them as a list of
    excluded shipping methods.
    The function uses a cache_key to reduce the number of
    requests which we call to the external APIs. In case when we have the same payload
    in a cache as we're going to send now, we will skip an additional request and use
    the response fetched from cache.
    The function will fetch the payload only in the case that we have any defined
    webhook.
    """

    excluded_methods_map: Dict[str, List[ExcludedShippingMethod]] = defaultdict(list)
    webhooks = _get_webhooks_for_event(event_type)
    if webhooks:
        payload = payload_fun()

        excluded_methods_map = get_excluded_shipping_methods_or_fetch(
            webhooks, event_type, payload, cache_key
        )

    # Gather responses for previous plugins
    for method in previous_value:
        excluded_methods_map[method.id].append(method)

    # Return a list of excluded methods, unique by id
    excluded_methods = []
    for method_id, methods in excluded_methods_map.items():
        reason = None
        if reasons := [m.reason for m in methods if m.reason]:
            reason = " ".join(reasons)
        excluded_methods.append(ExcludedShippingMethod(id=method_id, reason=reason))
    return excluded_methods


def get_excluded_shipping_methods_from_response(
    response_data: dict,
) -> List[dict]:
    excluded_methods = []
    for method_data in response_data.get("excluded_methods", []):
        try:
            raw_id = method_data["id"]
            typename, _id = graphene.Node.from_global_id(raw_id)
            if typename == "app":
                method_id = raw_id
            elif typename == "ShippingMethod":
                method_id = _id
            else:
                logger.warning(
                    "Invalid type received. Expected ShippingMethod, got %s", typename
                )
                continue
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("Malformed ShippingMethod id was provided: %s", e)
            continue
        excluded_methods.append(
            {"id": method_id, "reason": method_data.get("reason", "")}
        )
    return excluded_methods


def parse_excluded_shipping_methods(
    excluded_methods: List[dict],
) -> Dict[str, List[ExcludedShippingMethod]]:
    excluded_methods_map = defaultdict(list)
    for excluded_method in excluded_methods:
        method_id = excluded_method["id"]
        excluded_methods_map[method_id].append(
            ExcludedShippingMethod(
                id=method_id, reason=excluded_method.get("reason", "")
            )
        )
    return excluded_methods_map
