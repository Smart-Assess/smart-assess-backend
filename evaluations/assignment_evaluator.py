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
from evaluations.grammar import GrammarChecker
from evaluations.assignment_score import AssignmentScoreCalculator
from evaluations.feedback import FeedbackGenerator
from utils.mongodb import mongo_db
from models.models import AssignmentEvaluation

class AssignmentEvaluator:
    def __init__(self, course_id: int, assignment_id: int, request, rag, db):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.request = request
        self.rag = rag
        self.db = db
        
        # Initialize all components that always get used
        self.qa_extractor = PDFQuestionAnswerExtractor([], course_id, assignment_id, is_teacher=False)
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
        print(f"  - Plagiarism checking: {'Enabled' if request.enable_plagiarism else 'Disabled'}")
        print(f"  - Grammar checking: {'Enabled' if request.enable_grammar else 'Disabled'}")
        print(f"  - AI detection: {'Enabled' if request.enable_ai_detection else 'Disabled'}")
        
    def extract_qa_pairs(self, pdf_files, submission_ids=[]):
        teacher_pdf = pdf_files[0]
        student_pdfs = pdf_files[1:]
        
        teacher_extractor = PDFQuestionAnswerExtractor(
            pdf_files=[teacher_pdf],
            course_id=self.course_id,
            assignment_id=self.assignment_id,
            is_teacher=True
        )
        teacher_extractor.extract()
        
        student_extractor = PDFQuestionAnswerExtractor(
            pdf_files=student_pdfs,
            course_id=self.course_id,
            assignment_id=self.assignment_id,
            submission_ids=submission_ids,
            is_teacher=False
        )
        student_extractor.extract()

    def fetch_qa_pairs(self):
        """Fetch Q&A pairs from MongoDB for the given course and assignment"""
        cursor = mongo_db.db['qa_extractions'].find({
            "course_id": self.course_id,
            "assignment_id": self.assignment_id
        })

        teacher_questions = {}
        questions_answers_by_submission = {}

        for document in cursor:
            submission_id = document['submission_id']
            if document['is_teacher']:
                teacher_questions = document.get('qa_pairs', {})
            else:
                questions_answers_by_submission[submission_id] = document.get('qa_pairs', {})

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
        
        teacher_question_numbers.sort()  # Sort question numbers
        print(f"Teacher questions found: {teacher_question_numbers}")
        
        # For each submission, ensure all teacher questions exist
        # Even if the student left them blank
        for submission_id, qa_pairs in questions_answers_by_submission.items():
            student_question_numbers = []
            for key in qa_pairs:
                if key.startswith("Question#"):
                    question_number = int(key.replace("Question#", ""))
                    student_question_numbers.append(question_number)
            
            student_question_numbers.sort()  # Sort question numbers
            print(f"Student {submission_id} questions found: {student_question_numbers}")
            
            # Check for missing questions
            for q_num in teacher_question_numbers:
                question_key = f"Question#{q_num}"
                answer_key = f"Answer#{q_num}"
                
                if question_key not in qa_pairs:
                    print(f"Adding missing question {q_num} to submission {submission_id}")
                    # Add the question from teacher's version
                    qa_pairs[question_key] = teacher_questions[question_key]
                    qa_pairs[answer_key] = ""  # Empty answer
                    
                    # Update MongoDB with the added question
                    mongo_db.db['qa_extractions'].update_one(
                        {
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "submission_id": submission_id,
                            "is_teacher": False
                        },
                        {"$set": {"qa_pairs": qa_pairs}}
                    )

        # Now proceed with context scoring
        context_results = self.context_scorer.run(teacher_questions, questions_answers_by_submission, submission_ids, total_score=total_grade)
        print(f"Context scoring completed: {len(context_results['results'])} submissions processed")
        
        # Run plagiarism checking if enabled
        if self.request.enable_plagiarism:
            try:
                from evaluations.plagiarism import PlagiarismChecker
                self.plagiarism_checker = PlagiarismChecker(self.course_id, self.assignment_id, submission_ids=submission_ids)
                plagiarism_results = self.plagiarism_checker.run(teacher_questions, questions_answers_by_submission, submission_ids=submission_ids)
                print(f"Plagiarism checking completed: {len(plagiarism_results['results'])} submissions processed")
            except Exception as e:
                print(f"Error in plagiarism checking: {str(e)}")
        
        # Run AI detection if enabled
        if self.request.enable_ai_detection:
            try:
                from evaluations.ai_detection import AIDetector
                self.ai_detector = AIDetector(self.course_id, self.assignment_id)
                
                # Get AI detection delay from request (default to 1 second if not specified)
                ai_delay = getattr(self.request, "ai_detection_delay", 1.5)
                print(f"Running AI detection with {ai_delay}s delay between API calls")
                
                ai_results = self.ai_detector.run(
                    teacher_questions, 
                    questions_answers_by_submission, 
                    submission_ids=submission_ids,
                    delay=ai_delay
                )
                print(f"AI detection completed: {len(ai_results['results']) if ai_results else 0} submissions processed")
                
                # Debug: print the AI scores for each question in each submission
                for submission_id, scores in ai_results.items():
                    print(f"AI detection scores for {submission_id}: {scores}")
            except Exception as e:
                print(f"Error in AI detection: {str(e)}")
        
        # Run grammar checking if enabled
        if self.request.enable_grammar:
            try:
                self.grammar_checker = GrammarChecker()
                processed_count = 0
                
                # Get grammar delay from request (default to 0.5 seconds if not specified)
                grammar_delay = getattr(self.request, "grammar_delay", 0.5)
                print(f"Running grammar checking with {grammar_delay}s delay between API calls")
                
                for submission_id, qa_pairs in questions_answers_by_submission.items():
                    for key, text in qa_pairs.items():
                        if key.startswith("Answer#"):
                            q_num = int(key.split('#')[1])
                            
                            # Check for empty answers explicitly
                            if not text or len(text.strip()) < 5:
                                print(f"Empty answer {key} for submission {submission_id} - assigning zero grammar score")
                                
                                # Store zero grammar score for this empty answer
                                mongo_db.db['evaluation_results'].update_one(
                                    {
                                        "course_id": self.course_id,
                                        "assignment_id": self.assignment_id,
                                        "submission_id": submission_id,
                                        "questions.question_number": q_num
                                    },
                                    {
                                        "$set": {
                                            "questions.$.scores.grammar": {
                                                "score": 0.0,
                                                "evaluated_at": datetime.now(timezone.utc)
                                            }
                                        }
                                    }
                                )
                                continue  # Skip grammar checking for empty answers
                            
                            # Evaluate grammar with delay
                            print(f"Checking grammar for {submission_id} - Question {q_num}")
                            corrected_text, grammar_score = self.grammar_checker.evaluate(text, delay=grammar_delay)
                            print(f"Grammar score for {submission_id} - Question {q_num}: {grammar_score}")
                            processed_count += 1
                            
                            # Save grammar scores to MongoDB
                            mongo_db.db['evaluation_results'].update_one(
                                {
                                    "course_id": self.course_id,
                                    "assignment_id": self.assignment_id,
                                    "submission_id": submission_id,
                                    "questions.question_number": q_num
                                },
                                {
                                    "$set": {
                                        "questions.$.scores.grammar": {
                                            "score": round(grammar_score, 4),
                                            "evaluated_at": datetime.now(timezone.utc)
                                        }
                                    }
                                }
                            )
                            
                    # Calculate and save overall grammar score
                    cursor = mongo_db.db['evaluation_results'].find_one(
                        {
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "submission_id": submission_id
                        }
                    )
                    
                    if cursor:
                        questions = cursor.get("questions", [])
                        total_grammar = 0
                        count = len(questions)  # Count ALL questions, even unanswered ones
                        
                        for q in questions:
                            grammar_score = q.get("scores", {}).get("grammar", {}).get("score", 0)
                            # Include ALL questions in calculation, even with zero score
                            total_grammar += grammar_score
                        
                        # Calculate average - now properly handling empty answers
                        avg_grammar = total_grammar / count if count > 0 else 0
                        print(f"Overall grammar score for {submission_id}: {avg_grammar}")
                        
                        mongo_db.db['evaluation_results'].update_one(
                            {
                                "course_id": self.course_id,
                                "assignment_id": self.assignment_id,
                                "submission_id": submission_id
                            },
                            {
                                "$set": {
                                    "overall_scores.grammar": {
                                        "score": round(avg_grammar, 4),
                                        "evaluated_at": datetime.now(timezone.utc)
                                    }
                                }
                            }
                        )
                print(f"Grammar checking completed: {processed_count} answers processed")
            except Exception as e:
                print(f"Error in grammar checking: {str(e)}")
        
        # Generate feedback for each submission
        try:
            feedback_delay = getattr(self.request, "feedback_delay", 1.0)
            print(f"Running feedback generation with {feedback_delay}s delay between API calls")
            
            for i, pdf_file in enumerate(pdf_files[1:]):  # Skip teacher PDF
                if i < len(submission_ids):
                    submission_id = submission_ids[i]
                    feedback_result = self.feedback_generator.run([pdf_file], [submission_id], delay=feedback_delay)
                    print(f"Feedback generated for submission {submission_id}: {feedback_result}")
        except Exception as e:
            print(f"Error generating feedback: {str(e)}")
        
        # Initialize score calculator early
        score_calculator = AssignmentScoreCalculator(
            total_grade=total_grade,
            num_questions=len(teacher_questions) // 2,  # Divide by 2 since we have Q&A pairs
            db=self.db
        )

        # Calculate total scores for all submissions
        total_scores = []
        
        for i, pdf_file in enumerate(pdf_files[1:]):  # Skip teacher PDF
            if i < len(submission_ids):
                submission_id = submission_ids[i]
                
                # Get evaluation data from MongoDB
                eval_doc = mongo_db.db['evaluation_results'].find_one({
                    "course_id": self.course_id,
                    "assignment_id": self.assignment_id,
                    "submission_id": submission_id
                })
                
                if eval_doc:
                    questions = eval_doc.get("questions", [])
                    question_results = {}
                    
                    # Calculate score for each question
                    for question in questions:
                        q_num = question.get("question_number")
                        scores = question.get("scores", {})
                        
                        # Get individual scores
                        context_score = scores.get("context", {}).get("score", 0)
                        plagiarism_score = scores.get("plagiarism", {}).get("score", 0)
                        ai_score = scores.get("ai_detection", {}).get("score", 0)
                        grammar_score = scores.get("grammar", {}).get("score", 0)
                        
                        print(f"Scores for {submission_id} - Q{q_num}: Context={context_score}, Plagiarism={plagiarism_score}, AI={ai_score}, Grammar={grammar_score}")
                        
                        # Calculate question score using the score calculator
                        question_score = score_calculator.calculate_question_score(
                            context_score=context_score,
                            plagiarism_score=plagiarism_score,
                            ai_score=ai_score,
                            grammar_score=grammar_score
                        )
                        
                        # Store scores for this question
                        question_results[f"Question#{q_num}"] = {
                            "context_score": context_score,
                            "plagiarism_score": plagiarism_score,
                            "ai_score": ai_score,
                            "grammar_score": grammar_score,
                            "total_score": question_score  # Add total score for the question
                        }
                        
                        # Update MongoDB with question score
                        mongo_db.db['evaluation_results'].update_one(
                            {
                                "course_id": self.course_id,
                                "assignment_id": self.assignment_id,
                                "submission_id": submission_id,
                                "questions.question_number": q_num
                            },
                            {
                                "$set": {
                                    "questions.$.scores.total": {
                                        "score": round(question_score, 4),
                                        "evaluated_at": datetime.now(timezone.utc)
                                    }
                                }
                            }
                        )

                    # Calculate final overall scores
                    evaluation_result = score_calculator.calculate_submission_evaluation(
                        question_results=question_results
                    )
                    
                    # Debug output
                    print(f"Evaluation result for submission {submission_id}:")
                    print(f"  Total score: {evaluation_result['total_score']}")
                    print(f"  Context score: {evaluation_result.get('avg_context_score', 0)}")
                    print(f"  Plagiarism score: {evaluation_result.get('avg_plagiarism_score', 0)}")
                    print(f"  AI score: {evaluation_result.get('avg_ai_score', 0)}")
                    print(f"  Grammar score: {evaluation_result.get('avg_grammar_score', 0)}")
                    
                    # Save all scores to MongoDB in one go
                    update_fields = {
                        "overall_scores.total": {
                            "score": evaluation_result["total_score"],
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                    }
                    
                    # Only set these fields if they exist in the results
                    if "avg_context_score" in evaluation_result:
                        update_fields["overall_scores.context"] = {
                            "score": evaluation_result["avg_context_score"],
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                        
                    if "avg_plagiarism_score" in evaluation_result:
                        update_fields["overall_scores.plagiarism"] = {
                            "score": evaluation_result["avg_plagiarism_score"],
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                        
                    if "avg_ai_score" in evaluation_result:
                        update_fields["overall_scores.ai_detection"] = {
                            "score": evaluation_result["avg_ai_score"],
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                        
                    if "avg_grammar_score" in evaluation_result:
                        update_fields["overall_scores.grammar"] = {
                            "score": evaluation_result["avg_grammar_score"],
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                    
                    # Save to MongoDB
                    mongo_db.db['evaluation_results'].update_one(
                        {
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "submission_id": submission_id
                        },
                        {
                            "$set": update_fields
                        }
                    )
                    
                    # Get feedback content
                    feedback_content = ""
                    feedback_data = eval_doc.get("overall_feedback", {})
                    if isinstance(feedback_data, dict):
                        feedback_content = feedback_data.get("content", "")
                    elif isinstance(feedback_data, str):
                        feedback_content = feedback_data
                    
                    # Save to PostgreSQL
                    existing_eval = self.db.query(AssignmentEvaluation).filter(
                        AssignmentEvaluation.submission_id == submission_id
                    ).first()
                    
                    if existing_eval:
                        existing_eval.total_score = evaluation_result["total_score"]
                        existing_eval.plagiarism_score = evaluation_result.get("avg_plagiarism_score", 0)
                        existing_eval.ai_detection_score = evaluation_result.get("avg_ai_score", 0)
                        existing_eval.grammar_score = evaluation_result.get("avg_grammar_score", 0)
                        existing_eval.feedback = feedback_content
                        existing_eval.updated_at = datetime.now()
                    else:
                        # Create new evaluation record
                        new_eval = AssignmentEvaluation(
                            submission_id=submission_id,
                            total_score=evaluation_result["total_score"],
                            plagiarism_score=evaluation_result.get("avg_plagiarism_score", 0),
                            ai_detection_score=evaluation_result.get("avg_ai_score", 0),
                            grammar_score=evaluation_result.get("avg_grammar_score", 0),
                            feedback=feedback_content
                        )
                        self.db.add(new_eval)
                    
                    # Commit changes to PostgreSQL
                    self.db.commit()
                    
                    # Add to total scores list for return value
                    total_scores.append({
                        "submission_id": submission_id,
                        "total_score": evaluation_result["total_score"],
                        "context_score": evaluation_result.get("avg_context_score", 0),
                        "plagiarism_score": evaluation_result.get("avg_plagiarism_score", 0),
                        "ai_score": evaluation_result.get("avg_ai_score", 0),
                        "grammar_score": evaluation_result.get("avg_grammar_score", 0)
                    })
        
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
        collection_name="fyptest"
    )

    request = EvaluationRequest(enable_plagiarism=True, enable_grammar=True, enable_ai_detection=True)

    # Get a new database session
    db = next(get_db())

    try:
        evaluator = AssignmentEvaluator(course_id=1, assignment_id=1, request=request, rag=rag, db=db)
        evaluator.run(pdf_files=[
            "/home/samadpls/proj/fyp/smart-assess-backend/37.pdf",
            "/home/samadpls/proj/fyp/smart-assess-backend/p1.pdf"
        ], total_grade=100, submission_ids=[1, 2])
    finally:
        db.close()