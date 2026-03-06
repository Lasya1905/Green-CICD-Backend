from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID, uuid4
from ..services.carbon_service import calculate_energy, calculate_carbon, suggest_optimized_region
from ..schemas import OptimizationResponse
from sqlalchemy import func
from ..database import SessionLocal
from ..models import Project, PipelineRun
from ..schemas import ProjectResponse, ProjectCreate, PipelineRunResponse, PipelineRunCreate
from ..dependencies import get_current_user
from ..models import User

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- CREATE PROJECT ----------------

@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    project = Project(
        id=uuid4(),
        user_id=current_user.id,   # 🔥 Take user from JWT
        project_name=data.project_name,
        repo_url=data.repo_url
    )

    db.add(project)
    db.commit()
    db.refresh(project)

    return project


# ---------------- ADD PIPELINE RUN ----------------

@router.post("/pipeline-run", response_model=PipelineRunResponse, status_code=status.HTTP_201_CREATED)
def add_pipeline_run(
    data: PipelineRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == data.project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    energy = calculate_energy(
        data.cpu_usage,
        data.memory_usage,
        data.duration_minutes
    )

    try:
        carbon = calculate_carbon(db, data.region, energy)
    except Exception:
        raise HTTPException(
            status_code=404,
            detail="Region not found in carbon intensity table"
        )

    run = PipelineRun(
        id=uuid4(),
        project_id=data.project_id,
        cpu_usage=data.cpu_usage,
        memory_usage=data.memory_usage,
        duration_minutes=data.duration_minutes,
        region=data.region,
        energy_kwh=energy,
        carbon_kg=carbon
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    return run

# ---------------- OPTIMIZE REGION ----------------

@router.post("/optimize/{project_id}", response_model=OptimizationResponse)
def optimize_region(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    runs = db.query(PipelineRun).filter(
        PipelineRun.project_id == project_id
    ).all()

    if not runs:
        raise HTTPException(
            status_code=400,
            detail="No pipeline runs found for this project"
        )

    result = suggest_optimized_region(db, project_id)
    return result


@router.get("/projects", response_model=list[ProjectResponse])
def get_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(Project).filter(
        Project.user_id == current_user.id
    ).all()

@router.get("/pipeline-run/{project_id}", response_model=list[PipelineRunResponse])
def get_pipeline_runs(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return db.query(PipelineRun).filter(
        PipelineRun.project_id == project_id
    ).all()

@router.get("/carbon-trend/{project_id}")
def get_carbon_trend(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    results = db.query(
        func.date_trunc('day', PipelineRun.created_at).label("day"),
        func.sum(PipelineRun.carbon_kg).label("total_carbon")
    ).filter(
        PipelineRun.project_id == project_id
    ).group_by("day").order_by("day").all()

    return [
        {
            "day": r.day.strftime("%Y-%m-%d"),
            "total_carbon": float(r.total_carbon)
        }
        for r in results
    ]

@router.get("/project-summary/{project_id}")
def get_project_summary(project_id: UUID, db: Session = Depends(get_db)):

    runs = db.query(PipelineRun).filter(
        PipelineRun.project_id == project_id
    ).all()

    # Handle case where there are no pipeline runs yet
    if not runs:
        return {
            "total_carbon": 0,
            "total_energy": 0,
            "latest_region": None
        }

    total_carbon = sum(run.carbon_kg for run in runs)
    total_energy = sum(run.energy_kwh for run in runs)
    latest_region = runs[-1].region

    return {
        "total_carbon": total_carbon,
        "total_energy": total_energy,
        "latest_region": latest_region
    }