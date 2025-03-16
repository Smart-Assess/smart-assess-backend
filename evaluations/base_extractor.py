from typing import Dict, List
import pdfplumber
import requests
import re
from tempfile import NamedTemporaryFile
from utils.mongodb import mongo_db
from datetime import datetime, timezone

class PDFQuestionAnswerExtractor:
    def __init__(self, pdf_files: List[str], course_id: int, assignment_id: int, is_teacher: bool, submission_ids: str = None):
        self.pdf_files = pdf_files
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.is_teacher = is_teacher
        self.submission_ids = submission_ids

        # MongoDB setup
        
        self.db = mongo_db.db
        self.collection = self.db['qa_extractions']

    def extract_text_from_pdf(self, pdf_file: str) -> str:
        """Extract text from PDF with improved error handling"""
        temp_file = None
        
        try:
            if pdf_file.startswith(('http://', 'https://')):
                temp_file = self._download_pdf(pdf_file)
                pdf_path = temp_file.name
            else:
                pdf_path = pdf_file
                
            with pdfplumber.open(pdf_path) as pdf:
                text = '\n'.join(
                    page.extract_text() or '' 
                    for page in pdf.pages
                )
            return text.strip()
            
        finally:
            if temp_file:
                temp_file.close()
                
    def _download_pdf(self, url: str) -> NamedTemporaryFile:
        """Download PDF from URL to temporary file"""
        response = requests.get(url)
        response.raise_for_status()
        temp_file = NamedTemporaryFile(suffix='.pdf', delete=True)
        temp_file.write(response.content)
        return temp_file

    def parse_qa(self, text: str) -> Dict[str, Dict[str, str]]:
        """Extract question-answer pairs with improved parsing"""
        if "Question#" not in text or "Answer#" not in text:
            return {}

        qa_pattern = re.compile(r"(Question\s*#\d+:.*?)(Answer\s*#\d+:.*?)?(?=Question\s*#\d+:|$)", re.DOTALL)
        qa_dict = {}

        for match in qa_pattern.finditer(text):
            question = match.group(1)
            answer = match.group(2) if match.group(2) else "Answer: "
            question_key = question.split(':', 1)[0].strip()
            answer_key = "Answer#" + question_key.split('#')[1]
            question_text = self._clean_text(question.split(':', 1)[1].strip())
            answer_text = self._clean_text(answer.split(':', 1)[1].strip()) if ':' in answer else ""

            qa_dict[question_key] = question_text
            qa_dict[answer_key] = answer_text

        return qa_dict

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        return text

    def save_to_mongo(self, pdf_file: str, qa_pairs: Dict[str, Dict[str, str]], id):
        """Save extracted Q&A pairs to MongoDB"""
        document = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "is_teacher": self.is_teacher,
            "submission_id": self.submission_ids[id],
            "pdf_file": pdf_file,
            "qa_pairs": qa_pairs,
            "extracted_at": datetime.now(timezone.utc)
        }
        self.collection.update_one(
            {
                "course_id": self.course_id,
                "assignment_id": self.assignment_id,
                "is_teacher": self.is_teacher,
                "submission_id": self.submission_ids[id],
            },
            {"$set": document},
            upsert=True
        )

    def extract(self):
        """Main extraction method"""
        id = 0
        for pdf_file in self.pdf_files:
            try:
                text = self.extract_text_from_pdf(pdf_file)
                qa_pairs = self.parse_qa(text)
                print("Question/Answers: ",qa_pairs,"\n")
                if qa_pairs:
                    self.save_to_mongo(pdf_file, qa_pairs, id)
                else:
                    print(f"Warning: No Q&A pairs found in {pdf_file}")
                id+=1
                    
            except Exception as e:
                print(f"Error processing {pdf_file}: {str(e)}")
                continue
    

if __name__ == "__main__":
    pdf_files = [
        "/home/samadpls/proj/fyp/smart-assess-backend/teacher.pdf",
        # "/home/samadpls/proj/fyp/smart-assess-backend/p1.pdf"
    ]
    
    extractor = PDFQuestionAnswerExtractor(
        pdf_files=pdf_files,
        course_id=1,
        assignment_id=1,
        is_teacher=True,
        # student_id="student123"
    )
    extractor.extract()
    