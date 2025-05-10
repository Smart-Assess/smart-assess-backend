import os
import tempfile
from datetime import datetime
from typing import Dict, Optional, Any
from fpdf import FPDF
from matplotlib import pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
from utils.s3 import upload_to_s3, download_from_s3
import PyPDF2

class PDFReportGenerator:
    """
    Generate report pages to append to student submissions
    with score summaries and feedback from MongoDB.
    """
    
    def __init__(self):
        """Initialize the PDF report generator"""
        self.pdf = FPDF()
        self.pdf.set_auto_page_break(auto=True, margin=15)
        
        # Color scheme
        self.primary_color = (51, 102, 204)  # RGB for #3366CC
        self.secondary_color = (66, 133, 244)  # RGB for #4285F4
        self.text_color = (33, 33, 33)  # Dark gray
        self.heading_color = (0, 0, 0)  # Black
        self.success_color = (76, 175, 80)  # Green
        self.warning_color = (255, 152, 0)  # Orange
        self.danger_color = (244, 67, 54)  # Red
    
    def generate_report_from_mongodb(self, mongo_data: Dict[str, Any], total_possible: float, 
                                     student_name: str, course_name: str, assignment_name: str):
        """Generate report page with data from MongoDB evaluation results"""
        # Start a new page for the report
        self.pdf.add_page()
        
        # Add report title
        self.pdf.set_font("Arial", 'B', 18)
        self.pdf.set_text_color(*self.heading_color)
        self.pdf.cell(0, 15, "Assignment Evaluation Report", 0, 1, 'C')
        
        # Add course and assignment info
        self.pdf.set_font("Arial", 'B', 12)
        self.pdf.set_text_color(*self.primary_color)
        self.pdf.cell(0, 10, f"Course: {course_name}", 0, 1)
        self.pdf.cell(0, 10, f"Assignment: {assignment_name}", 0, 1)
        self.pdf.cell(0, 10, f"Student: {student_name}", 0, 1)
        
        # Add horizontal line
        self.pdf.set_draw_color(*self.primary_color)
        self.pdf.set_line_width(0.5)
        self.pdf.line(10, self.pdf.get_y(), 200, self.pdf.get_y())
        self.pdf.ln(5)
        
        # Overall score section
        overall_scores = mongo_data.get("overall_scores", {})
        total_score = overall_scores.get("total", {}).get("score", 0)
        percentage = round((total_score / total_possible * 100) if total_possible > 0 else 0, 2)
        
        self.pdf.set_font("Arial", 'B', 14)
        if percentage >= 70:
            self.pdf.set_text_color(*self.success_color)
        elif percentage >= 50:
            self.pdf.set_text_color(*self.warning_color)
        else:
            self.pdf.set_text_color(*self.danger_color)
            
        self.pdf.cell(0, 15, f"Total Score: {total_score}/{total_possible} ({percentage}%)", 0, 1, 'C')
        self.pdf.set_text_color(*self.text_color)
        
        # Component scores
        self.pdf.set_font("Arial", 'B', 12)
        self.pdf.set_text_color(*self.heading_color)
        self.pdf.cell(0, 10, "Component Scores", 0, 1)
        
        # Create score visualization
        scores = []
        labels = []
        
        context_score = overall_scores.get("context", {}).get("score", 0)
        plagiarism_score = overall_scores.get("plagiarism", {}).get("score", 0)
        ai_score = overall_scores.get("ai_detection", {}).get("score", 0)
        grammar_score = overall_scores.get("grammar", {}).get("score", 0)
        
        scores = [context_score, plagiarism_score, ai_score, grammar_score]
        labels = ["Context", "Originality", "AI Detection", "Grammar"]
        
        # Create the chart
        plt.figure(figsize=(7, 3.5))
        bars = plt.bar(labels, scores, color=[
            '#3366CC' if s >= 0.7 else '#FF9800' if s >= 0.5 else '#F44336' 
            for s in scores
        ])
        
        plt.ylim(0, 1.0)
        plt.ylabel('Score (0-1)')
        plt.title('Component Scores')
        
        # Add value labels on top of bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                    f'{height:.2f}', ha='center', va='bottom')
        
        # Save the chart to a temporary file
        chart_path = tempfile.mktemp(suffix='.png')
        plt.savefig(chart_path, dpi=100, bbox_inches='tight')
        plt.close()
        
        # Add chart to PDF
        self.pdf.image(chart_path, x=30, w=150)
        
        # Clean up the temporary file
        if os.path.exists(chart_path):
            os.remove(chart_path)
        
        # Add question scores
        questions = mongo_data.get("questions", [])
        if questions:
            self.pdf.ln(5)
            self.pdf.set_font("Arial", 'B', 12)
            self.pdf.set_text_color(*self.heading_color)
            self.pdf.cell(0, 10, "Question Scores", 0, 1)
            
            # Calculate max score per question
            question_total_marks = total_possible / len(questions) if questions else 0
            
            for question in questions:
                q_num = question.get("question_number", 0)
                scores = question.get("scores", {})
                q_score = scores.get("total", {}).get("score", 0)
                
                # Add question header
                self.pdf.set_font("Arial", 'B', 11)
                self.pdf.set_text_color(*self.primary_color)
                self.pdf.cell(0, 8, f"Question {q_num}", 0, 1)
                
                # Add total score for this question
                self.pdf.set_font("Arial", 'B', 10)
                percentage = round((q_score * 100) if q_score <= 1 else 0)
                if percentage >= 70:
                    self.pdf.set_text_color(*self.success_color)
                elif percentage >= 50:
                    self.pdf.set_text_color(*self.warning_color)
                else:
                    self.pdf.set_text_color(*self.danger_color)
                    
                question_points = q_score * question_total_marks
                self.pdf.cell(0, 6, f"Score: {question_points:.2f}/{question_total_marks:.2f} ({percentage}%)", 0, 1)
                
                # Add component scores table for this question
                self.pdf.set_font("Arial", '', 9)
                self.pdf.set_text_color(*self.text_color)
                
                # Create a table for component scores
                component_scores = [
                    ("Context", scores.get("context", {}).get("score", 0)),
                    ("Originality", scores.get("plagiarism", {}).get("score", 0)),
                    ("AI Detection", scores.get("ai_detection", {}).get("score", 0)),
                    ("Grammar", scores.get("grammar", {}).get("score", 0))
                ]
                
                # Table header
                self.pdf.set_fill_color(240, 240, 240)
                self.pdf.cell(50, 6, "Component", 1, 0, 'C', True)
                self.pdf.cell(30, 6, "Score", 1, 1, 'C', True)
                
                # Table rows
                for name, score in component_scores:
                    if score is None:
                        continue
                    
                    # Set text color based on score
                    if score >= 0.7:
                        self.pdf.set_text_color(*self.success_color)
                    elif score >= 0.5:
                        self.pdf.set_text_color(*self.warning_color)
                    else:
                        self.pdf.set_text_color(*self.danger_color)
                    
                    self.pdf.cell(50, 6, name, 1, 0)
                    self.pdf.cell(30, 6, f"{score:.2f}", 1, 1, 'C')
                    
                # Reset text color
                self.pdf.set_text_color(*self.text_color)
                
                # Special handling for plagiarism details
                if "copied_sentence" in scores.get("plagiarism", {}) and scores.get("plagiarism", {}).get("copied_sentence"):
                    copied_text = scores.get("plagiarism", {}).get("copied_sentence", "")
                    if copied_text:
                        self.pdf.ln(2)
                        self.pdf.set_font("Arial", 'I', 8)
                        self.pdf.set_text_color(150, 0, 0)  # Dark red
                        self.pdf.multi_cell(0, 4, f"Plagiarism detected: \"{copied_text}\"")
                        self.pdf.set_text_color(*self.text_color)
                
                # Add feedback
                feedback_data = question.get("feedback", {})
                feedback_content = ""
                if isinstance(feedback_data, dict):
                    feedback_content = feedback_data.get("content", "")
                elif isinstance(feedback_data, str):
                    feedback_content = feedback_data
                    
                if feedback_content:
                    self.pdf.ln(2)
                    self.pdf.set_font("Arial", 'B', 10)
                    self.pdf.set_text_color(*self.secondary_color)
                    self.pdf.cell(0, 6, "Feedback:", 0, 1)
                    
                    self.pdf.set_font("Arial", '', 10)
                    self.pdf.set_text_color(*self.text_color)
                    self.pdf.multi_cell(0, 6, feedback_content)
                
                self.pdf.ln(5)
        
        # Add overall feedback
        overall_feedback = mongo_data.get("overall_feedback", {})
        feedback_content = ""
        if isinstance(overall_feedback, dict):
            feedback_content = overall_feedback.get("content", "")
        elif isinstance(overall_feedback, str):
            feedback_content = overall_feedback
            
        if feedback_content:
            # Add a new page if we're more than 75% down the page
            if self.pdf.get_y() > 220:
                self.pdf.add_page()
            
            self.pdf.set_font("Arial", 'B', 12)
            self.pdf.set_text_color(*self.heading_color)
            self.pdf.cell(0, 10, "Overall Feedback", 0, 1)
            
            self.pdf.set_font("Arial", '', 11)
            self.pdf.set_text_color(*self.text_color)
            self.pdf.multi_cell(0, 6, feedback_content)
        
        # Add footer
        self.pdf.set_y(-15)
        self.pdf.set_font('Arial', 'I', 8)
        self.pdf.set_text_color(128, 128, 128)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.pdf.cell(0, 10, f'Generated on: {timestamp}', 0, 0, 'C')
    
    def append_to_student_pdf(self, student_pdf_path: str, output_path: str) -> bool:
        """
        Append the report page to an existing student PDF submission
        
        Args:
            student_pdf_path: Path to the student PDF submission
            output_path: Path to save the combined PDF
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Save report to a temporary file
            report_path = tempfile.mktemp(suffix='.pdf')
            self.pdf.output(report_path)
            
            # Open both PDFs
            with open(student_pdf_path, 'rb') as student_file, \
                 open(report_path, 'rb') as report_file, \
                 open(output_path, 'wb') as output_file:
                
                student_pdf = PyPDF2.PdfReader(student_file)
                report_pdf = PyPDF2.PdfReader(report_file)
                
                pdf_writer = PyPDF2.PdfWriter()
                
                # Add all pages from student submission
                for page_num in range(len(student_pdf.pages)):
                    pdf_writer.add_page(student_pdf.pages[page_num])
                
                # Add the report page
                for page_num in range(len(report_pdf.pages)):
                    pdf_writer.add_page(report_pdf.pages[page_num])
                
                # Write the combined PDF
                pdf_writer.write(output_file)
            
            # Clean up temporary file
            if os.path.exists(report_path):
                os.unlink(report_path)
                
            return True
        except Exception as e:
            print(f"Error appending PDF report: {str(e)}")
            return False
    
    def process_submission_with_report(
        self, 
        mongo_data: Dict[str, Any],
        student_pdf_url: str,
        total_possible: float,
        student_name: str,
        course_name: str,
        assignment_name: str,
        folder_name: str,
        output_filename: str
    ) -> Optional[str]:
        """
        Download student PDF, append report, and upload back to S3
        
        Args:
            mongo_data: MongoDB evaluation result document
            student_pdf_url: URL of the student PDF in S3
            total_possible: Maximum possible points
            student_name: Student's name
            course_name: Course name
            assignment_name: Assignment name
            folder_name: S3 folder name for report
            output_filename: Filename for output PDF
            
        Returns:
            Optional[str]: URL of the uploaded PDF with report or None if failed
        """
        temp_student_pdf = tempfile.mktemp(suffix='.pdf')
        temp_output_pdf = tempfile.mktemp(suffix='.pdf')
        
        try:
            # Download student PDF
            if not download_from_s3(student_pdf_url, temp_student_pdf):
                print(f"Failed to download student PDF from {student_pdf_url}")
                return None
            
            # Generate report from MongoDB data
            self.generate_report_from_mongodb(
                mongo_data=mongo_data,
                total_possible=total_possible,
                student_name=student_name,
                course_name=course_name,
                assignment_name=assignment_name
            )
            
            # Append report to student PDF
            if not self.append_to_student_pdf(temp_student_pdf, temp_output_pdf):
                print("Failed to append report to student PDF")
                return None
            
            # Upload combined PDF to S3
            s3_url = upload_to_s3(
                folder_name=folder_name,
                file_name=output_filename,
                file_path=temp_output_pdf
            )
            
            return s3_url
            
        finally:
            # Clean up temporary files
            for temp_file in [temp_student_pdf, temp_output_pdf]:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)