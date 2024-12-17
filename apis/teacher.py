# >> Import necessary modules and packages from FastAPI and other libraries
import json
import re
from tempfile import NamedTemporaryFile
from uuid import uuid4
from pymongo import MongoClient
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
from models.pydantic_model import EvaluationRequest
from utils.assingment_score import AssignmentScoreCalculator
from utils.context_score import SubmissionScorer
from utils.dependencies import get_db
from typing import List, Optional
from bestrag import BestRAG
from utils.plagiarism import PDFQuestionAnswerExtractor
from utils.s3 import delete_from_s3, download_from_s3, upload_to_s3
# from utils.security import get_password_hash
from bson import ObjectId
import json

class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)

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

def sanitize_folder_name(name: str) -> str:
    """Replace spaces and special characters in folder names"""
    return name.replace(' ', '_').strip()

router = APIRouter()

@router.post("/teacher/course", response_model=dict)
async def create_course(
    name: str = Form(...),
    batch: str = Form(...),
    group: Optional[str] = None,
    section: str = Form(...),
    status: str = Form(...),
    pdfs: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    # Step 1: Create the course without the PDF URLs
    collection_name = generate_collection_name(current_teacher.id, name)
    new_course = Course(
        name=name,
        batch=batch,
        group=group,
        section=section,
        status=status,
        pdf_urls=json.dumps([]),  # Temporary empty list
        teacher_id=current_teacher.id,
        collection_name=collection_name,
    )
    db.add(new_course)
    db.commit()
    db.refresh(new_course)  # Get the course ID after saving

    rag = get_teacher_rag(collection_name)
    pdf_urls = []

    # Step 2: Process the PDFs and upload them with course ID
    if pdfs:
        for pdf in pdfs:
            if not pdf.content_type == 'application/pdf':
                raise HTTPException(
                    status_code=400,
                    detail=f"File {pdf.filename} must be a PDF"
                )
            
            pdf_path = os.path.join("temp", pdf.filename)
            try:
                with open(pdf_path, "wb") as buffer:
                    os.makedirs("temp", exist_ok=True)
                    buffer.write(await pdf.read())
                
                # Include course ID in the folder or file name for uniqueness
                pdf_url = upload_to_s3(
                    folder_name=f"course_pdfs/{current_teacher.id}",
                    file_name=f"{new_course.id}_{pdf.filename}",  # Add course ID to file name
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

    # Step 3: Update the course record with the PDF URLs
    new_course.pdf_urls = json.dumps(pdf_urls)
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
@router.get("/teacher/courses", response_model=dict)
async def get_teacher_courses(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    # Calculate offset for pagination
    offset = (page - 1) * limit
    
    # Get total count of courses
    total = db.query(Course)\
        .filter(Course.teacher_id == current_teacher.id)\
        .count()

    # Get paginated courses
    courses = db.query(Course)\
        .filter(Course.teacher_id == current_teacher.id)\
        .order_by(Course.created_at.desc())\
        .offset(offset)\
        .limit(limit)\
        .all()
    
    # Format course data
    courses_data = [
        {
            "id": course.id,
            "name": course.name,
            "batch": course.batch,
            "group": course.group,
            "section": course.section,
            "course_code": course.course_code,
            "status": course.status,
            "created_at": course.created_at.strftime("%Y-%m-%d %H:%M")
        }
        for course in courses
    ]

    return {
        "success": True,
        "status": 200,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "courses": courses_data,
        "has_previous": page > 1,
        "has_next": (offset + limit) < total
    }


@router.put("/teacher/course/{course_id}", response_model=dict)
async def update_course(
    course_id: int,
    name: str = None,
    batch: str = None,
    group: str = None,
    section: str = None,
    status: str = None,
    pdfs: Optional[List[UploadFile]] = None,
    removed_pdfs: str = None,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Update fields only if non-empty strings provided
    if name is not None and name.strip(): course.name = name
    if batch is not None and batch.strip(): course.batch = batch 
    if group is not None and group.strip(): course.group = group
    if section is not None and section.strip(): course.section = section
    if status is not None and status.strip(): course.status = status

    try:
        # Handle PDF uploads if files provided
        if pdfs:
            existing_urls = json.loads(course.pdf_urls)
            rag = get_teacher_rag(course.collection_name)
            folder_name = f"course_pdfs/{current_teacher.id}/{course.name}"
            
            for pdf in pdfs:
                if not pdf.filename:
                    continue
                    
                if not pdf.content_type == 'application/pdf':
                    raise HTTPException(status_code=400, detail="File must be PDF")
                    
                with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    os.makedirs("temp", exist_ok=True)
                    content = await pdf.read()
                    temp_file.write(content)
                    temp_file_path = temp_file.name

                try:
                    pdf_url = upload_to_s3(
                        folder_name=folder_name,
                        file_name=pdf.filename,
                        file_path=temp_file_path
                    )
                    if pdf_url:
                        rag.store_pdf_embeddings(temp_file_path, pdf_url)
                        existing_urls.append(pdf_url)
                finally:
                    os.unlink(temp_file_path)
                    
            course.pdf_urls = json.dumps(existing_urls)

        # Handle PDF removals if URLs provided
        if removed_pdfs is not None and removed_pdfs.strip():
            try:
                removed_urls = json.loads(removed_pdfs)
                existing_urls = json.loads(course.pdf_urls)
                rag = get_teacher_rag(course.collection_name)
                
                for url in removed_urls:
                    if url in existing_urls:
                        if delete_from_s3(url):
                            rag.delete_pdf_embeddings(url)
                            existing_urls.remove(url)
                            
                course.pdf_urls = json.dumps(existing_urls)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid removed_pdfs format")

        db.commit()
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/teacher/assignments", response_model=dict)
async def get_teacher_assignments(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    offset = (page - 1) * limit
    
    try:
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
                "description": assignment.description,
                "batch": course.batch,
                "department": course.group,
                "section": course.section,
                "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
                "grade": assignment.grade,
                "course_id": course.id,
                "course_name": course.name
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/teacher/course/{course_id}/assignments", response_model=dict)
async def get_course_assignments(
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
    
    assignments = db.query(Assignment).filter(
        Assignment.course_id == course_id
    ).order_by(Assignment.created_at.desc()).all()
    
    assignments_data = []
    for assignment in assignments:
        assignments_data.append({
            "id": assignment.id,
            "name": assignment.name,
            "description": assignment.description,
            "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
            "grade": assignment.grade,
            "question_pdf_url": assignment.question_pdf_url,
            "created_at": assignment.created_at.strftime("%Y-%m-%d %H:%M")
        })

    return {
        "success": True,
        "status": 200,
        "assignments": assignments_data
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
    if question_pdf.content_type != 'application/pdf':
        raise HTTPException(
            status_code=400,
            detail="Question file must be a PDF"
        )

    # Parse the deadline string into a datetime object
    try:
        deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid deadline format. Use 'YYYY-MM-DD HH:MM'."
        )

    try:
        with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            os.makedirs("temp", exist_ok=True)
            content = await question_pdf.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        # Validate the format of the question PDF
        extractor = PDFQuestionAnswerExtractor(
            pdf_files=[],
            teacher_pdf=temp_file_path,
            course_id=course_id,
            assignment_id=0  # Dummy assignment ID for validation
        )
        teacher_text = extractor.extract_text_from_pdf(temp_file_path)
        valid_format = any("Question#" in page and "Answer#" in page for page in teacher_text)
        
        if not valid_format:
            raise HTTPException(
                status_code=400,
                detail="Assignment PDF is not in the correct format. It must contain 'Question#' and 'Answer#'."
            )

        # Sanitize and upload PDF to S3
        safe_course_name = sanitize_folder_name(course.name)
        s3_url = upload_to_s3(
            folder_name=f"course_assignments/{current_teacher.id}/{safe_course_name}",
            file_name=question_pdf.filename,
            file_path=temp_file_path
        )

        if not s3_url:
            raise HTTPException(
                status_code=500,
                detail="Failed to upload question PDF"
            )

        # Create new assignment in SQL database
        new_assignment = Assignment(
            course_id=course_id,
            name=name,
            description=description,
            deadline=deadline_dt,
            grade=grade,
            question_pdf_url=s3_url
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
                "question_pdf_url": new_assignment.question_pdf_url
            }
        }

    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@router.put("/teacher/course/{course_id}/assignment/{assignment_id}", response_model=dict)
async def update_assignment(
    course_id: int,
    assignment_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    deadline: Optional[str] = None, # YYYY-MM-DD HH:MM
    grade: Optional[int] = None,
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
    if question_pdf and not isinstance(question_pdf, str):
        if question_pdf.content_type != 'application/pdf':
            raise HTTPException(
                status_code=400,
                detail="Question file must be a PDF"
            )

        try:
            # Create temporary file for PDF extraction
            with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                content = await question_pdf.read()
                temp_file.write(content)
                temp_file_path = temp_file.name

            # Validate the format of the question PDF
            extractor = PDFQuestionAnswerExtractor(
                pdf_files=[],
                teacher_pdf=temp_file_path,
                course_id=course_id,
                assignment_id=assignment_id
            )
            teacher_text = extractor.extract_text_from_pdf(temp_file_path)
            valid_format = any("Question#" in page and "Answer#" in page for page in teacher_text)
            
            if not valid_format:
                raise HTTPException(
                    status_code=400,
                    detail="Assignment PDF is not in the correct format. It must contain 'Question#' and 'Answer#'."
                )

            # Delete old PDF from S3
            if assignment.question_pdf_url:
                delete_success = delete_from_s3(assignment.question_pdf_url)
                if not delete_success:
                    print(f"Failed to delete old PDF: {assignment.question_pdf_url}")

            # Upload new PDF to S3
            safe_course_name = sanitize_folder_name(course.name)
            pdf_url = upload_to_s3(
                folder_name=f"course_assignments/{current_teacher.id}/{safe_course_name}",
                file_name=question_pdf.filename,
                file_path=temp_file_path
            )

            if not pdf_url:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to upload question PDF"
                )

            # Update assignment PDF URL
            assignment.question_pdf_url = pdf_url

            # Cleanup temporary file
            os.unlink(temp_file_path)

        except Exception as e:
            if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process PDF: {str(e)}"
            )

    # Update other fields
    if deadline:
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
            assignment.deadline = deadline_dt
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid deadline format. Use YYYY-MM-DD HH:MM"
            )

    if name:
        assignment.name = name

    if description:
        assignment.description = description

    if grade is not None:
        if grade > 0:
            assignment.grade = grade
        else:
            raise HTTPException(
                status_code=400,
                detail="Grade must be a positive integer"
            )

    try:
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
                "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M") if assignment.deadline else None,
                "grade": assignment.grade,
                "question_pdf_url": assignment.question_pdf_url,
                "course_id": assignment.course_id,
                "created_at": assignment.created_at
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update assignment: {str(e)}"
        )


@router.get("/teacher/course/{course_id}/assignment/{assignment_id}", response_model=dict)
async def get_assignment(
    course_id: int,
    assignment_id: int,
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

    deadline_str = assignment.deadline.strftime("%Y-%m-%d %H:%M")
    deadline_date = assignment.deadline.strftime("%Y-%m-%d")
    deadline_time = assignment.deadline.strftime("%H:%M")

    return {
        "success": True,
        "status": 200,
        "assignment": {
            "id": assignment.id,
            "name": assignment.name,
            "description": assignment.description,
            "deadline": deadline_str,
            "deadline_date": deadline_date,
            "deadline_time": deadline_time,
            "grade": assignment.grade,
            "question_pdf_url": assignment.question_pdf_url,
            "course_id": assignment.course_id,
            "course_name": course.name,
            "created_at": assignment.created_at.strftime("%Y-%m-%d %H:%M")
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
                "department":student.department,
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

@router.get("/teacher/course/{course_id}/assignment/{assignment_id}/submissions", response_model=dict)
async def get_assignment_submissions(
    course_id: int,
    assignment_id: int,
    page: int = 1,
    limit: int = 10,
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
            detail="Assignment not found or you don't have access"
        )

    offset = (page - 1) * limit

    total = db.query(AssignmentSubmission)\
        .join(Student)\
        .filter(AssignmentSubmission.assignment_id == assignment_id)\
        .count()

    submissions = db.query(
        AssignmentSubmission,
        Student
    ).join(
        Student
    ).filter(
        AssignmentSubmission.assignment_id == assignment_id
    ).order_by(
        AssignmentSubmission.submitted_at.desc()
    ).offset(offset).limit(limit).all()

    submissions_data = []
    for submission, student in submissions:
        submissions_data.append({
            "submission_id": submission.id,
            "student": {
                "id": student.id,
                "student_id": student.student_id,
                "name": student.full_name,
                "batch": student.batch,
                "department": student.department,
                "section": student.section,
            },
            "submitted_at": submission.submitted_at.strftime("%I:%M %p - %d/%b/%Y"),
            "pdf_url": submission.submission_pdf_url
        })

    return {
        "success": True,
        "status": 200,
        "assignment_id": assignment_id,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "submissions": submissions_data,
        "has_previous": page > 1,
        "has_next": (offset + limit) < total
    }
    

@router.post("/teacher/{course_id}/assignment/{assignment_id}/evaluate", response_model=dict)
async def evaluate_submissions(
    course_id: int,
    assignment_id: int,
    request: EvaluationRequest,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    client = MongoClient(os.getenv("MONGO_URI"))
    db_mongo = client['FYP']
    evaluation_results = []
    temp_files = []

    try:
        # Verify assignment and course
        assignment = db.query(Assignment)\
            .join(Course)\
            .filter(
                Assignment.id == assignment_id,
                Course.teacher_id == current_teacher.id
            ).first()
        
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found or no access")

        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")

        # Get all submissions
        submissions = db.query(AssignmentSubmission).filter(
            AssignmentSubmission.assignment_id == assignment_id
        ).all()

        if not submissions:
            raise HTTPException(status_code=404, detail="No submissions found")

        # Initialize RAG
        rag = get_teacher_rag(course.collection_name)

        try:
            # Download teacher PDF
            teacher_temp_file = NamedTemporaryFile(delete=False, suffix='.pdf', mode='wb')
            if not download_from_s3(assignment.question_pdf_url, teacher_temp_file.name):
                raise HTTPException(status_code=500, detail="Failed to download teacher PDF")
            teacher_temp_file.close()
            temp_files.append(teacher_temp_file.name)
            teacher_pdf_path = teacher_temp_file.name

            # Verify teacher PDF
            if os.path.getsize(teacher_pdf_path) == 0:
                raise HTTPException(status_code=500, detail="Teacher PDF is empty")

            # Download student submissions
            submission_paths = {}
            for submission in submissions:
                temp_file = NamedTemporaryFile(delete=False, suffix='.pdf', mode='wb')
                if not download_from_s3(submission.submission_pdf_url, temp_file.name):
                    continue
                temp_file.close()
                
                if os.path.getsize(temp_file.name) > 0:
                    submission_paths[submission.id] = temp_file.name
                    temp_files.append(temp_file.name)

            # Process each submission
            for submission in submissions:
                if submission.id not in submission_paths:
                    continue

                submission_pdf_path = submission_paths[submission.id]

                # 1. Extract QA pairs
                base_extractor = PDFQuestionAnswerExtractor(
                    pdf_files=[submission_pdf_path],
                    teacher_pdf=teacher_pdf_path,
                    course_id=course_id,
                    assignment_id=assignment_id,
                    student_id=submission.student_id
                )
                qa_results = base_extractor.extract_qa_only()
                question_results = {}

                # 2. Run Plagiarism Detection
                if request.enable_plagiarism:
                    other_paths = [
                        path for sid, path in submission_paths.items() 
                        if sid != submission.id
                    ]
                    
                    if other_paths:
                        plagiarism_detector = PDFQuestionAnswerExtractor(
                            pdf_files=[submission_pdf_path] + other_paths,
                            teacher_pdf=teacher_pdf_path,
                            course_id=course_id,
                            assignment_id=assignment_id,
                            student_id=submission.student_id
                        )
                        plagiarism_results = plagiarism_detector.run()
                        
                        for result in plagiarism_results["results"]:
                            if str(submission.student_id) == str(result["student_id"]):
                                question_results.update(result["question_results"])
                                break

                # 3. Run Context Scoring
                context_scorer = SubmissionScorer(rag)
                context_scores = context_scorer.calculate_scores(
                    course_id=course_id,
                    assignment_id=assignment_id,
                    student_id=submission.student_id,
                    qa_results=qa_results
                )
                
                # Merge context scores
                if context_scores:
                    for result in context_scores:
                        for q_key, scores in result["question_results"].items():
                            if q_key in question_results:
                                question_results[q_key]["context_score"] = scores["context_score"]
                            else:
                                question_results[q_key] = scores

                # 4. Calculate Final Grades
                question_count = len([k for k in question_results.keys() if k.startswith("Question#")])
                score_calculator = AssignmentScoreCalculator(
                    total_grade=assignment.grade,
                    num_questions=question_count,
                    db=db
                )

                final_evaluation = score_calculator.calculate_submission_evaluation(
                    submission_id=submission.id,
                    course_id=course_id,
                    assignment_id=assignment_id,
                    student_id=submission.student_id,
                    question_results=question_results,
                    enabled_components={
                        'context': True,
                        'plagiarism': request.enable_plagiarism,
                        'ai_detection': request.enable_ai_detection,
                        'grammar': request.enable_grammar
                    }
                )

                # Clean question results
                cleaned_question_results = {
                    q_key: {
                        k: v for k, v in result.items() 
                        if v is not None and v != 0
                    }
                    for q_key, result in question_results.items()
                    if any(v is not None and v != 0 for v in result.values())
                }

                # Save to MongoDB
                mongo_doc = {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "student_id": submission.student_id,
                    "PDF_File": submission.submission_pdf_url,
                    "QA_Results": qa_results,
                    "questions": final_evaluation.get("questions", []),
                    "submission_id": submission.id,
                    "total_score": final_evaluation.get("total_score"),
                    "submitted_at": datetime.utcnow(),
                    "question_results": cleaned_question_results
                }

                db_mongo.submissions.update_one(
                    {
                        "course_id": course_id,
                        "assignment_id": assignment_id,
                        "student_id": submission.student_id,
                        "PDF_File": submission.submission_pdf_url
                    },
                    {"$set": mongo_doc},
                    upsert=True
                )

                evaluation_results.append(final_evaluation)

        finally:
            # Cleanup temp files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                except Exception as e:
                    print(f"Failed to delete temp file {temp_file}: {e}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")
    
    finally:
        client.close()

    return {
        "success": True,
        "status": 200,
        "message": f"Evaluated {len(evaluation_results)} submissions successfully",
        "results": evaluation_results
    }

@router.get("/teacher/course/{course_id}/assignment/{assignment_id}/submission/{submission_id}", response_model=dict)
async def get_submission_details(
    course_id: int,
    assignment_id: int,
    submission_id: int,
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

    submission = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.id == submission_id,
        AssignmentSubmission.assignment_id == assignment_id
    ).first()

    if not submission:
        raise HTTPException(
            status_code=404,
            detail="Submission not found"
        )

    # Fetch submission details from MongoDB
    client = MongoClient(os.getenv("MONGO_URI"))
    db_mongo = client['FYP']
    
    # Check both submissions and assignment_evaluations collections
    submission_data = None
    
    # First check submissions collection
    submission_data = db_mongo.submissions.find_one({
        "course_id": course_id,
        "assignment_id": assignment_id,
        "student_id": submission.student_id,
        "PDF_File": submission.submission_pdf_url
    })

    if not submission_data:
        # Try assignment_evaluations collection
        submission_data = db_mongo.assignment_evaluations.find_one({
            "course_id": course_id,
            "assignment_id": assignment_id,
            "student_id": submission.student_id,
            "submission_id": submission_id
        })

    if not submission_data:
        raise HTTPException(
            status_code=404,
            detail="Submission details not found in MongoDB"
        )

    # Convert MongoDB document to serializable format
    serializable_data = json.loads(json.dumps(submission_data, cls=JSONEncoder))

    return {
        "success": True,
        "status": 200,
        "submission": serializable_data
    }


@router.get("/teacher/course/{course_id}/assignment/{assignment_id}/total-scores", response_model=dict)
async def get_total_scores(
    course_id: int,
    assignment_id: int,
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

    submissions = db.query(AssignmentSubmission, Student).join(Student).filter(
        AssignmentSubmission.assignment_id == assignment_id
    ).all()

    # Initialize MongoDB connection
    client = MongoClient(os.getenv("MONGO_URI"))
    db_mongo = client['FYP']
    
    try:
        total_scores_data = []
        for submission, student in submissions:
            submission_data = db_mongo.submissions.find_one({
                "course_id": course_id,
                "assignment_id": assignment_id,
                "student_id": submission.student_id,
                "PDF_File": submission.submission_pdf_url
            })

            if submission_data:
                # Clean up scores data
                scores = {
                    "student_id": student.student_id,
                    "name": student.full_name,
                    "batch": student.batch,
                    "department": student.department,
                    "section": student.section
                }

                # Add non-null scores from MongoDB
                for score_type in ["total_score", "plagiarism_score", "contextual_score", "ai_score", "grammar_score"]:
                    if submission_data.get(score_type) is not None:
                        scores[score_type] = submission_data[score_type]

                # Add component scores from questions if available
                if "questions" in submission_data:
                    component_scores = {}
                    for question in submission_data["questions"]:
                        if "component_scores" in question:
                            for comp, score in question["component_scores"].items():
                                if score != 0 and score is not None:
                                    if comp not in component_scores:
                                        component_scores[comp] = []
                                    component_scores[comp].append(score)
                    
                    # Calculate averages for component scores
                    for comp, scores_list in component_scores.items():
                        if scores_list:
                            scores[f"avg_{comp}_score"] = round(sum(scores_list) / len(scores_list), 4)

                total_scores_data.append(scores)

        # Convert MongoDB ObjectIds to strings
        serializable_data = json.loads(json.dumps(total_scores_data, cls=JSONEncoder))

        return {
            "success": True,
            "status": 200,
            "total_scores": serializable_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch scores: {str(e)}")
    
    finally:
        client.close()