import re
from .bleurt.bleurt import score as bleurt_score
from typing import Dict, Optional
import numpy as np
from pymongo import MongoClient
from datetime import datetime

from fastembed import TextEmbedding
from sklearn.metrics.pairwise import cosine_similarity

class TextSimilarity:
    def __init__(self, model_name='sentence-transformers/all-MiniLM-L6-v2'):
        self.dense_model = TextEmbedding(model_name)

    def get_text_embedding(self, text):
        embedding = np.array(list(self.dense_model.embed([text]))[0])
        return embedding

    def compute_cosine_similarity(self, text1, text2):
        embedding1 = self.get_text_embedding(text1)
        embedding2 = self.get_text_embedding(text2)
        similarity = cosine_similarity([embedding1], [embedding2])
        return similarity[0][0]

class SubmissionScorer:
    def __init__(self, rag):
        self.scorer = bleurt_score.BleurtScorer()
        self.text_similarity = TextSimilarity()
        self.rag = rag
        self.mongo_client = MongoClient("mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority")
        self.db = self.mongo_client['FYP']
        self.BLEURT_WEIGHT = 0.7
        self.SIMILARITY_WEIGHT = 0.2
        self.RELEVANCE_WEIGHT = 0.1

    def calculate_combined_score(self, reference, answer, question, total_score_per_question):
        # Calculate BLEURT score
        q_input = "QUESTION: " + question + "\n\n"
        bleurt_score = float(np.round(
            self.scorer.score(
                references=[q_input + reference],
                candidates=[answer]
            ), 
            4
        ))
        
        similarity_score = float(np.round(
            self.text_similarity.compute_cosine_similarity(reference, answer),
            4
        ))
        # Calculate Relevance score
        relevance_score = float(np.round(
            self.text_similarity.compute_cosine_similarity(question, answer),
            4
        ))
        
        combined_score = (bleurt_score * self.BLEURT_WEIGHT) + (similarity_score * self.SIMILARITY_WEIGHT) + (relevance_score * self.RELEVANCE_WEIGHT)
        
        # Multiply combined score by the total score per question
        contextual_score = combined_score * total_score_per_question
        return np.round(contextual_score, 4)

    def calculate_scores(
        self, 
        course_id: int, 
        assignment_id: int,
        student_id: Optional[str] = None,
        qa_results: Optional[Dict] = None,
        total_score: float = 100.0  # Default total score
    ) -> Dict:
        if qa_results:
            question_results = {}
            num_questions = len(qa_results) // 2  # Assuming each question has a corresponding answer
            total_score_per_question = total_score / num_questions if num_questions > 0 else 0.0

            for q_num in range(1, num_questions + 1):
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
                            q_input= "QUESTION: " + question + "\n\n" 
                            
                            # Calculate combined score
                            context_score = self.calculate_combined_score(
                                reference=clean_reference,
                                answer=answer,
                                question=question,
                                total_score_per_question=total_score_per_question
                            )
                            question_results[q_key] = {
                                'context_score': context_score,
                                'plagiarism_score': None,
                                'ai_score': None,
                                'grammar_score': None
                            }
            
            result = {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "student_id": student_id,
                "question_results": question_results,
                "evaluated_at": datetime.utcnow()
            }
            
            return [result]
            
        else:
            # Existing MongoDB query logic remains unchanged
            query = {
                "course_id": int(course_id),
                "assignment_id": int(assignment_id)
            }
            if student_id:
                query["student_id"] = int(student_id)

            submission = self.db.submissions.find_one(query, sort=[('submitted_at', -1)])
            if not submission:
                return []

            qa_results = submission.get("QA_Results", {})
            return self.calculate_scores(course_id, assignment_id, student_id, qa_results, total_score)
    
    def clean_and_tokenize_text(self, data):
        cleaned_texts = ""
        for point in data.points:
            if 'text' in point.payload:
                raw_text = point.payload['text']

                cleaned_text = re.sub(r'[●■○]', '', raw_text)
                cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()

                tokens = cleaned_text.split()

                filtered_tokens = [
                    token.lower()
                    for token in tokens
                    if token.isalnum() 
                ]
                cleaned_text = ' '.join(filtered_tokens)
                cleaned_texts += cleaned_text
        return cleaned_texts