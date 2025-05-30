from utils.mongodb import mongo_db
from utils.bleurt.bleurt import score as bleurt_score
import re
import sys
import os
import numpy as np
from datetime import datetime, timezone
from pymongo import UpdateOne
from fastembed import TextEmbedding
from sklearn.metrics.pairwise import cosine_similarity

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)


class TextSimilarity:
    _instance = None
    _model = None

    def __new__(cls, model_name="BAAI/bge-small-en-v1.5"):
        if cls._instance is None:
            cls._instance = super(TextSimilarity, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_name="BAAI/bge-small-en-v1.5"):
        if TextSimilarity._model is None:
            print("Loading Text Embedding Model (one time only)...")
            TextSimilarity._model = TextEmbedding(model_name)
        self.dense_model = TextSimilarity._model

    def get_text_embedding(self, text):
        embedding = np.array(list(self.dense_model.embed([text]))[0])
        return embedding

    def compute_cosine_similarity(self, text1, text2):
        embedding1 = self.get_text_embedding(text1)
        embedding2 = self.get_text_embedding(text2)
        similarity = cosine_similarity([embedding1], [embedding2])
        return similarity[0][0]


class ContextScorer:
    _bleurt_scorer = None
    _text_similarity = None

    def __init__(self, course_id: int, assignment_id: int, rag):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.rag = rag

        # Initialize components with class-level caching
        if ContextScorer._text_similarity is None:
            print("Initializing TextSimilarity (cached for all future evaluations)...")
            ContextScorer._text_similarity = TextSimilarity()
        self.text_similarity = ContextScorer._text_similarity

        if ContextScorer._bleurt_scorer is None:
            print("Loading BLEURT scorer (cached for all future evaluations)...")
            ContextScorer._bleurt_scorer = bleurt_score.BleurtScorer()
        self.scorer = ContextScorer._bleurt_scorer

        # MongoDB setup
        self.db = mongo_db.db
        self.results_collection = self.db["evaluation_results"]

        # Scoring weights
        self.BLEURT_WEIGHT = 0.7
        self.SIMILARITY_WEIGHT = 0.2
        self.RELEVANCE_WEIGHT = 0.1

    def calculate_score(
        self, question: str, answer: str, total_score_per_question: float
    ) -> float:
        # Check for empty or very short answers first
        if not answer or len(answer.strip()) < 5:
            print(f"Empty or very short answer detected - assigning zero score")
            return 0.0

        # Get reference from RAG
        rag_results = self.rag.search(question)
        if not rag_results:
            return 0.0

        reference = self.clean_and_tokenize_text(rag_results)

        try:
            # Calculate BLEURT score
            bleurt_result = self.scorer.score(
                references=[f"QUESTION: {question}\n\n{reference}"], candidates=[answer]
            )

            if isinstance(bleurt_result, (list, np.ndarray)):
                bleurt = float(np.round(bleurt_result[0], 4))
            else:
                bleurt = float(np.round(bleurt_result, 4))

        except Exception as e:
            print(f"BLEURT scoring error: {e}")
            bleurt = 0.0

        try:
            # Calculate similarity scores
            similarity = float(
                np.round(
                    self.text_similarity.compute_cosine_similarity(reference, answer), 4
                )
            )

            relevance = float(
                np.round(
                    self.text_similarity.compute_cosine_similarity(question, answer), 4
                )
            )
        except Exception as e:
            print(f"Similarity calculation error: {e}")
            similarity = 0.0
            relevance = 0.0

        # Calculate weighted score and KEEP IT NORMALIZED (0-1)
        combined_score = (
            bleurt * self.BLEURT_WEIGHT
            + similarity * self.SIMILARITY_WEIGHT
            + relevance * self.RELEVANCE_WEIGHT
        )

        # Return normalized score (0-1), NOT multiplied by total_score_per_question
        return round(max(0.0, min(1.0, combined_score)), 4)

    def process_submission(
        self, teacher_questions: dict, qa_pairs: dict, total_score: float = 100.0
    ) -> dict:
        num_questions = len([k for k in teacher_questions if k.startswith("Question#")])

        question_scores = []
        total_normalized_score = 0

        # Process each question individually
        for q_num in range(1, num_questions + 1):
            q_key = f"Question#{q_num}"
            a_key = f"Answer#{q_num}"

            if q_key in teacher_questions:
                question = teacher_questions[q_key]
                answer = qa_pairs.get(a_key, "")

                if not answer or len(answer.strip()) < 5:
                    question_scores.append(
                        {
                            "question_key": q_key,
                            "context_score": 0.0,  # Normalized score (0-1)
                        }
                    )
                    continue

                # Get reference from RAG
                rag_results = self.rag.search(question)
                if not rag_results:
                    question_scores.append(
                        {
                            "question_key": q_key,
                            "context_score": 0.0,  # Normalized score (0-1)
                        }
                    )
                    continue

                reference = self.clean_and_tokenize_text(rag_results)

                # Calculate BLEURT score
                try:
                    bleurt_result = self.scorer.score(
                        references=[f"QUESTION: {question}\n\n{reference}"],
                        candidates=[answer],
                    )

                    if isinstance(bleurt_result, (list, np.ndarray)):
                        bleurt = float(np.round(bleurt_result[0], 4))
                    else:
                        bleurt = float(np.round(bleurt_result, 4))

                except Exception as e:
                    print(f"BLEURT scoring error for question {q_num}: {e}")
                    bleurt = 0.0

                # Calculate similarity scores
                try:
                    similarity = float(
                        np.round(
                            self.text_similarity.compute_cosine_similarity(
                                reference, answer
                            ),
                            4,
                        )
                    )

                    relevance = float(
                        np.round(
                            self.text_similarity.compute_cosine_similarity(
                                question, answer
                            ),
                            4,
                        )
                    )
                except Exception as e:
                    print(f"Similarity calculation error for question {q_num}: {e}")
                    similarity = 0.0
                    relevance = 0.0

                # Calculate weighted score - KEEP NORMALIZED (0-1)
                combined_score = (
                    bleurt * self.BLEURT_WEIGHT
                    + similarity * self.SIMILARITY_WEIGHT
                    + relevance * self.RELEVANCE_WEIGHT
                )

                # Store normalized score (0-1)
                normalized_score = round(max(0.0, min(1.0, combined_score)), 4)
                total_normalized_score += normalized_score

                question_scores.append(
                    {
                        "question_key": q_key,
                        "context_score": normalized_score,  # This is 0-1
                    }
                )

        # Calculate average normalized score (0-1)
        avg_normalized_score = (
            total_normalized_score / num_questions if num_questions > 0 else 0.0
        )

        return {
            "questions": question_scores,
            # This is 0-1
            "context_overall_score": round(avg_normalized_score, 4),
        }

    def save_results_to_mongo(self, submission_id: str, results: dict):
        """Update evaluation document with context scores using bulk operations"""

        # First ensure document exists with questions array - single operation
        self.results_collection.update_one(
            {
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "submission_id": submission_id,
            },
            {
                "$set": {
                    "overall_scores.context": {
                        "score": round(results["context_overall_score"], 4),
                        "evaluated_at": datetime.now(timezone.utc),
                    }
                },
                "$setOnInsert": {
                    "questions": [
                        {"question_number": q_num, "scores": {}}
                        for q_num in range(1, len(results["questions"]) + 1)
                    ]
                },
            },
            upsert=True,
        )

        # Bulk update all questions in one operation
        if results["questions"]:
            updates = []
            for question in results["questions"]:
                q_num = int(question["question_key"].split("#")[1])
                updates.append(
                    UpdateOne(
                        {
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "submission_id": submission_id,
                            "questions.question_number": q_num,
                        },
                        {
                            "$set": {
                                "questions.$.scores.context": {
                                    "score": round(question["context_score"], 4),
                                    "evaluated_at": datetime.now(timezone.utc),
                                }
                            }
                        },
                    )
                )

            # Execute all updates at once
            if updates:
                self.results_collection.bulk_write(updates)

    def run(
        self,
        teacher_questions,
        questions_answers_by_submission,
        submission_ids,
        total_score: float = 100.0,
    ) -> dict:
        final_results = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "results": [],
        }

        for submission_id, qa_pairs in questions_answers_by_submission.items():
            print("submission_id>>>", submission_id)

            try:
                # Process submission with error handling
                results = self.process_submission(
                    teacher_questions, qa_pairs, total_score=total_score
                )

                # Save to MongoDB
                self.save_results_to_mongo(submission_id, results)

                # Add to final results
                submission_result = {
                    "submission_id": submission_id,
                    "question_results": {
                        score["question_key"]: {"context_score": score["context_score"]}
                        for score in results["questions"]
                    },
                    "context_overall_score": results["context_overall_score"],
                    "evaluated_at": datetime.now(timezone.utc),
                }

                final_results["results"].append(submission_result)

            except Exception as e:
                print(f"Error processing submission {submission_id}: {e}")
                import traceback

                traceback.print_exc()

                # Add a default result for this submission
                final_results["results"].append(
                    {
                        "submission_id": submission_id,
                        "question_results": {},
                        "context_overall_score": 0.0,
                        "evaluated_at": datetime.now(timezone.utc),
                        "error": str(e),
                    }
                )

        return final_results

    def clean_and_tokenize_text(self, data):
        cleaned_texts = ""
        for point in data.points:
            if "text" in point.payload:
                raw_text = point.payload["text"]
                cleaned_text = re.sub(r"[●■○]", "", raw_text)
                cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
                tokens = cleaned_text.split()
                filtered_tokens = [token.lower() for token in tokens if token.isalnum()]
                cleaned_text = " ".join(filtered_tokens)
                cleaned_texts += cleaned_text
        return cleaned_texts


if __name__ == "__main__":

    from bestrag import BestRAG

    rag = BestRAG(
        url="https://3c2bb745-57c0-478a-b61f-af487f8382e8.eu-central-1-0.aws.cloud.qdrant.io:6333",
        api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwiZXhwIjoxNzQ3MzM3NzY4fQ.AEDv7pPyzgF2U1Od9NGbmcC2r5LahxLIPyb_KybZYhQ",
        collection_name="fyptest",
    )

    scorer = ContextScorer(course_id=1, assignment_id=1, rag=rag)
    results = scorer.run({}, {}, {})
    print(results)
