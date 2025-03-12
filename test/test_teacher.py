# test_teacher.py
import requests
import json

from pathlib import Path
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"

def get_teacher_token():
    login_data = {
        'grant_type': 'password',
        'username': 't@gmail.com',  # Teacher email
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

def test_create_course():
    token = get_teacher_token()
    if not token:
        print("Failed to get authorization token")
        return
    
    data = {
        "name": "Test Course 2",
        "batch": "2024",
        "group": "A",
        "section": "Morning",
        "status": "Active"
    }

    # Add course PDF
    files = {
        'pdfs': ('course.pdf', open('/home/myra/Downloads/Software-metrics.pdf', 'rb'), 'application/pdf')
    }

    # Combine data and files
    form_data = {k: (None, v) for k, v in data.items()}
    form_data.update(files)

    try:
        response = requests.post(
            f"{BASE_URL}/teacher/course",
            files=form_data,
            headers={'Authorization': f'Bearer {token}'}
        )
        print(f"Course Creation Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.json().get('course', {}).get('id')
    except Exception as e:
        print(f"Error creating course: {str(e)}")
        return None

def test_update_course():
    token = get_teacher_token()
    if not token:
        print("Failed to get authorization token")
        return

    # Assume an existing course has been created and we have its course_id.
    course_id = 5  # Replace with a valid course ID for testing

    # Form data for the update
    form_data = {
        "name": "Updated Course Name",
        "batch": "2024",
        "group": "B",
        "section": "2",
        "status": "active",
        "removed_pdfs": json.dumps(["https://smartassessfyp.s3.us-east-1.amazonaws.com/course_pdfs/34/testcourse_m/sre Notes.pdf"])
    }

    # Files to upload (if any)
    files = []
    
    # Add PDFs to upload if they exist
    pdf_path = Path("/home/myra/Downloads/Defect-Management.pdf")
    if pdf_path.exists():
        files.append(("pdfs", (pdf_path.name, open(pdf_path, "rb"), "application/pdf")))

    try:
        # Send the request using multipart/form-data
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}",
            data=form_data,
            files=files if files else None,
            headers={
                'Authorization': f'Bearer {token}',
                'accept': 'application/json'
                # Don't set Content-Type when using files - requests will set it
            }
        )
        
        # Close the files
        for _, file_tuple in files:
            if hasattr(file_tuple[1], 'close'):
                file_tuple[1].close()
        
        print("Update Course Status:", response.status_code)
        print("Response:", json.dumps(response.json(), indent=2))
        return response.json()
    except Exception as e:
        print("Error updating course:", str(e))
        return None

def test_delete_course():
    token = get_teacher_token()
    if not token:
        print("Failed to get authorization token")
        return

    # Assume an existing course has been created and we have its course_id.
    course_id = 4  # Replace with a valid course ID for testing

    try:
        # Send the delete request
        response = requests.delete(
            f"{BASE_URL}/teacher/course/{course_id}",
            headers={
                'Authorization': f'Bearer {token}',
                'accept': 'application/json'
            }
        )
        
        print("Delete Course Status:", response.status_code)
        print("Response:", json.dumps(response.json(), indent=2))
        return response.json()
    except Exception as e:
        print("Error deleting course:", str(e))
        return None
    
def test_create_assignment(course_id):
    if not course_id:
        print("No course ID provided")
        return
        
    token = get_teacher_token()
    if not token:
        return

    # Tomorrow's date for deadline
    deadline = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    print("Deadline:", deadline)
    
    try:
        # Verify PDF exists
        pdf_path = '/home/myra/Downloads/Software-metrics.pdf'
        if not Path(pdf_path).exists():
            print(f"PDF not found at {pdf_path}")
            return

        print(f"Found PDF at {pdf_path}")

        # Create multipart form data
        data = {
            "name": "Test Assignment",
            "description": "Test Description",
            "deadline": deadline,
            "grade": "10"
        }

        # Open file directly in files dict
        files = {
            'question_pdf': (
                'teacher.pdf',
                open(pdf_path, 'rb'),
                'application/pdf'
            )
        }

        # Create form data
        form_data = {k: (None, str(v)) for k, v in data.items()}
        form_data.update(files)

        print("Sending request with files:", files.keys())

        response = requests.post(
            f"{BASE_URL}/teacher/course/{course_id}/assignment",
            files=form_data,
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json'
            }
        )

        print(f"Assignment Creation Status: {response.status_code}")
        print(f"Response: {response.json()}")
        
        return response.json().get('assignment', {}).get('id')
            
    except Exception as e:
        print(f"Error creating assignment: {str(e)}")
        return None
    finally:
        # Clean up file handles
        if 'files' in locals():
            for file_tuple in files.values():
                if hasattr(file_tuple[1], 'close'):
                    file_tuple[1].close()

def test_update_assignment():
    token = get_teacher_token()
    if not token:
        print("Failed to get teacher authorization token")
        return

    # Course and assignment IDs to update
    course_id = 5  # Replace with actual course ID
    assignment_id = 1  # Replace with actual assignment ID

    # Data to update the assignment
    form_data = {
        "name": "Updated Assignment Name",
        "description": "This is an updated assignment description.",
        "deadline": "2023-12-31 23:59",
        "grade": 100
    }

    # Optional: Include a new PDF file
    files = []
    pdf_path = Path("/home/myra/Downloads/teacher-assignment.pdf")  # Replace with actual PDF path
    if pdf_path.exists():
        files.append(("question_pdf", (pdf_path.name, open(pdf_path, "rb"), "application/pdf")))

    try:
        # Send the request
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}/assignment/{assignment_id}",
            data=form_data,
            files=files if files else None,
            headers={
                'Authorization': f'Bearer {token}',
                'accept': 'application/json'
            }
        )
        
        # Close any open files
        for _, file_tuple in files:
            if hasattr(file_tuple[1], 'close'):
                file_tuple[1].close()
        
        print("Update Assignment Status:", response.status_code)
        print("Response:", json.dumps(response.json(), indent=2))
        return response.json()
    except Exception as e:
        print("Error updating assignment:", str(e))
        return None
def test_regenerate_course_code():
    """Test regenerating a course code for an existing course"""
    token = get_teacher_token()
    if not token:
        print("Failed to get authorization token")
        return
    
    # Assume an existing course has been created and we have its course_id
    course_id = 5  # Replace with a valid course ID for testing
    
    headers = {
        'Authorization': f'Bearer {token}',
        'accept': 'application/json'
    }
    
    try:
        # First, get the current course details to check the original code
        get_response = requests.get(
            f"{BASE_URL}/teacher/course/{course_id}",
            headers=headers
        )
        
        if get_response.status_code != 200:
            print(f"Failed to get original course details: Status {get_response.status_code}")
            print(get_response.text)
            return
        
        original_course = get_response.json().get("course", {})
        original_code = original_course.get("course_code")
        
        print(f"Original course code: {original_code}")
        
        # Now regenerate the course code
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}/regenerate-code",
            headers=headers
        )
        
        print("Regenerate Code Status:", response.status_code)
        print("Response:", json.dumps(response.json(), indent=2))
        
        if response.status_code == 201:
            new_code = response.json().get("new_code")
            print(f"New course code: {new_code}")
            
            # Verify the code has changed
            assert new_code != original_code, "Course code should have changed"
            
            # Get updated course details to double check
            updated_response = requests.get(
                f"{BASE_URL}/teacher/course/{course_id}",
                headers=headers
            )
            
            if updated_response.status_code == 200:
                updated_course = updated_response.json().get("course", {})
                updated_code = updated_course.get("course_code")
                
                assert updated_code == new_code, "Updated course should have the new code"
                print(f"Successfully verified new code in course: {updated_code}")
            
        return response.json()
    except Exception as e:
        print(f"Error in test_regenerate_course_code: {str(e)}")
        return None
    
def test_update_course_request(course_id, request_id):
    token = get_teacher_token()
    if not token:
        return

    data = {
        "status": "accepted"  # or "rejected"
    }

    try:
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}/request/{request_id}",
            data=data,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        print(f"Request Update Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error updating request: {str(e)}")


def test_evaluate_submissions():
    token = get_teacher_token()
    if not token:
        print("Failed to get authorization token")
        return

    course_id = 1  # Known course ID
    assignment_id = 6  # Known assignment ID
    submission_ids = [1]  # Test submission IDs

    test_cases = [
        {
            "name": "Only Context",
            "data": {
                "submission_ids": submission_ids,
                "enable_plagiarism": "false",
                "enable_ai_detection": "false",
                "enable_grammar": "false"
            }
        },
    ]

    for test_case in test_cases:
        print(f"\nTesting {test_case['name']}:")
        try:
            response = requests.post(
                f"{BASE_URL}/teacher/{course_id}/assignment/{assignment_id}/evaluate",
                data=test_case['data'],
                headers={
                    'Authorization': f'Bearer {token}',
                    'Accept': 'application/json'
                }
            )

            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("Success:", result['success'])
                print("Results:", result['results'])
            else:
                print("Error Response:", response.json())

        except Exception as e:
            print(f"Test Error: {str(e)}")

if __name__ == "__main__":
    # print("Testing Assingment Evalution:")
    # test_evaluate_submissions()
    # print("Testing Course Creation:")
    # course_id = test_create_course()
    #print("Testing Course Updation:")
    # test_update_course()
    # test_delete_course()
    # print("\nTesting Assignment Creation:")
    # assignment_id = test_create_assignment(1)
    # test_update_assignment()
    # test_regenerate_course_code()
    test_update_course_request(5,1)
