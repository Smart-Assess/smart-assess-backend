import re
import sys
import os
import numpy as np
from datetime import datetime, timezone
from pymongo import MongoClient, UpdateOne
from fastembed import TextEmbedding
from sklearn.metrics.pairwise import cosine_similarity

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)
from utils.bleurt.bleurt import score as bleurt_score

class TextSimilarity:
    def __init__(self, model_name='BAAI/bge-small-en-v1.5'):
        print("Loading Text Embedding Model...")
        self.dense_model = TextEmbedding(model_name)

    def get_text_embedding(self, text):
        embedding = np.array(list(self.dense_model.embed([text]))[0])
        return embedding

    def compute_cosine_similarity(self, text1, text2):
        embedding1 = self.get_text_embedding(text1)
        embedding2 = self.get_text_embedding(text2)
        similarity = cosine_similarity([embedding1], [embedding2])
        return similarity[0][0]

class ContextScorer:
    def __init__(self, course_id: int, assignment_id: int, rag):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.rag = rag
        
        # Initialize components
        self.text_similarity = TextSimilarity()
        self.scorer = bleurt_score.BleurtScorer()
        
        # MongoDB setup
        self.client = MongoClient("mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority")
        self.db = self.client['FYP']
        self.qa_collection = self.db['qa_extractions']
        self.results_collection = self.db['evaluation_results']
        
        # Scoring weights
        self.BLEURT_WEIGHT = 0.7
        self.SIMILARITY_WEIGHT = 0.2
        self.RELEVANCE_WEIGHT = 0.1

    def calculate_score(self, question: str, answer: str, total_score_per_question: float) -> float:
        # Get reference from RAG
        rag_results = self.rag.search(question)
        if not rag_results:
            return 0.0
        
        reference = self.clean_and_tokenize_text(rag_results)
        
        # Calculate BLEURT score
        bleurt = float(np.round(
            self.scorer.score(
                references=[f"QUESTION: {question}\n\n{reference}"],
                candidates=[answer]
            ),
            4
        ))
        
        # Calculate similarity scores
        similarity = float(np.round(
            self.text_similarity.compute_cosine_similarity(reference, answer),
            4
        ))
        
        relevance = float(np.round(
            self.text_similarity.compute_cosine_similarity(question, answer),
            4
        ))
        
        # Calculate weighted score
        combined_score = (
            bleurt * self.BLEURT_WEIGHT + 
            similarity * self.SIMILARITY_WEIGHT + 
            relevance * self.RELEVANCE_WEIGHT
        )
        
        return round(combined_score * total_score_per_question, 4)

    def process_submission(self, qa_pairs: dict, total_score: float = 100.0) -> dict:
        num_questions = len([k for k in qa_pairs if k.startswith("Question#")])
        score_per_question = total_score / num_questions if num_questions > 0 else 0
        
        question_scores = []
        total_context_score = 0
        
        for q_num in range(1, num_questions + 1):
            q_key = f"Question#{q_num}"
            a_key = f"Answer#{q_num}"
            
            if q_key in qa_pairs and a_key in qa_pairs:
                question = qa_pairs[q_key]
                answer = qa_pairs[a_key]
                
                if question and answer:
                    score = self.calculate_score(question, answer, score_per_question)
                    total_context_score += score
                    
                    question_scores.append({
                        "question_key": q_key,
                        "context_score": score
                    })
        
        return {
            "questions": question_scores,
            "context_overall_score": round(total_context_score, 4)
        }

    def save_results_to_mongo(self, pdf_file: str, results: dict):
        """Update evaluation document with context scores"""
        
        # First ensure document exists with questions array
        self.results_collection.update_one(
            {
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "pdf_file": pdf_file
            },
            {
                "$setOnInsert": {
                    "questions": [
                        {
                            "question_number": q_num,
                            "scores": {}
                        } for q_num in range(1, len(results["questions"]) + 1)
                    ]
                }
            },
            upsert=True
        )
    
        # Then update scores for each question
        updates = []
        for question in results["questions"]:
            q_num = int(question["question_key"].split('#')[1])
            updates.append(
                UpdateOne(
                    {
                        "course_id": self.course_id,
                        "assignment_id": self.assignment_id,
                        "pdf_file": pdf_file,
                        "questions.question_number": q_num
                    },
                    {
                        "$set": {
                            "questions.$.scores.context": {
                                "score": round(question["context_score"], 4),
                                "evaluated_at": datetime.now(timezone.utc)
                            },
                            "overall_scores.context": {
                                "score": round(results["context_overall_score"], 4),
                                "evaluated_at": datetime.now(timezone.utc)
                            }
                        }
                    }
                )
            )
    
        # Execute updates
        if updates:
            self.results_collection.bulk_write(updates)


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

    def run(self, total_score: float = 100.0) -> dict:
        # Fetch student submissions
        print("Fetching student submissions...")
        cursor = self.qa_collection.find({
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "is_teacher": False
        })

        final_results = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "results": []
        }

        for doc in cursor:
            pdf_file = doc["pdf_file"]
            qa_pairs = doc["qa_pairs"]
            
            # Process submission
            results = self.process_submission(qa_pairs, total_score=total_score)
            
            # Save to MongoDB
            self.save_results_to_mongo(pdf_file, results)
            
            # Add to final results
            submission_result = {
                "submission_id": pdf_file,
                "question_results": {
                    score["question_key"]: {"context_score": score["context_score"]}
                    for score in results["questions"]
                },
                "context_overall_score": results["context_overall_score"],
                "evaluated_at": datetime.now(timezone.utc)
            }
            
            final_results["results"].append(submission_result)

        return final_results

if __name__ == "__main__":
    from bestrag import BestRAG
    
    rag = BestRAG(
        url="https://3c2bb745-57c0-478a-b61f-af487f8382e8.eu-central-1-0.aws.cloud.qdrant.io:6333",
        api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwiZXhwIjoxNzQ3MzM3NzY4fQ.AEDv7pPyzgF2U1Od9NGbmcC2r5LahxLIPyb_KybZYhQ",
        collection_name="fyptest"
    )
    
    scorer = ContextScorer(course_id=1, assignment_id=1, rag=rag)
    results = scorer.run(3)
    print(results)