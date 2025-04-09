import os
from fastapi import APIRouter, Depends, File, HTTPException, Form, UploadFile
from utils.mongodb import mongo_db
from sqlalchemy.orm import Session
from models.models import *
from utils.dependencies import get_db
from apis.auth import get_current_admin
from utils.s3 import delete_from_s3, upload_to_s3
import uuid
from datetime import datetime as dt
from datetime import timezone
from tempfile import NamedTemporaryFile

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
    

@router.get("/student/course/{course_id}/assignments", response_model=dict)
async def get_course_assignments(
    course_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    # Verify student is enrolled
    enrollment = db.query(StudentCourse).filter(
        StudentCourse.student_id == current_student.id,
        StudentCourse.course_id == course_id,
        StudentCourse.status == "accepted"
    ).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=403,
            detail="You are not enrolled in this course"
        )
    
    # Get assignments with submission status
    assignments = db.query(Assignment).filter(
        Assignment.course_id == course_id
    ).all()
    
    assignments_data = []
    for assignment in assignments:
        # Check if student has submitted
        submission = db.query(AssignmentSubmission).filter(
            AssignmentSubmission.assignment_id == assignment.id,
            AssignmentSubmission.student_id == current_student.id
        ).first()
        
        assignments_data.append({
            "id": assignment.id,
            "name": assignment.name,
            "description": assignment.description,
            "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
            "grade": assignment.grade,
            "question_pdf_url": assignment.question_pdf_url,
            "submission": {
                "id": submission.id if submission else None,
                "submitted_at": submission.submitted_at if submission else None,
                "pdf_url": submission.submission_pdf_url if submission else None
            }
        })
    
    return {
        "success": True,
        "status": 200,
        "assignments": assignments_data
    }

@router.post("/student/assignment/{assignment_id}/submit", response_model=dict)
async def submit_assignment(
    assignment_id: int,
    submission_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    # Validation checks
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
        
    # Check if deadline has passed
    current_time = dt.now()
    if current_time > assignment.deadline:
        raise HTTPException(
            status_code=403,
            detail="Submission deadline has passed. You can no longer submit this assignment."
        )
    
    enrollment = db.query(StudentCourse).filter(
        StudentCourse.student_id == current_student.id,
        StudentCourse.course_id == assignment.course_id,
        StudentCourse.status == "accepted"
    ).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=403,
            detail="You are not enrolled in this course"
        )

    if not submission_pdf.content_type == 'application/pdf':
        raise HTTPException(
            status_code=400,
            detail="File must be a PDF"
        )
    
    # Generate a unique identifier
    unique_id = uuid.uuid4()
    timestamp = dt.now().strftime("%Y%m%d%H%M%S")
    
    # Check and remove existing submission
    existing_submission = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.assignment_id == assignment_id,
        AssignmentSubmission.student_id == current_student.id
    ).first()
    
    if existing_submission:
        delete_success = delete_from_s3(existing_submission.submission_pdf_url)
        if not delete_success:
            print(f"Failed to delete old submission: {existing_submission.submission_pdf_url}")
    
    # Process PDF file
    file_extension = submission_pdf.filename.split('.')[-1]
    new_file_name = f"{current_student.id}_{unique_id}_{timestamp}.{file_extension}"
    pdf_path = os.path.join("temp", new_file_name)
    
    os.makedirs("temp", exist_ok=True)
    try:
        with open(pdf_path, "wb") as buffer:
            buffer.write(await submission_pdf.read())

        # Upload to S3 with the new file name
        pdf_url = upload_to_s3(
            folder_name=f"assignment_submissions/{assignment.course_id}/{assignment_id}",
            file_name=new_file_name,
            file_path=pdf_path
        )
        
        if not pdf_url:
            raise HTTPException(status_code=500, detail="Failed to upload submission")

        # Update or create SQL record
        if existing_submission:
            existing_submission.submission_pdf_url = pdf_url
            submission = existing_submission
        else:
            submission = AssignmentSubmission(
                assignment_id=assignment_id,
                student_id=current_student.id,
                submission_pdf_url=pdf_url
            )
            db.add(submission)
        
        db.commit()
        db.refresh(submission)

        return {
            "success": True,
            "status": 201,
            "message": "Submission saved successfully",
            "submission": {
                "id": submission.id,
                "assignment_id": submission.assignment_id,
                "pdf_url": submission.submission_pdf_url,
                "submitted_at": submission.submitted_at
            }
        }

    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

@router.put("/student/assignment/{assignment_id}/update-submission", response_model=dict)
async def update_assignment_submission(
    assignment_id: int,
    submission_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    """
    Update an existing assignment submission:
    1. Validate the student has access to the assignment
    2. Check if a previous submission exists
    3. Check if deadline has passed
    4. Validate the new PDF follows the required format
    5. Delete the old submission from S3
    6. Upload the new submission to S3
    7. Update the database record
    """
    # Validation checks
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    # Check if deadline has passed
    current_time = dt.now()
    if current_time > assignment.deadline:
        raise HTTPException(
            status_code=403,
            detail="Submission deadline has passed. You can no longer update this assignment."
        )
        
    # Check enrollment
    enrollment = db.query(StudentCourse).filter(
        StudentCourse.student_id == current_student.id,
        StudentCourse.course_id == assignment.course_id,
        StudentCourse.status == "accepted"
    ).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=403,
            detail="You are not enrolled in this course"
        )

    # Check if submission exists
    existing_submission = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.assignment_id == assignment_id,
        AssignmentSubmission.student_id == current_student.id
    ).first()
    
    if not existing_submission:
        raise HTTPException(
            status_code=404,
            detail="No existing submission found to update. Please use the submit endpoint instead."
        )

    # Validate file is a PDF
    if not submission_pdf.content_type == 'application/pdf':
        raise HTTPException(
            status_code=400,
            detail="File must be a PDF"
        )
    
    
    from evaluations.base_extractor import PDFQuestionAnswerExtractor
    
    temp_file_path = None
    try:
        with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            content = await submission_pdf.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        # Validate PDF format using the extractor
        extractor = PDFQuestionAnswerExtractor(
            pdf_files=[temp_file_path],
            course_id=assignment.course_id,
            assignment_id=assignment_id,
            is_teacher=False
        )
        extracted_text = extractor.extract_text_from_pdf(temp_file_path)
        
        # Parse the Q&A to verify format
        parsed_dict = extractor.parse_qa(extracted_text)
        
        if not parsed_dict:
            raise HTTPException(
                status_code=400,
                detail="Submission PDF is not in the correct format. It must contain 'Question#' and 'Answer#' sections."
            )
        
        
        
        unique_id = uuid.uuid4()
        timestamp = dt.now().strftime("%Y%m%d%H%M%S")
        file_extension = submission_pdf.filename.split('.')[-1]
        new_file_name = f"{current_student.id}_{unique_id}_{timestamp}.{file_extension}"
        
        # Delete existing S3 file
        from utils.s3 import delete_from_s3, upload_to_s3
        
        delete_success = delete_from_s3(existing_submission.submission_pdf_url)
        if not delete_success:
            print(f"Warning: Failed to delete old submission from S3: {existing_submission.submission_pdf_url}")
        
        # Upload new file to S3
        pdf_url = upload_to_s3(
            folder_name=f"assignment_submissions/{assignment.course_id}/{assignment_id}",
            file_name=new_file_name,
            file_path=temp_file_path
        )
        
        if not pdf_url:
            raise HTTPException(status_code=500, detail="Failed to upload submission")
        
        # Update MongoDB record - delete any existing Q&A extraction for this submission
        from utils.mongodb import mongo_db
        
        mongo_db.db['qa_extractions'].delete_one({
            "course_id": assignment.course_id,
            "assignment_id": assignment_id,
            "submission_id": existing_submission.id,
            "is_teacher": False
        })
        
        # Store the extracted Q&A in MongoDB for future use
        qa_document = {
            "course_id": assignment.course_id,
            "assignment_id": assignment_id,
            "is_teacher": False,
            "submission_id": existing_submission.id,
            "pdf_file": temp_file_path,
            "qa_pairs": parsed_dict,
            "extracted_at": dt.now(timezone.utc)
        }
        
        mongo_db.db['qa_extractions'].update_one(
            {
                "course_id": assignment.course_id,
                "assignment_id": assignment_id,
                "submission_id": existing_submission.id,
                "is_teacher": False
            },
            {"$set": qa_document},
            upsert=True
        )
        
        # Update PostgreSQL submission
        existing_submission.submission_pdf_url = pdf_url
        existing_submission.submitted_at = dt.now()
        
        # Delete any existing evaluation for this submission
        existing_evaluation = db.query(AssignmentEvaluation).filter(
            AssignmentEvaluation.submission_id == existing_submission.id
        ).first()
        
        if existing_evaluation:
            db.delete(existing_evaluation)
        
        # Also delete MongoDB evaluation results
        mongo_db.db['evaluation_results'].delete_one({
            "course_id": assignment.course_id,
            "assignment_id": assignment_id,
            "submission_id": existing_submission.id
        })
        
        # Commit changes to database
        db.commit()
        db.refresh(existing_submission)
        
        return {
            "success": True,
            "status": 200,
            "message": "Submission updated successfully",
            "submission": {
                "id": existing_submission.id,
                "assignment_id": existing_submission.assignment_id,
                "pdf_url": existing_submission.submission_pdf_url,
                "submitted_at": existing_submission.submitted_at
            }
        }
        
    except Exception as e:
        # Rollback on error
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update submission: {str(e)}"
        )
    
    finally:
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)



@router.delete("/student/assignment/{assignment_id}/submission", response_model=dict)
async def delete_submission(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    print("current student id",current_student.id,assignment_id)
    submission = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.assignment_id == assignment_id,
        AssignmentSubmission.student_id == current_student.id
    ).first()
    print("submission id: ", submission)
    
    if not submission:
        raise HTTPException(
            status_code=404,
            detail="Submission not found"
        )

    # Delete from S3
    delete_success = delete_from_s3(submission.submission_pdf_url)
    if not delete_success:
        print(f"Failed to delete submission from S3: {submission.submission_pdf_url}")

    # Delete from database
    db.delete(submission)
    db.commit()

    return {
        "success": True,
        "status": 200,
        "message": "Submission deleted successfully"
    }
    
@router.get("/student/courses", response_model=dict)
async def get_enrolled_courses(
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    enrolled_courses = db.query(Course).join(StudentCourse).filter(
        StudentCourse.student_id == current_student.id,
        StudentCourse.status == "accepted"
    ).all()

    courses_data = []
    for course in enrolled_courses:
        courses_data.append({
            "id": course.id,
            "name": course.name,
            "batch": course.batch,
            "department": course.group,
            "section": course.section
        })

    return {
        "success": True,
        "status": 200,
        "courses": courses_data
    }

@router.get("/student/course/{course_id}/materials", response_model=dict)
async def get_course_materials(
    course_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    # Verify student is enrolled
    enrollment = db.query(StudentCourse).filter(
        StudentCourse.student_id == current_student.id,
        StudentCourse.course_id == course_id,
        StudentCourse.status == "accepted"
    ).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=403,
            detail="You are not enrolled in this course"
        )
    
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    return {
        "success": True,
        "status": 200,
        "course_materials": course.pdf_urls
    }
    
@router.get("/student/results", response_model=dict)
async def get_student_results(
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    submissions = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.student_id == current_student.id
    ).all()

    results_data = []

    try:
        for submission in submissions:
            evaluations = db.query(AssignmentEvaluation).filter(
                AssignmentEvaluation.submission_id == submission.id
            ).all()

            for evaluation in evaluations:
                # Get MongoDB detailed results from evaluation_results collection
                evaluation_data = mongo_db.db['evaluation_results'].find_one({
                    "course_id": submission.assignment.course_id,
                    "assignment_id": submission.assignment_id,
                    "submission_id": submission.id
                })

                if not evaluation_data:
                    continue

                # Prepare detailed question results
                detailed_questions = []
                for question in evaluation_data.get("questions", []):
                    q_num = question.get("question_number")
                    scores = question.get("scores", {})
                    feedback_obj = question.get("feedback", {})
                    
                    # Get question text and student answer from qa_extractions
                    qa_data = mongo_db.db['qa_extractions'].find_one({
                        "course_id": submission.assignment.course_id,
                        "assignment_id": submission.assignment_id,
                        "submission_id": submission.id,
                        "is_teacher": False
                    })
                    
                    question_text = ""
                    student_answer = ""
                    if qa_data and "qa_pairs" in qa_data:
                        qa_pairs = qa_data["qa_pairs"]
                        question_text = qa_pairs.get(f"Question#{q_num}", "")
                        student_answer = qa_pairs.get(f"Answer#{q_num}", "")
                    
                    feedback_content = ""
                    if isinstance(feedback_obj, dict):
                        feedback_content = feedback_obj.get("content", "")
                    elif isinstance(feedback_obj, str):
                        feedback_content = feedback_obj
                    
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

                # Get overall feedback
                overall_feedback_obj = evaluation_data.get("overall_feedback", {})
                overall_feedback = ""
                if isinstance(overall_feedback_obj, dict):
                    overall_feedback = overall_feedback_obj.get("content", "")
                elif isinstance(overall_feedback_obj, str):
                    overall_feedback = overall_feedback_obj

                # Determine feedback
                total_score = evaluation.total_score
                feedback = overall_feedback or evaluation.feedback
                if total_score == 0 and any(q["plagiarism_score"] > 0.7 for q in detailed_questions):
                    feedback = "Your total score is 0 because plagiarism was detected in your submission."

                results_data.append({
                    "assignment_id": submission.assignment_id,
                    "course_id": submission.assignment.course_id,
                    "total_score": total_score,
                    "plagiarism_score": evaluation.plagiarism_score,
                    "ai_detection_score": evaluation.ai_detection_score,
                    "grammar_score": evaluation.grammar_score,
                    "feedback": feedback,
                    "evaluated_at": evaluation.created_at.strftime("%Y-%m-%d %H:%M")
                })

    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to fetch student results: {str(e)}"
        )
    
    return {
        "success": True,
        "status": 200,
        "results": results_data
    }

@router.get("/student/assignment/{assignment_id}/result", response_model=dict)
async def get_assignment_result(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    # Verify submission exists
    submission = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.assignment_id == assignment_id,
        AssignmentSubmission.student_id == current_student.id
    ).first()
    
    if not submission:
        raise HTTPException(
            status_code=404,
            detail="No submission found for this assignment"
        )

    # Get SQL evaluation data
    evaluation = db.query(AssignmentEvaluation).filter(
        AssignmentEvaluation.submission_id == submission.id
    ).first()

    try:
        # Get MongoDB evaluation data
        evaluation_data = mongo_db.db['evaluation_results'].find_one({
            "course_id": submission.assignment.course_id,
            "assignment_id": assignment_id,
            "submission_id": submission.id
        })

        if not evaluation_data:
            raise HTTPException(
                status_code=404,
                detail="Detailed evaluation results not found"
            )

        # Get question-answer data
        qa_data = mongo_db.db['qa_extractions'].find_one({
            "course_id": submission.assignment.course_id,
            "assignment_id": assignment_id,
            "submission_id": submission.id,
            "is_teacher": False
        })
        
        qa_pairs = {}
        if qa_data:
            qa_pairs = qa_data.get("qa_pairs", {})

        # Prepare detailed question results
        detailed_questions = []
        for question in evaluation_data.get("questions", []):
            q_num = question.get("question_number")
            scores = question.get("scores", {})
            
            # Get feedback from the question data
            feedback_obj = question.get("feedback", {})
            feedback_content = ""
            if isinstance(feedback_obj, dict):
                feedback_content = feedback_obj.get("content", "")
            elif isinstance(feedback_obj, str):
                feedback_content = feedback_obj
            
            # Get question and answer text
            q_key = f"Question#{q_num}"
            a_key = f"Answer#{q_num}"
            
            # Get question total score (newly added)
            question_score = scores.get("total", {}).get("score", 0)
            
            detailed_questions.append({
                "question_number": q_num,
                "question_text": qa_pairs.get(q_key, ""),
                "student_answer": qa_pairs.get(a_key, ""),
                "plagiarism_score": scores.get("plagiarism", {}).get("score", 0),
                "context_score": scores.get("context", {}).get("score", 0),
                "ai_score": scores.get("ai_detection", {}).get("score", 0),
                "grammar_score": scores.get("grammar", {}).get("score", 0),
                "question_score": question_score,  # Added question total score
                "feedback": feedback_content
            })

        # Get overall scores
        overall_scores = evaluation_data.get("overall_scores", {})
        total_score = overall_scores.get("total", {}).get("score", 0) if overall_scores else 0
        
        # Get assignment details for total grade
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=404,
                detail="Assignment not found"
            )
        
        total_assignment_grade = assignment.grade
        
        # Calculate percentage score
        percentage_score = (total_score / total_assignment_grade * 100) if total_assignment_grade > 0 else 0
        percentage_score = round(percentage_score, 2)
        
        # Get overall feedback
        overall_feedback_obj = evaluation_data.get("overall_feedback", {})
        feedback = ""
        if isinstance(overall_feedback_obj, dict):
            feedback = overall_feedback_obj.get("content", "")
        elif isinstance(overall_feedback_obj, str):
            feedback = overall_feedback_obj
        
        # Use SQL evaluation feedback as fallback
        if not feedback and evaluation:
            feedback = evaluation.feedback
            
        # Override with plagiarism warning if applicable
        if total_score == 0 and any(q["plagiarism_score"] > 0.7 for q in detailed_questions):
            feedback = "Your total score is 0 because plagiarism was detected in your submission."

        result_data = {
            "submission_id": submission.id,
            "submitted_at": submission.submitted_at.strftime("%Y-%m-%d %H:%M"),
            "pdf_url": submission.submission_pdf_url,
            "total_score": total_score,
            "total_assignment_grade": total_assignment_grade,  # Added total possible grade
            "percentage_score": percentage_score,  # Added percentage score
            "questions": detailed_questions,
            "feedback": feedback,
            "scores": {
                "plagiarism": overall_scores.get("plagiarism", {}).get("score", 0) if overall_scores else (evaluation.plagiarism_score if evaluation else None),
                "ai_detection": overall_scores.get("ai_detection", {}).get("score", 0) if overall_scores else (evaluation.ai_detection_score if evaluation else None),
                "grammar": overall_scores.get("grammar", {}).get("score", 0) if overall_scores else (evaluation.grammar_score if evaluation else None)
            }
        }

        # Clean up null values
        result_data["scores"] = {
            k: v for k, v in result_data["scores"].items() 
            if v is not None
        }

        return {
            "success": True,
            "status": 200,
            "result": result_data
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to fetch evaluation results: {str(e)}"
        )

@router.get("/student/assignment/{assignment_id}", response_model=dict)
async def get_assignment_details(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    # Get assignment with course details
    assignment = db.query(Assignment).join(Course).filter(
        Assignment.id == assignment_id
    ).first()
    
    if not assignment:
        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )
    
    # Verify student enrollment
    enrollment = db.query(StudentCourse).filter(
        StudentCourse.student_id == current_student.id,
        StudentCourse.course_id == assignment.course_id,
        StudentCourse.status == "accepted"
    ).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=403,
            detail="You are not enrolled in this course"
        )
    
    # Get submission if exists
    submission = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.assignment_id == assignment_id,
        AssignmentSubmission.student_id == current_student.id
    ).first()

    evaluation_done = False
    if submission:
        evaluation = db.query(AssignmentEvaluation).filter(
            AssignmentEvaluation.submission_id == submission.id
        ).first()
        evaluation_done = evaluation is not None

    return {
        "success": True,
        "status": 200,
        "assignment": {
            "id": assignment.id,
            "name": assignment.name,
            "description": assignment.description,
            "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
            "grade": assignment.grade,
            "question_pdf_url": assignment.question_pdf_url,
            "course": {
                "id": assignment.course.id,
                "name": assignment.course.name,
                "batch": assignment.course.batch,
                "section": assignment.course.section,
                "department": assignment.course.group
            },
            "submission": {
                "id": submission.id if submission else None,
                "submitted_at": submission.submitted_at.strftime("%Y-%m-%d %H:%M") if submission else None,
                "pdf_url": submission.submission_pdf_url if submission else None,
                "status": "submitted" if submission else "pending",
                "evaluation_done": evaluation_done
            }
        }
    }