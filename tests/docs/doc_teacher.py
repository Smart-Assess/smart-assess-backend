# test_teacher.py
import requests
import json

from pathlib import Path
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"


def get_teacher_token():
    login_data = {
        "grant_type": "password",
        "username": "21b-146-se@students.uit.edu",  # Teacher email
        "password": "12345",
        "scope": "",
        "client_id": "",
        "client_secret": "",
    }

    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        response = requests.post(f"{BASE_URL}/login", data=login_data, headers=headers)
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
        "status": "Active",
    }

    # Add course PDF
    files = {
        "pdfs": (
            "course.pdf",
            open("/home/myra/Downloads/Software-metrics.pdf", "rb"),
            "application/pdf",
        )
    }

    # Combine data and files
    form_data = {k: (None, v) for k, v in data.items()}
    form_data.update(files)

    try:
        response = requests.post(
            f"{BASE_URL}/teacher/course",
            files=form_data,
            headers={"Authorization": f"Bearer {token}"},
        )
        print(f"Course Creation Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.json().get("course", {}).get("id")
    except Exception as e:
        print(f"Error creating course: {str(e)}")
        return None


def test_update_course():
    token = get_teacher_token()
    if not token:
        print("Failed to get authorization token")
        return

    # Assume an existing course has been created and we have its course_id.
    course_id = 35  # Replace with a valid course ID for testing

    # Form data for the update
    form_data = {
        "name": "Updated Course Name",
        "batch": "2024",
        "group": "B",
        "section": "2",
        "status": "active",
        # "removed_pdfs": json.dumps(["https://smartassessfyp.s3.us-east-1.amazonaws.com/course_pdfs/68/35_sre Notes (1).pdf"])
    }

    # Files to upload (if any)
    files = []

    pdf_paths = ["/home/myra/Downloads/sre Notes.pdf"]
    # pdf_paths= []
    # Add PDFs to upload if they exist
    for pdf_path in pdf_paths:
        pdf_path = Path(pdf_path)
        if pdf_path.exists():
            files.append(
                ("pdfs", (pdf_path.name, open(pdf_path, "rb"), "application/pdf"))
            )

    try:
        # Send the request using multipart/form-data
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}",
            data=form_data,
            files=files if files else None,
            headers={
                "Authorization": f"Bearer {token}",
                "accept": "application/json",
                # Don't set Content-Type when using files - requests will set it
            },
        )

        # Close the files
        for _, file_tuple in files:
            if hasattr(file_tuple[1], "close"):
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
            headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
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
        pdf_path = "/home/myra/Downloads/teacher.pdf"
        if not Path(pdf_path).exists():
            print(f"PDF not found at {pdf_path}")
            return

        print(f"Found PDF at {pdf_path}")

        # Create multipart form data
        data = {
            "name": "Test Assignment",
            "description": "Test Description",
            "deadline": deadline,
            "grade": "10",
        }

        # Open file directly in files dict
        files = {
            "question_pdf": ("teacher.pdf", open(pdf_path, "rb"), "application/pdf")
        }

        # Create form data
        form_data = {k: (None, str(v)) for k, v in data.items()}
        form_data.update(files)

        print("Sending request with files:", files.keys())

        response = requests.post(
            f"{BASE_URL}/teacher/course/{course_id}/assignment",
            files=form_data,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

        print(f"Assignment Creation Status: {response.status_code}")
        print(f"Response: {response.json()}")

        return response.json().get("assignment", {}).get("id")

    except Exception as e:
        print(f"Error creating assignment: {str(e)}")
        return None
    finally:
        # Clean up file handles
        if "files" in locals():
            for file_tuple in files.values():
                if hasattr(file_tuple[1], "close"):
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
        "grade": 100,
    }

    # Optional: Include a new PDF file
    files = []
    # Replace with actual PDF path
    pdf_path = Path("/home/myra/Downloads/teacher-assignment.pdf")
    if pdf_path.exists():
        files.append(
            ("question_pdf", (pdf_path.name, open(pdf_path, "rb"), "application/pdf"))
        )

    try:
        # Send the request
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}/assignment/{assignment_id}",
            data=form_data,
            files=files if files else None,
            headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
        )

        # Close any open files
        for _, file_tuple in files:
            if hasattr(file_tuple[1], "close"):
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

    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}

    try:
        # First, get the current course details to check the original code
        get_response = requests.get(
            f"{BASE_URL}/teacher/course/{course_id}", headers=headers
        )

        if get_response.status_code != 200:
            print(
                f"Failed to get original course details: Status {get_response.status_code}"
            )
            print(get_response.text)
            return

        original_course = get_response.json().get("course", {})
        original_code = original_course.get("course_code")

        print(f"Original course code: {original_code}")

        # Now regenerate the course code
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}/regenerate-code", headers=headers
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
                f"{BASE_URL}/teacher/course/{course_id}", headers=headers
            )

            if updated_response.status_code == 200:
                updated_course = updated_response.json().get("course", {})
                updated_code = updated_course.get("course_code")

                assert (
                    updated_code == new_code
                ), "Updated course should have the new code"
                print(f"Successfully verified new code in course: {updated_code}")

        return response.json()
    except Exception as e:
        print(f"Error in test_regenerate_course_code: {str(e)}")
        return None


def test_update_course_request(course_id, request_id):
    token = get_teacher_token()
    if not token:
        return

    data = {"status": "accepted"}  # or "rejected"

    try:
        response = requests.put(
            f"{BASE_URL}/teacher/course/{course_id}/request/{request_id}",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        print(f"Request Update Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error updating request: {str(e)}")


def test_get_assignment_submissions():
    """Test retrieving paginated student submissions for an assignment"""
    token = get_teacher_token()
    if not token:
        print("Failed to get teacher authorization token")
        return False

    # Test parameters
    course_id = 5  # Replace with a valid course ID for testing
    assignment_id = 1  # Replace with a valid assignment ID for testing
    page = 1
    limit = 10

    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}

    try:
        # Make the API request
        response = requests.get(
            f"{BASE_URL}/teacher/course/{course_id}/assignment/{assignment_id}/submissions?page={page}&limit={limit}",
            headers=headers,
        )

        print("\n--- Testing Assignment Submissions Retrieval ---")
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"Success: {result['success']}")
            print(f"Total submissions: {result['total']}")
            print(f"Current page: {result['page']} of {result['total_pages']}")
            print(f"Has previous page: {result['has_previous']}")
            print(f"Has next page: {result['has_next']}")

            # Display submissions information
            submissions = result["submissions"]
            print(f"\nFound {len(submissions)} submissions on this page:")
            for i, submission in enumerate(submissions, 1):
                student = submission["student"]
                print(f"\n{i}. Submission ID: {submission['submission_id']}")
                print(f"   Student: {student['name']} (ID: {student['student_id']})")
                print(
                    f"   Department: {student['department']}, Batch: {student['batch']}, Section: {student['section']}"
                )
                print(f"   Submitted at: {submission['submitted_at']}")
                print(f"   PDF URL: {submission['pdf_url']}")

            # Test pagination by fetching the next page if available
            if result["has_next"]:
                print("\nTesting pagination - fetching next page...")
                next_page = page + 1

                next_response = requests.get(
                    f"{BASE_URL}/teacher/course/{course_id}/assignment/{assignment_id}/submissions?page={next_page}&limit={limit}",
                    headers=headers,
                )

                if next_response.status_code == 200:
                    next_result = next_response.json()
                    print(f"Next page status: {next_response.status_code}")
                    print(f"Next page submissions: {len(next_result['submissions'])}")

                    # Verify that pages are different
                    if len(submissions) > 0 and len(next_result["submissions"]) > 0:
                        first_submission_id = (
                            submissions[0]["submission_id"] if submissions else None
                        )
                        next_first_submission_id = (
                            next_result["submissions"][0]["submission_id"]
                            if next_result["submissions"]
                            else None
                        )

                        if first_submission_id != next_first_submission_id:
                            print(
                                "Pagination verified: Different submissions on different pages"
                            )
                        else:
                            print(
                                "Warning: Same submission appears on consecutive pages"
                            )
                else:
                    print(f"Failed to fetch next page: {next_response.status_code}")
                    print(next_response.text)

            # Test with different limit
            print("\nTesting with different limit parameter...")
            small_limit = 3
            small_limit_response = requests.get(
                f"{BASE_URL}/teacher/course/{course_id}/assignment/{assignment_id}/submissions?page=1&limit={small_limit}",
                headers=headers,
            )

            if small_limit_response.status_code == 200:
                small_limit_result = small_limit_response.json()
                print(
                    f"Status with limit={small_limit}: {small_limit_response.status_code}"
                )
                print(f"Submissions returned: {len(small_limit_result['submissions'])}")

                # Verify the limit works
                assert (
                    len(small_limit_result["submissions"]) <= small_limit
                ), "Limit parameter not respected"
                print(
                    f"Limit parameter verified: returned {len(small_limit_result['submissions'])} submissions (limit was {small_limit})"
                )

            return result
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            return False

    except Exception as e:
        print(f"Error in test_get_assignment_submissions: {str(e)}")
        return False


def test_get_submission_details():
    """Test retrieving detailed information for a specific submission"""
    token = get_teacher_token()
    if not token:
        print("Failed to get teacher authorization token")
        return False

    # Test parameters - replace with valid IDs from your test environment
    course_id = 5
    assignment_id = 1
    submission_id = 1

    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}

    try:
        # Make the API request
        response = requests.get(
            f"{BASE_URL}/teacher/course/{course_id}/assignment/{assignment_id}/submission/{submission_id}",
            headers=headers,
        )

        print("\n--- Testing Submission Details Retrieval ---")
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"Success: {result['success']}")

            # Display submission data
            submission = result.get("submission", {})

            # Display basic submission info
            print("\nSubmission Details:")
            print(f"Course ID: {submission.get('course_id')}")
            print(f"Assignment ID: {submission.get('assignment_id')}")
            print(f"Student ID: {submission.get('student_id')}")
            print(f"PDF File: {submission.get('PDF_File', 'N/A')}")

            # Display evaluation data if available
            if "evaluation_data" in submission:
                eval_data = submission.get("evaluation_data", {})
                print("\nEvaluation Data:")
                print(f"Score: {eval_data.get('score', 'N/A')}")
                print(f"Evaluated At: {eval_data.get('evaluated_at', 'N/A')}")

                questions = eval_data.get("questions", [])
                if questions:
                    print(f"\nQuestions Evaluated: {len(questions)}")
                    # Show first 3 questions for brevity
                    for i, q in enumerate(questions[:3], 1):
                        print(f"\nQuestion {i}:")
                        # Show first 50 chars
                        print(f"  Text: {q.get('question_text', '')[:50]}...")
                        print(
                            f"  Score: {q.get('score', 'N/A')}/{q.get('max_score', 'N/A')}"
                        )
                        # Show first 50 chars
                        print(f"  Feedback: {q.get('feedback', '')[:50]}...")

                    if len(questions) > 3:
                        print(f"\n... and {len(questions) - 3} more questions")

            # Display answers if available
            if "answers" in submission:
                answers = submission.get("answers", [])
                print(f"\nAnswers Found: {len(answers)}")
                # Show first 3 answers for brevity
                for i, ans in enumerate(answers[:3], 1):
                    print(f"\nAnswer {i}:")
                    print(f"  Question: {ans.get('question_number', 'N/A')}")
                    # Show first 50 chars
                    print(f"  Answer Text: {ans.get('answer_text', '')[:50]}...")

                if len(answers) > 3:
                    print(f"\n... and {len(answers) - 3} more answers")

            # Test invalid submission ID
            print("\nTesting invalid submission ID...")
            invalid_response = requests.get(
                f"{BASE_URL}/teacher/course/{course_id}/assignment/{assignment_id}/submission/99999",
                headers=headers,
            )
            print(f"Invalid submission ID status: {invalid_response.status_code}")
            print(f"Response: {invalid_response.text}")

            return result
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            return False

    except Exception as e:
        print(f"Error in test_get_submission_details: {str(e)}")
        return False


def test_evaluate_submissions():
    token = get_teacher_token()
    if not token:
        print("Failed to get authorization token")
        return

    course_id = 5  # Known course ID
    assignment_id = 1  # Known assignment ID
    submission_ids = 1  # Test submission IDs

    test_cases = [
        {
            "name": "Only Context",
            "data": {
                "submission_ids": submission_ids,
                "enable_plagiarism": "false",
                "enable_ai_detection": "false",
                "enable_grammar": "false",
            },
        },
    ]

    for test_case in test_cases:
        print(f"\nTesting {test_case['name']}:")
        try:
            response = requests.post(
                f"{BASE_URL}/teacher/{course_id}/assignment/{assignment_id}/evaluate",
                data=test_case["data"],
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )

            print(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                print("Success:", result["success"])
                print("Results:", result["results"])
            else:
                print("Error Response:", response.json())

        except Exception as e:
            print(f"Test Error: {str(e)}")


if __name__ == "__main__":
    # print("Testing Assingment Evalution:")
    # test_evaluate_submissions()
    # print("Testing Course Creation:")
    # course_id = test_create_course()
    # print("Testing Course Updation:")
    # test_update_course()
    # test_delete_course()
    print("\nTesting Assignment Creation:")
    # assignment_id = test_create_assignment(35)
    # test_update_assignment()
    # test_regenerate_course_code()
    # test_update_course_request(35,2)
    # test_get_assignment_submissions()
    # test_get_submission_details()
