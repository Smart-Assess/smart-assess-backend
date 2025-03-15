# >> Import necessary modules and packages from FastAPI and other libraries
import json
import re
from pydantic import BaseModel
from tempfile import NamedTemporaryFile
from uuid import uuid4
from evaluations.assignment_evaluator import AssignmentEvaluator
from utils.mongodb import mongo_db
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
from utils.dependencies import get_db
from typing import List, Optional
from bestrag import BestRAG
from utils.s3 import delete_from_s3, download_from_s3, upload_to_s3
# from utils.security import get_password_hash
from bson import ObjectId
import json
from fastapi import Body
from evaluations.base_extractor import PDFQuestionAnswerExtractor   
from fastapi import APIRouter, UploadFile, Form, File, HTTPException, Depends
from utils.converter import convert_ppt_to_pdf

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

db_mongo = mongo_db.db

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
    group: str = Form(...),
    section: str = Form(...),
    status: str = Form(...),
    files: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    collection_name = generate_collection_name(current_teacher.id, name)
    new_course = Course(
        name=name,
        batch=batch,
        group=group,
        section=section,
        status=status,
        pdf_urls=json.dumps([]),
        teacher_id=current_teacher.id,
        collection_name=collection_name,
    )
    
    db.add(new_course)
    db.commit()
    db.refresh(new_course)

    rag = get_teacher_rag(collection_name)
    pdf_urls = []

    if files:
        temp_dir = "temp"
        os.makedirs(temp_dir, exist_ok=True)

        for file in files:
            ext = file.filename.split('.')[-1].lower()
            if ext not in ['pdf', 'ppt', 'pptx']:
                raise HTTPException(status_code=400, detail=f"File {file.filename} must be a PDF or PPT")

            file_path = os.path.join(temp_dir, file.filename)
            with open(file_path, "wb") as buffer:
                buffer.write(await file.read())

            
            if ext in ["ppt", "pptx"]:
                converted_pdf_path = convert_ppt_to_pdf(file_path)
                os.remove(file_path)  
                file_path = converted_pdf_path  

           
            pdf_url = upload_to_s3(
                folder_name=f"course_pdfs/{current_teacher.id}",
                file_name=f"{new_course.id}_{os.path.basename(file_path)}",
                file_path=file_path
            )

            if pdf_url:
                try:
                    rag.store_pdf_embeddings(file_path, pdf_url)
                except Exception as e:
                    print(f"Failed to store embeddings: {e}")

                pdf_urls.append(pdf_url)
            else:
                raise HTTPException(status_code=500, detail=f"Failed to upload file {file.filename}")

            os.remove(file_path)  # Clean up the temporary converted PDF

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
    print(course.collection_name)
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
    name: Optional[str] = Form(None),
    batch: Optional[str] = Form(None),
    group: Optional[str] = Form(None),
    section: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    removed_pdfs: Optional[str] = Form(None),  # JSON string of URLs to remove
    pdfs: List[UploadFile] = File([]),  # Default to empty list for optional files
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    """
    Update a course with optional fields:
    - course information (name, batch, group, section, status)
    - new PDF materials to upload
    - existing PDF materials to remove
    
    All fields are optional except course_id.
    """
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()

    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if name is not None: 
        course.name = name.strip()
    if batch is not None: 
        course.batch = batch.strip()
    if group is not None: 
        course.group = group.strip()
    if section is not None: 
        course.section = section.strip()
    if status is not None: 
        course.status = status.strip()
    
    try:
        existing_urls = json.loads(course.pdf_urls) if course.pdf_urls else []
        rag = get_teacher_rag(course.collection_name)
        updated_urls = existing_urls.copy()
        existing_filenames = {url.split("/")[-1].split("_", 1)[-1] for url in existing_urls}
        print(f"Existing Filenames: {existing_filenames}")
        if removed_pdfs:
            removed_pdf_urls = json.loads(removed_pdfs)
            for url in removed_pdf_urls:
                if url in updated_urls:
                    if delete_from_s3(url):
                        try:
                            rag.delete_pdf_embeddings(url)
                        except Exception as e:
                            print(f"Warning: Failed to delete embeddings for {url}: {e}")
                        updated_urls.remove(url)
                    else:
                        print(f"Warning: Failed to delete PDF from S3: {url}")
        
        if pdfs:
            folder_name = f"course_pdfs/{current_teacher.id}"
            
            for pdf in pdfs:
                if not pdf.filename:
                    continue  # Skip empty files
                
                if pdf.content_type != 'application/pdf':
                    raise HTTPException(
                        status_code=400, 
                        detail=f"File {pdf.filename} must be a PDF"
                    )
                
                original_filename, ext = os.path.splitext(pdf.filename.strip())
                filename = f"{original_filename}{ext}"
                counter = 1
                
                while filename in existing_filenames:
                    filename = f"{original_filename} ({counter}){ext}"
                    counter += 1
                
                temp_file = NamedTemporaryFile(delete=False, suffix=ext)
                try:
                    content = await pdf.read()
                    temp_file.write(content)
                    temp_file.close()
                    
                    s3_key = f"{course.id}_{filename}"
                    pdf_url = upload_to_s3(
                        folder_name=folder_name,
                        file_name=s3_key,
                        file_path=temp_file.name
                    )
                    
                    if pdf_url:
                        try:
                            rag.store_pdf_embeddings(temp_file.name, pdf_url)
                        except Exception as e:
                            print(f"Warning: Failed to store embeddings for {pdf_url}: {e}")
                        updated_urls.append(pdf_url)
                        existing_filenames.add(filename)
                    else:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Failed to upload PDF {filename}"
                        )
                finally:
                    if os.path.exists(temp_file.name):
                        os.remove(temp_file.name)
        
        course.pdf_urls = json.dumps(updated_urls)
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
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating course: {str(e)}")
@router.delete("/teacher/course/{course_id}", response_model=dict)
async def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    """
    Delete a course and all its associated resources:
    - Course record in database
    - PDF files in S3 bucket
    - RAG embeddings

    Returns:
        dict: Response with success status and message
    """
    # Find the course to delete
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()

    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        # 1. Delete PDF files from S3
        pdf_urls = json.loads(course.pdf_urls) if course.pdf_urls else []
        deleted_files = []
        failed_files = []
        
        for url in pdf_urls:
            if delete_from_s3(url):
                deleted_files.append(url)
            else:
                failed_files.append(url)

        # 2. Delete RAG embeddings associated with the course
        try:
            rag = get_teacher_rag(course.collection_name)
            # Delete all embeddings associated with this course
            for url in pdf_urls:
                try:
                    rag.delete_pdf_embeddings(url)
                except Exception as e:
                    print(f"Warning: Failed to delete embeddings for {url}: {e}")
        except Exception as e:
            print(f"Warning: Failed to delete RAG collection: {e}")

        # 3. Delete assignments associated with this course
        assignments = db.query(Assignment).filter(Assignment.course_id == course_id).all()
        for assignment in assignments:
            db.delete(assignment)

        # 4. Delete the course record from the database
        db.delete(course)
        db.commit()

        # 5. Return success response with details
        return {
            "success": True,
            "status": 200,
            "message": "Course deleted successfully",
            "details": {
                "course_id": course_id,
                "deleted_files": deleted_files,
                "failed_files": failed_files
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting course: {str(e)}")

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
            pdf_files=[temp_file_path],
            course_id = course_id,
            assignment_id = 0,
            is_teacher = True
        )
        teacher_text = extractor.extract_text_from_pdf(temp_file_path)
        print(teacher_text)
        # for page in teacher_text:
        #     print("Page:::",page)
        parsed_dict= extractor.parse_qa(teacher_text)
        # valid_format = any("Question#" in teacher_text and "Answer#" in teacher_text)
        print("parsed_dict: ",parsed_dict)
        
        
        if not parsed_dict:
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
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    deadline: Optional[str] = Form(None),  # Format: "YYYY-MM-DD HH:MM"
    grade: Optional[int] = Form(None),
    question_pdf: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    """
    Update an assignment with optional fields:
    - Basic information (name, description, deadline, grade)
    - Question PDF file
    
    All fields are optional except course_id and assignment_id.
    """
    # First, verify course exists and belongs to the teacher
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.teacher_id == current_teacher.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found or you don't have access"
        )
    
    # Find the assignment
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.course_id == course_id
    ).first()
    
    if not assignment:
        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )
    
    # Update basic assignment information if provided
    if name is not None:
        assignment.name = name
    
    if description is not None:
        assignment.description = description
    
    if deadline is not None:
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
            assignment.deadline = deadline_dt
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid deadline format. Use 'YYYY-MM-DD HH:MM'."
            )
    
    if grade is not None:
        assignment.grade = grade
    
    # Handle question PDF update if provided
    if question_pdf:
        # Validate PDF
        if question_pdf.content_type != 'application/pdf':
            raise HTTPException(
                status_code=400,
                detail="Question file must be a PDF"
            )
        
        temp_file_path = None
        try:
            # Save uploaded PDF to temp file
            with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                content = await question_pdf.read()
                temp_file.write(content)
                temp_file_path = temp_file.name
            
            # Validate the format of the question PDF
            extractor = PDFQuestionAnswerExtractor(
                pdf_files=[temp_file_path],
                course_id=course_id,
                assignment_id=assignment_id,
                is_teacher=True
            )
            teacher_text = extractor.extract_text_from_pdf(temp_file_path)
            parsed_dict = extractor.parse_qa(teacher_text)
            
            if not parsed_dict:
                raise HTTPException(
                    status_code=400,
                    detail="Assignment PDF is not in the correct format. It must contain 'Question#' and 'Answer#'."
                )
            
            # Delete old PDF from S3 if it exists
            if assignment.question_pdf_url:
                delete_success = delete_from_s3(assignment.question_pdf_url)
                if not delete_success:
                    print(f"Warning: Failed to delete old PDF from S3: {assignment.question_pdf_url}")
            
            # Upload new PDF to S3
            safe_course_name = sanitize_folder_name(course.name)
            s3_url = upload_to_s3(
                folder_name=f"course_assignments/{current_teacher.id}/{safe_course_name}",
                file_name=f"{assignment_id}_{question_pdf.filename}",
                file_path=temp_file_path
            )
            
            if not s3_url:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to upload question PDF"
                )
            
            # Update assignment with new PDF URL
            assignment.question_pdf_url = s3_url
            
        finally:
            # Clean up temp file
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    
    # Commit changes to database
    try:
        db.commit()
        db.refresh(assignment)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update assignment: {str(e)}"
        )
    
    # Return updated assignment
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
            "question_pdf_url": assignment.question_pdf_url
        }
    }



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

        # Get submissions
        submissions = db.query(AssignmentSubmission)\
            .filter(AssignmentSubmission.assignment_id == assignment_id)\
            .all()

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

            # Download student submissions
            submission_paths = {}
            submission_ids = []
            for submission in submissions:
                temp_file = NamedTemporaryFile(delete=False, suffix='.pdf', mode='wb')
                if not download_from_s3(submission.submission_pdf_url, temp_file.name):
                    print(f"Failed to download submission {submission.id}")
                    continue
                temp_file.close()
                
                if os.path.getsize(temp_file.name) > 0:
                    submission_paths[submission.id] = temp_file.name
                    submission_ids.append(submission.id)
                    temp_files.append(temp_file.name)

            # Create a list of all PDF files (teacher + student submissions)
            pdf_files = [teacher_pdf_path] + list(submission_paths.values())

            # Initialize AssignmentEvaluator
            evaluator = AssignmentEvaluator(course_id=course_id, assignment_id=assignment_id, request=request, rag=rag, db=db)
            evaluator.run(pdf_files=pdf_files, total_grade=assignment.grade, submission_ids=submission_ids)

            # Collect evaluation results
            for submission in submissions:
                submission_data = mongo_db.db['evaluation_results'].find_one({
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "pdf_file": submission.submission_pdf_url
                })

                if submission_data:
                    student = db.query(Student).filter(Student.id == submission.student_id).first()
                    evaluation_results.append({
                        "name": student.full_name,
                        "batch": student.batch,
                        "department": student.department,
                        "section": student.section,
                        "total_score": submission_data.get("overall_scores", {}).get("total", {}).get("score", 0),
                        "avg_context_score": submission_data.get("overall_scores", {}).get("context", {}).get("score", 0),
                        "avg_plagiarism_score": submission_data.get("overall_scores", {}).get("plagiarism", {}).get("score", 0),
                        "image": student.image_url
                    })

        finally:
            # Cleanup temp files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                except Exception as e:
                    print(f"Failed to delete temp file {temp_file}: {e}")

    except Exception as e:
        print(f"Evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")

    print("Evaluation completed", evaluation_results)
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
                    "section": student.section,
                    "image": student.image_url,
                    "total_score": submission_data.get("total_score", 0.0),
                    "avg_context_score": 0.0,
                    "avg_plagiarism_score": 0.0
                }

                # Calculate average context score and average plagiarism score
                if "questions" in submission_data:
                    total_context_score = 0.0
                    total_plagiarism_score = 0.0
                    num_questions = len(submission_data["questions"])

                    for question in submission_data["questions"]:
                        total_context_score += question.get("context_score", 0.0)
                        total_plagiarism_score += question.get("plagiarism_score", 0.0)

                    if num_questions > 0:
                        scores["avg_context_score"] = round(total_context_score / num_questions, 4)
                        scores["avg_plagiarism_score"] = round(total_plagiarism_score / num_questions, 4)

                total_scores_data.append(scores)

        return {
            "success": True,
            "status": 200,
            "total_scores": total_scores_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch scores: {str(e)}")