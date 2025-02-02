# >> Import necessary modules and packages from FastAPI and other libraries
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session
from apis.auth import get_current_admin
from models.models import *
from utils.dependencies import get_db
from typing import Optional

from utils.s3 import upload_to_s3, delete_from_s3
from utils.security import get_password_hash
import os
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
    existing_university = (
        db.query(University).filter(
            University.email == university_email).first()
    )
    if existing_university:
        raise HTTPException(
            status_code=400, detail="University with this email already exists"
        )

    existing_admin = (
        db.query(UniversityAdmin).filter(
            UniversityAdmin.email == admin_email).first()
    )
    if existing_admin:
        raise HTTPException(
            status_code=400, detail="University admin with this email already exists"
        )

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
        os.remove(image_path)

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
    university = db.query(University).filter(
        University.id == university_id,
        University.super_admin_id == current_admin.id
    ).first()

    if not university:
        raise HTTPException(
            status_code=404,
            detail="University not found or access denied"
        )

    university_admin = db.query(UniversityAdmin).filter(
        UniversityAdmin.university_id == university_id
    ).first()

    if not university_admin:
        raise HTTPException(
            status_code=404,
            detail="University admin not found"
        )

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


@router.get("/superadmin/universities", response_model=dict)
async def get_universities(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_admin: SuperAdmin = Depends(get_current_admin),
):
    offset = (page - 1) * limit

    total = db.query(University).filter(
        University.super_admin_id == current_admin.id
    ).count()

    universities = db.query(University).filter(
        University.super_admin_id == current_admin.id
    ).offset(offset).limit(limit).all()

    universities_data = []
    for uni in universities:
        universities_data.append({
            "uni_id": f"Id-{str(uni.id).zfill(4)}",
            "id": uni.id,
            "name": uni.name,
            "students_count": 0,
            "teachers_count": 0,
        })

    return {
        "success": True,
        "status": 200,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "universities": universities_data,
        "has_previous": page > 1,
        "has_next": (offset + limit) < total,
    }


@router.delete("/superadmin/university/{university_id}", response_model=dict)
async def delete_university(
    university_id: int,
    db: Session = Depends(get_db),
    current_admin: SuperAdmin = Depends(get_current_admin)
):

    university = db.query(University).filter(
        University.id == university_id,
        University.super_admin_id == current_admin.id
    ).first()

    if not university:
        raise HTTPException(
            status_code=404,
            detail="University not found or access denied"
        )

    db.query(UniversityAdmin).filter(
        UniversityAdmin.university_id == university_id
    ).delete()

    # Delete university
    db.delete(university)
    db.commit()

    return {
        "success": True,
        "status": 200,
        "message": "University and associated admin deleted successfully"
    }


@router.put("/superadmin/university/{university_id}", response_model=dict)
async def update_university(
    university_id: int,
    university_name: Optional[str] = Form(None),
    university_email: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    street_address: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    state: Optional[str] = Form(None),
    zipcode: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_admin: SuperAdmin = Depends(get_current_admin)
    ):
    # Check if university exists and belongs to the current admin
    university = db.query(University).filter(
        University.id == university_id,
        University.super_admin_id == current_admin.id
    ).first()

    if not university:
        raise HTTPException(
            status_code=404,
            detail="University not found or access denied"
        )

    # Check if email is taken by another university
    if university_email:
        existing_university = db.query(University).filter(
            University.email == university_email,
            University.id != university_id
        ).first()

        if existing_university:
            raise HTTPException(
                status_code=400,
                detail="Email already taken by another university"
            )

    # Handle image upload if provided
    if image:
        try:
            # Delete the old image if it exists
            if university.image_url:
                delete_success = delete_from_s3(university.image_url)
                if not delete_success:
                    print(f"Failed to delete old image: {university.image_url}")

            # Save the new image to a temporary file
            image_path = f"/tmp/{image.filename}"
            with open(image_path, "wb") as buffer:
                buffer.write(await image.read())

            # Upload the new image to S3
            image_url = upload_to_s3(
                folder_name="university_images",
                file_name=image.filename,
                file_path=image_path
            )
            if not image_url:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to upload university image"
                )

            # Clean up the temporary file
            os.remove(image_path)

            # Update the university's image URL
            university.image_url = image_url
        except Exception as e:
            print(f"Error handling image upload: {e}")
            raise HTTPException(
                status_code=500,
                detail="An error occurred while processing the image"
            )

    # Update university fields if provided
    if university_name:
        university.name = university_name
    if university_email:
        university.email = university_email
    if phone_number:
        university.phone_number = phone_number
    if street_address:
        university.street_address = street_address
    if city:
        university.city = city
    if state:
        university.state = state
    if zipcode:
        university.zipcode = zipcode

    # Commit changes to the database
    db.commit()
    db.refresh(university)

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
            "image_url": university.image_url
        }
    }