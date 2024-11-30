from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from models.models import *
from utils.dependencies import get_db
from apis.auth import get_current_admin

router = APIRouter()

@router.post("/student/course/join", response_model=dict)
async def join_course(
    course_code: str = Form(...),
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    course = db.query(Course).filter(Course.course_code == course_code).first()
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )
    
    # Verify university match
    course_teacher = db.query(Teacher).filter(
        Teacher.id == course.teacher_id
    ).first()
    if course_teacher.university_id != current_student.university_id:
        raise HTTPException(
            status_code=403,
            detail="You can only join courses from your university"
        )
    
    # Check if already requested
    existing_request = db.query(StudentCourse).filter(
        StudentCourse.student_id == current_student.id,
        StudentCourse.course_id == course.id
    ).first()
    
    if existing_request:
        raise HTTPException(
            status_code=400,
            detail=f"You have already {existing_request.status} this course"
        )
    
    # Create join request
    join_request = StudentCourse(
        student_id=current_student.id,
        course_id=course.id,
        status="pending"
    )
    
    db.add(join_request)
    db.commit()
    db.refresh(join_request)
    
    return {
        "success": True,
        "status": 201,
        "message": "Course join request submitted successfully",
        "request": {
            "id": join_request.id,
            "status": join_request.status,
            "created_at": join_request.created_at
        }
    }