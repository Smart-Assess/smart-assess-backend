from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict
from pymongo import MongoClient
from models.models import AssignmentEvaluation

class AssignmentScoreCalculator:
    def __init__(self, total_grade: float, num_questions: int, db: Session):
        self.total_grade = total_grade
        self.num_questions = num_questions
        self.points_per_question = total_grade / num_questions if num_questions > 0 else 0
        self.db = db  # SQLAlchemy session
        
        # Existing weights
        self.weights = {
            'context': 0.60,
            'plagiarism': 0.20, 
            'ai_detection': 0.10,
            'grammar': 0.10
        }
        
        # MongoDB setup (keep existing)
        self.client = MongoClient("mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority")
        self.mongo_db = self.client['FYP']
        self.evaluation_collection = self.mongo_db.assignment_evaluations

    def calculate_question_score(
        self,
        context_score: float,
        plagiarism_score: float = None,
        ai_score: float = None,
        grammar_score: float = None
    ) -> Dict:
        """
        Calculate weighted score for a single question
        
        Args:
            context_score: Score from context evaluation (0-1)
            plagiarism_score: Score from plagiarism detection (0-1)
            ai_score: Score from AI detection (0-1)
            grammar_score: Score from grammar checking (0-1)
        
        Returns:
            Dict with total and component scores
        """
        scores = {
            'context': context_score * self.weights['context'],
            'plagiarism': (1 - plagiarism_score) * self.weights['plagiarism'] if plagiarism_score is not None else 0,
            'ai_detection': (1 - ai_score) * self.weights['ai_detection'] if ai_score is not None else 0,
            'grammar': grammar_score * self.weights['grammar'] if grammar_score is not None else 0
        }

        # Redistribute weights if some components are missing
        available_weight = sum(self.weights[k] for k, v in scores.items() if v != 0)
        if available_weight < 1:
            factor = 1 / available_weight
            scores = {k: v * factor for k, v in scores.items()}

        # Calculate total score for question and scale to points_per_question
        total = sum(scores.values()) * self.points_per_question
        
        return {
            'total_score': round(total, 2),
            'component_scores': {k: round(v, 4) for k, v in scores.items()}
        }

    def calculate_submission_evaluation(
            self,
            submission_id: int,
            course_id: int,
            assignment_id: int,
            student_id: str,
            question_results: Dict[str, Dict],
            enabled_components: Dict[str, bool] = None

        ) -> Dict:
            """Calculate and store final evaluation result in both MongoDB and SQL"""
            
            enabled_components = enabled_components or {
                'context': True,  # Context always enabled
                'plagiarism': False,
                'ai_detection': False,
                'grammar': False
            }
            active_weights = {}
            total_weight = 0
            for component, weight in self.weights.items():
                if enabled_components.get(component, False):
                    active_weights[component] = weight
                    total_weight += weight
            
            # Normalize weights to sum to 1
            if total_weight > 0:
                active_weights = {k: v/total_weight for k, v in active_weights.items()}
            
            total_score = 0
            total_plagiarism = 0
            total_ai = 0
            total_grammar = 0
            num_processed = 0
            question_scores = {}
        
            for q_key, result in question_results.items():
                if not q_key.startswith("Question#"):
                    continue
        
                # Get scores with defaults of 0
                scores = {}
                if enabled_components.get('context'):
                    scores['context'] = float(result.get('context_score', 0) or 0)
                if enabled_components.get('plagiarism'):
                    scores['plagiarism'] = float(result.get('plagiarism_score', 0) or 0)
                if enabled_components.get('ai_detection'):
                    scores['ai_detection'] = float(result.get('ai_score', 0) or 0)
                if enabled_components.get('grammar'):
                    scores['grammar'] = float(result.get('grammar_score', 0) or 0)

                # Calculate weighted score using only enabled components
                question_score = sum(scores[k] * active_weights[k] for k in scores) * self.points_per_question
                
                question_scores[q_key] = {
                    'total_score': round(question_score, 2),
                    'component_scores': {k: round(v, 4) for k, v in scores.items()}
                }
                
                total_score += question_score
                if enabled_components.get('plagiarism'):
                    total_plagiarism += scores.get('plagiarism', 0)
                if enabled_components.get('ai_detection'):    
                    total_ai += scores.get('ai_detection', 0)
                if enabled_components.get('grammar'):
                    total_grammar += scores.get('grammar', 0)
                    
                num_processed += 1
        
            # Calculate averages with proper handling of zero division
            avg_plagiarism = round(total_plagiarism / num_processed, 4) if enabled_components.get('plagiarism') and num_processed > 0 else None
            avg_ai = round(total_ai / num_processed, 4) if enabled_components.get('ai_detection') and num_processed > 0 else None  
            avg_grammar = round(total_grammar / num_processed, 4) if enabled_components.get('grammar') and num_processed > 0 else None
        
            # Store in MongoDB
            mongo_data = {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "submission_id": submission_id,
                "student_id": student_id,
                "total_score": round(total_score, 2),
                "plagiarism_score": avg_plagiarism,
                "ai_detection_score": avg_ai,
                "grammar_score": avg_grammar,
                "question_scores": question_scores,
                "feedback": f"Total Grade: {total_score:.2f}/{self.total_grade}",
                "evaluated_at": datetime.utcnow()
            }
        
            self.evaluation_collection.update_one(
                {
                    "submission_id": submission_id,
                    "course_id": course_id,
                    "assignment_id": assignment_id
                },
                {"$set": mongo_data},
                upsert=True
            )
        
            # Store in SQL AssignmentEvaluation table
            eval_result = AssignmentEvaluation(
                submission_id=submission_id,
                total_score=round(total_score, 2),
                plagiarism_score=avg_plagiarism,
                ai_detection_score=avg_ai,
                grammar_score=avg_grammar,
                feedback=f"Total Grade: {total_score:.2f}/{self.total_grade}"
            )
            
            try:
                self.db.add(eval_result)
                self.db.commit()
            except Exception as e:
                self.db.rollback()
                raise Exception(f"Failed to store evaluation in SQL: {str(e)}")
        
            return {
                "submission_id": submission_id,
                "student_id": student_id,
                "total_score": f"{round(total_score, 2)}/{round(self.total_grade,2)}",
                "questions": [
                    {
                        "question_number": int(q_key.split('#')[1]),
                        "score": f"{scores['total_score']}/{round(self.points_per_question,2)}",
                        "component_scores": scores["component_scores"]
                    }
                    for q_key, scores in question_scores.items()
                ]
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