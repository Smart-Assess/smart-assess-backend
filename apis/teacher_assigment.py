
# >> Import necessary modules and packages from FastAPI and other libraries
import json
from tempfile import NamedTemporaryFile
import time
from evaluations.assignment_evaluator import AssignmentEvaluator
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
from typing import Optional
from utils.s3 import delete_from_s3, download_from_s3, upload_to_s3
from apis.teacher_course import sanitize_folder_name, get_teacher_rag, db_mongo, JSONEncoder
import json
from evaluations.base_extractor import PDFQuestionAnswerExtractor   
from fastapi import APIRouter, UploadFile, Form, File, HTTPException, Depends


import os
from dotenv import load_dotenv

load_dotenv()

# >> Define the router for the API

router = APIRouter()

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

            request_dict = request.dict()
            request_dict["grammar_delay"] = 0.5
            request_dict["ai_detection_delay"] = 1.0
            modified_request = EvaluationRequest(**request_dict)
            
            # Initialize AssignmentEvaluator with modified request
            evaluator = AssignmentEvaluator(
                course_id=course_id, 
                assignment_id=assignment_id, 
                request=modified_request, 
                rag=rag, 
                db=db
            )
            
            # Print evaluation configuration for debugging
            print(f"Evaluation configuration: AI detection: {request.enable_ai_detection}, Grammar: {request.enable_grammar}, Plagiarism: {request.enable_plagiarism}")
            print(f"Rate limiting: Grammar delay: 0.5s, AI detection delay: 1.0s")
            
            db_mongo.evaluation_results.delete_many({
                "course_id": course_id,
                "assignment_id": assignment_id
            })
            print(f"Removed existing MongoDB evaluations for assignment {assignment_id}")
            
            # Run evaluation
            evaluator.run(pdf_files=pdf_files, total_grade=assignment.grade, submission_ids=submission_ids)
            
            # Wait briefly to ensure MongoDB updates have completed
            time.sleep(0.5)

            # Collect evaluation results with proper feedback handling
            for submission_id, temp_path in submission_paths.items():
                # We need to find the evaluation by the submission_id
                submission_data = db_mongo.evaluation_results.find_one({
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "submission_id": submission_id
                })

                if submission_data:
                    # Find the submission and student
                    submission = db.query(AssignmentSubmission).filter(
                        AssignmentSubmission.id == submission_id
                    ).first()
                    
                    if not submission:
                        continue
                    
                    student = db.query(Student).filter(Student.id == submission.student_id).first()
                    if not student:
                        continue
                    
                    # Extract scores properly with defaults
                    overall_scores = submission_data.get("overall_scores", {})
                    
                    # Extract feedback with proper fallback
                    feedback_data = submission_data.get("overall_feedback", {})
                    feedback_content = ""
                    if isinstance(feedback_data, dict):
                        feedback_content = feedback_data.get("content", "")
                    elif isinstance(feedback_data, str):
                        feedback_content = feedback_data
                    
                    # Debug output
                    print(f"Submission ID {submission_id} - Overall scores: {overall_scores}")
                    print(f"Submission ID {submission_id} - Feedback: {feedback_content}")
                    
                    result = {
                        "name": student.full_name,
                        "batch": student.batch,
                        "department": student.department,
                        "section": student.section,
                        "total_score": overall_scores.get("total", {}).get("score", 0),
                        "avg_context_score": overall_scores.get("context", {}).get("score", 0),
                        "avg_plagiarism_score": overall_scores.get("plagiarism", {}).get("score", 0),
                        "avg_ai_score": overall_scores.get("ai_detection", {}).get("score", 0),
                        "avg_grammar_score": overall_scores.get("grammar", {}).get("score", 0),
                        "feedback": feedback_content,
                        "image": student.image_url
                    }
                    
                    # Add result to list
                    evaluation_results.append(result)
                    
                    # Update or create PostgreSQL record
                    existing_eval = db.query(AssignmentEvaluation).filter(
                        AssignmentEvaluation.submission_id == submission_id
                    ).first()
                    
                    if existing_eval:
                        # Update existing evaluation
                        print(f"Updating existing evaluation for submission {submission_id}")
                        existing_eval.total_score = overall_scores.get("total", {}).get("score", 0)
                        existing_eval.plagiarism_score = overall_scores.get("plagiarism", {}).get("score", 0)
                        existing_eval.ai_detection_score = overall_scores.get("ai_detection", {}).get("score", 0)
                        existing_eval.grammar_score = overall_scores.get("grammar", {}).get("score", 0)
                        existing_eval.feedback = feedback_content
                        existing_eval.updated_at = datetime.now()
                    else:
                        # Create new evaluation record
                        print(f"Creating new evaluation for submission {submission_id}")
                        new_eval = AssignmentEvaluation(
                            submission_id=submission_id,
                            total_score=overall_scores.get("total", {}).get("score", 0),
                            plagiarism_score=overall_scores.get("plagiarism", {}).get("score", 0),
                            ai_detection_score=overall_scores.get("ai_detection", {}).get("score", 0),
                            grammar_score=overall_scores.get("grammar", {}).get("score", 0),
                            feedback=feedback_content
                        )
                        db.add(new_eval)
                    
                    # Commit changes to PostgreSQL
                    db.commit()

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

    # Print full results for debugging
    print("Evaluation results:", json.dumps(evaluation_results, indent=2))
    
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

    # First check evaluation_results collection using submission_id
    submission_data = db_mongo.evaluation_results.find_one({
        "course_id": course_id,
        "assignment_id": assignment_id,
        "submission_id": submission_id
    })

    # If not found, try the alternate format (pdf_file as numeric ID)
    if not submission_data:
        submission_data = db_mongo.evaluation_results.find_one({
            "course_id": course_id,
            "assignment_id": assignment_id,
            "pdf_file": submission_id
        })

    # Make a deepcopy to avoid modifying the original document
    if submission_data:
        # We want to preserve all the original data
        processed_data = dict(submission_data)
        
        # Try to get question-answer extraction data from qa_extraction collection
        qa_data = db_mongo.qa_extractions.find_one({
            "course_id": course_id,
            "assignment_id": assignment_id,
            "submission_id": submission_id,
            "is_teacher": False  # Make sure we're getting student's answers
        })
        
        if not qa_data:
            # Try again with pdf_file
            qa_data = db_mongo.qa_extractions.find_one({
                "course_id": course_id,
                "assignment_id": assignment_id,
                "pdf_file": submission_id,
                "is_teacher": False
            })
        
        # Also get teacher's questions for reference
        teacher_qa = db_mongo.qa_extractions.find_one({
            "course_id": course_id,
            "assignment_id": assignment_id,
            "is_teacher": True
        })
        
        # Process and enhance questions with their text if available
        questions = processed_data.get("questions", [])
        
        if qa_data and "qa_pairs" in qa_data:
            # Create a mapping from question number to student answers
            qa_map = {}
            for pair in qa_data.get("qa_pairs", []):
                q_num = pair.get("question_number")
                if q_num:
                    qa_map[q_num] = {
                        "question": pair.get("question", ""),
                        "answer": pair.get("answer", "")
                    }
            
            # Create a mapping from question number to teacher questions
            teacher_qa_map = {}
            if teacher_qa and "qa_pairs" in teacher_qa:
                for pair in teacher_qa.get("qa_pairs", []):
                    q_num = pair.get("question_number")
                    if q_num:
                        teacher_qa_map[q_num] = {
                            "question": pair.get("question", ""),
                            "answer": pair.get("answer", "")
                        }
            
            # Enhance questions with text (while preserving all original data)
            for question in questions:
                q_num = question.get("question_number")
                
                # Add student's answer if available
                if q_num in qa_map:
                    question["question_text"] = qa_map[q_num].get("question", "")
                    question["student_answer"] = qa_map[q_num].get("answer", "")
                
                # Add teacher's question if available
                if q_num in teacher_qa_map:
                    if not question.get("question_text"):
                        question["question_text"] = teacher_qa_map[q_num].get("question", "")
                    question["teacher_answer"] = teacher_qa_map[q_num].get("answer", "")
            
            processed_data["questions"] = questions
        
        # Use the processed data with enhanced questions
        submission_data = processed_data
        
    else:
        # Check PostgreSQL database for evaluation data
        evaluation = db.query(AssignmentEvaluation).filter(
            AssignmentEvaluation.submission_id == submission_id
        ).first()
        
        if evaluation:
            # Create response with PostgreSQL data
            submission_data = {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "submission_id": submission_id,
                "pdf_file": submission_id,
                "overall_scores": {
                    "total": {
                        "score": float(evaluation.total_score or 0.0),
                        "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                    },
                    "plagiarism": {
                        "score": float(evaluation.plagiarism_score or 0.0),
                        "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                    },
                    "ai_detection": {
                        "score": float(evaluation.ai_detection_score or 0.0),
                        "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                    },
                    "grammar": {
                        "score": float(evaluation.grammar_score or 0.0),
                        "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                    }
                },
                "overall_feedback": {
                    "content": evaluation.feedback or "",
                    "generated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                },
                "questions": []
            }
            
            # Try to get question-answer extraction data to add questions
            qa_data = db_mongo.qa_extractions.find_one({
                "course_id": course_id,
                "assignment_id": assignment_id,
                "submission_id": submission_id,
                "is_teacher": False
            })
            
            if not qa_data:
                qa_data = db_mongo.qa_extractions.find_one({
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "pdf_file": submission_id,
                    "is_teacher": False
                })
            
            # Get teacher's questions
            teacher_qa = db_mongo.qa_extractions.find_one({
                "course_id": course_id,
                "assignment_id": assignment_id,
                "is_teacher": True
            })
                
            # If we found QA data, add question information
            questions = []
            if qa_data and "qa_pairs" in qa_data:
                for pair in qa_data.get("qa_pairs", []):
                    q_num = pair.get("question_number")
                    if q_num:
                        # Get teacher answer if available
                        teacher_answer = ""
                        if teacher_qa and "qa_pairs" in teacher_qa:
                            for teacher_pair in teacher_qa.get("qa_pairs", []):
                                if teacher_pair.get("question_number") == q_num:
                                    teacher_answer = teacher_pair.get("answer", "")
                                    break
                        
                        # Create a question entry with detailed structure
                        questions.append({
                            "question_number": q_num,
                            "question_text": pair.get("question", ""),
                            "student_answer": pair.get("answer", ""),
                            "teacher_answer": teacher_answer,
                            "scores": {
                                "context": {
                                    "score": 0.0,
                                    "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                                },
                                "plagiarism": {
                                    "score": 0.0,
                                    "copied_sentence": "",
                                    "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                                },
                                "ai_detection": {
                                    "score": 0.0,
                                    "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                                },
                                "grammar": {
                                    "score": 0.0,
                                    "evaluated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                                }
                            },
                            "feedback": {
                                "content": "",
                                "generated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else datetime.now().isoformat()
                            }
                        })
                
                submission_data["questions"] = sorted(questions, key=lambda x: x["question_number"])
        else:
            raise HTTPException(
                status_code=404,
                detail="Submission details not found"
            )

    # Get student information
    student = db.query(Student).filter(Student.id == submission.student_id).first()
    if student:
        submission_data["student"] = {
            "id": student.id,
            "student_id": student.student_id,
            "name": student.full_name,
            "batch": student.batch,
            "department": student.department,
            "section": student.section,
            "image": student.image_url
        }
    
    # Add submission information
    submission_data["submission"] = {
        "id": submission.id,
        "submitted_at": submission.submitted_at.strftime("%I:%M %p - %d/%b/%Y"),
        "pdf_url": submission.submission_pdf_url
    }

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
            # First try to find evaluation results in MongoDB
            evaluation_data = db_mongo.evaluation_results.find_one({
                "course_id": course_id,
                "assignment_id": assignment_id,
                "pdf_file": submission.submission_pdf_url
            })

            if evaluation_data:
                # Get total score and overall scores from evaluation results
                overall_scores = evaluation_data.get("overall_scores", {})
                feedback = evaluation_data.get("overall_feedback", {}).get("content", "")
                
                scores = {
                    "student_id": student.student_id,
                    "name": student.full_name,
                    "batch": student.batch,
                    "department": student.department,
                    "section": student.section,
                    "image": student.image_url,
                    "total_score": overall_scores.get("total", {}).get("score", 0.0),
                    "avg_context_score": overall_scores.get("context", {}).get("score", 0.0),
                    "avg_plagiarism_score": overall_scores.get("plagiarism", {}).get("score", 0.0),
                    "avg_ai_score": overall_scores.get("ai_detection", {}).get("score", 0.0),
                    "avg_grammar_score": overall_scores.get("grammar", {}).get("score", 0.0),
                    "feedback": feedback
                }

                total_scores_data.append(scores)
            else:
                # Fall back to checking PostgreSQL database
                evaluation = db.query(AssignmentEvaluation).filter(
                    AssignmentEvaluation.submission_id == submission.id
                ).first()
                
                if evaluation:
                    scores = {
                        "student_id": student.student_id,
                        "name": student.full_name,
                        "batch": student.batch,
                        "department": student.department,
                        "section": student.section,
                        "image": student.image_url,
                        "total_score": float(evaluation.total_score or 0.0),
                        "avg_context_score": 0.0,  # Not stored in older format
                        "avg_plagiarism_score": float(evaluation.plagiarism_score or 0.0),
                        "avg_ai_score": float(evaluation.ai_detection_score or 0.0),
                        "avg_grammar_score": float(evaluation.grammar_score or 0.0),
                        "feedback": evaluation.feedback or ""
                    }
                    
                    total_scores_data.append(scores)

        return {
            "success": True,
            "status": 200,
            "total_scores": total_scores_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch scores: {str(e)}")


@router.get("/teacher/course/{course_id}/assignment/{assignment_id}/student/{student_id}/evaluation", response_model=dict)
async def get_student_evaluation(
    course_id: int,
    assignment_id: int,
    student_id: int,
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
        AssignmentSubmission.assignment_id == assignment_id,
        AssignmentSubmission.student_id == student_id
    ).first()

    if not submission:
        raise HTTPException(
            status_code=404,
            detail="No submission found for this student"
        )

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=404,
            detail="Student not found"
        )

    # Fetch evaluation data from MongoDB
    evaluation_data = db_mongo.evaluation_results.find_one({
        "course_id": course_id,
        "assignment_id": assignment_id,
        "submission_id": submission.id
    })
    
    if not evaluation_data:
        evaluation_data = db_mongo.evaluation_results.find_one({
            "course_id": course_id,
            "assignment_id": assignment_id,
            "pdf_file": submission.id
        })

    # Fetch Q&A data
    qa_data = db_mongo.qa_extractions.find_one({
        "course_id": course_id,
        "assignment_id": assignment_id,
        "submission_id": submission.id,
        "is_teacher": False
    })
    
    if not qa_data:
        qa_data = db_mongo.qa_extractions.find_one({
            "course_id": course_id,
            "assignment_id": assignment_id,
            "pdf_file": submission.id,
            "is_teacher": False
        })
    
    # Fetch teacher's Q&A data
    teacher_qa = db_mongo.qa_extractions.find_one({
        "course_id": course_id,
        "assignment_id": assignment_id,
        "is_teacher": True
    })
    
    # Extract student Q&A pairs
    qa_pairs = {}
    if qa_data and "qa_pairs" in qa_data:
        qa_pairs = qa_data.get("qa_pairs", {})
    
    # Extract teacher Q&A pairs
    teacher_qa_pairs = {}
    if teacher_qa and "qa_pairs" in teacher_qa:
        teacher_qa_pairs = teacher_qa.get("qa_pairs", {})

    if not evaluation_data:
        # Fall back to SQL evaluation data
        evaluation = db.query(AssignmentEvaluation).filter(
            AssignmentEvaluation.submission_id == submission.id
        ).first()
        
        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail="No evaluation found for this submission"
            )
        
        # Format questions in consistent way with student API
        detailed_questions = []
        
        for i in range(1, 20):  # Assume max 20 questions
            q_key = f"Question#{i}"
            a_key = f"Answer#{i}"
            
            if q_key in qa_pairs or q_key in teacher_qa_pairs:
                question_text = qa_pairs.get(q_key, teacher_qa_pairs.get(q_key, ""))
                student_answer = qa_pairs.get(a_key, "")
                
                # Create question object in same format as student API
                detailed_questions.append({
                    "question_number": i,
                    "question_text": question_text,
                    "student_answer": student_answer,
                    "plagiarism_score": 0,
                    "context_score": 0,
                    "ai_score": 0,
                    "grammar_score": 0,
                    "feedback": ""
                })
        
        # Only include questions that have content
        detailed_questions = [q for q in detailed_questions if q["question_text"] or q["student_answer"]]
        
        # Process overall feedback
        overall_feedback = evaluation.feedback or ""
        
        # Build response with consistent format
        result_data = {
            "submission_id": submission.id,
            "submitted_at": submission.submitted_at.strftime("%Y-%m-%d %H:%M"),
            "pdf_url": submission.submission_pdf_url,
            "student": {
                "id": student.id,
                "student_id": student.student_id,
                "name": student.full_name,
                "batch": student.batch,
                "department": student.department,
                "section": student.section,
                "image": student.image_url
            },
            "total_score": float(evaluation.total_score or 0.0),
            "plagiarism_score": float(evaluation.plagiarism_score or 0.0),
            "ai_detection_score": float(evaluation.ai_detection_score or 0.0),
            "grammar_score": float(evaluation.grammar_score or 0.0),
            "feedback": overall_feedback,
            "questions": detailed_questions
        }
    else:
        # Use MongoDB evaluation data (preferred source)
        overall_scores = evaluation_data.get("overall_scores", {})
        questions_data = evaluation_data.get("questions", [])
        
        # Extract overall feedback
        overall_feedback_obj = evaluation_data.get("overall_feedback", {})
        overall_feedback = ""
        if isinstance(overall_feedback_obj, dict):
            overall_feedback = overall_feedback_obj.get("content", "")
        elif isinstance(overall_feedback_obj, str):
            overall_feedback = overall_feedback_obj
        
        # Format questions in consistent way with student API
        detailed_questions = []
        for question in questions_data:
            q_num = question.get("question_number")
            scores = question.get("scores", {})
            
            # Get feedback
            feedback_obj = question.get("feedback", {})
            feedback_content = ""
            if isinstance(feedback_obj, dict):
                feedback_content = feedback_obj.get("content", "")
            elif isinstance(feedback_obj, str):
                feedback_content = feedback_obj
            
            # Get question text and student answer
            q_key = f"Question#{q_num}"
            a_key = f"Answer#{q_num}"
            question_text = qa_pairs.get(q_key, teacher_qa_pairs.get(q_key, ""))
            student_answer = qa_pairs.get(a_key, "")
            
            # Create question object in same format as student API
            detailed_questions.append({
                "question_number": q_num,
                "question_text": question_text,
                "student_answer": student_answer,
                "plagiarism_score": scores.get("plagiarism", {}).get("score", 0),
                "context_score": scores.get("context", {}).get("score", 0),
                "ai_score": scores.get("ai_detection", {}).get("score", 0),
                "grammar_score": scores.get("grammar", {}).get("score", 0),
                "feedback": feedback_content
            })
        
        # Build response with consistent format
        result_data = {
            "submission_id": submission.id,
            "submitted_at": submission.submitted_at.strftime("%Y-%m-%d %H:%M"),
            "pdf_url": submission.submission_pdf_url,
            "student": {
                "id": student.id,
                "student_id": student.student_id,
                "name": student.full_name,
                "batch": student.batch,
                "department": student.department,
                "section": student.section,
                "image": student.image_url
            },
            "total_score": overall_scores.get("total", {}).get("score", 0),
            "plagiarism_score": overall_scores.get("plagiarism", {}).get("score", 0),
            "ai_score": overall_scores.get("ai_detection", {}).get("score", 0),
            "grammar_score": overall_scores.get("grammar", {}).get("score", 0),
            "feedback": overall_feedback,
            "questions": sorted(detailed_questions, key=lambda x: x["question_number"])
        }
    
    return {
        "success": True,
        "status": 200,
        "result": result_data
    }  
