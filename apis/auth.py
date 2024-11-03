import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models.models import SuperAdmin
from utils.dependencies import get_db
from utils.security import create_access_token, verify_password, get_password_hash, SECRET_KEY, ALGORITHM
from datetime import timedelta, datetime
from models.pydantic_model import OAuth2EmailRequestForm

from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
# from jose import jwt, JWTError
from fastapi import (
    Depends,
    HTTPException,
    status,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
router = APIRouter()


@router.post("/login", response_model=dict)
async def login_for_access_token(
    form_data: OAuth2EmailRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = None
    role = None
    user_data = {}

    user = authenticate_super_admin(db, form_data.email, form_data.password)
    if user:
        role = "superadmin"
        user_data = {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at,
            "role": role,
        }

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": str(user.id)}, role=role)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "status": 201,
        "success": True,
        "user": user_data,
    }

    

def authenticate_super_admin(db: Session, email: str, password: str):
    admin = db.query(SuperAdmin).filter(SuperAdmin.email == email.strip()).first()
    if admin and verify_password(password, admin.password):
        return admin
    return None