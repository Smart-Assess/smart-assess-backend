import os
import json
import time
from typing import Dict, Any, List
from datetime import datetime, timezone
from pymongo import UpdateOne
from groq import Groq
from utils.mongodb import mongo_db

class FeedbackGenerator:
    def __init__(self, course_id: int, assignment_id: int):
        self.course_id = course_id
        self.assignment_id = assignment_id
        
        # MongoDB setup
        self.db = mongo_db.db
        self.results_collection = self.db['evaluation_results']
        self.qa_collection = self.db['qa_extractions']
        
        # Groq client setup
        self.groq_api_key = os.getenv("GROQ_API_KEY", "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")
        self.client = Groq(api_key=self.groq_api_key, timeout=2.0)
        self.model = "llama3-8b-8192"
        
        # Default delay between API calls (in seconds)
        self.default_delay = 1.0
        
        # Prompt templates - updated to include question and answer content
        self.question_prompt = """Provide brief, constructive feedback (2-3 sentences only) for this student's answer.

Question: {question_text}

Student Answer: {student_answer}

Evaluation Scores:
- Context Score: {context_score} - How relevant the answer was to the question
- Plagiarism Score: {plagiarism_score} - How similar to other submissions (higher is worse)
- AI Detection Score: {ai_score} - Likelihood of AI-generated content (higher is worse)
- Grammar Score: {grammar_score} - Grammar issues (higher is worse)

Focus on the most important improvement needed based on the content of their answer and scores."""
        
        self.overall_prompt = """Provide brief, constructive overall feedback (2-3 sentences only) for this student's assignment based on these scores:
            
Overall Context Score: {overall_context_score}
Overall Plagiarism Score: {overall_plagiarism_score} 
Overall AI Detection Score: {overall_ai_score}
Overall Grammar Score: {overall_grammar_score}

Target 1-2 key areas for improvement based on the weakest scores."""
    
    def get_questions_and_answers(self, submission_id):
        """Fetch the actual questions and answers for a submission"""
        qa_data = self.qa_collection.find_one({
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "submission_id": submission_id,
            "is_teacher": False
        })
        
        if not qa_data:
            return {}
        
        return qa_data.get("qa_pairs", {})
    
    def get_teacher_questions(self):
        """Fetch the teacher's original questions"""
        teacher_data = self.qa_collection.find_one({
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "is_teacher": True
        })
        
        if not teacher_data:
            return {}
        
        return teacher_data.get("qa_pairs", {})
    
    def generate_question_feedback(self, q_num: int, scores: Dict[str, Any], 
                                  question_text: str, student_answer: str, delay: float = None) -> str:
        """Generate concise feedback for a specific question using Groq directly"""
        # Apply delay to avoid rate limiting
        delay = delay if delay is not None else self.default_delay
        time.sleep(delay)
        
        # Format the prompt with score values and question/answer content
        formatted_prompt = self.question_prompt.format(
            question_text=question_text,
            student_answer=student_answer,
            context_score=scores.get("context", {}).get("score", "N/A"),
            plagiarism_score=scores.get("plagiarism", {}).get("score", "N/A"),
            ai_score=scores.get("ai_detection", {}).get("score", "N/A"),
            grammar_score=scores.get("grammar", {}).get("score", "N/A")
        )
        
        try:
            # Call Groq API with exponential backoff retry
            max_retries = 3
            retry_delay = delay
            
            for attempt in range(max_retries):
                try:
                    response = self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": "You are a helpful educational assistant providing very brief, actionable feedback. Limit your response to 2-3 sentences maximum."},
                            {"role": "user", "content": formatted_prompt}
                        ],
                        model=self.model,
                        timeout=2.0,
                    )
                    
                    # Extract response content
                    feedback = response.choices[0].message.content.strip()
                    return feedback
                    
                except Exception as e:
                    print(f"Error calling Groq API (attempt {attempt+1}/{max_retries}): {str(e)}")
                    if attempt < max_retries - 1:
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Double the delay for next retry (exponential backoff)
                    else:
                        return "Feedback generation failed. Please review the scores manually."
        except Exception as e:
            print(f"Failed to generate feedback for question {q_num}: {str(e)}")
            return "Feedback generation failed. Please review the scores manually."
    
    def generate_overall_feedback(self, overall_scores: Dict[str, Any], question_feedback: Dict[int, str], delay: float = None) -> str:
        """Generate concise overall feedback for the submission using Groq directly"""
        # Apply delay to avoid rate limiting
        delay = delay if delay is not None else self.default_delay
        time.sleep(delay)
        
        # Create a summary of question-specific feedback
        feedback_summary = ""
        for q_num, feedback in sorted(question_feedback.items()):
            # Add a short extract from each question's feedback
            feedback_summary += f"Question {q_num}: {feedback[:80]}...\n"
        
        # Format the prompt with score values and question feedback summary
        formatted_prompt = f"""Provide brief, constructive overall feedback (2-3 sentences only) for this student's assignment.
    
    Individual Question Feedback Summary:
    {feedback_summary}
    
    Overall Evaluation Scores:
    - Context Score: {overall_scores.get("context", {}).get("score", "N/A")} - How relevant the answers were to the questions
    - Plagiarism Score: {overall_scores.get("plagiarism", {}).get("score", "N/A")} - How similar to other submissions (higher is worse)
    - AI Detection Score: {overall_scores.get("ai_detection", {}).get("score", "N/A")} - Likelihood of AI-generated content (higher is worse)
    - Grammar Score: {overall_scores.get("grammar", {}).get("score", "N/A")} - Grammar issues (higher is worse)
    
    Based on the individual question feedback and scores above, provide overall assessment and 1-2 key areas for improvement. Be specific and constructive."""
        
        try:
            # Call Groq API with exponential backoff retry
            max_retries = 3
            retry_delay = delay
            
            for attempt in range(max_retries):
                try:
                    response = self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": "You are a helpful educational assistant providing specific, actionable feedback. Limit your response to 2-3 sentences maximum."},
                            {"role": "user", "content": formatted_prompt}
                        ],
                        model=self.model,
                        timeout=3.0,  # Increased timeout for this task
                    )
                    
                    # Extract response content
                    feedback = response.choices[0].message.content.strip()
                    return feedback
                    
                except Exception as e:
                    print(f"Error calling Groq API (attempt {attempt+1}/{max_retries}): {str(e)}")
                    if attempt < max_retries - 1:
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Double the delay for next retry
                    else:
                        return "Overall feedback generation failed. Please review the scores manually."
        except Exception as e:
            print(f"Failed to generate overall feedback: {str(e)}")
            return "Overall feedback generation failed. Please review the scores manually."
    
    def save_feedback_to_mongo(self, submission_id: str, overall_feedback: str, question_feedback: Dict[int, str]):
        """Save generated feedback to MongoDB for each question and overall"""
        # First update the overall feedback
        self.results_collection.update_one(
            {
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "submission_id": submission_id
            },
            {
                "$set": {
                    "overall_feedback": {
                        "content": overall_feedback,
                        "generated_at": datetime.now(timezone.utc)
                    }
                }
            }
        )
        
        # Then update feedback for each question
        updates = []
        for q_num, feedback in question_feedback.items():
            updates.append(
                UpdateOne(
                    {
                        "course_id": self.course_id,
                        "assignment_id": self.assignment_id,
                        "submission_id": submission_id,
                        "questions.question_number": q_num
                    },
                    {
                        "$set": {
                            "questions.$.feedback": {
                                "content": feedback,
                                "generated_at": datetime.now(timezone.utc)
                            }
                        }
                    }
                )
            )
        
        if updates:
            self.results_collection.bulk_write(updates)
    
    def run(self, pdf_files: List[str], submission_ids: List[int] = None, delay: float = None):
        """Run feedback generation for multiple submissions"""
        delay = delay if delay is not None else self.default_delay
        print(f"Running feedback generation with {delay}s delay between API calls")
        
        results = []
        
        # Get teacher questions for reference
        teacher_questions = self.get_teacher_questions()
        print(f"Teacher questions retrieved: {len(teacher_questions)} items")
        print(f"Teacher questions sample: {list(teacher_questions.keys())[:3] if teacher_questions else 'None'}")
        
        for i, pdf_file in enumerate(pdf_files):
            # Get submission_id if available, otherwise use index
            submission_id = submission_ids[i] if submission_ids else i
            
            # Fetch evaluation data from MongoDB
            evaluation_data = self.results_collection.find_one({
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "submission_id": submission_id
            })
            
            if not evaluation_data:
                print(f"No evaluation data found for submission {submission_id}")
                continue
            
            # Get the actual questions and answers for this submission
            qa_pairs = self.get_questions_and_answers(submission_id)
            print(f"Student submission {submission_id} Q&A pairs: {len(qa_pairs)} items")
            print(f"Student submission {submission_id} Q&A sample: {list(qa_pairs.keys())[:3] if qa_pairs else 'None'}")
            
            # Extract data
            overall_scores = evaluation_data.get("overall_scores", {})
            questions = evaluation_data.get("questions", [])
            print(f"Found {len(questions)} questions in evaluation data")
            
            # Generate feedback for each question with delay FIRST
            question_feedback = {}
            for question in questions:
                q_num = question.get("question_number")
                scores = question.get("scores", {})
                
                # Get the question text and student's answer
                q_key = f"Question#{q_num}"
                a_key = f"Answer#{q_num}"
                
                question_text = teacher_questions.get(q_key, "")
                student_answer = qa_pairs.get(a_key, "")
                
                print(f"Q{q_num}: Found question text: {bool(question_text)} ({len(question_text)} chars)")
                print(f"Q{q_num}: Found student answer: {bool(student_answer)} ({len(student_answer)} chars)")
                
                # Add detailed debugging for specific case when either is missing
                if not question_text:
                    print(f"WARNING: Missing question text for {q_key}. Available keys: {list(teacher_questions.keys())[:5]}")
                if not student_answer:
                    print(f"WARNING: Missing student answer for {a_key}. Available keys: {list(qa_pairs.keys())[:5]}")
                
                if not question_text or not student_answer:
                    # Handle the case where either text is missing
                    # Provide at least something to generate feedback from
                    if not question_text:
                        question_text = f"Question {q_num}"
                    if not student_answer:
                        student_answer = "No answer provided."
                    print(f"Using fallback text: Q: '{question_text}', A: '{student_answer}'")
                
                feedback = self.generate_question_feedback(
                    q_num, 
                    scores, 
                    question_text,
                    student_answer,
                    delay
                )
                question_feedback[q_num] = feedback
                print(f"Generated feedback for Q{q_num}: {feedback[:50]}...")
            
            # THEN generate overall feedback using the question-specific feedback
            overall_feedback = self.generate_overall_feedback(overall_scores, question_feedback, delay)
            print(f"Generated overall feedback: {overall_feedback[:100]}...")
            
            # Save to MongoDB
            self.save_feedback_to_mongo(submission_id, overall_feedback, question_feedback)
            print(f"Saved feedback to MongoDB for submission {submission_id}")
            
            results.append({
                "submission_id": submission_id,
                "pdf_file": pdf_file,
                "overall_feedback": overall_feedback,
                "question_feedback": question_feedback,
                "generated_at": datetime.now(timezone.utc)
            })
        
        return {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "feedback_results": results
        }

if __name__ == "__main__":
    feedback_gen = FeedbackGenerator(course_id=1, assignment_id=1)
    result = feedback_gen.run(
        pdf_files=["/home/samadpls/proj/fyp/smart-assess-backend/p1.pdf"]
    )
    print(result)