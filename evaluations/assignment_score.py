import numpy as np
from sqlalchemy.orm import Session
from typing import Dict

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

        # Add total score for each question to the question results
        for q_key, scores in question_results.items():
            scores["total_score"] = self.calculate_question_score(
                context_score=scores.get("context_score"),
                plagiarism_score=scores.get("plagiarism_score"),
                ai_score=scores.get("ai_score"),
                grammar_score=scores.get("grammar_score")
            )

        return {
            "total_score": np.round(final_total_score, 4),
            "avg_context_score": np.round(avg_context_score, 4),
            "avg_plagiarism_score": np.round(avg_plagiarism_score, 4),
            "avg_ai_score": np.round(avg_ai_score, 4),
            "avg_grammar_score": np.round(avg_grammar_score, 4),
            "questions": question_results
        }