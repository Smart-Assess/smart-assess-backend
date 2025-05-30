from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from models.models import *
from utils.dependencies import get_db
from utils.security import create_access_token, verify_password, SECRET_KEY, ALGORITHM
from datetime import timedelta, datetime
from jose import jwt, JWTError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
router = APIRouter()


@router.post("/login", response_model=dict)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = None
    role = None
    user_data = {}

    auth_functions = [
        (authenticate_super_admin, "superadmin"),
        (authenticate_university_admin, "universityadmin"),
        (authenticate_teacher, "teacher"),
        (authenticate_student, "student"),
    ]

    for auth_function, user_role in auth_functions:
        user = auth_function(db, form_data.username, form_data.password)
        if user:
            role = user_role

            # Get the appropriate name field based on user type
            if user_role == "student" or user_role == "teacher":
                name = user.full_name
            elif user_role == "universityadmin":
                name = user.name
            elif user_role == "superadmin":
                name = user.email

            user_data = {
                "id": user.id,
                "email": user.email,
                "name": name,
                "created_at": user.created_at,
                "role": role,
            }
            break

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": str(user.id)},
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
    admin = db.query(SuperAdmin).filter(SuperAdmin.email == email.strip()).first()
    if admin and verify_password(password, admin.password):
        return admin
    return None


def authenticate_university_admin(db: Session, email: str, password: str):
    admin = (
        db.query(UniversityAdmin).filter(UniversityAdmin.email == email.strip()).first()
    )

    if admin and verify_password(password, admin.password):
        return admin
    return None


def authenticate_teacher(db: Session, email: str, password: str):
    admin = db.query(Teacher).filter(Teacher.email == email.strip()).first()

    if admin and verify_password(password, admin.password):
        return admin
    return None


def authenticate_student(db: Session, email: str, password: str):
    student = db.query(Student).filter(Student.email == email.strip()).first()
    if student and verify_password(password, student.password):
        return student
    return None


async def get_current_admin(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Decode the JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")

        if user_id is None:
            raise credentials_exception

        if role == "superadmin":
            user = db.query(SuperAdmin).filter(SuperAdmin.id == user_id).first()
        elif role == "universityadmin":
            user = (
                db.query(UniversityAdmin).filter(UniversityAdmin.id == user_id).first()
            )
        elif role == "teacher":
            user = db.query(Teacher).filter(Teacher.id == user_id).first()
            if user:
                # Verify university still exists
                university = (
                    db.query(University)
                    .filter(University.id == user.university_id)
                    .first()
                )
                if not university:
                    raise credentials_exception
        elif role == "student":
            user = db.query(Student).filter(Student.id == user_id).first()
            if user:
                # Verify university still exists
                university = (
                    db.query(University)
                    .filter(University.id == user.university_id)
                    .first()
                )
                if not university:
                    raise credentials_exception
        else:
            raise credentials_exception

        if user is None:
            raise credentials_exception

        return user

    except JWTError:
        raise credentials_exception
