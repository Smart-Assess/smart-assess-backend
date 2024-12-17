import os
from fastapi import APIRouter, Depends, File, HTTPException, Form, UploadFile
from pymongo import MongoClient
from sqlalchemy.orm import Session
from models.models import *
from utils.dependencies import get_db
from apis.auth import get_current_admin
from utils.s3 import delete_from_s3, upload_to_s3
from utils.plagiarism import PDFQuestionAnswerExtractor

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
    pdf_path = f"/tmp/{submission_pdf.filename}"
    try:
        with open(pdf_path, "wb") as buffer:
            buffer.write(await submission_pdf.read())

        # Upload to S3
        pdf_url = upload_to_s3(
            folder_name=f"assignment_submissions/{assignment.course_id}/{assignment_id}",
            file_name=f"{current_student.id}.pdf",
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
                "pdf_url": submission.submission_pdf_url,
                "submitted_at": submission.submitted_at
            }
        }

    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

@router.delete("/student/assignment/{assignment_id}/submission", response_model=dict)
async def delete_submission(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_admin)
):
    submission = db.query(AssignmentSubmission).filter(
        AssignmentSubmission.assignment_id == assignment_id,
        AssignmentSubmission.student_id == current_student.id
    ).first()
    
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
    for submission in submissions:
        evaluations = db.query(AssignmentEvaluation).filter(
            AssignmentEvaluation.submission_id == submission.id
        ).all()

        for evaluation in evaluations:
            results_data.append({
                "assignment_id": submission.assignment_id,
                "course_id": submission.assignment.course_id,
                "total_score": evaluation.total_score,
                "plagiarism_score": evaluation.plagiarism_score,
                "ai_detection_score": evaluation.ai_detection_score,
                "grammar_score": evaluation.grammar_score,
                "feedback": evaluation.feedback,
                "evaluated_at": evaluation.created_at.strftime("%Y-%m-%d %H:%M")
            })

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

    # Get MongoDB detailed results
    client = MongoClient(os.getenv("MONGO_URI"))
    db_mongo = client['FYP']
    
    try:
        submission_data = db_mongo.submissions.find_one({
            "assignment_id": assignment_id,
            "student_id": current_student.id,
            "PDF_File": submission.submission_pdf_url
        })

        if not submission_data:
            raise HTTPException(
                status_code=404,
                detail="Detailed evaluation results not found"
            )

        # Convert MongoDB ObjectIds to strings
        submission_data["_id"] = str(submission_data["_id"])

        result_data = {
            "submission_id": submission.id,
            "submitted_at": submission.submitted_at.strftime("%Y-%m-%d %H:%M"),
            "pdf_url": submission.submission_pdf_url,
            "total_score": submission_data.get("total_score", "Not evaluated"),
            "questions": submission_data.get("questions", []),
            "feedback": evaluation.feedback if evaluation else None,
            "scores": {
                "plagiarism": evaluation.plagiarism_score if evaluation else None,
                "ai_detection": evaluation.ai_detection_score if evaluation else None,
                "grammar": evaluation.grammar_score if evaluation else None
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
    
    finally:
        client.close()

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
                "status": "submitted" if submission else "pending"
            }
        }
    }