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

from fastapi import HTTPException
from utils.smtp import send_email
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
        db.query(University).filter(University.email == university_email).first()
    )
    if existing_university:
        raise HTTPException(
            status_code=400, detail="University with this email already exists"
        )

    existing_admin = (
        db.query(UniversityAdmin).filter(UniversityAdmin.email == admin_email).first()
    )
    if existing_admin:
        raise HTTPException(
            status_code=400, detail="University admin with this email already exists"
        )

    image_url = None
    if image:
        image_path = os.path.join("temp", image.filename)
        with open(image_path, "wb") as buffer:
            os.makedirs("temp", exist_ok=True)
            buffer.write(await image.read())
        image_url = upload_to_s3(
            folder_name="university_images",
            file_name=image.filename,
            file_path=image_path,
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

    send_email(university_email, admin_email, admin_password, "admin")
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
    university = (
        db.query(University)
        .filter(
            University.id == university_id,
            University.super_admin_id == current_admin.id,
        )
        .first()
    )

    if not university:
        raise HTTPException(
            status_code=404, detail="University not found or access denied"
        )

    university_admin = (
        db.query(UniversityAdmin)
        .filter(UniversityAdmin.university_id == university_id)
        .first()
    )

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
            "password": university_admin.password,
            "university_id": university_admin.university_id,
            "created_at": university_admin.created_at,
        },
    }


@router.get("/superadmin/universities", response_model=dict)
async def get_universities(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_admin: SuperAdmin = Depends(get_current_admin),
):
    offset = (page - 1) * limit

    total = (
        db.query(University)
        .filter(University.super_admin_id == current_admin.id)
        .count()
    )

    universities = (
        db.query(University)
        .filter(University.super_admin_id == current_admin.id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    universities_data = []
    for uni in universities:
        teachers_count = (
            db.query(Teacher).filter(Teacher.university_id == uni.id).count()
        )

        students_count = (
            db.query(Student).filter(Student.university_id == uni.id).count()
        )

        universities_data.append(
            {
                "uni_id": f"Id-{str(uni.id).zfill(4)}",
                "id": uni.id,
                "name": uni.name,
                "students_count": students_count,
                "teachers_count": teachers_count,
            }
        )

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
    current_admin: SuperAdmin = Depends(get_current_admin),
):

    university = (
        db.query(University)
        .filter(
            University.id == university_id,
            University.super_admin_id == current_admin.id,
        )
        .first()
    )

    if not university:
        raise HTTPException(
            status_code=404, detail="University not found or access denied"
        )

    try:
        # Count records that will be deleted for reporting
        admin_count = (
            db.query(UniversityAdmin)
            .filter(UniversityAdmin.university_id == university_id)
            .count()
        )

        teacher_count = (
            db.query(Teacher).filter(Teacher.university_id == university_id).count()
        )

        student_count = (
            db.query(Student).filter(Student.university_id == university_id).count()
        )

        # Delete university (with cascade)
        db.delete(university)
        db.commit()

        return {
            "success": True,
            "status": 200,
            "message": "University and associated users deleted successfully",
            "details": {
                "admins_deleted": admin_count,
                "teachers_deleted": teacher_count,
                "students_deleted": student_count,
            },
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to delete university: {str(e)}"
        )


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
    admin_name: Optional[str] = Form(None),
    admin_email: Optional[str] = Form(None),
    admin_password: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_admin: SuperAdmin = Depends(get_current_admin),
):
    # Check if university exists
    university = (
        db.query(University)
        .filter(
            University.id == university_id,
            University.super_admin_id == current_admin.id,
        )
        .first()
    )

    if not university:
        raise HTTPException(
            status_code=404, detail="University not found or access denied"
        )

    # Check if email is taken by another university
    if university_email and university_email != university.email:
        existing_university = (
            db.query(University)
            .filter(
                University.email == university_email, University.id != university_id
            )
            .first()
        )
        if existing_university:
            raise HTTPException(
                status_code=400, detail="Email already taken by another university"
            )

    # Fetch associated university admin
    university_admin = (
        db.query(UniversityAdmin)
        .filter(UniversityAdmin.university_id == university.id)
        .first()
    )

    if not university_admin:
        raise HTTPException(status_code=404, detail="University admin not found")

    # Check if admin email is taken
    if admin_email and admin_email != university_admin.email:
        existing_admin = (
            db.query(UniversityAdmin)
            .filter(
                UniversityAdmin.email == admin_email,
                UniversityAdmin.id != university_admin.id,
            )
            .first()
        )
        if existing_admin:
            raise HTTPException(
                status_code=400, detail="Email already taken by another admin"
            )

    # Handle image upload if provided
    if image:
        try:
            # Validate file type
            allowed_extensions = ["jpg", "jpeg", "png", "gif"]
            file_extension = image.filename.split(".")[-1].lower()
            if file_extension not in allowed_extensions:
                raise HTTPException(
                    status_code=400,
                    detail="Only JPG, JPEG, PNG, and GIF files are allowed",
                )

            # Delete the old image if it exists
            if university.image_url:
                delete_success = delete_from_s3(university.image_url)
                if not delete_success:
                    print(f"Failed to delete old image: {university.image_url}")

            # Save the new image to a temporary file
            temp_dir = "temp"
            os.makedirs(temp_dir, exist_ok=True)
            image_path = os.path.join(temp_dir, image.filename)

            with open(image_path, "wb") as buffer:
                buffer.write(await image.read())

            # Upload the new image to S3
            image_url = upload_to_s3(
                folder_name="university_images",
                file_name=f"{university.id}_{image.filename}",
                file_path=image_path,
            )

            if not image_url:
                raise HTTPException(
                    status_code=500, detail="Failed to upload university image"
                )

            # Clean up the temporary file
            os.remove(image_path)

            # Update the university's image URL
            university.image_url = image_url

        except Exception as e:
            print(f"Error handling image upload: {e}")
            raise HTTPException(
                status_code=500, detail="An error occurred while processing the image"
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

    # Update university admin fields if provided
    if admin_name:
        university_admin.name = admin_name
    if admin_email:
        university_admin.email = admin_email
    if admin_password:
        university_admin.password = get_password_hash(admin_password)

    # Commit changes
    try:
        db.commit()
        db.refresh(university)
        db.refresh(university_admin)

        # Only send email if password was updated
        if admin_password:
            send_email(university_admin.email, "", admin_password, "admin")

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update university: {str(e)}"
        )

    return {
        "success": True,
        "status": 200,
        "message": "University updated successfully",
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
        },
        "admin": {
            "id": university_admin.id,
            "name": university_admin.name,
            "email": university_admin.email,
        },
    }
