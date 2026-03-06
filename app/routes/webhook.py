from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import uuid4
from urllib.parse import urlparse
from .project import get_db
from ..models import Project, PipelineRun
from ..services.carbon_service import calculate_energy, calculate_carbon

router = APIRouter()


def _normalize_repo_identifier(value: str | None) -> str | None:
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    if raw.startswith("git@") and ":" in raw:
        path = raw.split(":", 1)[1]
    elif raw.startswith(("http://", "https://", "ssh://", "git://")):
        path = urlparse(raw).path
    else:
        path = raw

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]

    if "/" not in path:
        return None

    owner, repo = path.split("/", 1)
    return f"{owner.lower()}/{repo.lower()}"

@router.post("/webhook/github")   # ← THIS WAS MISSING
async def github_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    repo_data = payload.get("repository", {})
    repo_name = repo_data.get("name")
    repo_full_name = repo_data.get("full_name")
    repo_html_url = repo_data.get("html_url")
    repo_clone_url = repo_data.get("clone_url")
    repo_ssh_url = repo_data.get("ssh_url")
    repo_git_url = repo_data.get("git_url")

    if not repo_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload"
        )

    print("Webhook received")
    print("Repository:", repo_name)

    candidate_urls = [
        repo_html_url,
        repo_clone_url,
        repo_ssh_url,
        repo_git_url,
    ]

    project = db.query(Project).filter(
        Project.repo_url.in_([url for url in candidate_urls if url])
    ).first()

    if not project:
        webhook_repo_id = _normalize_repo_identifier(repo_full_name)

        if webhook_repo_id:
            projects = db.query(Project).filter(Project.repo_url.isnot(None)).all()
            project = next(
                (
                    current
                    for current in projects
                    if _normalize_repo_identifier(current.repo_url) == webhook_repo_id
                ),
                None,
            )

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not registered"
        )

    # Dummy pipeline metrics for now
    cpu_usage = 50
    memory_usage = 1024
    duration_minutes = 10
    region = "us-east-1"

    energy = calculate_energy(cpu_usage, memory_usage, duration_minutes)
    try:
        carbon = calculate_carbon(db, region, energy)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Region not found in carbon intensity table"
        )

    run = PipelineRun(
        id=uuid4(),
        project_id=project.id,
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
        duration_minutes=duration_minutes,
        region=region,
        energy_kwh=energy,
        carbon_kg=carbon
    )

    db.add(run)
    db.commit()

    

    return {"message": "Pipeline run recorded"}

