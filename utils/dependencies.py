from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from models.models import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def get_async_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
