import requests
from datetime import datetime, timezone
from pymongo import UpdateOne
from utils.mongodb import mongo_db

class AIDetector:
    def __init__(self, course_id: int, assignment_id: int):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.ai_service_url = "http://ai_detection:5000/detect"
        
        # MongoDB setup
        self.db = mongo_db.db
        self.results_collection = self.db['evaluation_results']
        
        self.questions_answers_by_pdf = {}
        self.teacher_questions = {}
        self.ai_detection_results = {}

    def detect_ai_content(self, text):
        """Call the AI detection service to check if text is AI-generated"""
        try:
            response = requests.post(
                self.ai_service_url, 
                json={'text': text},
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json().get('probability', 0)
            else:
                print(f"Error from AI detection service: {response.status_code}")
                return 0
                
        except Exception as e:
            print(f"Exception calling AI detection service: {str(e)}")
            return 0

    def analyze_answers(self):
        """Analyze answers for AI-generated content"""
        self.ai_detection_results = {pdf_file: {} for pdf_file in self.questions_answers_by_pdf}

        for pdf_file in self.questions_answers_by_pdf:
            qa_dict = self.questions_answers_by_pdf.get(pdf_file, {})

            for question_key in self.teacher_questions:
                if not question_key.startswith("Question#"):
                    continue

                answer_key = f"Answer#{question_key.split('#')[1]}"
                answer = qa_dict.get(answer_key, "").strip()
                
                if not answer:
                    ai_score = 0
                else:
                    # Call AI detection service
                    ai_score = self.detect_ai_content(answer)

                self.ai_detection_results[pdf_file][question_key] = {
                    "ai_score": ai_score
                }
    
    def save_results_to_mongo(self):
        """Save AI detection scores in unified evaluation document"""
        for pdf_file, qa_results in self.questions_answers_by_pdf.items():
            ai_data = self.ai_detection_results.get(pdf_file, {})
            
            # Calculate overall AI score
            total_ai_score = 0
            question_count = 0
            question_updates = []
    
            for q_key in qa_results:
                if q_key.startswith("Question#"):
                    q_num = int(q_key.split('#')[1])
                    if q_key in ai_data:
                        ai_score = ai_data[q_key].get("ai_score", 0)
                        
                        # Create proper UpdateOne object
                        question_updates.append(UpdateOne(
                            {
                                "course_id": self.course_id,
                                "assignment_id": self.assignment_id,
                                "pdf_file": pdf_file,
                                "questions.question_number": q_num
                            },
                            {
                                "$set": {
                                    "questions.$.scores.ai_detection": {
                                        "score": round(ai_score, 4),
                                        "evaluated_at": datetime.now(timezone.utc)
                                    }
                                }
                            }
                        ))
                        
                        total_ai_score += ai_score
                        question_count += 1
    
            # First ensure document exists with questions array
            self.results_collection.update_one(
                {
                    "course_id": self.course_id,
                    "assignment_id": self.assignment_id,
                    "pdf_file": pdf_file
                },
                {
                    "$set": {
                        "overall_scores.ai_detection": {
                            "score": round(total_ai_score / question_count, 4) if question_count > 0 else 0,
                            "evaluated_at": datetime.now(timezone.utc)
                        }
                    },
                    "$setOnInsert": {
                        "questions": [
                            {
                                "question_number": i,
                                "scores": {}
                            } for i in range(1, len(qa_results)//2 + 1)
                        ]
                    }
                },
                upsert=True
            )
    
            # Execute question updates if any
            if question_updates:
                self.results_collection.bulk_write(question_updates)

    def run(self, teacher_questions, questions_answers_by_pdf):
        self.teacher_questions = teacher_questions
        self.questions_answers_by_pdf = questions_answers_by_pdf
        
        # Analyze answers for AI content
        self.analyze_answers()
        
        # Save results
        self.save_results_to_mongo()

        # Prepare final results structure
        final_results = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "results": []
        }

        # Include results for all PDFs
        for pdf_file in self.questions_answers_by_pdf:
            qa_results = self.questions_answers_by_pdf.get(pdf_file, {})
            ai_data = self.ai_detection_results.get(pdf_file, {})
            
            question_results = {}
            total_ai_score = 0
            question_count = 0

            for q_key in qa_results:
                if q_key.startswith("Question#"):
                    if q_key in ai_data:
                        ai_score = ai_data[q_key].get("ai_score", 0)
                        
                        question_results[q_key] = {
                            'ai_score': round(ai_score, 4)
                        }
                        
                        total_ai_score += ai_score
                        question_count += 1

            submission_result = {
                "submission_id": pdf_file,
                "question_results": question_results,
                "overall_ai_score": round(total_ai_score / question_count, 4) if question_count > 0 else 0,
                "evaluated_at": datetime.now(timezone.utc)
            }
            
            final_results["results"].append(submission_result)

        return final_results


if __name__ == "__main__":
    # Test code
    teacher_questions = {"Question#1": "What is AI?"}
    questions_answers_by_pdf = {
        "student1.pdf": {
            "Answer#1": "AI is artificial intelligence that can think like humans."
        }
    }
    
    detector = AIDetector(course_id=1, assignment_id=1)
    # Uncomment to test (requires running AI detection service)
    # results = detector.run(teacher_questions, questions_answers_by_pdf)
    # print(results)