import hashlib
import os
import uuid
import logging

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.workspace import Workspace
from app.models.document import Document

from app.models.document_chunk import DocumentChunk
from app.services.document_processor import process_document
from app.services.embedding_service import generate_embeddings

logger = logging.getLogger(__name__)
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "openai/text-embedding-3-small",
)

router = APIRouter(prefix="/workspaces", tags=["Documents"])

STORAGE_PATH = Path(
    os.getenv("DOCUMENT_STORAGE", "/data/documents")
)

MAX_UPLOAD_SIZE = int(
    os.getenv("MAX_UPLOAD_SIZE", "26214400")
)

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
}

class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)

@router.post("/{workspace_slug}/documents", status_code=201)
def upload_document(
    workspace_slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    workspace = db.query(Workspace).filter(
        Workspace.slug == workspace_slug
    ).first()

    if not workspace:
        raise HTTPException(404, "Workspace not found")

    original_name = Path(file.filename or "").name

    if not original_name:
        raise HTTPException(400, "Invalid filename")

    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Unsupported file extension")

    STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    document_id = str(uuid.uuid4())
    stored_filename = f"{document_id}{extension}"

    final_path = STORAGE_PATH / stored_filename
    temp_path = STORAGE_PATH / f"{stored_filename}.tmp"

    sha256 = hashlib.sha256()
    size = 0

    try:
        with temp_path.open("wb") as output:
            while True:
                chunk = file.file.read(1024 * 1024)

                if not chunk:
                    break

                size += len(chunk)

                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        413,
                        "File exceeds the 25 MB upload limit",
                    )

                sha256.update(chunk)
                output.write(chunk)

        os.replace(temp_path, final_path)

        document = Document(
            id=document_id,
            workspace_id=workspace.id,
            original_filename=original_name,
            stored_filename=stored_filename,
            file_extension=extension,
            mime_type=file.content_type,
            size_bytes=size,
            sha256=sha256.hexdigest(),
            status="uploaded",
        )

        db.add(document)
        db.commit()
        db.refresh(document)

        return {
            "id": document.id,
            "workspace": workspace.slug,
            "filename": document.original_filename,
            "size_bytes": document.size_bytes,
            "sha256": document.sha256,
            "status": document.status,
        }

    except Exception:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    finally:
        file.file.close()


@router.get("/{workspace_slug}/documents")
def list_documents(
    workspace_slug: str,
    db: Session = Depends(get_db),
):
    workspace = db.query(Workspace).filter(
        Workspace.slug == workspace_slug
    ).first()

    if not workspace:
        raise HTTPException(404, "Workspace not found")

    documents = db.query(Document).filter(
        Document.workspace_id == workspace.id
    ).order_by(Document.created_at.desc()).all()

    return [
        {
            "id": doc.id,
            "filename": doc.original_filename,
            "extension": doc.file_extension,
            "size_bytes": doc.size_bytes,
            "status": doc.status,
            "created_at": doc.created_at,
        }
        for doc in documents
    ]


@router.post("/{workspace_slug}/documents/{document_id}/process")
def process_uploaded_document(
    workspace_slug: str,
    document_id: str,
    db: Session = Depends(get_db),
):
    workspace = db.query(Workspace).filter(
        Workspace.slug == workspace_slug
    ).first()

    if not workspace:
        raise HTTPException(404, "Workspace not found")

    document = db.query(Document).filter(
        Document.id == document_id,
        Document.workspace_id == workspace.id,
    ).first()

    if not document:
        raise HTTPException(404, "Document not found")

    storage_path = STORAGE_PATH / document.stored_filename

    if not storage_path.is_file():
        raise HTTPException(404, "Original document file not found")

    try:
        chunks = process_document(
            storage_path,
            document.file_extension,
        )

        if not chunks:
            raise ValueError("No extractable text found")

        # Remove previous chunks if this document is reprocessed.
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document.id
        ).delete(synchronize_session=False)

        for chunk in chunks:
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk["chunk_index"],
                    page_number=chunk["page_number"],
                    content=chunk["content"],
                )
            )

        document.status = "processed"

        db.commit()

        return {
            "document_id": document.id,
            "filename": document.original_filename,
            "status": document.status,
            "total_chunks": len(chunks),
            "total_characters": sum(
                len(chunk["content"]) for chunk in chunks
            ),
        }

    except Exception as exc:
        db.rollback()

        document = db.query(Document).filter(
            Document.id == document_id,
            Document.workspace_id == workspace.id,
        ).first()

        if document:
            document.status = "processing_failed"
            db.commit()

        if isinstance(exc, HTTPException):
            raise

        raise HTTPException(
            status_code=422,
            detail=f"Document processing failed: {str(exc)}",
        )

@router.post("/{workspace_slug}/documents/{document_id}/embed")
def embed_document(
    workspace_slug: str,
    document_id: str,
    db: Session = Depends(get_db),
):
    workspace = db.query(Workspace).filter(
        Workspace.slug == workspace_slug
    ).first()

    if not workspace:
        raise HTTPException(404, "Workspace not found")

    document = db.query(Document).filter(
        Document.id == document_id,
        Document.workspace_id == workspace.id,
    ).first()

    if not document:
        raise HTTPException(404, "Document not found")

    chunks = db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document.id
    ).order_by(DocumentChunk.chunk_index).all()

    if not chunks:
        raise HTTPException(
            400,
            "Document has no processed chunks",
        )

    model_name = os.getenv(
        "EMBEDDING_MODEL",
        "openai/text-embedding-3-small",
    )

    batch_size = int(
        os.getenv("EMBEDDING_BATCH_SIZE", "64")
    )

    try:
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]

            texts = [
                chunk.content
                for chunk in batch
            ]

            vectors = generate_embeddings(texts)

            if len(vectors) != len(batch):
                raise ValueError("Embedding count mismatch")

            for chunk, vector in zip(batch, vectors):
                chunk.embedding = vector
                chunk.embedding_model = model_name
                chunk.embedding_dimensions = len(vector)

        db.commit()

        return {
            "document_id": document.id,
            "filename": document.original_filename,
            "embedding_model": model_name,
            "total_embedded_chunks": len(chunks),
            "dimensions": chunks[0].embedding_dimensions,
            "status": "embedded",
        }

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=502,
            detail="Embedding generation failed. Check provider configuration and API logs.",
        )
@router.post("/{workspace_slug}/search")
def search_documents(
    workspace_slug: str,
    data: SearchRequest,
    db: Session = Depends(get_db),
):
    # 1. Verify workspace
    workspace = (
        db.query(Workspace)
        .filter(Workspace.slug == workspace_slug)
        .first()
    )

    if not workspace:
        raise HTTPException(
            status_code=404,
            detail="Workspace not found",
        )

    # 2. Generate embedding for the search query
    try:
        query_embedding = generate_embeddings([data.query])[0]

    except Exception as exc:
        logger.exception("Search query embedding failed")

        raise HTTPException(
            status_code=502,
            detail=f"Query embedding failed: {type(exc).__name__}",
        )

    dimensions = len(query_embedding)

    # 3. Calculate cosine distance
    distance = DocumentChunk.embedding.cosine_distance(
        query_embedding
    )

    # 4. Search chunks belonging to this workspace
    results = (
        db.query(
            DocumentChunk,
            Document,
            distance.label("distance"),
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id,
        )
        .filter(
            Document.workspace_id == workspace.id,
            DocumentChunk.embedding.isnot(None),
            DocumentChunk.embedding_model == EMBEDDING_MODEL,
            DocumentChunk.embedding_dimensions == dimensions,
        )
        .order_by(distance)
        .limit(data.top_k)
        .all()
    )

    # 5. Format results
    response_results = []

    for chunk, document, distance_value in results:
        similarity = 1.0 - float(distance_value)

        response_results.append({
            "document_id": document.id,
            "filename": document.original_filename,
            "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "content": chunk.content,
            "similarity": round(similarity, 4),
        })

    return {
        "workspace": workspace_slug,
        "query": data.query,
        "embedding_model": EMBEDDING_MODEL,
        "total_results": len(response_results),
        "results": response_results,
    }
