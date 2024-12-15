import pymongo
import requests
from tempfile import NamedTemporaryFile
from typing import List, Dict, Optional
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import PyPDF2
import re

class PDFQuestionAnswerExtractor:
    def __init__(
        self, 
        pdf_files: List[str],
        teacher_pdf: str,
        course_id: int,
        assignment_id: int,
        student_id: Optional[str] = None,
        min_characters: int = 100,
        similarity_threshold: float = 0.8
    ):
        self.pdf_files = pdf_files
        self.teacher_pdf = teacher_pdf
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.student_id = student_id
        self.min_characters = min_characters
        self.similarity_threshold = similarity_threshold
        
        self.questions_answers_by_pdf = {}
        self.teacher_questions = {}
        self.similarity_results = {}
        self.final_results = {}

        # MongoDB setup
        self.client = pymongo.MongoClient(
            "mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority"
        )
        self.db = self.client['FYP']
        self.qa_collection = self.db.submissions
        self.plagiarism_collection = self.db.plagiarism_results

    def extract_qa_only(self) -> Dict:
        """Extract QA pairs without plagiarism checking"""
        teacher_text = self.extract_text_from_pdf(self.teacher_pdf)
        self.teacher_questions = {}
        for page in teacher_text:
            self.teacher_questions.update(self.parse_questions_answers(page))

        qa_results = {}
        for pdf_file in self.pdf_files:
            text_by_page = self.extract_text_from_pdf(pdf_file)
            for text in text_by_page:
                qa_dict = self.parse_questions_answers(text)
                qa_results.update(qa_dict)

        return qa_results

    def run(self) -> Dict:
        # First extract teacher questions
        teacher_text = self.extract_text_from_pdf(self.teacher_pdf)
        for page in teacher_text:
            page_questions = self.parse_questions_answers(page)
            print("Teacher Page Questions:", page_questions)
            self.teacher_questions.update(page_questions)

        # Extract student answers
        for pdf_file in self.pdf_files:
            text_by_page = self.extract_text_from_pdf(pdf_file)
            pdf_qa_dict = {}
            
            for text in text_by_page:
                page_qa_dict = self.parse_questions_answers(text)
                # Only keep answers that match teacher questions
                filtered_qa_dict = {}
                for key, value in page_qa_dict.items():
                    if key.startswith("Question#"):
                        if key in self.teacher_questions:
                            filtered_qa_dict[key] = value
                            ans_key = f"Answer#{key.split('#')[1]}"
                            if ans_key in page_qa_dict and len(page_qa_dict[ans_key]) >= self.min_characters:
                                filtered_qa_dict[ans_key] = page_qa_dict[ans_key]
                
                pdf_qa_dict.update(filtered_qa_dict)
            
            self.questions_answers_by_pdf[pdf_file] = pdf_qa_dict

        # Compare answers between students
        self.compare_answers()
        
        # Save results
        self.save_results_to_mongo()

        # Prepare final results
        final_results = {
        "course_id": self.course_id,
        "assignment_id": self.assignment_id,
        "results": []
        }

        for pdf_file in self.pdf_files:
            question_results = {}
            qa_results = self.questions_answers_by_pdf.get(pdf_file, {})
            similarity_data = self.similarity_results.get(pdf_file, {})

            total_similarity = 0
            question_count = 0

            for q_key in qa_results:
                if q_key.startswith("Question#"):
                    if q_key in similarity_data:
                        comparisons = similarity_data[q_key]["Comparisons"]
                        avg_similarity = sum(c["similarity"] for c in comparisons.values()) / len(comparisons) if comparisons else 0
                        
                        # New format for question results
                        question_results[q_key] = {
                            'context_score': None,
                            'plagiarism_score': round(avg_similarity, 4),
                            'ai_score': None,
                            'grammar_score': None
                        }
                        
                        total_similarity += avg_similarity
                        question_count += 1

            submission_result = {
                "student_id": self.student_id,
                "submission_id": pdf_file,  # Using pdf_file as submission_id
                "question_results": question_results,
                "overall_similarity": round(total_similarity / question_count, 4) if question_count > 0 else 0,
                "evaluated_at": datetime.utcnow()
            }
            
            final_results["results"].append(submission_result)

        return final_results

    def compare_answers(self):
        """Compare answers between student submissions"""
        self.similarity_results = {pdf_file: {} for pdf_file in self.pdf_files}

        for i, pdf_file in enumerate(self.pdf_files):
            current_qa_dict = self.questions_answers_by_pdf.get(pdf_file, {})

            for question_key in self.teacher_questions:
                if not question_key.startswith("Question#"):
                    continue

                answer_key = f"Answer#{question_key.split('#')[1]}"
                current_answer = current_qa_dict.get(answer_key, "")
                
                question_result = {
                    "Question": self.teacher_questions[question_key],
                    "Answer": current_answer if len(current_answer) >= self.min_characters else "No valid answer",
                    "Comparisons": {}
                }

                for j, other_pdf in enumerate(self.pdf_files):
                    if i == j:
                        continue

                    other_qa_dict = self.questions_answers_by_pdf.get(other_pdf, {})
                    other_answer = other_qa_dict.get(answer_key, "")

                    if len(current_answer) < self.min_characters or len(other_answer) < self.min_characters:
                        similarity = 0.0
                        status = "Skipped"
                    else:
                        vectorizer = TfidfVectorizer()
                        tfidf_matrix = vectorizer.fit_transform([current_answer, other_answer])
                        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                        status = "Similar" if similarity >= self.similarity_threshold else "Not Similar"

                    question_result["Comparisons"][other_pdf] = {
                        "similarity": similarity,
                        "status": status
                    }

                self.similarity_results[pdf_file][question_key] = question_result

    def save_results_to_mongo(self):
        """Save results with course/assignment context"""
        for pdf_file, qa_results in self.questions_answers_by_pdf.items():
            question_results = {}
            similarity_data = self.similarity_results.get(pdf_file, {})

            for q_key in qa_results:
                if q_key.startswith("Question#"):
                    if q_key in similarity_data:
                        comparisons = similarity_data[q_key]["Comparisons"]
                        avg_similarity = sum(c["similarity"] for c in comparisons.values()) / len(comparisons) if comparisons else 0
                        
                        question_results[q_key] = {
                            'context_score': None,
                            'plagiarism_score': round(avg_similarity, 4),
                            'ai_score': None,
                            'grammar_score': None
                        }

            # Save to submissions collection with new format
            submission_data = {
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "PDF_File": pdf_file,
                "student_id": self.student_id,
                "submitted_at": datetime.utcnow(),
                "QA_Results": qa_results,
                "question_results": question_results
            }

            self.qa_collection.update_one(
                {
                    "course_id": self.course_id,
                    "assignment_id": self.assignment_id,
                    "student_id": self.student_id,
                    "PDF_File": pdf_file
                },
                {"$set": submission_data},
                upsert=True
            )

            # Save plagiarism results separately
            plagiarism_data = {
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "student_id": self.student_id,
                "PDF_File": pdf_file,
                "checked_at": datetime.utcnow(),
                "question_results": question_results,
                "overall_similarity": sum(result['plagiarism_score'] for result in question_results.values()) / len(question_results) if question_results else 0
            }
        
            self.plagiarism_collection.update_one(
                {
                    "course_id": self.course_id,
                    "assignment_id": self.assignment_id,
                    "student_id": self.student_id,
                    "PDF_File": pdf_file
                },
                {"$set": plagiarism_data},
                upsert=True
            )
        
    def extract_text_from_pdf(self, pdf_file: str) -> List[str]:
        text_by_page = []
        try:
            if pdf_file.startswith("http://") or pdf_file.startswith("https://"):
                response = requests.get(pdf_file)
                response.raise_for_status()
                with NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name
                pdf_file = temp_file_path

            with open(pdf_file, "rb") as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    text_by_page.append(page.extract_text())
        except Exception as e:
            print(f"Could not read {pdf_file}: {e}")
        return text_by_page

    def parse_questions_answers(self, text: str) -> Dict[str, str]:
        if "Question#" not in text or "Answer#" not in text:
            return {}

        qa_pattern = re.compile(r"(Question\s*#\d+:.*?)(Answer\s*#\d+:.*?)?(?=Question\s*#\d+:|$)", re.DOTALL)
        qa_dict = {}

        for match in qa_pattern.finditer(text):
            question = match.group(1)
            answer = match.group(2) if match.group(2) else "Answer: "
            question_key = question.split(':', 1)[0].strip()
            answer_key = "Answer#" + question_key.split('#')[1]
            question_text = self.clean_text(question.split(':', 1)[1].strip())
            answer_text = self.clean_text(answer.split(':', 1)[1].strip()) if ':' in answer else ""

            if len(answer_text) < self.min_characters:
                answer_text = ""

            qa_dict[question_key] = question_text
            qa_dict[answer_key] = answer_text

        return qa_dict
    
    def clean_text(self, text: str) -> str:
        return ' '.join(text.split()).strip()

# # Initialize and run the extra/ctor
if __name__ == "__main__":
    extractor = PDFQuestionAnswerExtractor(
    pdf_files=["/home/samadpls/proj/fyp/smart-assess-backend/p3.pdf", "/home/samadpls/proj/fyp/smart-assess-backend/p1.pdf"],
    teacher_pdf="/home/samadpls/proj/fyp/smart-assess-backend/teacher.pdf",
    course_id=12,
    assignment_id=456,
    student_id="localtest"
)

    results = extractor.run()
    print(results)
