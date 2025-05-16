# >> Import necessary modules and packages from FastAPI and other libraries
import json
import re
from tempfile import NamedTemporaryFile
from uuid import uuid4
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
from utils.dependencies import get_db
from typing import List, Optional
from bestrag import BestRAG
from utils.s3 import delete_from_s3, upload_to_s3
# from utils.security import get_password_hash
from bson import ObjectId
import json
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
            api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.11FasiHP2CCIpFT4rQ2dWpLLQBedlDAGjd2fuWYpDzM",
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
    # Define max file size
    MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB per file
    
    # Validate file sizes if files are provided
    if files:
        for file in files:
            # Check file size
            contents = await file.read()
            file_size = len(contents)
            
            if file_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File {file.filename} exceeds the size limit of 15MB"
                )
            
            # Reset file position for later processing
            await file.seek(0)
    
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
                
                ext = pdf.filename.split('.')[-1].lower()
                if ext not in ['pdf', 'ppt', 'pptx']:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"File {pdf.filename} must be a PDF or PPT"
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
                    
                    file_path = temp_file.name
                    # Convert PPT/PPTX to PDF if needed
                    if ext.lower() in ['.ppt', '.pptx']:
                        converted_pdf_path = convert_ppt_to_pdf(file_path)
                        os.remove(file_path)  
                        file_path = converted_pdf_path
                        filename = f"{original_filename}.pdf"  # Update filename to .pdf
                    
                    s3_key = f"{course.id}_{filename}"
                    pdf_url = upload_to_s3(
                        folder_name=folder_name,
                        file_name=s3_key,
                        file_path=file_path
                    )
                    
                    if pdf_url:
                        try:
                            rag.store_pdf_embeddings(file_path, pdf_url)
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
