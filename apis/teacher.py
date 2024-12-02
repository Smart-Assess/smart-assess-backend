# >> Import necessary modules and packages from FastAPI and other libraries
import json
import re
from tempfile import NamedTemporaryFile
from uuid import uuid4
from pymongo import MongoClient
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
from utils.plagrism import PDFQuestionAnswerExtractor
from utils.s3 import delete_from_s3, upload_to_s3
from utils.clean_text import clean_and_tokenize_text
from utils.bleurt.bleurt.score import BleurtScorer
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
        try:
            removed_urls = json.loads(removed_pdfs)
        except json.JSONDecodeError:
            removed_urls = [url.strip() for url in removed_pdfs.split(',') if url.strip()]
            print(removed_urls)
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

    try:
        with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            content = await question_pdf.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        # Create new assignment in SQL database
        new_assignment = Assignment(
            course_id=course_id,
            name=name,
            description=description,
            deadline=deadline,
            grade=grade
        )
        db.add(new_assignment)
        db.flush()

        pdf_extractor = PDFQuestionAnswerExtractor(
            pdf_files=[temp_file_path],
            role="teacher",
            assignment_id=new_assignment.id
        )
        pdf_extractor.run()
        pdf_extractor.save_results_to_mongo()

        db.commit()

        os.unlink(temp_file_path)

        return {
            "success": True,
            "status": 201,
            "message": "Assignment created successfully",
            "assignment": {
            "id": new_assignment.id,
            "name": new_assignment.name,
            "description": new_assignment.description,
            "deadline": new_assignment.deadline.strftime("%Y-%m-%d %H:%M"),
            "grade": new_assignment.grade,
            "question_pdf_url": new_assignment.question_pdf_url,
            "course_id": new_assignment.course_id,
            "created_at": new_assignment.created_at,
        },
        }

    except Exception as e:
        db.rollback()
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create assignment: {str(e)}"
        )
    
@router.put("/teacher/course/{course_id}/assignment/{assignment_id}", response_model=dict)
async def update_assignment(
    course_id: int,
    assignment_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    deadline: Optional[str] = Form(None),
    grade: Optional[str] = Form(None),
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

        try:
            # Create temporary file for PDF extraction
            with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                content = await question_pdf.read()
                temp_file.write(content)
                temp_file_path = temp_file.name

            # Process PDF for Q&A extraction
            pdf_extractor = PDFQuestionAnswerExtractor(
                pdf_files=[temp_file_path],
                role="teacher",
                assignment_id=assignment_id
            )
            pdf_extractor.run()
            pdf_extractor.save_results_to_mongo()

            # Delete old PDF from S3
            if assignment.question_pdf_url:
                delete_success = delete_from_s3(assignment.question_pdf_url)
                if not delete_success:
                    print(f"Failed to delete old PDF: {assignment.question_pdf_url}")

            # Upload new PDF to S3
            pdf_url = upload_to_s3(
                folder_name=f"course_assignments/{current_teacher.id}/{course.name}",
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

    if name: assignment.name = name
    if description: assignment.description = description
    if grade is not None:
        if grade.strip():  # Check if grade is not empty string
            try:
                grade_int = int(grade)
                if grade_int <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Grade must be a positive integer"
                    )
                assignment.grade = grade_int
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Grade must be a valid integer"
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
                "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
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

    return {
        "success": True,
        "status": 200,
        "assignment": {
            "id": assignment.id,
            "name": assignment.name,
            "description": assignment.description,
            "deadline": assignment.deadline.strftime("%I%p %d/%b/%Y"),
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

@router.get("/teacher/assignment/{assignment_id}/submissions", response_model=dict)
async def get_assignment_submissions(
    assignment_id: int,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin)
):
    assignment = db.query(Assignment)\
        .join(Course)\
        .filter(
            Assignment.id == assignment_id,
            Course.teacher_id == current_teacher.id
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
    submission_ids: List[int] = Form(...),
    enable_plagiarism: bool = Form(False),
    enable_ai_detection: bool = Form(False), 
    enable_grammar: bool = Form(False),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
    
):
    # Verify assignment and get course
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

    rag = get_teacher_rag(course.collection_name)
    scorer = BleurtScorer()
    evaluation_results = []

    # Get MongoDB connection
    mongo_client = MongoClient("mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority")
    mongo_db = mongo_client['FYP']

    # Process each submission
    for submission_id in submission_ids:
        submission = db.query(AssignmentSubmission).filter_by(id=submission_id).first()
        if not submission:
            continue

        submission_result = {
            "submission_id": submission_id,
            "student_id": submission.student_id,
            "scores": {},
            "question_grades": {},
            "plagiarism": {
                "overall_similarity": 0,
                "per_question": {}
            }
        }

        # Run plagiarism detection using PDFQuestionAnswerExtractor
        if enable_plagiarism:
            pdf_extractor = PDFQuestionAnswerExtractor(
                pdf_files=[submission.submission_pdf_url],
                role="student",
                student_id=submission.student_id,
                assignment_id=assignment_id
            )
            pdf_extractor.run()
            pdf_extractor.compare_answers()
            
            plagiarism_data = pdf_extractor.get_plagiarism_results()
            print("Plagiarism_data",plagiarism_data)
            total_similarity = 0
            question_count = 0
            
            for q_key, result in plagiarism_data.items():
                if q_key.startswith("Question#"):
                    avg_similarity = sum(c["similarity"] for c in result["Comparisons"].values()) / len(result["Comparisons"]) if result["Comparisons"] else 0
                    submission_result["plagiarism"]["per_question"][q_key] = {
                        "similarity": avg_similarity,
                        "status": "Similar" if avg_similarity >= 0.8 else "Not Similar"
                    }
                    total_similarity += avg_similarity
                    question_count += 1
            
            submission_result["plagiarism"]["overall_similarity"] = total_similarity / question_count if question_count > 0 else 0
            print("Submission_results",submission_result)
            student_answers = mongo_db.submissions.find_one({
                    "assignment_id": assignment_id,
                    "student_id": submission.student_id
                })
            print("Student_answers",student_answers)
            if student_answers:
                total_score = 0
                question_count = len([k for k in student_answers.get("QA_Results", {}).keys() if k.startswith("Question#")])
                points_per_question = assignment.grade / question_count if question_count > 0 else 0
                
                for q_key, student_question in student_answers.get("QA_Results", {}).items():
                    if not q_key.startswith("Question#"):
                        continue
                        
                    ans_key = f"Answer#{q_key.split('#')[1]}"
                    student_answer = student_answers["QA_Results"].get(ans_key, "")
                    
                    if student_answer:
                        rag_results = rag.search(student_question)
                        if rag_results:
                            clean_reference = clean_and_tokenize_text(rag_results)
                            score = scorer.score(
                                references=[clean_reference], 
                                candidates=[student_answer]
                            )[0]
                            
                            submission_result["scores"][q_key] = score
                            # Calculate actual grade for this question
                            question_grade = score * points_per_question
                            submission_result["question_grades"][q_key] = question_grade
                            total_score += question_grade

                submission_result["total_grade"] = total_score
                print("Submision_results",submission_result)
                    
            # Store evaluation
            eval_result = AssignmentEvaluation(
                submission_id=submission_id,
                total_score=total_score,
                plagiarism_score=submission_result["plagiarism"]["overall_similarity"] if enable_plagiarism else None,
                ai_detection_score=None,
                grammar_score=None,
                feedback=f"Total Grade: {total_score:.2f}/{assignment.grade}"
            )
            
            db.add(eval_result)
            evaluation_results.append(submission_result)

    try:
        db.commit()
        return {
            "success": True,
            "status": 200,
            "message": "Evaluation completed",
            "results": evaluation_results
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to store evaluation results: {str(e)}")