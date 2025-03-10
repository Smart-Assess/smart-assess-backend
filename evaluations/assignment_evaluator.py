from datetime import datetime, timezone
import os
import sys
# Get project root path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add to Python path if not already there
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)
from evaluations.base_extractor import PDFQuestionAnswerExtractor
from evaluations.context_score import ContextScorer
from evaluations.plagiarism import PlagiarismChecker
from evaluations.grammar import GrammarChecker
from evaluations.assignment_score import AssignmentScoreCalculator
from utils.mongodb import mongo_db
from models.models import AssignmentEvaluation

class AssignmentEvaluator:
    def __init__(self, course_id: int, assignment_id: int, request, rag, db):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.request = request
        self.rag = rag
        self.db = db
        self.qa_extractor = PDFQuestionAnswerExtractor([], course_id, assignment_id, is_teacher=False)
        self.context_scorer = ContextScorer(course_id, assignment_id, rag)
        self.plagiarism_checker = None
        self.grammar_checker = None
        if request.enable_plagiarism:
            self.plagiarism_checker = PlagiarismChecker(course_id, assignment_id)
        if request.enable_grammar:
            self.grammar_checker = GrammarChecker()

    def extract_qa_pairs(self, pdf_files):
        self.qa_extractor.pdf_files = pdf_files
        self.qa_extractor.extract()

    def fetch_qa_pairs(self):
        """Fetch Q&A pairs from MongoDB for the given course and assignment"""
        cursor = mongo_db.db['qa_extractions'].find({
            "course_id": self.course_id,
            "assignment_id": self.assignment_id
        })

        teacher_questions = {}
        questions_answers_by_pdf = {}

        for document in cursor:
            pdf_file = document['pdf_file']
            if document['is_teacher']:
                teacher_questions = document.get('qa_pairs', {})
            else:
                questions_answers_by_pdf[pdf_file] = document.get('qa_pairs', {})

        return teacher_questions, questions_answers_by_pdf

    def run(self, pdf_files, total_grade, submission_ids):
        self.extract_qa_pairs(pdf_files)
        teacher_questions, questions_answers_by_pdf = self.fetch_qa_pairs()

        _ = self.context_scorer.run(teacher_questions, questions_answers_by_pdf)
        if self.plagiarism_checker:
            _ = self.plagiarism_checker.run(teacher_questions, questions_answers_by_pdf)

        # Combine results and calculate total scores
        for pdf_file, submission_id in zip(pdf_files[1:], submission_ids):
            submission_data = mongo_db.db['evaluation_results'].find_one({
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "pdf_file": pdf_file
            })

            if submission_data:
                question_results = {}
                for question in submission_data.get("questions", []):
                    q_num = question["question_number"]
                    context_score = question["scores"].get("context", {}).get("score", 0)
                    plagiarism_score = question["scores"].get("plagiarism", {}).get("score", 0)
                    ai_score = question["scores"].get("ai_detection", {}).get("score", 0)
                    grammar_score = question["scores"].get("grammar", {}).get("score", 0)
                    
                    # Evaluate grammar if enabled
                    if self.grammar_checker:
                        answer_text = question["answer"]
                        corrected_text, grammar_score = self.grammar_checker.evaluate(answer_text)
                    
                    question_results[f"Question#{q_num}"] = {
                        "context_score": context_score,
                        "plagiarism_score": plagiarism_score,
                        "ai_score": ai_score,
                        "grammar_score": grammar_score
                    }

                # Calculate total score
                score_calculator = AssignmentScoreCalculator(
                    total_grade=total_grade,
                    num_questions=len(question_results),
                    db=self.db
                )
                evaluation_result = score_calculator.calculate_submission_evaluation(
                    question_results=question_results
                )

                # Save to PostgreSQL
                evaluation = AssignmentEvaluation(
                    submission_id=submission_id,
                    total_score=evaluation_result["total_score"],
                    plagiarism_score=evaluation_result["avg_plagiarism_score"],
                    ai_detection_score=evaluation_result["avg_ai_score"],
                    grammar_score=evaluation_result["avg_grammar_score"],
                    feedback=None
                )
                self.db.add(evaluation)
                self.db.commit()

                # Save individual question results to MongoDB
                for q_num, scores in evaluation_result["questions"].items():
                    update_data = {
                        "questions.$.scores.total": {
                            "score": scores["total_score"],
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                    }
                    if self.grammar_checker:
                        update_data["questions.$.scores.grammar"] = {
                            "score": scores["grammar_score"],
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                    mongo_db.db['evaluation_results'].update_one(
                        {
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "pdf_file": pdf_file,
                            "questions.question_number": int(q_num.split('#')[1])
                        },
                        {
                            "$set": update_data
                        }
                    )


if __name__ == "__main__":
    from bestrag import BestRAG
    from utils.dependencies import get_db
    from models.pydantic_model import EvaluationRequest
    from dotenv import load_dotenv

    load_dotenv()

    rag = BestRAG(
        url="https://3c2bb745-57c0-478a-b61f-af487f8382e8.eu-central-1-0.aws.cloud.qdrant.io:6333",
        api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwiZXhwIjoxNzQ3MzM3NzY4fQ.AEDv7pPyzgF2U1Od9NGbmcC2r5LahxLIPyb_KybZYhQ",
        collection_name="fyptest"
    )

    request = EvaluationRequest(enable_plagiarism=False, enable_grammar=True)

    # Get a new database session
    db = next(get_db())

    try:
        evaluator = AssignmentEvaluator(course_id=1, assignment_id=1, request=request, rag=rag, db=db)
        evaluator.run(pdf_files=[
            "/home/samadpls/proj/fyp/smart-assess-backend/37.pdf",
            "/home/samadpls/proj/fyp/smart-assess-backend/p1.pdf"
        ], total_grade=3, submission_ids=[1, 2])
    finally:
        db.close()