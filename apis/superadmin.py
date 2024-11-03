# >> Import necessary modules and packages from FastAPI and other libraries
from sqlalchemy.exc import IntegrityError
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session
# from apis.auth import get_current_admin
from models.models import *
from utils.dependencies import get_db

router = APIRouter()
