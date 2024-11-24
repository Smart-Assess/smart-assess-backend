from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from models.models import SuperAdmin
from utils.dependencies import get_db
from utils.security import create_access_token, verify_password, SECRET_KEY, ALGORITHM
from datetime import timedelta, datetime
from jose import jwt, JWTError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
router = APIRouter()

@router.post("/login", response_model=dict)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = None
    role = None
    user_data = {}

    user = authenticate_super_admin(db, form_data.username, form_data.password)
    if user:
        role = "superadmin"
        user_data = {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at,
            "role": role,
        }

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={
            "sub": str(user.id)
            },
        role=role,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "status": 201,
        "success": True,
        "user": user_data,
    }

def authenticate_super_admin(db: Session, email: str, password: str):
    admin = db.query(SuperAdmin).filter(
        SuperAdmin.email == email.strip()).first()
    if admin and verify_password(password, admin.password):
        return admin
    return None

async def get_current_admin(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        admin_id: str = payload.get("sub")
        role: str = payload.get("role")

        if admin_id is None or role != "superadmin":
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    admin = db.query(SuperAdmin).filter(SuperAdmin.id == admin_id).first()
    if admin is None:
        raise credentials_exception
    return admin