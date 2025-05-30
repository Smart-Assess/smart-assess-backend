from datetime import datetime, timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pymongo import UpdateOne
from utils.mongodb import mongo_db
import logging

logger = logging.getLogger(__name__)


class PlagiarismChecker:
    def __init__(
        self,
        course_id: int,
        assignment_id: int,
        similarity_threshold: float = 0.8,
        submission_ids=None,
    ):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.similarity_threshold = similarity_threshold
        self.submission_ids = submission_ids or []
        self.questions_answers_by_pdf = {}
        self.teacher_questions = {}
        self.similarity_results = {}
        self.db = mongo_db.db
        self.results_collection = self.db["evaluation_results"]

    def find_common_parts(self, answer_1: str, answer_2: str) -> str:
        answer_1_sentences = set(s.strip() for s in answer_1.split(".") if s.strip())
        answer_2_sentences = set(s.strip() for s in answer_2.split(".") if s.strip())
        common_sentences = answer_1_sentences.intersection(answer_2_sentences)
        return ". ".join(sorted(list(common_sentences))) if common_sentences else ""

    def compare_answers(self):
        self.similarity_results = {
            pdf_file: {} for pdf_file in self.questions_answers_by_pdf
        }
        pdf_files_processed = list(self.questions_answers_by_pdf.keys())

        for i, current_pdf_file in enumerate(pdf_files_processed):
            current_qa_dict = self.questions_answers_by_pdf.get(current_pdf_file, {})
            self.similarity_results[current_pdf_file] = {}

            for question_key in self.teacher_questions:
                if not question_key.startswith("Question#"):
                    continue
                answer_key = f"Answer#{question_key.split('#')[1]}"
                current_answer = current_qa_dict.get(answer_key, "").strip()

                if not current_answer or len(current_answer.split()) < 5:  # Min 5 words
                    logger.info(
                        f"Empty or very short answer for {current_pdf_file} - {answer_key} - assigning zero plagiarism score"
                    )
                    self.similarity_results[current_pdf_file][question_key] = {
                        "Comparisons": {},
                        "max_similarity": 0.0,
                        "copied_sentence": "",
                        "compared_with_submission_id": None,
                    }
                    continue

                question_result = {
                    "Comparisons": {},
                    "max_similarity": 0.0,
                    "copied_sentence": "",
                    "compared_with_submission_id": None,
                }

                for j, other_pdf_file in enumerate(pdf_files_processed):
                    if i == j:
                        continue

                    other_submission_id = (
                        self.submission_ids[j]
                        if j < len(self.submission_ids)
                        else other_pdf_file
                    )

                    other_qa_dict = self.questions_answers_by_pdf.get(
                        other_pdf_file, {}
                    )
                    other_answer = other_qa_dict.get(answer_key, "").strip()

                    if not other_answer or len(other_answer.split()) < 5:  # Min 5 words
                        similarity = 0.0
                        copied_sentence = ""
                    else:
                        try:
                            vectorizer = TfidfVectorizer()
                            tfidf_matrix = vectorizer.fit_transform(
                                [current_answer, other_answer]
                            )
                            similarity = cosine_similarity(
                                tfidf_matrix[0:1], tfidf_matrix[1:2]
                            )[0][0]
                        except (
                            ValueError
                        ):  # Happens if one of the answers is empty after vectorization
                            similarity = 0.0

                        copied_sentence = ""
                        if similarity >= self.similarity_threshold:
                            copied_sentence = self.find_common_parts(
                                current_answer, other_answer
                            )

                    question_result["Comparisons"][other_submission_id] = {
                        "similarity": round(similarity, 4),
                        "copied_sentence": copied_sentence,
                    }

                    if similarity > question_result["max_similarity"]:
                        question_result["max_similarity"] = round(similarity, 4)
                        question_result["copied_sentence"] = copied_sentence
                        question_result["compared_with_submission_id"] = (
                            other_submission_id
                        )

                self.similarity_results[current_pdf_file][
                    question_key
                ] = question_result

    def save_results_to_mongo(self):
        operations = []
        pdf_files_list = list(self.questions_answers_by_pdf.keys())

        for pdf_idx, pdf_file in enumerate(pdf_files_list):
            submission_id = (
                self.submission_ids[pdf_idx]
                if pdf_idx < len(self.submission_ids)
                else pdf_file
            )

            similarity_data_for_pdf = self.similarity_results.get(pdf_file, {})
            question_scores_for_mongo = []
            valid_similarities_for_overall = []

            for q_key, data in similarity_data_for_pdf.items():
                if q_key.startswith("Question#"):
                    q_num = int(q_key.split("#")[1])
                    max_similarity = data.get("max_similarity", 0.0)
                    copied_sentence = data.get("copied_sentence", "")
                    compared_with_submission_id = data.get(
                        "compared_with_submission_id"
                    )

                    question_scores_for_mongo.append(
                        {
                            "question_number": q_num,
                            "scores": {
                                "plagiarism": {
                                    "score": round(max_similarity, 4),
                                    "copied_sentence": copied_sentence,
                                    "compared_with_submission_id": compared_with_submission_id,
                                    "evaluated_at": datetime.now(timezone.utc),
                                }
                            },
                        }
                    )
                    valid_similarities_for_overall.append(max_similarity)

            overall_plagiarism_score = 0.0
            if valid_similarities_for_overall:
                overall_plagiarism_score = round(
                    sum(valid_similarities_for_overall)
                    / len(valid_similarities_for_overall),
                    4,
                )

            update_doc = {
                "$set": {
                    f"overall_scores.plagiarism": {
                        "score": overall_plagiarism_score,
                        "evaluated_at": datetime.now(timezone.utc),
                    },
                    "pdf_file_reference": pdf_file,
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

            for qs_mongo in question_scores_for_mongo:
                operations.append(
                    UpdateOne(
                        {
                            "submission_id": submission_id,
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "questions.question_number": qs_mongo["question_number"],
                        },
                        {
                            "$set": {
                                "questions.$.scores.plagiarism": qs_mongo["scores"][
                                    "plagiarism"
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
                            "questions.question_number": {
                                "$ne": qs_mongo["question_number"]
                            },
                        },
                        {
                            "$addToSet": {
                                "questions": {
                                    "question_number": qs_mongo["question_number"],
                                    "scores": {
                                        "plagiarism": qs_mongo["scores"]["plagiarism"]
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
                    f"MongoDB bulk write for plagiarism: {result.bulk_api_result}"
                )
            except Exception as e:
                logger.error(f"Error saving plagiarism to MongoDB: {str(e)}")

    def run(self, teacher_questions, questions_answers_by_pdf, submission_ids=None):
        self.teacher_questions = teacher_questions
        self.questions_answers_by_pdf = questions_answers_by_pdf
        if submission_ids:
            self.submission_ids = submission_ids
        else:
            self.submission_ids = list(questions_answers_by_pdf.keys())

        self.compare_answers()
        self.save_results_to_mongo()

        final_results_list = []
        pdf_files_list = list(self.questions_answers_by_pdf.keys())

        for pdf_idx, pdf_file in enumerate(pdf_files_list):
            submission_id = (
                self.submission_ids[pdf_idx]
                if pdf_idx < len(self.submission_ids)
                else pdf_file
            )
            similarity_data = self.similarity_results.get(pdf_file, {})

            question_results_for_output = {}
            valid_similarities_for_overall = []

            for q_key, data in similarity_data.items():
                if q_key.startswith("Question#"):
                    max_similarity = data.get("max_similarity", 0.0)
                    copied_sentence = data.get("copied_sentence", "")
                    compared_with_submission_id = data.get(
                        "compared_with_submission_id"
                    )
                    question_results_for_output[q_key] = {
                        "plagiarism_score": round(max_similarity, 4),
                        "copied_sentence": copied_sentence,
                        "compared_with_submission_id": compared_with_submission_id,
                    }
                    valid_similarities_for_overall.append(max_similarity)

            overall_similarity = 0.0
            if valid_similarities_for_overall:
                overall_similarity = round(
                    sum(valid_similarities_for_overall)
                    / len(valid_similarities_for_overall),
                    4,
                )

            final_results_list.append(
                {
                    "submission_id": submission_id,
                    "pdf_file_reference": pdf_file,
                    "question_results": question_results_for_output,
                    "overall_similarity": overall_similarity,
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        return {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "results": final_results_list,
        }


if __name__ == "__main__":
    teacher_q = {
        "Question#1": "Explain photosynthesis.",
        "Question#2": "What is gravity?",
    }
    student_answers = {
        "studentA.pdf": {
            "Question#1": "Photosynthesis is the process by which green plants use sunlight, water, and carbon dioxide to create their own food and release oxygen. It is a vital process for life on Earth.",
            "Answer#1": "Photosynthesis is the process by which green plants use sunlight, water, and carbon dioxide to create their own food and release oxygen. It is a vital process for life on Earth.",
            "Question#2": "Gravity is a force of attraction that exists between any two masses, any two bodies, any two particles.",
            "Answer#2": "Gravity is a fundamental force of attraction that exists between any two objects with mass. The more mass an object has, the stronger its gravitational pull.",
        },
        "studentB.pdf": {
            "Question#1": "Photosynthesis is how plants make food. They use sunlight and water. It is very important.",
            "Answer#1": "Photosynthesis is how plants make food. They use sunlight and water. It is very important.",
            "Question#2": "Gravity is what keeps us on the ground. It pulls things down.",
            "Answer#2": "Gravity is what keeps us on the ground. It pulls things down. Without it we would float away.",
        },
        "studentC.pdf": {
            "Question#1": "Photosynthesis is the process by which green plants use sunlight, water, and carbon dioxide to create their own food and release oxygen. It is a vital process for life on Earth.",  # Identical to A
            "Answer#1": "Photosynthesis is the process by which green plants use sunlight, water, and carbon dioxide to create their own food and release oxygen. It is a vital process for life on Earth.",
            "Question#2": "Gravity is a force of attraction. It makes apples fall from trees.",
            "Answer#2": "Gravity is a force of attraction. It makes apples fall from trees. Newton discovered it.",
        },
    }
    submission_ids_main = ["studA_id", "studB_id", "studC_id"]

    checker = PlagiarismChecker(
        course_id=101, assignment_id=202, submission_ids=submission_ids_main
    )
    plagiarism_results = checker.run(teacher_q, student_answers)
    import json

    print(json.dumps(plagiarism_results, indent=2))
