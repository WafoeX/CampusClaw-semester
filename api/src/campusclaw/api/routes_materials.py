# pyright: basic, reportMissingImports=false
"""Class-scoped material read endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DatabaseSession
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.formparsers import MultiPartException

from campusclaw.api.dependencies import (
    Principal,
    get_database,
    get_db,
    get_settings,
    require_csrf,
    require_supported_role,
    require_teacher,
)
from campusclaw.api.schemas import MaterialResponse
from campusclaw.application.materials import persist_material_upload
from campusclaw.application.storage import (
    MalformedUploadError,
    UploadTooLargeError,
    contained_storage_path,
    sanitize_display_filename,
    stage_upload,
    verify_stored_file,
)
from campusclaw.config import Settings
from campusclaw.persistence.database import Database
from campusclaw.persistence.materials import MaterialRepository

router = APIRouter(prefix="/api/materials", tags=["materials"])
repository = MaterialRepository()


def material_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "material_not_found", "message": "Material not found"},
    )


def material_response(material: object) -> MaterialResponse:
    return MaterialResponse.model_validate(material)


@router.get("", response_model=list[MaterialResponse])
def list_materials(
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[DatabaseSession, Depends(get_db)],
) -> list[MaterialResponse]:
    return [material_response(item) for item in repository.list_ready(database, principal.class_id)]


@router.post("", response_model=MaterialResponse, status_code=status.HTTP_201_CREATED)
async def upload_material(
    request: Request,
    principal: Annotated[Principal, Depends(require_teacher)],
    _csrf: Annotated[Principal, Depends(require_csrf)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaterialResponse:
    try:
        form = await request.form(
            max_files=2,
            max_fields=20,
            # Starlette's part limit is for parser safety; the streaming stage
            # below is the authoritative configured file-size check.
            max_part_size=max(settings.UPLOAD_MAX_BYTES + 1, 1_048_576),
        )
    except MultiPartException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_upload", "message": "Malformed multipart upload"},
        ) from exc

    files = [value for _, value in form.multi_items() if isinstance(value, StarletteUploadFile)]
    titles = form.getlist("title")
    if (
        len(files) != 1
        or len(titles) != 1
        or not isinstance(titles[0], str)
        or not titles[0].strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_upload",
                "message": "One file and a non-empty title are required",
            },
        )

    upload = files[0]
    try:
        try:
            staged = stage_upload(
                upload.file,
                settings.UPLOAD_ROOT,
                settings.UPLOAD_MAX_BYTES,
            )
        except UploadTooLargeError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "upload_too_large",
                    "message": "Upload exceeds the configured limit",
                },
            ) from exc
        except (MalformedUploadError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_upload", "message": "Invalid upload"},
            ) from exc

        try:
            material = persist_material_upload(
                database,
                principal,
                staged=staged,
                upload_root=settings.UPLOAD_ROOT,
                title=titles[0],
                original_filename=upload.filename or "unnamed",
                content_type=upload.content_type or "application/octet-stream",
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_upload", "message": str(exc)},
            ) from exc
        return material_response(material)
    finally:
        await upload.close()


@router.get("/{material_id}", response_model=MaterialResponse)
def get_material(
    material_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[DatabaseSession, Depends(get_db)],
) -> MaterialResponse:
    material = repository.get_metadata(database, principal.class_id, material_id)
    if material is None:
        raise material_not_found()
    return material_response(material)


@router.get("/{material_id}/download")
def download_material(
    material_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[DatabaseSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    material = repository.get_for_download(database, principal.class_id, material_id)
    if material is None:
        raise material_not_found()
    root = settings.UPLOAD_ROOT.resolve()
    try:
        path = contained_storage_path(root, material.storage_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "material_unavailable", "message": "Material file unavailable"},
        ) from exc
    if not verify_stored_file(path, material.byte_size, material.sha256):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "material_unavailable", "message": "Material file unavailable"},
        )
    return FileResponse(
        path,
        media_type=material.content_type,
        filename=sanitize_display_filename(material.original_filename),
        headers={"content-length": str(material.byte_size)},
    )
