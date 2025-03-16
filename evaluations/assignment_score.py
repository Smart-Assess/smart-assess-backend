import numpy as np
from sqlalchemy.orm import Session
from typing import Dict

class AssignmentScoreCalculator:
    def __init__(self, total_grade: float, num_questions: int, db: Session):
        self.total_grade = total_grade
        self.num_questions = num_questions
        self.db = db
        
        # Penalty configuration
        self.plagiarism_penalty = 0.2  # 20% penalty
        self.ai_detection_penalty = 0.2  # 20% penalty
        self.grammar_penalty = 0.2  # 20% penalty
        self.max_penalty = 0.7  # Maximum penalty for any category (70%)

    def calculate_question_score(
        self,
        context_score: float,
        plagiarism_score: float = None,
        ai_score: float = None,
        grammar_score: float = None
    ) -> float:
        """Calculate the score for a single question based on various metrics"""
        # Ensure all scores are floats with proper defaults
        context_score = float(context_score) if context_score is not None else 0.0
        plagiarism_score = float(plagiarism_score) if plagiarism_score is not None else 0.0
        ai_score = float(ai_score) if ai_score is not None else 0.0
        grammar_score = float(grammar_score) if grammar_score is not None else 0.0
        
        # Start with context score (basis for grading)
        base_score = context_score
        
        # Apply penalties if scores are available
        total_penalty = 0
        
        # Plagiarism penalty (lower score = more plagiarism, so apply penalty for low scores)
        if plagiarism_score is not None and plagiarism_score < 1.0:
            plagiarism_penalty = (1 - plagiarism_score) * self.plagiarism_penalty
            total_penalty += plagiarism_penalty
        
        # AI detection penalty (higher score = more AI-generated, so apply penalty for high scores)
        if ai_score is not None and ai_score > 0:
            ai_penalty = ai_score * self.ai_detection_penalty
            total_penalty += ai_penalty
        
        # Grammar penalty (lower score = worse grammar, so apply penalty for low scores)
        if grammar_score is not None and grammar_score < 1.0:
            grammar_penalty = (1 - grammar_score) * self.grammar_penalty
            total_penalty += grammar_penalty
        
        # Cap total penalty
        total_penalty = min(total_penalty, self.max_penalty)
        
        # Apply penalty to base score
        adjusted_score = base_score * (1 - total_penalty)
        
        # Debug output
        print(f"Question score calculation:")
        print(f"  Base (context) score: {base_score}")
        print(f"  Plagiarism score: {plagiarism_score}, penalty: {(1 - plagiarism_score) * self.plagiarism_penalty if plagiarism_score is not None else 0}")
        print(f"  AI score: {ai_score}, penalty: {ai_score * self.ai_detection_penalty if ai_score is not None else 0}")
        print(f"  Grammar score: {grammar_score}, penalty: {(1 - grammar_score) * self.grammar_penalty if grammar_score is not None else 0}")
        print(f"  Total penalty: {total_penalty}")
        print(f"  Final adjusted score: {adjusted_score}")
        
        return adjusted_score

    def calculate_submission_evaluation(
        self,
        question_results: Dict[str, Dict[str, float]]
    ) -> Dict:
        """Calculate overall evaluation scores based on per-question results"""
        # Initialize counters for different score types
        total_score = 0
        context_sum = 0
        plagiarism_sum = 0
        ai_sum = 0
        grammar_sum = 0
        
        # Track which metrics have values
        has_context = False
        has_plagiarism = False
        has_ai = False
        has_grammar = False
        
        # Process each question's scores
        for question_key, scores in question_results.items():
            # Get individual scores with proper defaults
            context_score = scores.get("context_score", 0)
            plagiarism_score = scores.get("plagiarism_score", 0)
            ai_score = scores.get("ai_score", 0)
            grammar_score = scores.get("grammar_score", 0)
            
            # Add to totals
            context_sum += context_score
            if context_score > 0:
                has_context = True
                
            plagiarism_sum += plagiarism_score
            if plagiarism_score > 0:
                has_plagiarism = True
                
            ai_sum += ai_score
            if ai_score > 0:
                has_ai = True
                
            grammar_sum += grammar_score
            if grammar_score > 0:
                has_grammar = True
            
            # Calculate question score based on all available metrics
            question_score = self.calculate_question_score(
                context_score=context_score,
                plagiarism_score=plagiarism_score,
                ai_score=ai_score,
                grammar_score=grammar_score
            )
            
            # Add to total score
            total_score += question_score
        
        # Calculate per-question share of total grade
        question_count = max(len(question_results), 1)  # Avoid division by zero
        
        # Scale the total score to match the total grade
        scaled_total_score = (total_score / question_count) * self.total_grade
        
        # Calculate averages for the metrics that have values
        avg_context = context_sum / question_count if has_context else 0
        avg_plagiarism = plagiarism_sum / question_count if has_plagiarism else 0
        avg_ai = ai_sum / question_count if has_ai else 0
        avg_grammar = grammar_sum / question_count if has_grammar else 0
        
        # Ensure we return all metrics, even if they're zero
        return {
            "total_score": round(scaled_total_score, 2),
            "avg_context_score": round(avg_context, 4),
            "avg_plagiarism_score": round(avg_plagiarism, 4),
            "avg_ai_score": round(avg_ai, 4),
            "avg_grammar_score": round(avg_grammar, 4)
        }     

