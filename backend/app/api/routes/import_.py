import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.db.models import Project, ProjectCharacter
from app.jobs.manager import job_manager
from app.metadata.registry import get_provider
from app.orchestrator.orchestrator import orchestrate_project

router = APIRouter(prefix="/import", tags=["import"])
logger = logging.getLogger(__name__)


class DirectoryOut(BaseModel):
    name: str
    file_count: int


class ImportRequest(BaseModel):
    directory_name: str
    provider: str
    provider_id: str
    anime_title: str
    anime_title_native: str | None = None
    anime_year: int | None = None


class ImportResultOut(BaseModel):
    id: int
    name: str
    source_directory: str
    status: str


@router.get("/directories", response_model=list[DirectoryOut])
async def list_import_directories() -> list[DirectoryOut]:
    import_root = settings.import_root
    if not import_root.exists():
        return []

    async with AsyncSessionLocal() as session:
        existing: set[str] = set(
            (await session.scalars(select(Project.source_directory))).all()
        )

    dirs: list[DirectoryOut] = []
    for entry in sorted(import_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in existing:
            continue
        file_count = sum(1 for f in entry.rglob("*") if f.is_file())
        dirs.append(DirectoryOut(name=entry.name, file_count=file_count))

    return dirs


@router.post("", response_model=ImportResultOut, status_code=201)
async def import_project(body: ImportRequest) -> ImportResultOut:
    # Safety: reject names with path separators or traversal
    if "/" in body.directory_name or "\\" in body.directory_name or ".." in body.directory_name:
        raise HTTPException(status_code=400, detail="Invalid directory name")

    import_root = settings.import_root.resolve()
    dir_path = (import_root / body.directory_name).resolve()

    if not dir_path.is_relative_to(import_root) or not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Directory not found under import root")

    # Create project
    project = Project(
        name=body.anime_title,
        source_directory=body.directory_name,
        anime_provider=body.provider,
        anime_external_id=body.provider_id,
        status="new",
        speaker_mapping_status="awaiting_discovery",
    )

    try:
        async with AsyncSessionLocal() as session:
            session.add(project)
            await session.commit()
            await session.refresh(project)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Directory already imported")

    # Fetch + store characters in a separate transaction (best-effort)
    try:
        provider = get_provider(body.provider)
        characters = await provider.get_characters(body.provider_id)
        if characters:
            async with AsyncSessionLocal() as session:
                for char in characters:
                    session.add(ProjectCharacter(
                        project_id=project.id,
                        external_id=char.provider_id,
                        name=char.name,
                        role=char.role.value if char.role else None,
                        gender=char.gender,
                    ))
                await session.commit()
    except Exception:
        logger.warning(
            "Failed to fetch characters for %s/%s (project %d created without characters)",
            body.provider, body.provider_id, project.id, exc_info=True,
        )

    # Kick off scan immediately (don't wait for 30s sweep)
    try:
        await orchestrate_project(project.id, job_manager.enqueue)
    except Exception:
        logger.warning("Failed to trigger initial scan for project %d", project.id, exc_info=True)

    return ImportResultOut(
        id=project.id,
        name=project.name,
        source_directory=project.source_directory,
        status=project.status,
    )
