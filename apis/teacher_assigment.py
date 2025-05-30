# >> Import necessary modules and packages from FastAPI and other libraries
from datetime import timezone
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
from apis.teacher_course import (
    sanitize_folder_name,
    get_teacher_rag,
    db_mongo,
    JSONEncoder,
)
import json
from evaluations.base_extractor import PDFQuestionAnswerExtractor
from fastapi import APIRouter, UploadFile, Form, File, HTTPException, Depends
from utils.pdf_report import PDFReportGenerator


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
    current_teacher: Teacher = Depends(get_current_admin),
):
    offset = (page - 1) * limit

    try:
        total = (
            db.query(Assignment)
            .join(Course)
            .filter(Course.teacher_id == current_teacher.id)
            .count()
        )

        assignments = (
            db.query(Assignment, Course)
            .join(Course)
            .filter(Course.teacher_id == current_teacher.id)
            .order_by(Assignment.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        assignments_data = []
        for assignment, course in assignments:
            assignments_data.append(
                {
                    "id": assignment.id,
                    "name": assignment.name,
                    "description": assignment.description,
                    "batch": course.batch,
                    "department": course.group,
                    "section": course.section,
                    "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
                    "grade": assignment.grade,
                    "course_id": course.id,
                    "course_name": course.name,
                }
            )

        return {
            "success": True,
            "status": 200,
            "total": total,
            "page": page,
            "total_pages": (total + limit - 1) // limit,
            "assignments": assignments_data,
            "has_previous": page > 1,
            "has_next": (offset + limit) < total,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/teacher/course/{course_id}/assignments", response_model=dict)
async def get_course_assignments(
    course_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignments = (
        db.query(Assignment)
        .filter(Assignment.course_id == course_id)
        .order_by(Assignment.created_at.desc())
        .all()
    )

    assignments_data = []
    for assignment in assignments:
        assignments_data.append(
            {
                "id": assignment.id,
                "name": assignment.name,
                "description": assignment.description,
                "deadline": assignment.deadline.strftime("%Y-%m-%d %H:%M"),
                "grade": assignment.grade,
                "question_pdf_url": assignment.question_pdf_url,
                "created_at": assignment.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    return {"success": True, "status": 200, "assignments": assignments_data}


@router.post("/teacher/course/{course_id}/assignment", response_model=dict)
async def create_assignment(
    course_id: int,
    name: str = Form(...),
    description: str = Form(...),
    deadline: str = Form(...),  # Format: "YYYY-MM-DD HH:MM"
    grade: int = Form(...),
    question_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    # Validate PDF
    if question_pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Question file must be a PDF")

    # Check file size limit (10 MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes
    contents = await question_pdf.read()
    file_size = len(contents)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, detail=f"File size exceeds the limit of 10MB"
        )

    await question_pdf.seek(0)

    # Parse the deadline string into a datetime object
    try:
        deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid deadline format. Use 'YYYY-MM-DD HH:MM'."
        )

    try:
        with NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            os.makedirs("temp", exist_ok=True)
            content = await question_pdf.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        # Validate the format of the question PDF
        extractor = PDFQuestionAnswerExtractor(
            pdf_files=[temp_file_path],
            course_id=course_id,
            assignment_id=0,
            is_teacher=True,
        )
        teacher_text = extractor.extract_text_from_pdf(temp_file_path)
        print("Extracted text from teacher PDF")
        parsed_dict = extractor.parse_qa(teacher_text)
        print("Parsed Q&A pairs:", parsed_dict)

        if not parsed_dict:
            raise HTTPException(
                status_code=400,
                detail="Assignment PDF is not in the correct format. It must contain 'Question#' and 'Answer#'.",
            )

        # Sanitize and upload PDF to S3
        safe_course_name = sanitize_folder_name(course.name)
        s3_url = upload_to_s3(
            folder_name=f"course_assignments/{current_teacher.id}/{safe_course_name}",
            file_name=question_pdf.filename,
            file_path=temp_file_path,
        )

        if not s3_url:
            raise HTTPException(status_code=500, detail="Failed to upload question PDF")

        # Create new assignment in SQL database
        new_assignment = Assignment(
            course_id=course_id,
            name=name,
            description=description,
            deadline=deadline_dt,
            grade=grade,
            question_pdf_url=s3_url,
        )
        db.add(new_assignment)
        db.commit()
        db.refresh(new_assignment)

        # Now that we have the assignment ID, save the extracted Q&A pairs to MongoDB
        # Save in the same format as the example
        mongo_document = {
            "is_teacher": True,
            "course_id": course_id,
            "assignment_id": new_assignment.id,
            "submission_id": None,
            "extracted_at": datetime.now(timezone.utc),
            "pdf_file": temp_file_path,
            "qa_pairs": parsed_dict,
        }

        # Insert into MongoDB
        result = db_mongo.qa_extractions.insert_one(mongo_document)
        print(f"Saved teacher Q&A to MongoDB with ID: {result.inserted_id}")

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
            },
        }

    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@router.put(
    "/teacher/course/{course_id}/assignment/{assignment_id}", response_model=dict
)
async def update_assignment(
    course_id: int,
    assignment_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    deadline: Optional[str] = Form(None),  # Format: "YYYY-MM-DD HH:MM"
    grade: Optional[int] = Form(None),
    question_pdf: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    """
    Update an assignment with optional fields:
    - Basic information (name, description, deadline, grade)
    - Question PDF file

    All fields are optional except course_id and assignment_id.
    """
    # First, verify course exists and belongs to the teacher
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    # Find the assignment
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

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
                detail="Invalid deadline format. Use 'YYYY-MM-DD HH:MM'.",
            )

    if grade is not None:
        assignment.grade = grade

    # Handle question PDF update if provided
    if question_pdf:
        # Validate PDF
        if question_pdf.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="Question file must be a PDF")

        temp_file_path = None
        try:
            # Save uploaded PDF to temp file
            with NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                content = await question_pdf.read()
                temp_file.write(content)
                temp_file_path = temp_file.name

            # Validate the format of the question PDF
            extractor = PDFQuestionAnswerExtractor(
                pdf_files=[temp_file_path],
                course_id=course_id,
                assignment_id=assignment_id,
                is_teacher=True,
            )
            teacher_text = extractor.extract_text_from_pdf(temp_file_path)
            parsed_dict = extractor.parse_qa(teacher_text)

            if not parsed_dict:
                raise HTTPException(
                    status_code=400,
                    detail="Assignment PDF is not in the correct format. It must contain 'Question#' and 'Answer#'.",
                )

            # Delete old PDF from S3 if it exists
            if assignment.question_pdf_url:
                delete_success = delete_from_s3(assignment.question_pdf_url)
                if not delete_success:
                    print(
                        f"Warning: Failed to delete old PDF from S3: {assignment.question_pdf_url}"
                    )

            # Upload new PDF to S3
            safe_course_name = sanitize_folder_name(course.name)
            s3_url = upload_to_s3(
                folder_name=f"course_assignments/{current_teacher.id}/{safe_course_name}",
                file_name=f"{assignment_id}_{question_pdf.filename}",
                file_path=temp_file_path,
            )

            if not s3_url:
                raise HTTPException(
                    status_code=500, detail="Failed to upload question PDF"
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
            status_code=500, detail=f"Failed to update assignment: {str(e)}"
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
            "question_pdf_url": assignment.question_pdf_url,
        },
    }


@router.get(
    "/teacher/course/{course_id}/assignment/{assignment_id}", response_model=dict
)
async def get_assignment(
    course_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    # Verify course and assignment ownership
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

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
            "created_at": assignment.created_at.strftime("%Y-%m-%d %H:%M"),
        },
    }


@router.get(
    "/teacher/course/{course_id}/assignment/{assignment_id}/submissions",
    response_model=dict,
)
async def get_assignment_submissions(
    course_id: int,
    assignment_id: int,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    # Verify course and assignment ownership
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(
            status_code=404, detail="Assignment not found or you don't have access"
        )

    offset = (page - 1) * limit

    total = (
        db.query(AssignmentSubmission)
        .join(Student)
        .filter(AssignmentSubmission.assignment_id == assignment_id)
        .count()
    )

    submissions = (
        db.query(AssignmentSubmission, Student)
        .join(Student)
        .filter(AssignmentSubmission.assignment_id == assignment_id)
        .order_by(AssignmentSubmission.submitted_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    submissions_data = []
    for submission, student in submissions:
        submissions_data.append(
            {
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
                "pdf_url": submission.submission_pdf_url,
            }
        )

    return {
        "success": True,
        "status": 200,
        "assignment_id": assignment_id,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "submissions": submissions_data,
        "has_previous": page > 1,
        "has_next": (offset + limit) < total,
    }


@router.post(
    "/teacher/{course_id}/assignment/{assignment_id}/evaluate", response_model=dict
)
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
        assignment = (
            db.query(Assignment)
            .join(Course)
            .filter(
                Assignment.id == assignment_id, Course.teacher_id == current_teacher.id
            )
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=404, detail="Assignment not found or no access"
            )

        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")

        # Get submissions
        submissions = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.assignment_id == assignment_id)
            .all()
        )

        if not submissions:
            raise HTTPException(status_code=404, detail="No submissions found")

        # Initialize RAG
        rag = get_teacher_rag(course.collection_name)

        try:
            # Download teacher PDF
            teacher_temp_file = NamedTemporaryFile(
                delete=False, suffix=".pdf", mode="wb"
            )
            if not download_from_s3(
                assignment.question_pdf_url, teacher_temp_file.name
            ):
                raise HTTPException(
                    status_code=500, detail="Failed to download teacher PDF"
                )
            teacher_temp_file.close()
            temp_files.append(teacher_temp_file.name)
            teacher_pdf_path = teacher_temp_file.name

            # Download student submissions
            submission_paths = {}
            submission_ids = []
            for submission in submissions:
                temp_file = NamedTemporaryFile(delete=False, suffix=".pdf", mode="wb")
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
            request_dict["grammar_delay"] = 0.2  # Reduced from 0.5
            request_dict["ai_detection_delay"] = 0.5  # Reduced from 1.0
            request_dict["feedback_delay"] = 0.3  # Add this for feedback generation
            modified_request = EvaluationRequest(**request_dict)

            # Initialize AssignmentEvaluator with modified request
            evaluator = AssignmentEvaluator(
                course_id=course_id,
                assignment_id=assignment_id,
                request=modified_request,
                rag=rag,
                db=db,
            )

            # Print evaluation configuration for debugging
            print(
                f"Evaluation configuration: AI detection: {request.enable_ai_detection}, Grammar: {request.enable_grammar}, Plagiarism: {request.enable_plagiarism}"
            )
            print(
                f"Rate limiting: Grammar delay: 0.2s, AI detection delay: 0.5s, Feedback delay: 0.3s"
            )

            db_mongo.evaluation_results.delete_many(
                {"course_id": course_id, "assignment_id": assignment_id}
            )
            print(
                f"Removed existing MongoDB evaluations for assignment {assignment_id}"
            )

            # Run evaluation
            evaluator.run(
                pdf_files=pdf_files,
                total_grade=assignment.grade,
                submission_ids=submission_ids,
            )

            # Wait briefly to ensure MongoDB updates have completed
            time.sleep(0.5)

            # Collect evaluation results and generate reports
            for submission_id, temp_path in submission_paths.items():
                # We need to find the evaluation by the submission_id
                submission_data = db_mongo.evaluation_results.find_one(
                    {
                        "course_id": course_id,
                        "assignment_id": assignment_id,
                        "submission_id": submission_id,
                    }
                )

                if submission_data:
                    # Find the submission and student
                    submission = (
                        db.query(AssignmentSubmission)
                        .filter(AssignmentSubmission.id == submission_id)
                        .first()
                    )

                    if not submission:
                        continue

                    student = (
                        db.query(Student)
                        .filter(Student.id == submission.student_id)
                        .first()
                    )
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

                    # Create PDF report with MongoDB data
                    try:
                        report_generator = PDFReportGenerator()

                        # Generate filename for the report
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        safe_student_id = str(student.student_id).replace("/", "_")
                        report_filename = f"report_{safe_student_id}_{timestamp}.pdf"

                        print(
                            f"Generating report for student {student.full_name} (ID: {student.student_id})"
                        )

                        # Process the submission - download, append report, upload
                        report_url = report_generator.process_submission_with_report(
                            mongo_data=submission_data,
                            student_pdf_url=submission.submission_pdf_url,
                            total_possible=float(assignment.grade),
                            student_name=student.full_name,
                            course_name=course.name,
                            assignment_name=assignment.name,
                            folder_name=f"assignment_reports/{course_id}/{assignment_id}",
                            output_filename=report_filename,
                        )

                        print(
                            f"Report generation result for submission {submission_id}: {report_url}"
                        )

                        # Update MongoDB with the report URL
                        if report_url:
                            update_result = db_mongo.evaluation_results.update_one(
                                {
                                    "course_id": course_id,
                                    "assignment_id": assignment_id,
                                    "submission_id": submission_id,
                                },
                                {"$set": {"report_url": report_url}},
                            )
                            print(
                                f"MongoDB update result: {update_result.modified_count} documents modified"
                            )

                            # Verify the update
                            updated_doc = db_mongo.evaluation_results.find_one(
                                {
                                    "course_id": course_id,
                                    "assignment_id": assignment_id,
                                    "submission_id": submission_id,
                                }
                            )
                            print(
                                f"Verified report URL in MongoDB: {updated_doc.get('report_url', 'NOT FOUND')}"
                            )
                        else:
                            print(
                                f"Failed to generate report for submission {submission_id}"
                            )

                    except Exception as report_error:
                        print(
                            f"Error generating report for submission {submission_id}: {str(report_error)}"
                        )
                        import traceback

                        traceback.print_exc()

                    # Create evaluation result with report URL
                    result = {
                        "name": student.full_name,
                        "batch": student.batch,
                        "department": student.department,
                        "section": student.section,
                        "total_score": overall_scores.get("total", {}).get("score", 0),
                        "avg_context_score": overall_scores.get("context", {}).get(
                            "score", 0
                        ),
                        "avg_plagiarism_score": overall_scores.get(
                            "plagiarism", {}
                        ).get("score", 0),
                        "avg_ai_score": overall_scores.get("ai_detection", {}).get(
                            "score", 0
                        ),
                        "avg_grammar_score": overall_scores.get("grammar", {}).get(
                            "score", 0
                        ),
                        "feedback": feedback_content,
                        "image": student.image_url,
                        "report_url": report_url,
                    }

                    # Add result to list
                    evaluation_results.append(result)

                    # Update or create PostgreSQL record
                    existing_eval = (
                        db.query(AssignmentEvaluation)
                        .filter(AssignmentEvaluation.submission_id == submission_id)
                        .first()
                    )

                    if existing_eval:
                        # Update existing evaluation
                        print(
                            f"Updating existing evaluation for submission {submission_id}"
                        )
                        existing_eval.total_score = overall_scores.get("total", {}).get(
                            "score", 0
                        )
                        existing_eval.plagiarism_score = overall_scores.get(
                            "plagiarism", {}
                        ).get("score", 0)
                        existing_eval.ai_detection_score = overall_scores.get(
                            "ai_detection", {}
                        ).get("score", 0)
                        existing_eval.grammar_score = overall_scores.get(
                            "grammar", {}
                        ).get("score", 0)
                        existing_eval.feedback = feedback_content
                        existing_eval.updated_at = datetime.now()
                    else:
                        # Create new evaluation record
                        print(f"Creating new evaluation for submission {submission_id}")
                        new_eval = AssignmentEvaluation(
                            submission_id=submission_id,
                            total_score=overall_scores.get("total", {}).get("score", 0),
                            plagiarism_score=overall_scores.get("plagiarism", {}).get(
                                "score", 0
                            ),
                            ai_detection_score=overall_scores.get(
                                "ai_detection", {}
                            ).get("score", 0),
                            grammar_score=overall_scores.get("grammar", {}).get(
                                "score", 0
                            ),
                            feedback=feedback_content,
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
        "results": evaluation_results,
    }


@router.get(
    "/teacher/course/{course_id}/assignment/{assignment_id}/submission/{submission_id}",
    response_model=dict,
)
async def get_submission_details(
    course_id: int,
    assignment_id: int,
    submission_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    # Verify course and assignment ownership
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    submission = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.id == submission_id,
            AssignmentSubmission.assignment_id == assignment_id,
        )
        .first()
    )

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # First check evaluation_results collection using submission_id
    submission_data = db_mongo.evaluation_results.find_one(
        {
            "course_id": course_id,
            "assignment_id": assignment_id,
            "submission_id": submission_id,
        }
    )

    # If not found, try the alternate format (pdf_file as numeric ID)
    if not submission_data:
        submission_data = db_mongo.evaluation_results.find_one(
            {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "pdf_file": submission_id,
            }
        )

    # Make a deepcopy to avoid modifying the original document
    if submission_data:
        # We want to preserve all the original data
        processed_data = dict(submission_data)

        # Try to get question-answer extraction data from qa_extraction collection
        qa_data = db_mongo.qa_extractions.find_one(
            {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "submission_id": submission_id,
                "is_teacher": False,  # Make sure we're getting student's answers
            }
        )

        if not qa_data:
            # Try again with pdf_file
            qa_data = db_mongo.qa_extractions.find_one(
                {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "pdf_file": submission_id,
                    "is_teacher": False,
                }
            )

        # Also get teacher's questions for reference
        teacher_qa = db_mongo.qa_extractions.find_one(
            {"course_id": course_id, "assignment_id": assignment_id, "is_teacher": True}
        )

        # Process and enhance questions with their text if available
        questions = processed_data.get("questions", [])

        if qa_data and "qa_pairs" in qa_data:
            # Create a mapping from question number to student answers
            qa_map = {}
            qa_pairs = qa_data.get("qa_pairs", {})

            # Handle both dictionary and list formats
            if isinstance(qa_pairs, dict):
                for key, value in qa_pairs.items():
                    if key.startswith("Question#"):
                        q_num = int(key.replace("Question#", ""))
                        answer_key = f"Answer#{q_num}"
                        qa_map[q_num] = {
                            "question": value,
                            "answer": qa_pairs.get(answer_key, ""),
                        }
            elif isinstance(qa_pairs, list):
                for pair in qa_pairs:
                    if isinstance(pair, dict):
                        q_num = pair.get("question_number")
                        if q_num:
                            qa_map[q_num] = {
                                "question": pair.get("question", ""),
                                "answer": pair.get("answer", ""),
                            }

            # Create a mapping from question number to teacher questions
            teacher_qa_map = {}
            teacher_pairs = teacher_qa.get("qa_pairs", {}) if teacher_qa else {}

            # Handle both dictionary and list formats for teacher Q&A
            if isinstance(teacher_pairs, dict):
                for key, value in teacher_pairs.items():
                    if key.startswith("Question#"):
                        q_num = int(key.replace("Question#", ""))
                        answer_key = f"Answer#{q_num}"
                        teacher_qa_map[q_num] = {
                            "question": value,
                            "answer": teacher_pairs.get(answer_key, ""),
                        }
            elif isinstance(teacher_pairs, list):
                for pair in teacher_pairs:
                    if isinstance(pair, dict):
                        q_num = pair.get("question_number")
                        if q_num:
                            teacher_qa_map[q_num] = {
                                "question": pair.get("question", ""),
                                "answer": pair.get("answer", ""),
                            }

            # Enhance questions with text (while preserving all original data)
            for question in questions:
                q_num = question.get("question_number")

                # Add student's answer if available
                if q_num in qa_map:
                    question["question_text"] = qa_map[q_num].get("question", "")
                    question["student_answer"] = qa_map[q_num].get("answer", "")
                    # Add question scores if available
                    scores = question.get("scores", {})
                    question["question_score"] = scores.get("total", {}).get("score", 0)

                # Add teacher's question if available
                if q_num in teacher_qa_map:
                    if not question.get("question_text"):
                        question["question_text"] = teacher_qa_map[q_num].get(
                            "question", ""
                        )
                    question["teacher_answer"] = teacher_qa_map[q_num].get("answer", "")

            processed_data["questions"] = questions

        # Use the processed data with enhanced questions
        submission_data = processed_data

    else:
        # Check PostgreSQL database for evaluation data
        evaluation = (
            db.query(AssignmentEvaluation)
            .filter(AssignmentEvaluation.submission_id == submission_id)
            .first()
        )

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
                        "evaluated_at": (
                            evaluation.updated_at.isoformat()
                            if evaluation.updated_at
                            else datetime.now().isoformat()
                        ),
                    },
                    "plagiarism": {
                        "score": float(evaluation.plagiarism_score or 0.0),
                        "evaluated_at": (
                            evaluation.updated_at.isoformat()
                            if evaluation.updated_at
                            else datetime.now().isoformat()
                        ),
                    },
                    "ai_detection": {
                        "score": float(evaluation.ai_detection_score or 0.0),
                        "evaluated_at": (
                            evaluation.updated_at.isoformat()
                            if evaluation.updated_at
                            else datetime.now().isoformat()
                        ),
                    },
                    "grammar": {
                        "score": float(evaluation.grammar_score or 0.0),
                        "evaluated_at": (
                            evaluation.updated_at.isoformat()
                            if evaluation.updated_at
                            else datetime.now().isoformat()
                        ),
                    },
                },
                "overall_feedback": {
                    "content": evaluation.feedback or "",
                    "generated_at": (
                        evaluation.updated_at.isoformat()
                        if evaluation.updated_at
                        else datetime.now().isoformat()
                    ),
                },
                "questions": [],
            }

            # Try to get question-answer extraction data to add questions
            qa_data = db_mongo.qa_extractions.find_one(
                {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "submission_id": submission_id,
                    "is_teacher": False,
                }
            )

            if not qa_data:
                qa_data = db_mongo.qa_extractions.find_one(
                    {
                        "course_id": course_id,
                        "assignment_id": assignment_id,
                        "pdf_file": submission_id,
                        "is_teacher": False,
                    }
                )

            # Get teacher's questions
            teacher_qa = db_mongo.qa_extractions.find_one(
                {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "is_teacher": True,
                }
            )

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
                        questions.append(
                            {
                                "question_number": q_num,
                                "question_text": pair.get("question", ""),
                                "student_answer": pair.get("answer", ""),
                                "teacher_answer": teacher_answer,
                                "scores": {
                                    "context": {
                                        "score": 0.0,
                                        "evaluated_at": (
                                            evaluation.updated_at.isoformat()
                                            if evaluation.updated_at
                                            else datetime.now().isoformat()
                                        ),
                                    },
                                    "plagiarism": {
                                        "score": 0.0,
                                        "copied_sentence": "",
                                        "evaluated_at": (
                                            evaluation.updated_at.isoformat()
                                            if evaluation.updated_at
                                            else datetime.now().isoformat()
                                        ),
                                    },
                                    "ai_detection": {
                                        "score": 0.0,
                                        "evaluated_at": (
                                            evaluation.updated_at.isoformat()
                                            if evaluation.updated_at
                                            else datetime.now().isoformat()
                                        ),
                                    },
                                    "grammar": {
                                        "score": 0.0,
                                        "evaluated_at": (
                                            evaluation.updated_at.isoformat()
                                            if evaluation.updated_at
                                            else datetime.now().isoformat()
                                        ),
                                    },
                                },
                                "feedback": {
                                    "content": "",
                                    "generated_at": (
                                        evaluation.updated_at.isoformat()
                                        if evaluation.updated_at
                                        else datetime.now().isoformat()
                                    ),
                                },
                            }
                        )

                submission_data["questions"] = sorted(
                    questions, key=lambda x: x["question_number"]
                )
        else:
            raise HTTPException(status_code=404, detail="Submission details not found")

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
            "image": student.image_url,
        }

    # Add submission information
    submission_data["submission"] = {
        "id": submission.id,
        "submitted_at": submission.submitted_at.strftime("%I:%M %p - %d/%b/%Y"),
        "pdf_url": submission.submission_pdf_url,
    }

    # Convert MongoDB document to serializable format
    serializable_data = json.loads(json.dumps(submission_data, cls=JSONEncoder))

    return {"success": True, "status": 200, "submission": serializable_data}


@router.get(
    "/teacher/course/{course_id}/assignment/{assignment_id}/total-scores",
    response_model=dict,
)
async def get_total_scores(
    course_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    # Verify course and assignment ownership
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    submissions = (
        db.query(AssignmentSubmission, Student)
        .join(Student)
        .filter(AssignmentSubmission.assignment_id == assignment_id)
        .all()
    )

    try:
        total_scores_data = []
        total_assignment_grade = assignment.grade

        for submission, student in submissions:
            # Try to find evaluation results in MongoDB using submission_id first (more reliable)
            evaluation_data = db_mongo.evaluation_results.find_one(
                {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "submission_id": submission.id,
                }
            )

            # If not found, try fallback method
            if not evaluation_data:
                evaluation_data = db_mongo.evaluation_results.find_one(
                    {
                        "course_id": course_id,
                        "assignment_id": assignment_id,
                        "pdf_file": submission.id,
                    }
                )

            if evaluation_data:
                # Get overall scores from evaluation results
                overall_scores = evaluation_data.get("overall_scores", {})

                # Get feedback with proper fallback
                feedback_obj = evaluation_data.get("overall_feedback", {})
                feedback_content = ""
                if isinstance(feedback_obj, dict):
                    feedback_content = feedback_obj.get("content", "")
                elif isinstance(feedback_obj, str):
                    feedback_content = feedback_obj
                context_score = overall_scores.get("context", {}).get("score", 0.0)
                total_score = overall_scores.get("total", {}).get("score", 0.0)

                percentage_score = (
                    (total_score / total_assignment_grade * 100)
                    if total_assignment_grade > 0
                    else 0
                )
                percentage_score = round(percentage_score, 2)

                scores = {
                    "student_id": student.student_id,
                    "id": student.id,
                    "name": student.full_name,
                    "batch": student.batch,
                    "department": student.department,
                    "section": student.section,
                    "image": student.image_url,
                    "total_score": total_score,
                    "total_assignment_grade": total_assignment_grade,
                    "percentage_score": percentage_score,
                    "avg_context_score": context_score,
                    "avg_plagiarism_score": overall_scores.get("plagiarism", {}).get(
                        "score", 0.0
                    ),
                    "avg_ai_score": overall_scores.get("ai_detection", {}).get(
                        "score", 0.0
                    ),
                    "avg_grammar_score": overall_scores.get("grammar", {}).get(
                        "score", 0.0
                    ),
                    "feedback": feedback_content,
                    "report_url": evaluation_data.get("report_url", ""),
                }

                total_scores_data.append(scores)
            else:
                # Fall back to checking PostgreSQL database
                evaluation = (
                    db.query(AssignmentEvaluation)
                    .filter(AssignmentEvaluation.submission_id == submission.id)
                    .first()
                )

                if evaluation:
                    # Calculate percentage score
                    total_score = float(evaluation.total_score or 0.0)
                    percentage_score = (
                        (total_score / total_assignment_grade * 100)
                        if total_assignment_grade > 0
                        else 0
                    )
                    percentage_score = round(percentage_score, 2)

                    scores = {
                        "student_id": student.student_id,
                        "name": student.full_name,
                        "id": student.id,
                        "batch": student.batch,
                        "department": student.department,
                        "section": student.section,
                        "image": student.image_url,
                        "total_score": total_score,
                        "total_assignment_grade": total_assignment_grade,
                        "percentage_score": percentage_score,
                        "avg_context_score": 0.0,  # No context score in SQL
                        "avg_plagiarism_score": float(
                            evaluation.plagiarism_score or 0.0
                        ),
                        "avg_ai_score": float(evaluation.ai_detection_score or 0.0),
                        "avg_grammar_score": float(evaluation.grammar_score or 0.0),
                        "feedback": evaluation.feedback or "",
                        "report_url": "",  # No report URL in SQL
                    }

                    total_scores_data.append(scores)

        return {"success": True, "status": 200, "total_scores": total_scores_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch scores: {str(e)}")


@router.get(
    "/teacher/course/{course_id}/assignment/{assignment_id}/student/{student_id}/evaluation",
    response_model=dict,
)
async def get_student_evaluation(
    course_id: int,
    assignment_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    total_assignment_grade = assignment.grade
    submission = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == assignment_id,
            AssignmentSubmission.student_id == student_id,
        )
        .first()
    )

    if not submission:
        raise HTTPException(
            status_code=404, detail="No submission found for this student"
        )

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Fetch evaluation data from MongoDB
    evaluation_data = db_mongo.evaluation_results.find_one(
        {
            "course_id": course_id,
            "assignment_id": assignment_id,
            "submission_id": submission.id,
        }
    )

    if not evaluation_data:
        evaluation_data = db_mongo.evaluation_results.find_one(
            {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "pdf_file": submission.id,
            }
        )

    # Fetch Q&A data
    qa_data = db_mongo.qa_extractions.find_one(
        {
            "course_id": course_id,
            "assignment_id": assignment_id,
            "submission_id": submission.id,
            "is_teacher": False,
        }
    )

    if not qa_data:
        qa_data = db_mongo.qa_extractions.find_one(
            {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "pdf_file": submission.id,
                "is_teacher": False,
            }
        )

    # Fetch teacher's Q&A data
    teacher_qa = db_mongo.qa_extractions.find_one(
        {"course_id": course_id, "assignment_id": assignment_id, "is_teacher": True}
    )

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
        evaluation = (
            db.query(AssignmentEvaluation)
            .filter(AssignmentEvaluation.submission_id == submission.id)
            .first()
        )
        question_count = len(detailed_questions)
        question_total_marks = (
            round(total_assignment_grade / question_count, 2)
            if question_count > 0
            else 0
        )

        if not evaluation:
            raise HTTPException(
                status_code=404, detail="No evaluation found for this submission"
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
                detailed_questions.append(
                    {
                        "question_number": i,
                        "question_text": question_text,
                        "student_answer": student_answer,
                        "plagiarism_score": 0,
                        "context_score": 0,
                        "ai_score": 0,
                        "grammar_score": 0,
                        "question_score": 0,
                        "feedback": "",
                    }
                )

        # Only include questions that have content
        detailed_questions = [
            q for q in detailed_questions if q["question_text"] or q["student_answer"]
        ]

        # Process overall feedback
        overall_feedback = evaluation.feedback or ""

        # Calculate percentage score
        total_score = float(evaluation.total_score or 0.0)
        percentage_score = (
            (total_score / total_assignment_grade * 100)
            if total_assignment_grade > 0
            else 0
        )
        percentage_score = round(percentage_score, 2)

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
                "image": student.image_url,
            },
            "total_score": total_score,
            "total_assignment_grade": total_assignment_grade,  # Add assignment grade
            "percentage_score": percentage_score,  # Add percentage score
            "plagiarism_score": float(evaluation.plagiarism_score or 0.0),
            "ai_detection_score": float(evaluation.ai_detection_score or 0.0),
            "grammar_score": float(evaluation.grammar_score or 0.0),
            "feedback": overall_feedback,
            "question_total_marks": question_total_marks,
            "questions": detailed_questions,
            "report_url": "",  # No report URL in SQL
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
            detailed_questions.append(
                {
                    "question_number": q_num,
                    "question_text": question_text,
                    "student_answer": student_answer,
                    "plagiarism_score": scores.get("plagiarism", {}).get("score", 0),
                    "context_score": scores.get("context", {}).get("score", 0),
                    "ai_score": scores.get("ai_detection", {}).get("score", 0),
                    "grammar_score": scores.get("grammar", {}).get("score", 0),
                    "question_score": scores.get("total", {}).get(
                        "score", 0
                    ),  # Include question total score
                    "feedback": feedback_content,
                }
            )

        # Get the total score from MongoDB
        total_score = overall_scores.get("total", {}).get("score", 0)

        # Calculate percentage score
        percentage_score = (
            (total_score / total_assignment_grade * 100)
            if total_assignment_grade > 0
            else 0
        )
        percentage_score = round(percentage_score, 2)
        question_count = len(detailed_questions)
        question_total_marks = (
            round(total_assignment_grade / question_count, 2)
            if question_count > 0
            else 0
        )

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
                "image": student.image_url,
            },
            "total_score": total_score,
            "total_assignment_grade": total_assignment_grade,  # Add assignment grade
            "percentage_score": percentage_score,  # Add percentage score
            "question_total_marks": question_total_marks,  # Add question total marks
            "plagiarism_score": overall_scores.get("plagiarism", {}).get("score", 0),
            "ai_score": overall_scores.get("ai_detection", {}).get("score", 0),
            "grammar_score": overall_scores.get("grammar", {}).get("score", 0),
            "feedback": overall_feedback,
            "questions": sorted(detailed_questions, key=lambda x: x["question_number"]),
            "report_url": evaluation_data.get("report_url", ""),
        }

    return {"success": True, "status": 200, "result": result_data}


@router.delete(
    "/teacher/course/{course_id}/assignment/{assignment_id}", response_model=dict
)
async def delete_assignment(
    course_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    """Delete an assignment and all related data (submissions, evaluations, and MongoDB records)"""
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    try:
        # Get all submissions for this assignment first
        submissions = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.assignment_id == assignment_id)
            .all()
        )

        submission_ids = [submission.id for submission in submissions]

        # Step 1: Delete MongoDB data first
        # Delete evaluation results
        mongo_eval_result = db_mongo.evaluation_results.delete_many(
            {"course_id": course_id, "assignment_id": assignment_id}
        )

        # Delete Q&A extractions for this assignment
        mongo_qa_result = db_mongo.qa_extractions.delete_many(
            {"course_id": course_id, "assignment_id": assignment_id}
        )

        # Step 2: Delete S3 files
        # Delete student submission PDFs from S3
        s3_submissions_deleted = 0
        for submission in submissions:
            if submission.submission_pdf_url:
                if delete_from_s3(submission.submission_pdf_url):
                    s3_submissions_deleted += 1

        # Delete assignment PDF from S3 if exists
        s3_assignment_deleted = False
        if assignment.question_pdf_url:
            s3_assignment_deleted = delete_from_s3(assignment.question_pdf_url)

        # Step 3: Delete SQL data
        # Delete evaluations for all submissions
        evaluations_deleted = 0
        if submission_ids:
            evaluations_deleted = (
                db.query(AssignmentEvaluation)
                .filter(AssignmentEvaluation.submission_id.in_(submission_ids))
                .delete(synchronize_session=False)
            )

        # Delete all submissions for this assignment
        submissions_deleted = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.assignment_id == assignment_id)
            .delete(synchronize_session=False)
        )

        # Step 4: Delete the assignment itself
        db.delete(assignment)
        db.commit()

        return {
            "success": True,
            "status": 200,
            "message": f"Assignment and all related data deleted successfully",
            "details": {
                "assignment_id": assignment_id,
                "submissions_deleted": submissions_deleted,
                "evaluations_deleted": evaluations_deleted,
                "mongo_evaluations_deleted": (
                    mongo_eval_result.deleted_count if mongo_eval_result else 0
                ),
                "mongo_qa_deleted": (
                    mongo_qa_result.deleted_count if mongo_qa_result else 0
                ),
                "s3_files_deleted": {
                    "assignment_file": s3_assignment_deleted,
                    "submission_files": s3_submissions_deleted,
                },
            },
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to delete assignment: {str(e)}"
        )


@router.delete(
    "/teacher/course/{course_id}/assignment/{assignment_id}/submission/{submission_id}",
    response_model=dict,
)
async def delete_student_submission(
    course_id: int,
    assignment_id: int,
    submission_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_admin),
):
    """Delete a specific student's assignment submission with all related data"""
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.teacher_id == current_teacher.id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404, detail="Course not found or you don't have access"
        )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.course_id == course_id)
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Find the submission
    submission = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.id == submission_id,
            AssignmentSubmission.assignment_id == assignment_id,
        )
        .first()
    )

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Get student information for the response
    student = db.query(Student).filter(Student.id == submission.student_id).first()
    student_info = (
        {"id": student.id, "student_id": student.student_id, "name": student.full_name}
        if student
        else {"id": None, "student_id": None, "name": "Unknown"}
    )

    try:
        # Step 1: Delete MongoDB data
        # Delete evaluation results
        mongo_eval_result = db_mongo.evaluation_results.delete_many(
            {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "$or": [{"submission_id": submission_id}, {"pdf_file": submission_id}],
            }
        )

        # Delete Q&A extractions
        mongo_qa_result = db_mongo.qa_extractions.delete_many(
            {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "is_teacher": False,
                "$or": [{"submission_id": submission_id}, {"pdf_file": submission_id}],
            }
        )

        # Step 2: Delete S3 file if exists
        s3_deleted = False
        if submission.submission_pdf_url:
            s3_deleted = delete_from_s3(submission.submission_pdf_url)

        # Step 3: Delete evaluation record from SQL if exists
        evaluation_deleted = (
            db.query(AssignmentEvaluation)
            .filter(AssignmentEvaluation.submission_id == submission_id)
            .delete(synchronize_session=False)
        )

        # Step 4: Delete the submission itself
        db.delete(submission)
        db.commit()

        return {
            "success": True,
            "status": 200,
            "message": "Student submission deleted successfully",
            "details": {
                "student": student_info,
                "submission_id": submission_id,
                "evaluation_deleted": bool(evaluation_deleted),
                "mongo_evaluation_deleted": (
                    mongo_eval_result.deleted_count > 0 if mongo_eval_result else False
                ),
                "mongo_qa_deleted": (
                    mongo_qa_result.deleted_count > 0 if mongo_qa_result else False
                ),
                "s3_file_deleted": s3_deleted,
            },
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to delete submission: {str(e)}"
        )
