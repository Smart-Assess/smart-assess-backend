import os
import requests
from datetime import datetime, timezone
from pymongo import UpdateOne
from utils.mongodb import mongo_db
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIDetector:
    def __init__(self, course_id: int, assignment_id: int):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.ai_service_host = os.getenv(
            "AI_DETECTION_SERVICE_HOST", "http://localhost:5001"
        )  # Default to local if not set
        self.ai_service_url = f"{self.ai_service_host}/detect"
        self.health_url = f"{self.ai_service_host}/health"
        self.service_available = False
        self.db = mongo_db.db
        self.results_collection = self.db["evaluation_results"]
        self.questions_answers_by_pdf = {}
        self.teacher_questions = {}
        self.ai_detection_results = {}
        self.submission_ids = []

        self.service_available = self._wait_for_service(max_retries=2, retry_interval=1)
        if not self.service_available:
            logger.warning(
                "AI detection service unavailable. Fallback scores (None) will be used."
            )

    def _wait_for_service(self, max_retries=1, retry_interval=2):
        for i in range(max_retries):
            try:
                response = requests.get(self.health_url, timeout=2)
                if response.status_code == 200:
                    logger.info("AI detection service is ready")
                    return True
                logger.warning(
                    f"AI detection service not ready yet (Status: {response.status_code}). Attempt {i+1}/{max_retries}"
                )
            except Exception as e:
                logger.warning(
                    f"Could not connect to AI detection service: {str(e)}. Attempt {i+1}/{max_retries}"
                )
            if i < max_retries - 1:
                time.sleep(retry_interval)
        logger.warning("AI detection service failed to become ready after retries.")
        return False

    def detect_ai_content(self, text, delay=0):
        if not text or len(text.strip()) < 10:
            logger.info(
                "Empty or very short answer - assigning None for AI detection score"
            )
            return None
        if not self.service_available:
            logger.info("AI detection service unavailable, returning None for score.")
            return None
        if delay > 0:
            time.sleep(delay)
        try:
            response = requests.post(
                self.ai_service_url,
                json={"text": text},
                timeout=5,
            )
            if response.status_code == 200:
                result = response.json()
                logger.info(f"AI detection result: {result}")
                return result.get("probability")
            else:
                logger.error(
                    f"Error from AI detection service: {response.status_code} - {response.text[:100]}"
                )
                self.service_available = False
                return None
        except requests.exceptions.Timeout:
            logger.error(
                f"Timeout calling AI detection service for text: {text[:50]}..."
            )
            self.service_available = False
            return None
        except requests.exceptions.ConnectionError:
            logger.error(
                f"Connection error with AI detection service for text: {text[:50]}..."
            )
            self.service_available = False
            return None
        except Exception as e:
            logger.error(
                f"Exception calling AI detection service: {str(e)} for text: {text[:50]}..."
            )
            self.service_available = False
            return None

    def analyze_answers(self, delay=0):
        self.ai_detection_results = {
            pdf_file: {} for pdf_file in self.questions_answers_by_pdf
        }
        if not self.service_available:
            logger.warning(
                "AI detection service is not available. All scores will be None."
            )

        for pdf_file in self.questions_answers_by_pdf:
            qa_dict = self.questions_answers_by_pdf.get(pdf_file, {})
            logger.info(f"Analyzing answers for PDF: {pdf_file}")
            for question_key in self.teacher_questions:
                if not question_key.startswith("Question#"):
                    continue
                answer_key = f"Answer#{question_key.split('#')[1]}"
                answer = qa_dict.get(answer_key, "").strip()
                ai_score = self.detect_ai_content(
                    answer, delay if self.service_available else 0
                )
                logger.info(f"AI score for {pdf_file} - {question_key}: {ai_score}")
                self.ai_detection_results[pdf_file][question_key] = {
                    "ai_score": ai_score
                }

    def save_results_to_mongo(self):
        pdf_files_list = list(self.questions_answers_by_pdf.keys())
        operations = []

        for pdf_idx, pdf_file in enumerate(pdf_files_list):
            submission_id = (
                self.submission_ids[pdf_idx]
                if pdf_idx < len(self.submission_ids)
                else pdf_file
            )

            ai_data_for_pdf = self.ai_detection_results.get(pdf_file, {})
            question_scores = []
            valid_scores_for_overall = []

            for q_key, data in ai_data_for_pdf.items():
                if q_key.startswith("Question#"):
                    q_num = int(q_key.split("#")[1])
                    ai_score = data.get("ai_score")

                    question_scores.append(
                        {
                            "question_number": q_num,
                            "scores": {
                                "ai_detection": {
                                    "score": ai_score,
                                    "evaluated_at": datetime.now(timezone.utc),
                                    "simulated": not self.service_available
                                    and ai_score is not None,
                                }
                            },
                        }
                    )
                    if ai_score is not None:
                        valid_scores_for_overall.append(ai_score)

            overall_ai_score = None
            if valid_scores_for_overall:
                overall_ai_score = round(
                    sum(valid_scores_for_overall) / len(valid_scores_for_overall), 4
                )

            update_doc = {
                "$set": {
                    f"overall_scores.ai_detection": {
                        "score": overall_ai_score,
                        "evaluated_at": datetime.now(timezone.utc),
                        "simulated": not self.service_available
                        and overall_ai_score is not None,
                    }
                },
                "$setOnInsert": {
                    "course_id": self.course_id,
                    "assignment_id": self.assignment_id,
                    "submission_id": submission_id,
                    "questions": [],
                },
            }
            operations.append(
                UpdateOne(
                    {
                        "submission_id": submission_id,
                        "course_id": self.course_id,
                        "assignment_id": self.assignment_id,
                    },
                    update_doc,
                    upsert=True,
                )
            )

            for qs in question_scores:
                operations.append(
                    UpdateOne(
                        {
                            "submission_id": submission_id,
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "questions.question_number": qs["question_number"],
                        },
                        {
                            "$set": {
                                "questions.$.scores.ai_detection": qs["scores"][
                                    "ai_detection"
                                ]
                            }
                        },
                    )
                )
                operations.append(
                    UpdateOne(
                        {
                            "submission_id": submission_id,
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "questions.question_number": {"$ne": qs["question_number"]},
                        },
                        {
                            "$addToSet": {
                                "questions": {
                                    "question_number": qs["question_number"],
                                    "scores": {
                                        "ai_detection": qs["scores"]["ai_detection"]
                                    },
                                }
                            }
                        },
                    )
                )

        if operations:
            try:
                result = self.results_collection.bulk_write(operations, ordered=False)
                logger.info(
                    f"MongoDB bulk write for AI detection: {result.bulk_api_result}"
                )
            except Exception as e:
                logger.error(f"Error saving AI detection to MongoDB: {str(e)}")

    def run(self, teacher_questions, questions_answers_by_pdf, submission_ids, delay=0):
        self.teacher_questions = teacher_questions
        self.questions_answers_by_pdf = questions_answers_by_pdf
        self.submission_ids = submission_ids
        logger.info(
            f"Starting AI detection for {len(questions_answers_by_pdf)} submissions with {delay}s delay between calls"
        )
        self.analyze_answers(delay)
        self.save_results_to_mongo()
        final_results = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "results": {},
            "service_available": self.service_available,
        }
        pdf_files_list = list(self.questions_answers_by_pdf.keys())
        for pdf_idx, pdf_file in enumerate(pdf_files_list):
            submission_id = (
                self.submission_ids[pdf_idx]
                if pdf_idx < len(self.submission_ids)
                else pdf_file
            )
            ai_data = self.ai_detection_results.get(pdf_file, {})
            question_results_for_submission = {}
            valid_scores_for_overall = []
            for q_key, data in ai_data.items():
                if q_key.startswith("Question#"):
                    ai_score = data.get("ai_score")
                    question_results_for_submission[q_key] = {"ai_score": ai_score}
                    if ai_score is not None:
                        valid_scores_for_overall.append(ai_score)

            overall_ai_score = None
            if valid_scores_for_overall:
                overall_ai_score = round(
                    sum(valid_scores_for_overall) / len(valid_scores_for_overall), 4
                )

            final_results["results"][submission_id] = {
                "question_results": question_results_for_submission,
                "overall_ai_score": overall_ai_score,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        logger.info("AI detection completed for all submissions")
        return final_results


if __name__ == "__main__":
    teacher_questions_test = {"Question#1": "What is AI?"}
    questions_answers_by_pdf_test = {
        "student1.pdf": {
            **teacher_questions_test,
            "Answer#1": "AI is artificial intelligence that can think like humans.",
        }
    }
    submission_ids_test = ["sub1"]
    detector = AIDetector(course_id=1, assignment_id=1)
    results = detector.run(
        teacher_questions_test, questions_answers_by_pdf_test, submission_ids_test
    )
    print(results)
