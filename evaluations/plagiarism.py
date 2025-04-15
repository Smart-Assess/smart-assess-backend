from datetime import datetime, timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pymongo import UpdateOne

from utils.mongodb import mongo_db

class PlagiarismChecker:
    def __init__(self, course_id: int, assignment_id: int, similarity_threshold: float = 0.8, submission_ids=None):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.similarity_threshold = similarity_threshold
        self.submission_ids = submission_ids or []  # List of submission_ids
        
        self.questions_answers_by_pdf = {}
        self.teacher_questions = {}
        self.similarity_results = {}

        # MongoDB setup
        self.db = mongo_db.db
        self.results_collection = self.db['evaluation_results']

    def find_common_parts(self, answer_1: str, answer_2: str) -> str:
        """Find common parts between two answers by comparing sentences."""
        answer_1_sentences = set(answer_1.split('. '))
        answer_2_sentences = set(answer_2.split('. '))
        common_sentences = answer_1_sentences.intersection(answer_2_sentences)
        return '. '.join(common_sentences)

    def compare_answers(self):
        """Compare answers between student submissions"""
        self.similarity_results = {pdf_file: {} for pdf_file in self.questions_answers_by_pdf}

        for i, pdf_file in enumerate(self.questions_answers_by_pdf):
            current_qa_dict = self.questions_answers_by_pdf.get(pdf_file, {})

            for question_key in self.teacher_questions:
                if not question_key.startswith("Question#"):
                    continue

                answer_key = f"Answer#{question_key.split('#')[1]}"
                current_answer = current_qa_dict.get(answer_key, "").strip()
                
                # Handle empty answers explicitly
                if not current_answer or len(current_answer) < 3:
                    print(f"Empty or very short answer for {pdf_file} - {answer_key} - assigning zero plagiarism score")
                    self.similarity_results[pdf_file][question_key] = {
                        "Comparisons": {},
                        "max_similarity": 0.0,
                        "copied_sentence": ""
                    }
                    continue  # Skip further processing for empty answers
                
                question_result = {
                    "Comparisons": {},
                    "max_similarity": 0.0,
                    "copied_sentence": ""
                }

                for j, other_pdf in enumerate(self.questions_answers_by_pdf):
                    if i == j:
                        continue  

                    other_qa_dict = self.questions_answers_by_pdf.get(other_pdf, {})
                    other_answer = other_qa_dict.get(answer_key, "").strip()

                    if not current_answer or not other_answer:
                        similarity = 0.0
                        copied_sentence = ""
                    else:
                        common_parts = self.find_common_parts(current_answer, other_answer)
                        vectorizer = TfidfVectorizer()
                        tfidf_matrix = vectorizer.fit_transform([current_answer, other_answer])
                        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                        copied_sentence = common_parts if similarity >= self.similarity_threshold else ""

                    question_result["Comparisons"][other_pdf] = {
                        "similarity": similarity,
                        "copied_sentence": copied_sentence
                    }

                    if similarity > question_result["max_similarity"]:
                        question_result["max_similarity"] = similarity
                        question_result["copied_sentence"] = copied_sentence

                self.similarity_results[pdf_file][question_key] = question_result
    
    def save_results_to_mongo(self, submission_id, results):
        """Save plagiarism scores in unified evaluation document"""
        similarity_data = results.get("similarity_data", {})
        pdf_file = results.get("pdf_file", "")
        qa_results = results.get("qa_results", {})
        
        # Calculate overall similarity
        total_similarity = 0
        question_count = 0
        question_updates = []

        for q_key in qa_results:
            if q_key.startswith("Question#"):
                q_num = int(q_key.split('#')[1])
                if q_key in similarity_data:
                    max_similarity = similarity_data[q_key].get("max_similarity", 0)
                    copied_sentence = similarity_data[q_key].get("copied_sentence", "")
                    
                    # Create proper UpdateOne object
                    question_updates.append(UpdateOne(
                        {
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "submission_id": submission_id,
                            "questions.question_number": q_num
                        },
                        {
                            "$set": {
                                "questions.$.scores.plagiarism": {
                                    "score": round(max_similarity, 4),
                                    "copied_sentence": copied_sentence,
                                    "evaluated_at": datetime.now(timezone.utc)
                                }
                            }
                        }
                    ))
                    
                    total_similarity += max_similarity
                    question_count += 1

        # First ensure document exists with questions array
        self.results_collection.update_one(
            {
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "submission_id": submission_id
            },
            {
                "$set": {
                    "overall_scores.plagiarism": {
                        "score": round(total_similarity / question_count, 4) if question_count > 0 else 0,
                        "evaluated_at": datetime.now(timezone.utc)
                    },
                    "pdf_file": pdf_file  # Keep this for reference
                },
                "$setOnInsert": {
                    "questions": [
                        {
                            "question_number": i,
                            "scores": {}
                        } for i in range(1, len(self.teacher_questions)//2 + 1)
                    ]
                }
            },
            upsert=True
        )

        # Execute question updates if any
        if question_updates:
            self.results_collection.bulk_write(question_updates)

    def run(self, teacher_questions, questions_answers_by_pdf, submission_ids=None):
        self.teacher_questions = teacher_questions
        self.questions_answers_by_pdf = questions_answers_by_pdf
        
        if submission_ids:
            self.submission_ids = submission_ids
        
        # Compare answers between students
        self.compare_answers()
        
        # Prepare final results structure
        final_results = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "results": []
        }

        # Include results for all PDFs
        pdf_files_list = list(self.questions_answers_by_pdf.keys())
        for pdf_file in self.questions_answers_by_pdf:
            qa_results = self.questions_answers_by_pdf.get(pdf_file, {})
            similarity_data = self.similarity_results.get(pdf_file, {})
            submission_id = self.submission_ids[pdf_files_list.index(pdf_file)] if self.submission_ids else pdf_file
            
            question_results = {}
            total_similarity = 0
            question_count = 0

            for q_key in qa_results:
                if q_key.startswith("Question#"):
                    if q_key in similarity_data:
                        max_similarity = similarity_data[q_key].get("max_similarity", 0)
                        copied_sentence = similarity_data[q_key].get("copied_sentence", "")
                        
                        question_results[q_key] = {
                            'plagiarism_score': round(max_similarity, 4),
                            'copied_sentence': copied_sentence
                        }
                        
                        total_similarity += max_similarity
                        question_count += 1

            submission_result = {
                "submission_id": submission_id,
                "pdf_file": pdf_file,
                "question_results": question_results,
                "overall_similarity": round(total_similarity / question_count, 4) if question_count > 0 else 0,
                "evaluated_at": datetime.now(timezone.utc)
            }
            
            final_results["results"].append(submission_result)
            
            # Save to MongoDB
            self.save_results_to_mongo(submission_id, {
                "similarity_data": similarity_data,
                "pdf_file": pdf_file,
                "qa_results": qa_results
            })

        return final_results