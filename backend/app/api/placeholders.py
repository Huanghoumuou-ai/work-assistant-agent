from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse


router = APIRouter()

NOT_IMPLEMENTED_BODY = {
    "success": False,
    "code": "NOT_IMPLEMENTED",
    "message": "This API is reserved for later stages.",
    "data": None,
}


async def reserved_api() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=NOT_IMPLEMENTED_BODY,
    )
