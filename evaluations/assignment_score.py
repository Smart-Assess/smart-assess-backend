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
        """Calculate question score based on individual components"""
        try:
            # Ensure all scores are normalized (0-1)
            context = float(context_score) if context_score is not None else 0.0
            plagiarism = float(plagiarism_score) if plagiarism_score is not None else 0.0
            ai = float(ai_score) if ai_score is not None else 0.0
            grammar = float(grammar_score) if grammar_score is not None else 0.0
            
            # Ensure context score is normalized (0-1)
            context = max(0.0, min(1.0, context))
            
            # Calculate score per question (maximum points for each question)
            score_per_question = self.total_grade / self.num_questions
            
            # Start with context score as base (multiply normalized score by max points)
            base_score = context * score_per_question
            
            # Apply penalties for high plagiarism/AI scores
            if plagiarism > self.plagiarism_threshold or ai > self.ai_threshold:
                return 0.0  # Zero score for high plagiarism/AI
            
            # Apply graduated penalties
            plagiarism_penalty = min(plagiarism * self.plagiarism_penalty, self.max_penalty)
            ai_penalty = min(ai * self.ai_detection_penalty, self.max_penalty)
            grammar_penalty = min((1.0 - grammar) * self.grammar_penalty, self.max_penalty)
            
            # Total penalty cannot exceed max_penalty
            total_penalty = min(plagiarism_penalty + ai_penalty + grammar_penalty, self.max_penalty)
            
            # Apply penalty to base score
            final_score = base_score * (1.0 - total_penalty)
            
            return max(0.0, round(final_score, 4))
            
        except (TypeError, ValueError) as e:
            print(f"Error calculating question score: {e}")
            print(f"Scores: context={context_score}, plagiarism={plagiarism_score}, ai={ai_score}, grammar={grammar_score}")
            return 0.0

    def calculate_submission_evaluation(self, question_results: Dict[str, Dict[str, float]]) -> Dict:
        """Calculate overall evaluation scores based on per-question results"""
        # Initialize counters
        total_score = 0
        context_sum = 0
        plagiarism_sum = 0
        ai_sum = 0
        grammar_sum = 0
        
        # Use the total number of questions from initialization
        question_count = self.num_questions
        
        # Process each question's scores
        for question_key, scores in question_results.items():
            # Get individual scores with proper defaults (all should be 0-1)
            context_score = scores.get("context_score", 0)
            plagiarism_score = scores.get("plagiarism_score", 0)
            ai_score = scores.get("ai_score", 0)
            grammar_score = scores.get("grammar_score", 0)
            question_total = scores.get("total_score", None)
                
            # Add to totals for metric averages (normalized scores 0-1)
            context_sum += context_score
            plagiarism_sum += plagiarism_score
            ai_sum += ai_score
            grammar_sum += grammar_score
            
            # Calculate actual question score in points
            if question_total is not None:
                question_score = question_total
            else:
                question_score = self.calculate_question_score(
                    context_score=context_score,
                    plagiarism_score=plagiarism_score,
                    ai_score=ai_score,
                    grammar_score=grammar_score
                )
            
            # Add to total score (this is in actual points)
            total_score += question_score
        
        # Calculate averages for all metrics (these remain normalized 0-1)
        avg_context = context_sum / question_count if question_count > 0 else 0.0
        avg_plagiarism = plagiarism_sum / question_count if question_count > 0 else 0.0
        avg_ai = ai_sum / question_count if question_count > 0 else 0.0
        avg_grammar = grammar_sum / question_count if question_count > 0 else 0.0
        
        return {
            "total_score": round(total_score, 2),  # Actual points (e.g., 85.5/100)
            "avg_context_score": round(avg_context, 4),  # Normalized (0-1)
            "avg_plagiarism_score": round(avg_plagiarism, 4),  # Normalized (0-1)
            "avg_ai_score": round(avg_ai, 4),  # Normalized (0-1)
            "avg_grammar_score": round(avg_grammar, 4)  # Normalized (0-1)
        }