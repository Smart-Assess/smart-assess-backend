import pymongo
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
        self.client = pymongo.MongoClient(
            "mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority"
        )
        self.db = self.client['FYP']
        self.qa_collection = self.db['qa_extractions']

    def fetch_qa_pairs(self):
        """Fetch Q&A pairs from MongoDB for the given course and assignment"""
        cursor = self.qa_collection.find({
            "course_id": self.course_id,
            "assignment_id": self.assignment_id
        })
        for document in cursor:
            pdf_file = document['pdf_file']
            if document['is_teacher']:
                self.teacher_questions = document['qa_pairs']
            else:
                self.questions_answers_by_pdf[pdf_file] = document['qa_pairs']

    def compare_answers(self):
        """Compare answers between student submissions"""
        self.similarity_results = {pdf_file: {} for pdf_file in self.questions_answers_by_pdf}

        for i, pdf_file in enumerate(self.questions_answers_by_pdf):
            current_qa_dict = self.questions_answers_by_pdf.get(pdf_file, {})
            for question_key in self.teacher_questions:
                if not question_key.startswith("Question#"):
                    continue

                answer_key = f"Answer#{question_key.split('#')[1]}"
                current_answer = current_qa_dict.get(answer_key, "")
                
                question_result = {
                    "Question": self.teacher_questions[question_key],
                    "Answer": current_answer,
                    "Comparisons": {}
                }

                max_similarity = 0.0

                for j, other_pdf in enumerate(self.questions_answers_by_pdf):
                    if i == j:
                        continue

                    other_qa_dict = self.questions_answers_by_pdf.get(other_pdf, {})
                    other_answer = other_qa_dict.get(answer_key, "")
                    if not current_answer or not other_answer:
                        similarity = 0.0
                    else:
                        vectorizer = TfidfVectorizer()
                        tfidf_matrix = vectorizer.fit_transform([current_answer, other_answer])
                        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]

                    question_result["Comparisons"][other_pdf] = {
                        "similarity": similarity,
                    }

                    if similarity > max_similarity:
                        max_similarity = similarity

                question_result["max_similarity"] = max_similarity
                self.similarity_results[pdf_file][question_key] = question_result

    def save_results_to_mongo(self):
        print("Starting MongoDB save operation...")
        for pdf_file, qa_results in self.questions_answers_by_pdf.items():
            similarity_data = self.similarity_results.get(pdf_file, {})
            
            for q_key in qa_results:
                if q_key.startswith("Question#"):
                    question_num = q_key.split('#')[1]
                    answer_key = f"Answer#{question_num}"
                    
                    # Get plagiarism score
                    plagiarism_score = 0
                    if q_key in similarity_data:
                        max_similarity = similarity_data[q_key].get("max_similarity", 0)
                        plagiarism_score = max_similarity
                    
                    # Update the document with plagiarism score
                    self.qa_collection.update_one(
                        {
                            "course_id": self.course_id,
                            "assignment_id": self.assignment_id,
                            "pdf_file": pdf_file,
                            f"qa_pairs.{q_key}": {"$exists": True}
                        },
                        {
                            "$set": {
                                f"qa_pairs.{q_key}.plagiarism_score": round(plagiarism_score, 4)
                            }
                        }
                    )

    def run(self):
        # Fetch Q&A pairs from MongoDB
        self.fetch_qa_pairs()
        
        # Compare answers between students
        self.compare_answers()
        
        # Save results
        # self.save_results_to_mongo()

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
                        
                        question_results[q_key] = {
                            'plagiarism_score': round(max_similarity, 4)
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


# 
if __name__ == "__main__":
    # Initialize the plagiarism checker
    checker = PlagiarismChecker(
        course_id=1,
        assignment_id=1,
        similarity_threshold=0.8
    )

    # Run the plagiarism checker
    results = checker.run()
    print(results)