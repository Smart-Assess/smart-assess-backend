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
        
        # Thresholds for zeroing out scores
        self.plagiarism_threshold = 0.9  # If plagiarism score is above 90%, zero the score
        self.ai_threshold = 0.9  # If AI score is above 90%, zero the score

    def calculate_question_score(self, context_score, plagiarism_score=None, ai_score=None, grammar_score=None):
        # If context score is zero, it's either an empty answer or completely irrelevant
        if context_score == 0:
            return 0.0
        
        # Zero out the score if plagiarism or AI detection is above threshold
        if plagiarism_score is not None and plagiarism_score >= self.plagiarism_threshold:
            print(f"Zeroing score due to high plagiarism: {plagiarism_score}")
            return 0.0
            
        if ai_score is not None and ai_score >= self.ai_threshold:
            print(f"Zeroing score due to high AI detection: {ai_score}")
            return 0.0
        
        # Otherwise continue with normal penalty calculation
        base_score = context_score 
        total_penalty = 0
        
        # Calculate penalties from plagiarism, AI, grammar scores
        if plagiarism_score is not None:
            plagiarism_penalty = plagiarism_score * self.plagiarism_penalty
            total_penalty += plagiarism_penalty
            
        if ai_score is not None:
            ai_penalty = ai_score * self.ai_detection_penalty
            total_penalty += ai_penalty
            
        if grammar_score is not None:
            grammar_penalty = (1 - grammar_score) * self.grammar_penalty
            total_penalty += grammar_penalty
            
        total_penalty = min(total_penalty, self.max_penalty)
        
        # Calculate final score for question
        adjusted_score = base_score * (1 - total_penalty)
        
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
        
        # Count questions - this should be the TOTAL number of questions
        # not just the ones that were answered
        question_count = self.num_questions  # Use the number from initialization
        
        # Process each question's scores
        for question_key, scores in question_results.items():
            # Get individual scores with proper defaults
            context_score = scores.get("context_score", 0)
            plagiarism_score = scores.get("plagiarism_score", 0)
            ai_score = scores.get("ai_score", 0)
            grammar_score = scores.get("grammar_score", 0)
            question_total = scores.get("total_score", None)
                
            # Add to totals for metric averages (including zeros for unanswered questions)
            context_sum += context_score
            plagiarism_sum += plagiarism_score
            ai_sum += ai_score
            grammar_sum += grammar_score
            
            # If the question already has a calculated total score, use that
            # Otherwise calculate it
            if question_total is not None:
                question_score = question_total
            else:
                # Calculate question score based on all available metrics
                question_score = self.calculate_question_score(
                    context_score=context_score,
                    plagiarism_score=plagiarism_score,
                    ai_score=ai_score,
                    grammar_score=grammar_score
                )
            
            # Add to total score
            total_score += question_score
        
        # Scale the total score to match the total grade
        scaled_total_score = (total_score / question_count) * self.total_grade
        
        # Calculate averages for all metrics
        avg_context = context_sum / question_count
        avg_plagiarism = plagiarism_sum / question_count
        avg_ai = ai_sum / question_count
        avg_grammar = grammar_sum / question_count
        
        return {
            "total_score": round(scaled_total_score, 2),
            "avg_context_score": round(avg_context, 4),
            "avg_plagiarism_score": round(avg_plagiarism, 4),
            "avg_ai_score": round(avg_ai, 4),
            "avg_grammar_score": round(avg_grammar, 4)
        }