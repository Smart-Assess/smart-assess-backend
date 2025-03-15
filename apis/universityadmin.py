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

from utils.s3 import upload_to_s3, delete_from_s3
from utils.security import get_password_hash

from fastapi import HTTPException
from utils.smtp import send_email  
import os

router = APIRouter()


############################### STUDENTS #################################
@router.post("/universityadmin/student", response_model=dict)
async def add_student(
    full_name: str = Form(...),
    student_id: str = Form(...),
    department: str = Form(...),
    email: str = Form(...),
    batch: str = Form(...),
    section: str = Form(...),
    password: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(
        get_current_admin
    ),  # Get the current admin's info
):
    # Check if a student with the same email already exists
    existing_student = db.query(Student).filter(Student.email == email).first()
    if existing_student:
        raise HTTPException(
            status_code=400, detail="Student with this email already exists"
        )
    image_url = None
    if image:
        image_path = os.path.join("temp", image.filename)
        with open(image_path, "wb") as buffer:
            os.makedirs("temp", exist_ok=True)
            buffer.write(await image.read())
        image_url = upload_to_s3(
            folder_name="student_images", file_name=image.filename, file_path=image_path
        )
        if not image_url:
            raise HTTPException(
                status_code=500, detail="Failed to upload student image"
            )
        os.remove(image_path)

    # Create the new student object, using the admin's university_id automatically
    new_student = Student(
        full_name=full_name,
        student_id=student_id,
        department=department,
        email=email,
        batch=batch,
        section=section,
        image_url=image_url,
        password=get_password_hash(password),  # Hash the password
        university_id=current_admin.university_id,  # Set university_id from the admin's associated university
    )
    send_email(email,"",password,"student")
    # Add the new student to the session and commit
    db.add(new_student)
    db.commit()
    db.refresh(new_student)

    return {
        "success": True,
        "status": 201,
        "student_id": new_student.id,
    }


@router.get("/universityadmin/students", response_model=dict)
async def get_students(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    offset = (page - 1) * limit

    total = (
        db.query(Student)
        .filter(Student.university_id == current_admin.university_id)
        .count()
    )

    students = (
        db.query(Student)
        .filter(Student.university_id == current_admin.university_id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    students_data = []
    for student in students:
        students_data.append(
            {
                "id": student.id,
                "full_name": student.full_name,
                "student_id": student.student_id,
                "department": student.department,
                "email": student.email,
                "image_url": student.image_url,
                "created_at": student.created_at,
                "university_id": student.university_id,
            }
        )

    return {
        "success": True,
        "status": 200,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "students": students_data,
        "has_previous": page > 1,
        "has_next": (offset + limit) < total,
    }


@router.get("/universityadmin/student/{student_id}", response_model=dict)
async def get_student(
    student_id: str,  # Change to str
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    student = (
        db.query(Student).filter(Student.student_id == student_id).first()
    )  # Change to student_id
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    return {
        "success": True,
        "status": 200,
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "student_id": student.student_id,
            "department": student.department,
            "email": student.email,
            "batch": student.batch,
            "section": student.section,
            "created_at": student.created_at,
            "university_id": student.university_id,
        },
    }


@router.delete("/universityadmin/student/{student_id}", response_model=dict)
async def delete_student(
    student_id: str,  # Change to str
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    student = (
        db.query(Student).filter(Student.student_id == student_id).first()
    )  # Change to student_id
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    db.delete(student)
    db.commit()

    return {"success": True, "status": 200, "message": "Student deleted successfully"}


@router.put("/universityadmin/student/{student_id}", response_model=dict)
async def update_student(
    student_id: str,
    full_name: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    batch: Optional[str] = Form(None),
    section: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    student = db.query(Student).filter(Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if email:
        existing_student = (
            db.query(Student)
            .filter(Student.email == email, Student.student_id != student_id)
            .first()
        )
        if existing_student:
            raise HTTPException(
                status_code=400, detail="Email already taken by another student"
            )

    if full_name:
        student.full_name = full_name
    if department:
        student.department = department
    if email:
        student.email = email
    if batch:
        student.batch = batch
    if section:
        student.section = section
    if password:
        student.password = get_password_hash(password)

    # Handle image upload if provided
    if image:
        try:
            # Delete the old image if it exists
            if student.image_url:
                delete_success = delete_from_s3(student.image_url)
                if not delete_success:
                    print(f"Failed to delete old image: {student.image_url}")

            # Save the new image to a temporary file
            image_path = f"/tmp/{image.filename}"
            with open(image_path, "wb") as buffer:
                buffer.write(await image.read())

            # Upload the new image to S3
            image_url = upload_to_s3(
                folder_name="student_images",
                file_name=image.filename,
                file_path=image_path,
            )
            if not image_url:
                raise HTTPException(
                    status_code=500, detail="Failed to upload university image"
                )

            # Clean up the temporary file
            os.remove(image_path)

            # Update the university's image URL
            student.image_url = image_url
        except Exception as e:
            print(f"Error handling image upload: {e}")
            raise HTTPException(
                status_code=500, detail="An error occurred while processing the image"
            )

    db.commit()
    send_email(student.email,"",student.password,"student")
    db.refresh(student)

    return {
        "success": True,
        "status": 200,
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "student_id": student.student_id,
            "department": student.department,
            "email": student.email,
            "batch": student.batch,
            "section": student.section,
            "image_url": student.image_url,
            "created_at": student.created_at,
            "university_id": student.university_id,
        },
    }


############################### TEACHER #################################
@router.post("/universityadmin/teacher", response_model=dict)
async def add_teacher(
    full_name: str = Form(...),
    teacher_id: str = Form(...),
    department: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    existing_teacher = db.query(Teacher).filter(Teacher.email == email).first()
    if existing_teacher:
        raise HTTPException(
            status_code=400, detail="Teacher with this email already exists"
        )

    image_url = None
    if image:

        image_path = os.path.join("temp", image.filename)
        with open(image_path, "wb") as buffer:
            os.makedirs("temp", exist_ok=True)
            buffer.write(await image.read())
        image_url = upload_to_s3(
            folder_name="teacher_images", file_name=image.filename, file_path=image_path
        )
        if not image_url:
            raise HTTPException(
                status_code=500, detail="Failed to upload teacher image"
            )
        os.remove(image_path)

    new_teacher = Teacher(
        full_name=full_name,
        teacher_id=teacher_id,
        department=department,
        email=email,
        password=get_password_hash(password),
        image_url=image_url,
        university_id=current_admin.university_id,
    )
    send_email(email,"",password,"teacher")

    db.add(new_teacher)
    db.commit()
    db.refresh(new_teacher)

    return {
        "success": True,
        "status": 201,
        "teacher_id": new_teacher.id,
    }


@router.get("/universityadmin/teacher/{teacher_id}", response_model=dict)
async def get_teacher(
    teacher_id: str,  # Change to str
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    teacher = (
        db.query(Teacher).filter(Teacher.teacher_id == teacher_id).first()
    )  # Change to teacher_id
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    return {
        "success": True,
        "status": 200,
        "teacher": {
            "id": teacher.id,
            "full_name": teacher.full_name,
            "teacher_id": teacher.teacher_id,
            "department": teacher.department,
            "email": teacher.email,
            "image_url": teacher.image_url,
            "created_at": teacher.created_at,
            "university_id": teacher.university_id,
        },
    }


@router.delete("/universityadmin/teacher/{teacher_id}", response_model=dict)
async def delete_teacher(
    teacher_id: str,  # Change to str
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    teacher = (
        db.query(Teacher).filter(Teacher.teacher_id == teacher_id).first()
    )  # Change to teacher_id
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    db.delete(teacher)
    db.commit()

    return {"success": True, "status": 200, "message": "Teacher deleted successfully"}


@router.put("/universityadmin/teacher/{teacher_id}", response_model=dict)
async def update_teacher(
    teacher_id: str,
    full_name: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    """Update teacher details with all fields optional except teacher_id."""

    teacher = db.query(Teacher).filter(Teacher.teacher_id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    if email:
        existing_teacher = (
            db.query(Teacher)
            .filter(Teacher.email == email, Teacher.teacher_id != teacher_id)
            .first()
        )
        if existing_teacher:
            raise HTTPException(
                status_code=400, detail="Email already taken by another teacher"
            )
        teacher.email = email

    if full_name:
        teacher.full_name = full_name

    if department:
        teacher.department = department

    if password:
        teacher.password = get_password_hash(password)

    # Handle image upload if provided
    if image:
        try:
            # Delete the old image if it exists
            if teacher.image_url:
                delete_success = delete_from_s3(teacher.image_url)
                if not delete_success:
                    print(f"Failed to delete old image: {teacher.image_url}")

            # Save the new image to a temporary file
            image_path = f"/tmp/{image.filename}"
            with open(image_path, "wb") as buffer:
                buffer.write(await image.read())

            # Upload the new image to S3
            image_url = upload_to_s3(
                folder_name="teacher_images",
                file_name=image.filename,
                file_path=image_path,
            )
            if not image_url:
                raise HTTPException(
                    status_code=500, detail="Failed to upload university image"
                )

            # Clean up the temporary file
            os.remove(image_path)

            # Update the university's image URL
            teacher.image_url = image_url
        except Exception as e:
            print(f"Error handling image upload: {e}")
            raise HTTPException(
                status_code=500, detail="An error occurred while processing the image"
            )

    db.commit()
    send_email(teacher.email,"",teacher.password,"teacher")
    db.refresh(teacher)

    return {
        "success": True,
        "status": 200,
        "teacher": {
            "id": teacher.id,
            "full_name": teacher.full_name,
            "teacher_id": teacher.teacher_id,
            "department": teacher.department,
            "email": teacher.email,
            "image_url": teacher.image_url,
            "created_at": teacher.created_at,
            "university_id": teacher.university_id,
        },
    }


@router.get("/universityadmin/teachers", response_model=dict)
async def get_teachers(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_admin: UniversityAdmin = Depends(get_current_admin),
):
    offset = (page - 1) * limit

    total = (
        db.query(Teacher)
        .filter(Teacher.university_id == current_admin.university_id)
        .count()
    )

    teachers = (
        db.query(Teacher)
        .filter(Teacher.university_id == current_admin.university_id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    teachers_data = []
    for teacher in teachers:
        teachers_data.append(
            {
                "id": teacher.id,
                "full_name": teacher.full_name,
                "teacher_id": teacher.teacher_id,
                "department": teacher.department,
                "email": teacher.email,
                "image_url": teacher.image_url,
                "created_at": teacher.created_at,
                "university_id": teacher.university_id,
            }
        )

    return {
        "success": True,
        "status": 200,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "teachers": teachers_data,
        "has_previous": page > 1,
        "has_next": (offset + limit) < total,
    }
