"""
Test environment. Import this module before anything from `app`.

The application reads DATABASE_URL and ASSET_STORAGE when its modules
are first imported, so they have to be set here, once, for every test
module. Tests use an in-memory SQLite database and a temporary asset
directory; they never touch PostgreSQL, Redis or a real LLM.
"""

import os
import tempfile

from pathlib import Path

ASSET_DIR = Path(tempfile.mkdtemp(prefix="aimkt-test-assets-")).resolve()

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ASSET_STORAGE"] = str(ASSET_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base  # noqa: E402
from app.models.brand_profile import BrandProfile  # noqa: E402
from app.models.video_asset import VideoAsset  # noqa: E402
from app.models.video_job import VideoJob  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402

WORKSPACE_SLUG = "iotelligen-marketing"

# Only the tables these tests need. The document tables use pgvector
# column types that SQLite cannot store.
TEST_TABLES = [
    Workspace.__table__,
    BrandProfile.__table__,
    VideoJob.__table__,
    VideoAsset.__table__,
]


def new_session_factory():
    """A fresh in-memory database with one workspace."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine, tables=TEST_TABLES)

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    with factory() as db:
        db.add(Workspace(name="IoTelliGen Marketing", slug=WORKSPACE_SLUG))
        db.commit()

    return factory
