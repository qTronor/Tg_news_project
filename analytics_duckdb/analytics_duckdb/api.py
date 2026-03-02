from __future__ import annotations

from typing import Optional

from aiohttp import web

from analytics_duckdb.duckdb_store import AnalyticsDuckDB

STORE_KEY: web.AppKey[AnalyticsDuckDB] = web.AppKey("analytics_store", AnalyticsDuckDB)


def _opt_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _require_param(request: web.Request, key: str) -> str:
    value = request.query.get(key)
    if not value:
        raise web.HTTPBadRequest(text=f"missing required query param: {key}")
    return value


def _parse_int(request: web.Request, key: str, default: int) -> int:
    raw = request.query.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=f"invalid integer query param: {key}") from exc
    if value < 0:
        raise web.HTTPBadRequest(text=f"query param must be >= 0: {key}")
    return value


def _parse_bucket(request: web.Request) -> str:
    bucket = request.query.get("bucket", "day")
    if bucket not in {"hour", "day"}:
        raise web.HTTPBadRequest(text="bucket must be 'hour' or 'day'")
    return bucket


def _store(request: web.Request) -> AnalyticsDuckDB:
    return request.app[STORE_KEY]


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def overview_clusters(request: web.Request) -> web.Response:
    date_from = _require_param(request, "from")
    date_to = _require_param(request, "to")
    channel = _opt_str(request.query.get("channel"))
    topic = _opt_str(request.query.get("topic"))
    rows = _store(request).overview_clusters(date_from, date_to, channel, topic)
    return web.json_response({"items": rows, "count": len(rows)})


async def top_entities(request: web.Request) -> web.Response:
    date_from = _require_param(request, "from")
    date_to = _require_param(request, "to")
    cluster_id = _opt_str(request.query.get("cluster_id"))
    topic = _opt_str(request.query.get("topic"))
    entity_type = _opt_str(request.query.get("entity_type"))
    rows = _store(request).top_entities(
        date_from=date_from,
        date_to=date_to,
        cluster_id=cluster_id,
        topic=topic,
        entity_type=entity_type,
    )
    return web.json_response({"items": rows, "count": len(rows)})


async def sentiment_dynamics(request: web.Request) -> web.Response:
    date_from = _require_param(request, "from")
    date_to = _require_param(request, "to")
    bucket = _parse_bucket(request)
    channel = _opt_str(request.query.get("channel"))
    topic = _opt_str(request.query.get("topic"))
    cluster_id = _opt_str(request.query.get("cluster_id"))
    rows = _store(request).sentiment_dynamics(
        date_from=date_from,
        date_to=date_to,
        bucket=bucket,
        channel=channel,
        topic=topic,
        cluster_id=cluster_id,
    )
    return web.json_response({"items": rows, "count": len(rows)})


async def cluster_documents(request: web.Request) -> web.Response:
    cluster_id = request.match_info["cluster_id"]
    date_from = _require_param(request, "from")
    date_to = _require_param(request, "to")
    limit = _parse_int(request, "limit", 20)
    offset = _parse_int(request, "offset", 0)
    rows = _store(request).cluster_documents(
        cluster_id=cluster_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return web.json_response({"items": rows, "count": len(rows)})


async def related_clusters(request: web.Request) -> web.Response:
    cluster_id = request.match_info["cluster_id"]
    date_from = _require_param(request, "from")
    date_to = _require_param(request, "to")
    limit = _parse_int(request, "limit", 20)
    rows = _store(request).related_clusters(
        cluster_id=cluster_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return web.json_response({"items": rows, "count": len(rows)})


def create_app(store: AnalyticsDuckDB) -> web.Application:
    app = web.Application()
    app[STORE_KEY] = store
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/analytics/overview/clusters", overview_clusters)
    app.router.add_get("/analytics/entities/top", top_entities)
    app.router.add_get("/analytics/sentiment/dynamics", sentiment_dynamics)
    app.router.add_get("/analytics/clusters/{cluster_id}/documents", cluster_documents)
    app.router.add_get("/analytics/clusters/{cluster_id}/related", related_clusters)
    return app
