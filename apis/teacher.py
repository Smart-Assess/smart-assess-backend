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
from apis.auth import get_current_admin
from models.models import *
from utils.dependencies import get_db
from typing import Optional

from utils.s3 import upload_to_s3
from utils.security import get_password_hash
import os
router = APIRouter()

@router.post("/teacher/course", response_model=dict)
async def create_course(
    name: str = Form(...),
    batch: str = Form(...),
    group: Optional[str] = Form(None),
    section: str = Form(...),
    status: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),  # Get the current teacher's info
):
    image_url = None
    if image:
        image_path = f"/tmp/{image.filename}"
        with open(image_path, "wb") as buffer:
            buffer.write(await image.read())
        image_url = upload_to_s3(
            folder_name="course_images", file_name=image.filename, file_path=image_path
        )
        if not image_url:
            raise HTTPException(
                status_code=500, detail="Failed to upload course image"
            )
        os.remove(image_path)

    new_course = Course(
        name=name,
        batch=batch,
        group=group,
        section=section,
        status=status,
        image_url=image_url,
        teacher_id=current_teacher.id,
    )

    db.add(new_course)
    db.commit()
    db.refresh(new_course)

    return {
        "success": True,
        "status": 201,
        "course_id": new_course.id,
    }