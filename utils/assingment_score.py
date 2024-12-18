import numpy as np
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict
from models.models import AssignmentEvaluation

class AssignmentScoreCalculator:
    def __init__(self, total_grade: float, num_questions: int, db: Session):
        self.total_grade = total_grade
        self.num_questions = num_questions
        self.db = db

    def calculate_question_score(
        self,
        context_score: float,
        plagiarism_score: float = None,
        ai_score: float = None,
        grammar_score: float = None
    ) -> float:
        # Ensure all scores are floats and not None
        context_score = float(context_score) if context_score is not None else 0.0
        plagiarism_score = float(plagiarism_score) if plagiarism_score is not None else 0.0
        ai_score = float(ai_score) if ai_score is not None else 0.0
        grammar_score = float(grammar_score) if grammar_score is not None else 0.0

        # Calculate base score
        if plagiarism_score > 1:
            total_score = 0.0
        else:
            total_score = context_score - (context_score * min(plagiarism_score, 0.7))  # Apply penalty, max 70%

        total_score -= (context_score * min(ai_score, 0.7))  # Apply AI detection penalty, max 70%
        total_score -= (context_score * min(grammar_score, 0.7))  # Apply grammar penalty, max 70%

        # Ensure the total score is not negative
        total_score = max(total_score, 0.0)

        return np.round(total_score, 4)

    def calculate_submission_evaluation(
        self,
        submission_id: int,
        question_results: Dict[str, Dict[str, float]]
    ) -> Dict:
        total_score = 0.0
        total_context_score = 0.0
        total_plagiarism_score = 0.0
        total_ai_score = 0.0
        total_grammar_score = 0.0
        question_scores = []

        for q_key, scores in question_results.items():
            question_score = self.calculate_question_score(
                context_score=scores.get("context_score"),
                plagiarism_score=scores.get("plagiarism_score"),
                ai_score=scores.get("ai_score"),
                grammar_score=scores.get("grammar_score")
            )
            question_scores.append(question_score)
            total_score += question_score
            total_context_score += scores.get("context_score", 0.0)
            total_plagiarism_score += scores.get("plagiarism_score", 0.0)
            total_ai_score += scores.get("ai_score", 0.0)
            total_grammar_score += scores.get("grammar_score", 0.0)

        # Calculate average scores
        avg_context_score = total_context_score / self.num_questions if self.num_questions > 0 else 0.0
        avg_plagiarism_score = total_plagiarism_score / self.num_questions if self.num_questions > 0 else 0.0
        avg_ai_score = total_ai_score / self.num_questions if self.num_questions > 0 else 0.0
        avg_grammar_score = total_grammar_score / self.num_questions if self.num_questions > 0 else 0.0

        # Calculate total score by subtracting the penalties
        total_penalty = avg_plagiarism_score + avg_ai_score + avg_grammar_score
        final_total_score = total_score - total_penalty

        # Save evaluation to database (example, adjust as needed)
        evaluation = AssignmentEvaluation(
            submission_id=submission_id,
            total_score=final_total_score,
            plagiarism_score=avg_plagiarism_score,
            ai_detection_score=avg_ai_score,
            grammar_score=avg_grammar_score,
            feedback="",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        self.db.add(evaluation)
        self.db.commit()

        return {
            "total_score": np.round(final_total_score, 4),
            "avg_context_score": np.round(avg_context_score, 4),
            "avg_plagiarism_score": np.round(avg_plagiarism_score, 4),
            "questions": question_results
        }
# def serialize_evaluation(eval_result: AssignmentEvaluation) -> dict:
#     """Convert AssignmentEvaluation model to dictionary"""
#     return {
#         "submission_id": eval_result.submission_id,
#         "total_score": eval_result.total_score,
#         "plagiarism_score": eval_result.plagiarism_score,
#         "ai_detection_score": eval_result.ai_detection_score,
#         "grammar_score": eval_result.grammar_score,
#         "feedback": eval_result.feedback,
#         "created_at": eval_result.created_at.isoformat() if eval_result.created_at else None,
#         "updated_at": eval_result.updated_at.isoformat() if eval_result.updated_at else None
#     }