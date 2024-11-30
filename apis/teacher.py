# >> Import necessary modules and packages from FastAPI and other libraries
import json
import re
from uuid import uuid4
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
from typing import List, Optional
from bestrag import BestRAG
from utils.s3 import delete_from_s3, upload_to_s3
# from utils.security import get_password_hash
import os
from dotenv import load_dotenv

load_dotenv()

teacher_rag_cache = {}
# >> Define the router for the API
def generate_collection_name(teacher_id: int, course_name: str) -> str:
    """Generate unique collection name for course"""
    sanitized_name = re.sub(r'[^a-zA-Z0-9]', '_', course_name.lower())
    unique_id = str(uuid4())[:8]
    return f"teacher_{teacher_id}_{sanitized_name}_{unique_id}"

def get_teacher_rag(collection_name: str) -> BestRAG:
    """Get or create BestRAG instance using collection name"""
    if collection_name not in teacher_rag_cache:
        teacher_rag_cache[collection_name] = BestRAG(
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY"),
            collection_name=collection_name
        )
    return teacher_rag_cache[collection_name]

router = APIRouter()

@router.post("/teacher/course", response_model=dict)
async def create_course(
    name: str = Form(...),
    batch: str = Form(...),
    group: Optional[str] = Form(None),
    section: str = Form(...),
    status: str = Form(...),
    pdfs: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    collection_name = generate_collection_name(current_teacher.id, name)
    rag = get_teacher_rag(collection_name)
    pdf_urls = []
    if pdfs:
        for pdf in pdfs:
            if not pdf.content_type == 'application/pdf':
                raise HTTPException(
                    status_code=400, 
                    detail=f"File {pdf.filename} must be a PDF"
                )
            
            pdf_path = f"/tmp/{pdf.filename}"
            try:
                with open(pdf_path, "wb") as buffer:
                    buffer.write(await pdf.read())
                
                pdf_url = upload_to_s3(
                    folder_name=f"course_pdfs/{current_teacher.id}",
                    file_name=pdf.filename,
                    file_path=pdf_path
                )

                if pdf_url:
                    try:
                        rag.store_pdf_embeddings(pdf_path, pdf_url)
                    except Exception as e:
                        print(f"Failed to store embeddings: {e}")
                        
                    pdf_urls.append(pdf_url)
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to upload PDF {pdf.filename}"
                    )
            finally:
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
            pdf_urls.append(pdf_url)

    new_course = Course(
        name=name,
        batch=batch,
        group=group,
        section=section,
        status=status,
        pdf_urls=json.dumps(pdf_urls),
        teacher_id=current_teacher.id,
        collection_name=collection_name,
    )

    db.add(new_course)
    db.commit()
    db.refresh(new_course)

    return {
        "success": True,
        "status": 201,
        "course": {
            "id": new_course.id,
            "name": new_course.name,
            "course_code": new_course.course_code,
            "batch": new_course.batch,
            "group": new_course.group,
            "section": new_course.section,
            "status": new_course.status,
            "pdf_urls": json.loads(new_course.pdf_urls)
        }
    }
    
@router.get("/teacher/course/{course_id}", response_model=dict)
async def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )

    return {
        "success": True,
        "status": 200,
        "course": {
            "id": course.id,
            "name": course.name,
            "batch": course.batch,
            "group": course.group,
            "section": course.section,
            "status": course.status,
            "course_code": course.course_code,
            "pdf_urls": json.loads(course.pdf_urls),
            "created_at": course.created_at
        }
    }

@router.put("/teacher/course/{course_id}/regenerate-code", response_model=dict)
async def regenerate_course_code(
    course_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )

    while True:
        new_code = generate_course_code()
        exists = db.query(Course).filter(Course.course_code == new_code).first()
        if not exists:
            break

    course.course_code = new_code
    db.commit()
    db.refresh(course)

    return {
        "success": True,
        "status": 201,
        "message": "Course code regenerated successfully",
        "new_code": course.course_code
    }

@router.put("/teacher/course/{course_id}", response_model=dict)
async def update_course(
    course_id: int,
    name: Optional[str] = Form(None),
    batch: Optional[str] = Form(None),
    group: Optional[str] = Form(None),
    section: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    pdfs: Optional[List[UploadFile]] = File(None),
    removed_pdfs: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),

):
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    rag = get_teacher_rag(course.collection_name)
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )

    # Handle PDF removals
    if removed_pdfs:
        removed_urls = json.loads(removed_pdfs)
        existing_urls = json.loads(course.pdf_urls)
        
        for url in removed_urls:
            if url in existing_urls:
                delete_success = delete_from_s3(url)
                if delete_success:
                    try:
                        rag.delete_pdf_embeddings(url)
                    except Exception as e:
                        print(f"Failed to delete embeddings: {e}")
                    existing_urls.remove(url)
                else:
                    print(f"Failed to delete PDF from S3: {url}")
        
        course.pdf_urls = json.dumps(existing_urls)

    if pdfs:
        existing_urls = json.loads(course.pdf_urls)
        folder_name = f"course_pdfs/{current_teacher.id}/{name if name else course.name}"
        
        for pdf in pdfs:
            if not pdf.content_type == 'application/pdf':
                raise HTTPException(
                    status_code=400,
                    detail=f"File {pdf.filename} must be a PDF"
                )
            
            pdf_path = f"/tmp/{pdf.filename}"
            with open(pdf_path, "wb") as buffer:
                buffer.write(await pdf.read())
            
            pdf_url = upload_to_s3(
                folder_name=folder_name,
                file_name=pdf.filename,
                file_path=pdf_path
            )
            
            if pdf_url:
                try:
                    rag.store_pdf_embeddings(pdf_path, pdf_url)
                except Exception as e:
                    print(f"Failed to store embeddings: {e}")
                existing_urls.append(pdf_url)
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to upload PDF {pdf.filename}"
                )
            os.remove(pdf_path)        
        course.pdf_urls = json.dumps(existing_urls)

    if name and name != course.name:
        old_urls = json.loads(course.pdf_urls)
        new_urls = []
        
        for old_url in old_urls:
            if old_url in (removed_urls if removed_pdfs else []):
                continue
                
            file_name = old_url.split('/')[-1]
            new_folder = f"course_pdfs/{current_teacher.id}/{name}"
            
            new_url = upload_to_s3(
                folder_name=new_folder,
                file_name=file_name,
                file_path=f"/tmp/{file_name}"
            )
            
            if new_url:
                new_urls.append(new_url)
                delete_from_s3(old_url)
            else:
                new_urls.append(old_url)
                
        course.pdf_urls = json.dumps(new_urls)

    if name: course.name = name
    if batch: course.batch = batch
    if group: course.group = group
    if section: course.section = section
    if status: course.status = status

    db.commit()
    db.refresh(course)

    return {
        "success": True,
        "status": 200,
        "message": "Course updated successfully",
        "course": {
            "id": course.id,
            "name": course.name,
            "batch": course.batch,
            "group": course.group,
            "section": course.section,
            "status": course.status,
            "course_code": course.course_code,
            "pdf_urls": json.loads(course.pdf_urls)
        }
    }
    
@router.post("/teacher/course/{course_id}/assignment", response_model=dict)
async def create_assignment(
    course_id: int,
    name: str = Form(...),
    description: str = Form(...),
    deadline: str = Form(...),  # Format: "YYYY-MM-DD HH:MM"
    grade: int = Form(...),
    question_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):

    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )

    # Validate PDF
    if not question_pdf.content_type == 'application/pdf':
        raise HTTPException(
            status_code=400,
            detail="Question file must be a PDF"
        )

    # Upload PDF to S3
    pdf_path = f"/tmp/{question_pdf.filename}"
    with open(pdf_path, "wb") as buffer:
        buffer.write(await question_pdf.read())
    
    pdf_url = upload_to_s3(
        folder_name=f"course_assignments/{current_teacher.id}/{course.name}",
        file_name=question_pdf.filename,
        file_path=pdf_path
    )
    
    if not pdf_url:
        raise HTTPException(
            status_code=500,
            detail="Failed to upload question PDF"
        )
    os.remove(pdf_path)

    try:
        deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid deadline format. Use YYYY-MM-DD HH:MM"
        )

    # Create assignment
    new_assignment = Assignment(
        name=name,
        description=description,
        deadline=deadline_dt,
        grade=grade,
        question_pdf_url=pdf_url,
        course_id=course_id
    )

    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)

    return {
        "success": True,
        "status": 201,
        "assignment": {
            "id": new_assignment.id,
            "name": new_assignment.name,
            "description": new_assignment.description,
            "deadline": new_assignment.deadline.strftime("%Y-%m-%d %H:%M"),
            "grade": new_assignment.grade,
            "question_pdf_url": new_assignment.question_pdf_url,
            "course_id": new_assignment.course_id,
            "created_at": new_assignment.created_at
        }
    }

@router.get("/teacher/assignments", response_model=dict)
async def get_teacher_assignments(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    offset = (page - 1) * limit
    
    total = db.query(Assignment)\
        .join(Course)\
        .filter(Course.teacher_id == current_teacher.id)\
        .count()
    
    assignments = db.query(Assignment, Course)\
        .join(Course)\
        .filter(Course.teacher_id == current_teacher.id)\
        .order_by(Assignment.created_at.desc())\
        .offset(offset)\
        .limit(limit)\
        .all()
    
    assignments_data = []
    for assignment, course in assignments:
        assignments_data.append({
            "id": assignment.id,
            "name": assignment.name,
            "batch": course.batch,
            "department": course.group,
            "section": course.section,
            "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
            "grade": assignment.grade
        })

    return {
        "success": True,
        "status": 200,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "assignments": assignments_data,
        "has_previous": page > 1,
        "has_next": (offset + limit) < total
    }
    
@router.put("/teacher/course/{course_id}/assignment/{assignment_id}", response_model=dict)
async def update_assignment(
    course_id: int,
    assignment_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    deadline: Optional[str] = Form(None),
    grade: Optional[int] = Form(None),
    question_pdf: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    # Verify course and assignment ownership
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )

    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.course_id == course_id
    ).first()
    
    if not assignment:
        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )

    # Handle PDF update if provided
    if question_pdf:
        if not question_pdf.content_type == 'application/pdf':
            raise HTTPException(
                status_code=400,
                detail="Question file must be a PDF"
            )

        # Delete old PDF from S3
        if assignment.question_pdf_url:
            delete_success = delete_from_s3(assignment.question_pdf_url)
            if not delete_success:
                print(f"Failed to delete old PDF: {assignment.question_pdf_url}")

        # Upload new PDF
        pdf_path = f"/tmp/{question_pdf.filename}"
        with open(pdf_path, "wb") as buffer:
            buffer.write(await question_pdf.read())
        
        pdf_url = upload_to_s3(
            folder_name=f"course_assignments/{current_teacher.id}/{course.name}",
            file_name=question_pdf.filename,
            file_path=pdf_path
        )
        
        if not pdf_url:
            raise HTTPException(
                status_code=500,
                detail="Failed to upload question PDF"
            )
        os.remove(pdf_path)
        assignment.question_pdf_url = pdf_url

    # Update deadline if provided
    if deadline:
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
            assignment.deadline = deadline_dt
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid deadline format. Use YYYY-MM-DD HH:MM"
            )

    # Update other fields if provided
    if name: assignment.name = name
    if description: assignment.description = description
    if grade: assignment.grade = grade

    db.commit()
    db.refresh(assignment)

    return {
        "success": True,
        "status": 200,
        "message": "Assignment updated successfully",
        "assignment": {
            "id": assignment.id,
            "name": assignment.name,
            "description": assignment.description,
            "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
            "grade": assignment.grade,
            "question_pdf_url": assignment.question_pdf_url,
            "course_id": assignment.course_id,
            "created_at": assignment.created_at
        }
    }
    

@router.get("/teacher/course/{course_id}/requests", response_model=dict)
async def get_course_requests(
    course_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )

    # Get all pending requests with student info
    requests = db.query(StudentCourse, Student)\
        .join(Student)\
        .filter(
            StudentCourse.course_id == course_id,
            StudentCourse.status == "pending"
        ).all()
    
    requests_data = []
    for request, student in requests:
        requests_data.append({
            "request_id": request.id,
            "status": request.status,
            "created_at": request.created_at,
            "student": {
                "id": student.id,
                "name": student.full_name,
                "email": student.email,
                "batch": student.batch,
                "section": student.section
            }
        })

    return {
        "success": True,
        "status": 200,
        "course_id": course_id,
        "requests": requests_data
    }

@router.put("/teacher/course/{course_id}/request/{request_id}", response_model=dict)
async def update_course_request(
    course_id: int,
    request_id: int,
    status: str = Form(...),  # accepted or rejected
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    # Validate status
    if status not in ["accepted", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be 'accepted' or 'rejected'"
        )

    # Verify course ownership
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )

    # Get request
    join_request = db.query(StudentCourse).filter(
        StudentCourse.id == request_id,
        StudentCourse.course_id == course_id,
        StudentCourse.status == "pending"
    ).first()
    
    if not join_request:
        raise HTTPException(
            status_code=404,
            detail="Request not found or already processed"
        )

    # Update status
    join_request.status = status
    db.commit()
    db.refresh(join_request)

    return {
        "success": True,
        "status": 200,
        "message": f"Request {status} successfully",
        "request": {
            "id": join_request.id,
            "status": join_request.status,
            "course_id": join_request.course_id,
            "student_id": join_request.student_id,
            "created_at": join_request.created_at
        }
    }
