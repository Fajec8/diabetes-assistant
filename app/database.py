import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    sessionmaker,
)


load_dotenv()


DATABASE_URL = os.getenv(
    "DATABASE_URL"
)


if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set"
    )


# Cloud providers commonly return:
#
# postgresql://user:password@host/database
#
# The project uses psycopg 3, so SQLAlchemy should
# explicitly use the psycopg driver.
if DATABASE_URL.startswith(
    "postgresql://"
):
    DATABASE_URL = (
        DATABASE_URL.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1
        )
    )


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()