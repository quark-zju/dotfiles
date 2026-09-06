"""Pure device-snapshot merge logic used by the Tokscale dummy server.

The wire payload is a snapshot for a scan scope, not a stream of session
records.  Full-history snapshots replace the clients they cover; partial
snapshots replace only the clients present on each submitted date.

Examples (run with ``python3 -m doctest tokscale_merge.py``)::

    >>> payload = {"device": {"id": "dev-a"}, "scanScope": {"fullHistory": True}, "contributions": [{"date": "2026-01-01", "totals": {"tokens": 3, "cost": 0.1, "messages": 1}, "clients": [{"client": "claude", "modelId": "sonnet", "tokens": {"input": 2, "output": 1, "cacheRead": 0, "cacheWrite": 0, "reasoning": 0}, "cost": 0.1, "messages": 1}]}]}
    >>> state = merge_device(None, payload)
    >>> state["summary"]["totalTokens"]
    3
    >>> partial = {"device": {"id": "dev-a"}, "scanScope": {"fullHistory": False}, "summary": {"clients": ["claude"]}, "contributions": [{"date": "2026-01-01", "totals": {"tokens": 4, "cost": 0.2, "messages": 1}, "clients": [{"client": "claude", "modelId": "sonnet", "tokens": {"input": 3, "output": 1, "cacheRead": 0, "cacheWrite": 0, "reasoning": 0}, "cost": 0.2, "messages": 1}]}]}
    >>> merge_device(state, partial)["summary"]["totalTokens"]
    4
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any


def _scope_clients(payload: dict[str, Any]) -> set[str]:
    summary = payload.get("summary") or {}
    clients = set(summary.get("clients") or [])
    scan_scope = payload.get("scanScope") or {}
    clients.update((scan_scope.get("parserVersions") or {}).keys())
    for day in payload.get("contributions") or []:
        clients.update(item.get("client") for item in day.get("clients") or [] if item.get("client"))
    return clients


def _day_totals(clients: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {"tokens": 0, "cost": 0.0, "messages": 0}
    breakdown = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "reasoning": 0}
    for item in clients:
        tokens = item.get("tokens") or {}
        totals["tokens"] += sum(int(tokens.get(key, 0) or 0) for key in breakdown)
        totals["cost"] += float(item.get("cost", 0) or 0)
        totals["messages"] += int(item.get("messages", 0) or 0)
        for key in breakdown:
            breakdown[key] += int(tokens.get(key, 0) or 0)
    return totals, breakdown


def _rebuild_day(day: dict[str, Any], clients: list[dict[str, Any]]) -> dict[str, Any]:
    result = dict(day)
    totals, breakdown = _day_totals(clients)
    result["clients"] = clients
    result["totals"] = totals
    result["tokenBreakdown"] = breakdown
    return result


def _summary(days: list[dict[str, Any]]) -> dict[str, Any]:
    total_tokens = sum(int((d.get("totals") or {}).get("tokens", 0) or 0) for d in days)
    total_cost = sum(float((d.get("totals") or {}).get("cost", 0) or 0) for d in days)
    clients = sorted({c.get("client") for d in days for c in d.get("clients") or [] if c.get("client")})
    models = sorted({c.get("modelId") for d in days for c in d.get("clients") or [] if c.get("modelId")})
    return {
        "totalTokens": total_tokens,
        "totalCost": total_cost,
        "totalDays": len(days),
        "activeDays": sum(1 for d in days if (d.get("totals") or {}).get("tokens", 0) > 0),
        "averagePerDay": total_tokens / len(days) if days else 0,
        "maxCostInSingleDay": max((float((d.get("totals") or {}).get("cost", 0) or 0) for d in days), default=0),
        "clients": clients,
        "models": models,
    }


def merge_device(existing: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Merge one submit payload into a device snapshot.

    ``fullHistory`` replaces all dates for the clients in the payload's scan
    scope. A partial payload replaces only the client cells it actually sends.
    Uncovered clients/dates are retained. The function never mutates inputs.
    """
    old = deepcopy(existing or {})
    incoming = deepcopy(payload)
    full_history = bool((incoming.get("scanScope") or {}).get("fullHistory"))
    scoped = _scope_clients(incoming)
    days: dict[str, dict[str, Any]] = {
        d["date"]: deepcopy(d)
        for d in old.get("contributions") or []
        if isinstance(d, dict) and d.get("date")
    }

    if full_history:
        for day_key, day in list(days.items()):
            kept = [c for c in day.get("clients") or [] if c.get("client") not in scoped]
            if kept:
                days[day_key] = _rebuild_day(day, kept)
            else:
                del days[day_key]

    for incoming_day in incoming.get("contributions") or []:
        day_key = incoming_day.get("date")
        if not day_key:
            continue
        old_day = days.get(day_key, {"date": day_key})
        incoming_clients = incoming_day.get("clients") or []
        incoming_names = {c.get("client") for c in incoming_clients if c.get("client")}
        kept = [c for c in old_day.get("clients") or [] if c.get("client") not in incoming_names]
        days[day_key] = _rebuild_day(old_day | incoming_day, kept + incoming_clients)

    ordered_days = [days[key] for key in sorted(days, key=lambda value: date.fromisoformat(value))]
    result = old
    result.update({key: deepcopy(incoming[key]) for key in ("device", "meta", "scanScope", "mcpServers") if key in incoming})
    result["contributions"] = ordered_days
    result["summary"] = _summary(ordered_days)
    if "timeMetrics" in incoming:
        if full_history or not old.get("timeMetrics"):
            result["timeMetrics"] = incoming["timeMetrics"]
        else:
            result["timeMetrics"] = {
                key: max(int((old["timeMetrics"] or {}).get(key, 0) or 0), int(incoming["timeMetrics"].get(key, 0) or 0))
                for key in ("totalActiveTimeMs", "longestContinuousMs", "maxConcurrentSessions", "sessionCount")
            }
    return result
