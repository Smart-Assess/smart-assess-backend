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
router = APIRouter()

@router.post("/superadmin/university", response_model=dict)
async def add_university(
    university_name: str = Form(...),
    university_email: str = Form(...),
    phone_number: str = Form(...),
    street_address: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    zipcode: str = Form(...),
    admin_name: str = Form(...),
    admin_email: str = Form(...),
    admin_password: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_admin: SuperAdmin = Depends(get_current_admin),
):
    # Validate university details
    existing_university = (
        db.query(University).filter(University.email == university_email).first()
    )
    if existing_university:
        raise HTTPException(
            status_code=400, detail="University with this email already exists"
        )

    # Validate admin details
    existing_admin = (
        db.query(UniversityAdmin).filter(UniversityAdmin.email == admin_email).first()
    )
    if existing_admin:
        raise HTTPException(
            status_code=400, detail="University admin with this email already exists"
        )

    # Handle image upload (optional)
    image_url = None
    if image:
        image_path = f"/tmp/{image.filename}"
        with open(image_path, "wb") as buffer:
            buffer.write(await image.read())
        image_url = upload_to_s3(
            folder_name="university_images", file_name=image.filename, file_path=image_path
        )
        if not image_url:
            raise HTTPException(
                status_code=500, detail="Failed to upload university image"
            )

    # Create the new university
    new_university = University(
        name=university_name,
        email=university_email,
        phone_number=phone_number,
        street_address=street_address,
        city=city,
        state=state,
        zipcode=zipcode,
        image_url=image_url,
        super_admin_id=current_admin.id,
    )
    db.add(new_university)
    db.commit()
    db.refresh(new_university)

    # Create the university admin
    new_university_admin = UniversityAdmin(
        name=admin_name,
        email=admin_email,
        password=get_password_hash(admin_password),
        university_id=new_university.id,
    )
    db.add(new_university_admin)
    db.commit()

    return {
        "success": True,
        "status": 201,
        "university_id": new_university.id,
        "admin_id": new_university_admin.id,
    }

@router.get("/superadmin/university/{university_id}", response_model=dict)
async def get_university(
    university_id: int,
    db: Session = Depends(get_db),
    current_admin: SuperAdmin = Depends(get_current_admin),
):
    # Retrieve the university details
    university = db.query(University).filter(University.id == university_id).first()
    if not university:
        raise HTTPException(status_code=404, detail="University not found")

    # Retrieve the associated university admin details
    university_admin = db.query(UniversityAdmin).filter(UniversityAdmin.university_id == university_id).first()
    if not university_admin:
        raise HTTPException(status_code=404, detail="University admin not found")

    return {
        "success": True,
        "status": 200,
        "university": {
            "id": university.id,
            "name": university.name,
            "email": university.email,
            "phone_number": university.phone_number,
            "street_address": university.street_address,
            "city": university.city,
            "state": university.state,
            "zipcode": university.zipcode,
            "image_url": university.image_url,
            "super_admin_id": university.super_admin_id,
        },
        "admin": {
            "id": university_admin.id,
            "name": university_admin.name,
            "email": university_admin.email,
            "university_id": university_admin.university_id,
            "created_at": university_admin.created_at,
        }
    }