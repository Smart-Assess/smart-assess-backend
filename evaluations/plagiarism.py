from pymongo import UpdateOne, MongoClient
from datetime import datetime, timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class PlagiarismChecker:
    def __init__(self, course_id: int, assignment_id: int, similarity_threshold: float = 0.8):
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.similarity_threshold = similarity_threshold
        
        self.questions_answers_by_pdf = {}
        self.teacher_questions = {}
        self.similarity_results = {}

        # MongoDB setup
        self.client = MongoClient(
            "mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority"
        )
        self.db = self.client['FYP']
        self.qa_collection = self.db['qa_extractions']
        self.results_collection = self.db['evaluation_results']

    def fetch_qa_pairs(self):
        """Fetch Q&A pairs from MongoDB for the given course and assignment"""
        cursor = self.qa_collection.find({
            "course_id": self.course_id,
            "assignment_id": self.assignment_id
        })

        for document in cursor:
            pdf_file = document['pdf_file']
            if document['is_teacher']:
                self.teacher_questions = document.get('qa_pairs', {})
            else:
                self.questions_answers_by_pdf[pdf_file] = document.get('qa_pairs', {})

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
    
    def save_results_to_mongo(self):
        """Save plagiarism scores in unified evaluation document"""
        for pdf_file, qa_results in self.questions_answers_by_pdf.items():
            similarity_data = self.similarity_results.get(pdf_file, {})
            
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
                                "pdf_file": pdf_file,
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
                    "pdf_file": pdf_file
                },
                {
                    "$set": {
                        "overall_scores.plagiarism": {
                            "score": round(total_similarity / question_count, 4) if question_count > 0 else 0,
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

    def run(self):
        # Fetch Q&A pairs from MongoDB
        self.fetch_qa_pairs()
        
        # Compare answers between students
        self.compare_answers()
        
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
            similarity_data = self.similarity_results.get(pdf_file, {})
            
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
                "submission_id": pdf_file,
                "question_results": question_results,
                "overall_similarity": round(total_similarity / question_count, 4) if question_count > 0 else 0,
                "evaluated_at": datetime.now(timezone.utc)
            }
            
            final_results["results"].append(submission_result)

        return final_results


# Run the plagiarism checker
if __name__ == "__main__":
    checker = PlagiarismChecker(course_id=1, assignment_id=1, similarity_threshold=0.01)
    results = checker.run()
    print(results)