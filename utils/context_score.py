from .bleurt.bleurt import score as bleurt_score
from typing import Dict, Optional
import numpy as np
from pymongo import MongoClient
from datetime import datetime

class SubmissionScorer:
    def __init__(self, rag):
        self.scorer = bleurt_score.BleurtScorer()
        self.rag = rag
        self.mongo_client = MongoClient("mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority")
        self.db = self.mongo_client['FYP']

    def clean_and_tokenize_text(self, text: str) -> str:
        return text

    
    def calculate_scores(
        self, 
        course_id: int, 
        assignment_id: int,
        student_id: Optional[str] = None
    ) -> Dict:
        # Convert query params to match document types
        query = {
            "course_id": int(course_id),
            "assignment_id": int(assignment_id)
        }
        if student_id:
            query["student_id"] = int(student_id)

        print("Query:", query)
        print("Collections:", self.db.list_collection_names())

        submissions = list(self.db.submissions.find(query))
        print(f"Found {len(submissions)} submissions")

        results = []
        for submission in submissions:
            question_results = {}
            qa_results = submission.get("QA_Results", {})
            
            # Process each question/answer pair
            for q_num in range(1, len(qa_results)//2 + 1):
                q_key = f"Question#{q_num}"
                a_key = f"Answer#{q_num}"
                
                if q_key in qa_results and a_key in qa_results:
                    question = qa_results[q_key]
                    answer = qa_results[a_key]
                    
                    if question and answer:
                        # Generate reference using RAG
                        rag_results = self.rag.search(question)
                        if rag_results:
                            clean_reference = self.clean_and_tokenize_text(rag_results)
                            
                            # Calculate BLEURT score
                            context_score = float(np.round(
                                self.scorer.score(
                                    references=[clean_reference],
                                    candidates=[answer]
                                ), 
                                4
                            ))
                            
                            question_results[q_key] = {
                                'context_score': context_score,
                                'plagiarism_score': None,
                                'ai_score': None,
                                'grammar_score': None
                            }
            
            result = {
                "course_id": submission["course_id"],
                "assignment_id": submission["assignment_id"], 
                "student_id": submission["student_id"],
                "submission_id": str(submission["_id"]),
                "question_results": question_results,
                "evaluated_at": datetime.utcnow()
            }
            
            # Update scores collection
            self.db.submission_scores.update_one(
                {
                    "course_id": submission["course_id"],
                    "assignment_id": submission["assignment_id"],
                    "student_id": submission["student_id"]
                },
                {"$set": result},
                upsert=True
            )
            
            results.append(result)
        
        return results
        
