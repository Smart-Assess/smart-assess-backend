# test_student.py
import requests
from pathlib import Path
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"

def get_student_token():
    """Get authentication token for student"""
    login_data = {
        'grant_type': 'password',
        'username': 's@gmail.com',
        'password': '12345',
        'scope': '',
        'client_id': '',
        'client_secret': ''
    }
    
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = requests.post(
            f"{BASE_URL}/login",
            data=login_data,
            headers=headers
        )
        if response.status_code != 200:
            print(f"Login failed: {response.text}")
            return None
        return response.json()["access_token"]
    except Exception as e:
        print(f"Login error: {str(e)}")
        return None

def test_join_course():
    """Test joining a course with course code"""
    token = get_student_token()
    if not token:
        print("Failed to get authorization token")
        return
    
    data = {
        "course_code": "ZZTU42"
    }

    try:
        response = requests.post(
            f"{BASE_URL}/student/course/join",
            data=data,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        print(f"Course Join Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.json().get('request_id')
    except Exception as e:
        print(f"Error joining course: {str(e)}")
        return None

def test_submit_assignment(assignment_id):
    """Test submitting an assignment"""
    token = get_student_token()
    if not token:
        print("Failed to get authorization token")
        return
    
    try:
        # Verify PDF exists
        pdf_path = '/home/samadpls/proj/fyp/smart-assess-backend/p3.pdf'
        if not Path(pdf_path).exists():
            print(f"PDF not found at {pdf_path}")
            return

        print(f"Found PDF at {pdf_path}")

        # Create multipart form data with PDF
        files = {
            'submission_pdf': (
                'p3.pdf',
                open(pdf_path, 'rb'),
                'application/pdf'
            )
        }

        response = requests.post(
            f"{BASE_URL}/student/assignment/{assignment_id}/submit",
            files=files,
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json'
            }
        )

        print(f"Assignment Submission Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.json().get('submission_id')
            
    except Exception as e:
        print(f"Error submitting assignment: {str(e)}")
        return None
    finally:
        # Clean up file handles
        if 'files' in locals():
            for file_tuple in files.values():
                if hasattr(file_tuple[1], 'close'):
                    file_tuple[1].close()

if __name__ == "__main__":
    # print("Testing Course Join:")
    # request_id = test_join_course()
    
        print("\nTesting Assignment Submission:")
        submission_id = test_submit_assignment(6)
        print(f"Submission ID: {submission_id}")