from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field

from app.database import Base, engine, get_db
from app.models.workspace import Workspace
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.marketing_post import MarketingPost
from app.models.marketing_post_version import MarketingPostVersion

from app.routers.documents import router as documents_router
from app.routers.marketing import router as marketing_router

from app.models.video_job import VideoJob
from app.models.video_asset import VideoAsset
from app.models.video_version import VideoVersion

from app.routers.videos import router as videos_router

from fastapi.middleware.cors import CORSMiddleware

from app.routers.asset_generation import router as asset_generation_router

# Initial prototype: create tables automatically.
Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="IoTelliGen Knowledge API",
    version="0.2.0",
    description="Knowledge platform and Marketing Agent API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(marketing_router)

app.include_router(documents_router)
app.include_router(marketing_router)
app.include_router(videos_router)
app.include_router(asset_generation_router)

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    slug: str = Field(min_length=2, max_length=100)
    description: str | None = None


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "healthy",
        "database": "connected",
    }


@app.post("/workspaces", status_code=201)
def create_workspace(
    data: WorkspaceCreate,
    db: Session = Depends(get_db),
):
    existing = db.query(Workspace).filter(
        Workspace.slug == data.slug
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Workspace already exists",
        )

    workspace = Workspace(**data.model_dump())

    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    return workspace


@app.get("/workspaces")
def list_workspaces(db: Session = Depends(get_db)):
    return db.query(Workspace).order_by(
        Workspace.created_at
    ).all()
