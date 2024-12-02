import PyPDF2
import re
import pymongo
from typing import List, Dict
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class PDFQuestionAnswerExtractor:
    def __init__(self, pdf_files: List[str], role: str, student_id: str = None, 
                 assignment_id: int = None, min_characters: int = 100):
        self.pdf_files = pdf_files
        self.role = role
        self.student_id = student_id
        self.assignment_id = assignment_id
        self.min_characters = min_characters
        self.questions_answers_by_pdf = {}
        self.similarity_results = {}

        # MongoDB setup
        self.client = pymongo.MongoClient(
            "mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority&appName=FYP"
        )
        self.db = self.client['FYP']
        self.qa_collection = self.db.teacher_assignments if role == "teacher" else self.db.submissions
        self.plagiarism_collection = self.db.plagiarism_results

    def extract_text_from_pdf(self, pdf_file: str) -> List[str]:
        text_by_page = []
        try:
            with open(pdf_file, "rb") as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    text_by_page.append(page.extract_text())
        except Exception as e:
            print(f"Could not read {pdf_file}: {e}")
        return text_by_page

    def clean_text(self, text: str) -> str:
        return ' '.join(text.split()).strip()

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

    def run(self):
        for pdf_file in self.pdf_files:
            text_by_page = self.extract_text_from_pdf(pdf_file)
            pdf_qa_dict = {}

            for page_number, text in enumerate(text_by_page, start=1):
                if text:
                    if "Question#" not in text or "Answer#" not in text:
                        continue

                    page_qa_dict = self.parse_questions_answers(text)
                    filtered_qa_dict = {
                        key: value for key, value in page_qa_dict.items()
                        if not key.startswith("Answer#") or len(value) >= self.min_characters
                    }
                    pdf_qa_dict.update(filtered_qa_dict)

            self.questions_answers_by_pdf[pdf_file] = pdf_qa_dict

    def compare_answers(self, similarity_threshold=0.8):
        self.similarity_results = {pdf_file: {} for pdf_file in self.pdf_files}

        for i, pdf_file in enumerate(self.pdf_files):
            current_qa_dict = self.questions_answers_by_pdf.get(pdf_file, {})

            for question_key, question_text in current_qa_dict.items():
                if not question_key.startswith("Question#"):
                    continue

                answer_key = f"Answer#{question_key.split('#')[1]}"
                current_answer = current_qa_dict.get(answer_key, "")
                current_is_skipped = len(current_answer) < self.min_characters

                question_result = {
                    "Question": question_text,
                    "Answer": current_answer if not current_is_skipped else "No answer provided",
                    "Comparisons": {}
                }

                for j, other_pdf in enumerate(self.pdf_files):
                    if i == j:
                        continue

                    other_qa_dict = self.questions_answers_by_pdf.get(other_pdf, {})
                    other_answer = other_qa_dict.get(answer_key, "")
                    other_is_skipped = len(other_answer) < self.min_characters

                    if current_is_skipped or other_is_skipped:
                        similarity = 0.0
                        status = "Skipped"
                    else:
                        vectorizer = TfidfVectorizer()
                        tfidf_matrix = vectorizer.fit_transform([current_answer, other_answer])
                        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                        status = "Similar" if similarity >= similarity_threshold else "Not Similar"

                    question_result["Comparisons"][other_pdf] = {
                        "similarity": similarity,
                        "status": status
                    }

                self.similarity_results[pdf_file][question_key] = question_result

    def save_results_to_mongo(self):
        """Save Q&A and plagiarism results to MongoDB"""
        for pdf_file, qa_results in self.questions_answers_by_pdf.items():
            data = {
                "PDF_File": pdf_file,
                "Role": self.role,
                "student_id": self.student_id,
                "assignment_id": self.assignment_id,
                "submitted_at": datetime.utcnow(),
                "QA_Results": qa_results,
            }

            if pdf_file in self.similarity_results:
                data["similarity_results"] = self.similarity_results[pdf_file]

            # Update or insert in QA collection
            self.qa_collection.update_one(
                {
                    "assignment_id": self.assignment_id,
                    "student_id": self.student_id,
                    "PDF_File": pdf_file
                },
                {"$set": data},
                upsert=True
            )

            # Save plagiarism results if they exist
            if self.similarity_results:
                plagiarism_data = {
                    "assignment_id": self.assignment_id,
                    "student_id": self.student_id,
                    "PDF_File": pdf_file,
                    "checked_at": datetime.utcnow(),
                    "similarity_results": self.similarity_results[pdf_file]
                }
                
                self.plagiarism_collection.update_one(
                    {
                        "assignment_id": self.assignment_id,
                        "student_id": self.student_id,
                        "PDF_File": pdf_file
                    },
                    {"$set": plagiarism_data},
                    upsert=True
                )


# # Initialize and run the extractor
# pdf_files = ["p1.pdf", "p2.pdf", "p3.pdf"]
# role = "student"
# min_characters = 100

# extractor = PDFQuestionAnswerExtractor(pdf_files, role, min_characters)
# extractor.run()
# extractor.compare_answers(similarity_threshold=0.8)
# extractor.save_results_to_mongo()  # Save the results to MongoDB