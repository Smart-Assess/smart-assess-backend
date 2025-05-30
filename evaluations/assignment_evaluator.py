from models.models import AssignmentEvaluation
from utils.mongodb import mongo_db
from evaluations.feedback import FeedbackGenerator
from evaluations.assignment_score import AssignmentScoreCalculator
from evaluations.grammar import GrammarChecker
from evaluations.context_score import ContextScorer
from evaluations.base_extractor import PDFQuestionAnswerExtractor
from pymongo import UpdateOne
from datetime import datetime, timezone
import os
import sys
import time
import logging

# Add logger
logger = logging.getLogger(__name__)

# Get project root path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add to Python path if not already there
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)


class AssignmentEvaluator:
    def __init__(self, course_id: int, assignment_id: int, request, rag, db):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.request = request
        self.rag = rag
        self.db = db

        # Initialize all components that always get used
        self.qa_extractor = PDFQuestionAnswerExtractor(
            [], course_id, assignment_id, is_teacher=False
        )
        self.context_scorer = ContextScorer(course_id, assignment_id, rag)
        self.feedback_generator = FeedbackGenerator(course_id, assignment_id)

        # Initialize optional components early based on request
        self.plagiarism_checker = None
        self.ai_detector = None
        self.grammar_checker = None

        # Log evaluation options
        print(f"Assignment Evaluator initialized with:")
        print(f"  - Course ID: {course_id}")
        print(f"  - Assignment ID: {assignment_id}")
        print(
            f"  - Plagiarism checking: {'Enabled' if request.enable_plagiarism else 'Disabled'}"
        )
        print(
            f"  - Grammar checking: {'Enabled' if request.enable_grammar else 'Disabled'}"
        )
        print(
            f"  - AI detection: {'Enabled' if request.enable_ai_detection else 'Disabled'}"
        )

    def extract_qa_pairs(self, pdf_files, submission_ids=[]):
        teacher_pdf = pdf_files[0]
        student_pdfs = pdf_files[1:]

        teacher_extractor = PDFQuestionAnswerExtractor(
            pdf_files=[teacher_pdf],
            course_id=self.course_id,
            assignment_id=self.assignment_id,
            is_teacher=True,
        )
        teacher_extractor.extract()

        student_extractor = PDFQuestionAnswerExtractor(
            pdf_files=student_pdfs,
            course_id=self.course_id,
            assignment_id=self.assignment_id,
            submission_ids=submission_ids,
            is_teacher=False,
        )
        student_extractor.extract()

    def fetch_qa_pairs(self):
        """Fetch Q&A pairs from MongoDB for the given course and assignment"""
        cursor = mongo_db.db["qa_extractions"].find(
            {"course_id": self.course_id, "assignment_id": self.assignment_id}
        )

        teacher_questions = {}
        questions_answers_by_submission = {}

        for document in cursor:
            submission_id = document["submission_id"]
            if document["is_teacher"]:
                teacher_questions = document.get("qa_pairs", {})
            else:
                questions_answers_by_submission[submission_id] = document.get(
                    "qa_pairs", {}
                )

        return teacher_questions, questions_answers_by_submission

    def run(self, pdf_files, total_grade, submission_ids=None):
        # Extract questions and answers from PDFs
        self.extract_qa_pairs(pdf_files, submission_ids=submission_ids)
        teacher_questions, questions_answers_by_submission = self.fetch_qa_pairs()

        # Process teacher questions to get a clear list of question numbers
        teacher_question_numbers = []
        for key in teacher_questions:
            if key.startswith("Question#"):
                question_number = int(key.replace("Question#", ""))
                teacher_question_numbers.append(question_number)

        teacher_question_numbers.sort()
        print(f"Teacher questions found: {teacher_question_numbers}")

        # Bulk add missing questions
        bulk_qa_updates = []
        for submission_id, qa_pairs in questions_answers_by_submission.items():
            for q_num in teacher_question_numbers:
                question_key = f"Question#{q_num}"
                answer_key = f"Answer#{q_num}"

                if question_key not in qa_pairs:
                    qa_pairs[question_key] = teacher_questions[question_key]
                    qa_pairs[answer_key] = ""

            bulk_qa_updates.append(
                UpdateOne(
                    {
                        "course_id": self.course_id,
                        "assignment_id": self.assignment_id,
                        "submission_id": submission_id,
                        "is_teacher": False,
                    },
                    {"$set": {"qa_pairs": qa_pairs}},
                )
            )

        if bulk_qa_updates:
            mongo_db.db["qa_extractions"].bulk_write(bulk_qa_updates)

        # Context scoring (already optimized with batch BLEURT)
        context_results = self.context_scorer.run(
            teacher_questions,
            questions_answers_by_submission,
            submission_ids,
            total_score=total_grade,
        )
        print(
            f"Context scoring completed: {len(context_results['results'])} submissions processed"
        )

        # Plagiarism checking if enabled
        if self.request.enable_plagiarism:
            try:
                from evaluations.plagiarism import PlagiarismChecker

                self.plagiarism_checker = PlagiarismChecker(
                    self.course_id, self.assignment_id, submission_ids=submission_ids
                )
                plagiarism_results = self.plagiarism_checker.run(
                    teacher_questions,
                    questions_answers_by_submission,
                    submission_ids=submission_ids,
                )
                print(
                    f"Plagiarism checking completed: {len(plagiarism_results['results'])} submissions processed"
                )
            except Exception as e:
                print(f"Error in plagiarism checking: {str(e)}")

        # AI detection if enabled
        if self.request.enable_ai_detection:
            try:
                from evaluations.ai_detection import AIDetector

                self.ai_detector = AIDetector(self.course_id, self.assignment_id)

                # Reduced AI detection delay
                # Reduced from 0.5
                ai_delay = getattr(self.request, "ai_detection_delay", 0.3)
                print(f"Running AI detection with {ai_delay}s delay between API calls")

                ai_results = self.ai_detector.run(
                    teacher_questions,
                    questions_answers_by_submission,
                    submission_ids=submission_ids,
                    delay=ai_delay,
                )
                print(
                    f"AI detection completed: {len(ai_results['results']) if ai_results else 0} submissions processed"
                )
            except Exception as e:
                print(f"Error in AI detection: {str(e)}")

        # Grammar checking with batch processing
        if self.request.enable_grammar:
            print("🔍 Starting grammar checking section...")
            try:
                self.grammar_checker = GrammarChecker()
                grammar_delay = getattr(
                    self.request, "grammar_delay", 0.1
                )  # Reduced from 0.2
                print(f"📝 Grammar checker initialized with delay: {grammar_delay}")

                # Process all submissions' answers in optimized batches
                all_grammar_updates = []
                submission_grammar_scores = {}

                print(
                    f"📊 Processing {len(questions_answers_by_submission)} submissions for grammar"
                )

                for submission_id, qa_pairs in questions_answers_by_submission.items():
                    print(f"📝 Processing grammar for submission {submission_id}")

                    # Collect all answers for this submission
                    answers_to_check = {}
                    for key, text in qa_pairs.items():
                        if key.startswith("Answer#"):
                            answers_to_check[key] = text

                    print(
                        f"📝 Found {len(answers_to_check)} answers to check for submission {submission_id}"
                    )

                    # Batch process all answers for this submission
                    grammar_results = self.grammar_checker.evaluate_batch(
                        answers_to_check, grammar_delay
                    )
                    print(
                        f"📝 Grammar results for submission {submission_id}: {grammar_results}"
                    )

                    grammar_scores = []
                    for key, (corrected_text, grammar_score) in grammar_results.items():
                        q_num = int(key.split("#")[1])
                        grammar_scores.append(grammar_score)

                        # Prepare individual question update
                        all_grammar_updates.append(
                            UpdateOne(
                                {
                                    "course_id": self.course_id,
                                    "assignment_id": self.assignment_id,
                                    "submission_id": submission_id,
                                    "questions.question_number": q_num,
                                },
                                {
                                    "$set": {
                                        "questions.$.scores.grammar": {
                                            "score": round(grammar_score, 4),
                                            "evaluated_at": datetime.now(timezone.utc),
                                        }
                                    }
                                },
                            )
                        )

                    # Calculate average grammar score for submission
                    avg_grammar = (
                        sum(grammar_scores) / len(grammar_scores)
                        if grammar_scores
                        else 0
                    )
                    submission_grammar_scores[submission_id] = avg_grammar

                # Execute all grammar updates in one bulk operation
                if all_grammar_updates:
                    mongo_db.db["evaluation_results"].bulk_write(all_grammar_updates)

                # Update overall grammar scores in bulk
                overall_grammar_updates = []
                for submission_id, avg_score in submission_grammar_scores.items():
                    overall_grammar_updates.append(
                        UpdateOne(
                            {
                                "course_id": self.course_id,
                                "assignment_id": self.assignment_id,
                                "submission_id": submission_id,
                            },
                            {
                                "$set": {
                                    "overall_scores.grammar": {
                                        "score": round(avg_score, 4),
                                        "evaluated_at": datetime.now(timezone.utc),
                                    }
                                }
                            },
                        )
                    )

                if overall_grammar_updates:
                    mongo_db.db["evaluation_results"].bulk_write(
                        overall_grammar_updates
                    )

            except Exception as e:
                print(f"Error in grammar checking: {str(e)}")
        else:
            print("❌ Grammar checking is disabled")

        # Generate feedback for each submission
        try:
            feedback_delay = getattr(self.request, "feedback_delay", 1.0)
            print(
                f"Running feedback generation with {feedback_delay}s delay between API calls"
            )

            for i, pdf_file in enumerate(pdf_files[1:]):  # Skip teacher PDF
                if i < len(submission_ids):
                    submission_id = submission_ids[i]
                    feedback_result = self.feedback_generator.run(
                        [pdf_file], [submission_id], delay=feedback_delay
                    )
                    print(
                        f"Feedback generated for submission {submission_id}: {feedback_result}"
                    )
        except Exception as e:
            print(f"Error generating feedback: {str(e)}")

        # Initialize score calculator early
        score_calculator = AssignmentScoreCalculator(
            total_grade=total_grade,
            # Divide by 2 since we have Q&A pairs
            num_questions=len(teacher_questions) // 2,
            db=self.db,
        )

        # Calculate total scores for all submissions - OPTIMIZED
        total_scores = []
        final_score_updates = []

        for i, pdf_file in enumerate(pdf_files[1:]):  # Skip teacher PDF
            if i < len(submission_ids):
                submission_id = submission_ids[i]

                # Get evaluation data from MongoDB
                eval_doc = mongo_db.db["evaluation_results"].find_one(
                    {
                        "course_id": self.course_id,
                        "assignment_id": self.assignment_id,
                        "submission_id": submission_id,
                    }
                )

                if eval_doc:
                    questions = eval_doc.get("questions", [])
                    question_results = {}

                    # Calculate score for each question
                    for question in questions:
                        q_num = question.get("question_number")
                        scores = question.get("scores", {})

                        print(
                            f"Processing question {q_num}, scores type: {type(scores)}, scores: {scores}"
                        )

                        # Safely extract scores, handling both dict and float formats
                        try:
                            context_score = (
                                scores.get("context", {})
                                if isinstance(scores, dict)
                                else {}
                            )
                            print(
                                f"Context score raw: {context_score}, type: {type(context_score)}"
                            )

                            if isinstance(context_score, dict):
                                context_score = context_score.get("score", 0)
                            else:
                                context_score = (
                                    float(context_score)
                                    if context_score is not None
                                    else 0
                                )

                            plagiarism_score = (
                                scores.get("plagiarism", {})
                                if isinstance(scores, dict)
                                else {}
                            )
                            if isinstance(plagiarism_score, dict):
                                plagiarism_score = plagiarism_score.get("score", 0)
                            else:
                                plagiarism_score = (
                                    float(plagiarism_score)
                                    if plagiarism_score is not None
                                    else 0
                                )

                            ai_score = (
                                scores.get("ai_detection", {})
                                if isinstance(scores, dict)
                                else {}
                            )
                            if isinstance(ai_score, dict):
                                ai_score = ai_score.get("score", 0)
                            else:
                                ai_score = (
                                    float(ai_score) if ai_score is not None else 0
                                )

                            grammar_score = (
                                scores.get("grammar", {})
                                if isinstance(scores, dict)
                                else {}
                            )
                            if isinstance(grammar_score, dict):
                                grammar_score = grammar_score.get("score", 0)
                            else:
                                grammar_score = (
                                    float(grammar_score)
                                    if grammar_score is not None
                                    else 0
                                )

                            print(
                                f"Extracted scores - context: {context_score}, plagiarism: {plagiarism_score}, ai: {ai_score}, grammar: {grammar_score}"
                            )

                            question_score = score_calculator.calculate_question_score(
                                context_score=context_score,
                                plagiarism_score=plagiarism_score,
                                ai_score=ai_score,
                                grammar_score=grammar_score,
                            )

                            question_results[f"Question#{q_num}"] = {
                                "context_score": context_score,
                                "plagiarism_score": plagiarism_score,
                                "ai_score": ai_score,
                                "grammar_score": grammar_score,
                                "total_score": question_score,
                            }

                        except Exception as e:
                            logger.error(
                                f"Error processing scores for question {q_num}: {e}"
                            )
                            logger.error(f"Scores object: {scores}")
                            # Set default values
                            question_results[f"Question#{q_num}"] = {
                                "context_score": 0,
                                "plagiarism_score": 0,
                                "ai_score": 0,
                                "grammar_score": 0,
                                "total_score": 0,
                            }

                    # Calculate final evaluation
                    evaluation_result = (
                        score_calculator.calculate_submission_evaluation(
                            question_results=question_results
                        )
                    )

                    # Prepare bulk update for total scores and question scores
                    update_fields = {
                        "overall_scores.total": {
                            "score": evaluation_result["total_score"],
                            "evaluated_at": datetime.now(timezone.utc),
                        }
                    }

                    # Add other scores if they exist
                    if "avg_context_score" in evaluation_result:
                        update_fields["overall_scores.context"] = {
                            "score": evaluation_result["avg_context_score"],
                            "evaluated_at": datetime.now(timezone.utc),
                        }

                    # Prepare question score updates
                    question_score_updates = []
                    for question in questions:
                        q_num = question.get("question_number")
                        q_key = f"Question#{q_num}"
                        if q_key in question_results:
                            question_score_updates.append(
                                UpdateOne(
                                    {
                                        "course_id": self.course_id,
                                        "assignment_id": self.assignment_id,
                                        "submission_id": submission_id,
                                        "questions.question_number": q_num,
                                    },
                                    {
                                        "$set": {
                                            "questions.$.scores.total": {
                                                "score": round(
                                                    question_results[q_key][
                                                        "total_score"
                                                    ],
                                                    4,
                                                ),
                                                "evaluated_at": datetime.now(
                                                    timezone.utc
                                                ),
                                            }
                                        }
                                    },
                                )
                            )

                    # Add to bulk operations
                    final_score_updates.append(
                        UpdateOne(
                            {
                                "course_id": self.course_id,
                                "assignment_id": self.assignment_id,
                                "submission_id": submission_id,
                            },
                            {"$set": update_fields},
                        )
                    )

                    # Execute question score updates
                    if question_score_updates:
                        mongo_db.db["evaluation_results"].bulk_write(
                            question_score_updates
                        )

                    total_scores.append(
                        {
                            "submission_id": submission_id,
                            "total_score": evaluation_result["total_score"],
                            "context_score": evaluation_result.get(
                                "avg_context_score", 0
                            ),
                            "plagiarism_score": evaluation_result.get(
                                "avg_plagiarism_score", 0
                            ),
                            "ai_score": evaluation_result.get("avg_ai_score", 0),
                            "grammar_score": evaluation_result.get(
                                "avg_grammar_score", 0
                            ),
                        }
                    )

        # Execute all final score updates in one operation
        if final_score_updates:
            mongo_db.db["evaluation_results"].bulk_write(final_score_updates)

        print(f"Total scores calculated: {len(total_scores)}")
        return total_scores


if __name__ == "__main__":
    from bestrag import BestRAG
    from utils.dependencies import get_db
    from models.pydantic_model import EvaluationRequest
    from dotenv import load_dotenv

    load_dotenv()

    rag = BestRAG(
        url="https://3c2bb745-57c0-478a-b61f-af487f8382e8.eu-central-1-0.aws.cloud.qdrant.io:6333",
        api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwiZXhwIjoxNzQ3MzM3NzY4fQ.AEDv7pPyzgF2U1Od9NGbmcC2r5LahxLIPyb_KybZYhQ",
        collection_name="fyptest",
    )

    request = EvaluationRequest(
        enable_plagiarism=True, enable_grammar=True, enable_ai_detection=True
    )

    # Get a new database session
    db = next(get_db())

    try:
        evaluator = AssignmentEvaluator(
            course_id=1, assignment_id=1, request=request, rag=rag, db=db
        )
        evaluator.run(
            pdf_files=[
                "/home/samadpls/proj/fyp/smart-assess-backend/37.pdf",
                "/home/samadpls/proj/fyp/smart-assess-backend/p1.pdf",
            ],
            total_grade=100,
            submission_ids=[1, 2],
        )
    finally:
        db.close()
