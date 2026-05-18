"""Dev/admin endpoints for trialing the LibreLinkUp follower API integration.

All endpoints require admin auth AND the env flag `ENABLE_LLU_DEV_ENDPOINTS=true`.
Designed for hand-driven verification (curl / HTTP client), not for production use.
"""

from typing import Optional

from decouple import config
from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import postgres_store
from lib.models.admin import Admin
from lib.models.patient_connected_app import PatientConnectedApp, PatientLibreView
from lib.services.librelink_up_client import LibreLinkUpClient
from lib.workers.tasks.librelink_up.sync import sync_all_patients_librelink_up

router = APIRouter(prefix="/test/llu", tags=["Test - LibreLinkUp"])


def _require_dev_flag() -> None:
    raw = config("ENABLE_LLU_DEV_ENDPOINTS", default="false")
    if str(raw).strip().lower() not in ("1", "true", "yes", "on"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLU dev endpoints disabled. Set ENABLE_LLU_DEV_ENDPOINTS=true.",
        )


def _maybe_invalidate(client: LibreLinkUpClient, fresh: bool) -> None:
    if fresh:
        client._invalidate_auth()


@router.post("/login-raw")
async def llu_login_raw(_admin: Admin = Depends(get_current_admin)):
    """Raw login round-trip — returns whatever Abbott responded with.

    Use when `/login-check` fails: the response body tells us *why* (stale
    version, bad creds, TOS step required, etc). Bypasses cache + parsing.
    """
    _require_dev_flag()
    import httpx

    client = LibreLinkUpClient()
    base_url = client.base_url
    headers = client._llu_headers()
    body = {"email": client.email, "password": client.password}

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"{base_url}/llu/auth/login", json=body, headers=headers
            )
            try:
                payload = resp.json()
            except Exception:
                payload = {"_raw_text": resp.text[:1000]}
            return {
                "request": {
                    "url": f"{base_url}/llu/auth/login",
                    "version_header": headers.get("version"),
                    "product_header": headers.get("product"),
                    "email": client.email,
                },
                "response": {
                    "http_status": resp.status_code,
                    "body": payload,
                },
            }
    except Exception as e:
        logger.exception("[llu/login-raw] failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login-check")
async def llu_login_check(
    fresh: bool = Query(False, description="Skip Redis cache and force a fresh login"),
    _admin: Admin = Depends(get_current_admin),
):
    """Confirm the shared follower account can log in. Returns metadata only."""
    _require_dev_flag()
    try:
        async with LibreLinkUpClient() as client:
            _maybe_invalidate(client, fresh)
            token, account_id_sha256, base_url = await client._get_auth()
            return {
                "ok": True,
                "fresh": fresh,
                "base_url": base_url,
                "token_prefix": token[:12] + "...",
                "account_id_sha256_prefix": account_id_sha256[:12] + "...",
            }
    except Exception as e:
        logger.exception("[llu/login-check] failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connections")
async def llu_connections(
    fresh: bool = Query(False),
    _admin: Admin = Depends(get_current_admin),
):
    """Raw `/llu/connections` — every patient the follower account follows."""
    _require_dev_flag()
    try:
        async with LibreLinkUpClient() as client:
            _maybe_invalidate(client, fresh)
            raw = await client.connections()
            slim = [
                {
                    "patientId": c.get("patientId"),
                    "firstName": c.get("firstName"),
                    "lastName": c.get("lastName"),
                    "country": c.get("country"),
                    "uom": c.get("uom"),
                    "latest": c.get("glucoseMeasurement"),
                }
                for c in raw
            ]
            return {"count": len(raw), "connections": slim}
    except Exception as e:
        logger.exception("[llu/connections] failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/{llu_patient_id}")
async def llu_graph(
    llu_patient_id: str,
    normalized: bool = Query(
        True, description="Include parsed/normalized rows alongside raw response"
    ),
    fresh: bool = Query(False),
    _admin: Admin = Depends(get_current_admin),
):
    """Raw rolling-12h graph for one connection, plus normalized rows. Read-only."""
    _require_dev_flag()
    try:
        async with LibreLinkUpClient() as client:
            _maybe_invalidate(client, fresh)
            raw = await client.graph(llu_patient_id)
            response = {
                "raw_summary": {
                    "graph_data_count": len(raw.get("graphData") or []),
                    "has_latest": bool(
                        (raw.get("connection") or {}).get("glucoseMeasurement")
                    ),
                },
                "raw": raw,
            }
            if normalized:
                rows = client.normalize_graph(raw, "<dev-preview>")
                # Convert datetime → ISO for JSON output.
                response["normalized"] = [
                    {
                        **r,
                        "time": r["time"].isoformat() + "Z",
                    }
                    for r in rows
                ]
            return response
    except Exception as e:
        logger.exception("[llu/graph/{}] failed", llu_patient_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-now")
async def llu_sync_now(
    _admin: Admin = Depends(get_current_admin),
):
    """Run the global sync task once, inline. WRITES to ClickHouse."""
    _require_dev_flag()
    result = await sync_all_patients_librelink_up({"job_id": "dev:sync-now"})
    return {
        "success": result.success,
        "data": result.data,
        "error": result.error,
    }


@router.post("/sync-now/{patient_id}")
async def llu_sync_now_one(
    patient_id: str,
    _admin: Admin = Depends(get_current_admin),
):
    """Sync a single internal patient_id end-to-end. WRITES to ClickHouse.

    Resolves `patient_id` → `libreview_id` → LLU `connection.patientId`,
    pulls the graph, writes via CGMUploadService.
    """
    _require_dev_flag()

    async with postgres_store.get_session() as session:
        result = await session.execute(
            select(PatientConnectedApp)
            .where(PatientConnectedApp.patient_id == patient_id)
            .options(selectinload(PatientConnectedApp.libreview))
        )
        connected_app = result.scalars().first()

    if not connected_app or not connected_app.libreview:
        raise HTTPException(404, f"No LibreView connection for patient {patient_id}")

    libreview_id = connected_app.libreview.libreview_id.strip()

    from lib.dependencies.service_dependencies import get_cgm_service

    cgm_service = get_cgm_service()

    try:
        async with LibreLinkUpClient() as client:
            connections = await client.connections()
            match: Optional[dict] = next(
                (c for c in connections if c.get("patientId") == libreview_id),
                None,
            )
            if not match:
                raise HTTPException(
                    404,
                    f"libreview_id {libreview_id} not found among {len(connections)} "
                    "follower connections — is this account shared with the follower?",
                )

            rows = await client.fetch_readings_for_connection(
                libreview_id, patient_id
            )
            written = 0
            if rows:
                written = await cgm_service.write_readings(
                    patient_id=patient_id,
                    rows=rows,
                    source="librelinkup",
                )  # type: ignore

            return {
                "success": True,
                "patient_id": patient_id,
                "libreview_id": libreview_id,
                "rows_normalized": len(rows),
                "rows_written": written,
                "first_time": rows[0]["time"].isoformat() + "Z" if rows else None,
                "last_time": rows[-1]["time"].isoformat() + "Z" if rows else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[llu/sync-now/{}] failed", patient_id)
        raise HTTPException(status_code=500, detail=str(e))
