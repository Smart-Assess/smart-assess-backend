# import psycopg2
# from psycopg2 import sql
# from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# # Connection parameters
# host = "proj-db.cn0824m6mgt7.us-east-1.rds.amazonaws.com"
# port = "5432"
# user = "postgres"
# password = "admin1234"
# dbname = "postgres"  # Connect to the default 'postgres' database initially

# try:
#     # Connect to the default 'postgres' database
#     connection = psycopg2.connect(
#         host=host,
#         port=port,
#         user=user,
#         password=password,
#         dbname=dbname
#     )
    
#     connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
#     cursor = connection.cursor()

#     # Check if the database already exists
#     cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'smartassess-db'")
#     exists = cursor.fetchone()

#     if not exists:
#         # Create the new database if it doesn't exist
#         cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier('smartassess-db')))
#         print("Database 'smartassess-db' created successfully.")
#     else:
#         print("Database 'smartassess-db' already exists.")

# except Exception as e:
#     print(f"Error: {e}")

# finally:
#     # Clean up
#     if cursor:
#         cursor.close()
#     if connection:
#         connection.close()


import re

# Load the English NLP model from spaCy
def clean_and_tokenize_text(data):
    cleaned_texts = ""

    for point in data.points:
        if 'text' in point.payload:
            # Extract raw text
            raw_text = point.payload['text']

            # Step 1: Remove unwanted characters (like bullet points)
            cleaned_text = re.sub(r'[●■○]', '', raw_text)  # Remove specific bullets
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()  # Normalize spaces

            # Step 2: Tokenize the text
            tokens = cleaned_text.split()

            # Step 3: Filter tokens (remove non-alphanumeric tokens)
            filtered_tokens = [
                token.lower()  # Lowercase
                for token in tokens
                if token.isalnum()  # Remove non-alphanumeric tokens
            ]

            # Step 4: Join filtered tokens back into a string
            cleaned_text = ' '.join(filtered_tokens)

            # Append cleaned text to the list
            cleaned_texts += cleaned_text

    return cleaned_texts



# from bestrag import BestRAG
# from utils.bleurt.bleurt.score import BleurtScorer
# checkpoint = "BLEURT-20"
# scorer = BleurtScorer(checkpoint)

# rag = BestRAG(
#     url="https://846f5809-f781-4194-af40-e057b8f767d6.us-east4-0.gcp.cloud.qdrant.io",
#     api_key="B0_ynUALyh2bQk0PlRQeihqbLPOB6xS5KL62khtrD_twV_awmMe8Kg",
#     collection_name="fyptest"
# )

# data = rag.search("How is SPM different from traditional Project Management (PM)?")
# cleaned_text = clean_and_tokenize_text(data)
# answer="""
# Strategic Project Management (SPM) focuses on aligning projects with an organization’s long-term strategic goals, emphasizing broader business outcomes and competitive advantage. In contrast, traditional Project Management (PM) primarily centers on executing specific projects efficiently, managing scope, time, cost, and quality. SPM integrates strategic thinking into project selection and prioritization, ensuring projects contribute to organizational objectives, whereas PM focuses on delivering individual projects successfully within predefined constraints.
# """
# scores = scorer.score(references=[cleaned_text], candidates=[answer], batch_size=32)
# print(scores)

import requests
from pathlib import Path

# Base URL of your FastAPI application
BASE_URL = "http://127.0.0.1:8000"
# def test_add_university():
#     # Step 1: Get authentication token
#     login_data = {
#         'grant_type': 'password',
#         'username': 'abdulsamadsid1@gmail.com',
#         'password': '12345',
#         'scope': '',
#         'client_id': '',
#         'client_secret': ''
#     }
    
#     headers = {
#         'accept': 'application/json',
#         'Content-Type': 'application/x-www-form-urlencoded'
#     }

#     login_response = requests.post(
#         f"{BASE_URL}/login",
#         data=login_data,
#         headers=headers
#     )
    
#     # Extract token
#     print("Login Response:", login_response.text)
#     if login_response.status_code != 200:
#         print("Login failed!")
#         return
#     token = login_response.json()["access_token"]
    
#     # Step 2: Prepare headers with token
#     headers = {
#         "Authorization": f"Bearer {token}",
#         'accept': 'application/json',
#     }
    
#     # Step 3: Prepare university data
#     university_data = {
#         "university_name": "Test University",
#         "university_email": "test@university.com",
#         "phone_number": "1234567890",
#         "street_address": "123 Test Street",
#         "city": "Test City",
#         "state": "Test State",
#         "zipcode": "12345",
#         "admin_name": "Test Admin",
#         "admin_email": "admin1@test.com",
#         "admin_password": "admin123"
#     }
    
#     # Optional: Prepare image file if needed
#     files = None
#     if Path("university_logo.png").exists():
#         files = {
#             "image": ("university_logo.png", open("university_logo.png", "rb"), "image/png")
#         }
    
#     # Step 4: Make request to create university
#     response = requests.post(
#         f"{BASE_URL}/superadmin/university",
#         data=university_data,
#         headers=headers,
#         files=files
#     )
    
#     # Step 5: Print response
#     print("Status Code:", response.status_code)
    # print("Response:", response.text)


# def test_add_student():
#     # Step 1: Get authentication token
#     login_data = {
#         'grant_type': 'password',
#         'username': 'admin1@test.com',  # Replace with the admin's login credentials
#         'password': 'admin123',
#         'scope': '',
#         'client_id': '',
#         'client_secret': ''
#     }
    
#     headers = {
#         'accept': 'application/json',
#         'Content-Type': 'application/x-www-form-urlencoded'
#     }

#     login_response = requests.post(
#         f"{BASE_URL}/login",  # Replace with the actual login endpoint
#         data=login_data,
#         headers=headers
#     )
    
#     # Extract token
#     print("Login Response:", login_response.text)
#     if login_response.status_code != 200:
#         print("Login failed!")
#         return
#     token = login_response.json()["access_token"]
    
#     # Step 2: Prepare headers with token
#     headers = {
#         "Authorization": f"Bearer {token}",
#         'accept': 'application/json',
#         'Content-Type': 'application/x-www-form-urlencoded',
#     }

#     # Step 3: Prepare student data
#     student_data = {
#         "full_name": "test student",
#         "student_id": '213',
#         "department": "Computer Science",
#         "email": "std1@gmail.com",
#         "batch": "21B",
#         "section": "B",
#         "password": "1234"
#     }
#     files = None
#     if Path("pfp.jpg").exists():
#         files = {
#             "image": ("pfp.jpg", open("pfp.jpg", "rb"), "image/png")
#         }
#     # Step 4: Make a POST request to add a student
#     response = requests.post(
#         f"{BASE_URL}/universityadmin/student",
#         headers=headers,
#         data=student_data  # Send form data
#     )
    
#     # Step 5: Print response
#     print("Status Code:", response.status_code)
#     print("Response:", response.text)
# def test_add_teacher():
#     # Step 1: Get authentication token
#     login_data = {
#         'grant_type': 'password',
#         'username': 'admin1@test.com',  # Replace with the admin's login credentials
#         'password': 'admin123',
#         'scope': '',
#         'client_id': '',
#         'client_secret': ''
#     }
    
#     headers = {
#         'accept': 'application/json',
#         'Content-Type': 'application/x-www-form-urlencoded'
#     }

#     login_response = requests.post(
#         f"{BASE_URL}/login",  # Replace with the actual login endpoint
#         data=login_data,
#         headers=headers
#     )
    
#     # Extract token
#     print("Login Response:", login_response.text)
#     if login_response.status_code != 200:
#         print("Login failed!")
#         return
#     token = login_response.json()["access_token"]
    
#     # Step 2: Prepare headers with token
#     headers = {
#         "Authorization": f"Bearer {token}",
#         'accept': 'application/json',
#         'Content-Type': 'application/x-www-form-urlencoded',
#     }

#     # Step 3: Prepare teacher data
#     teacher_data = {
#         "full_name": "Oliver Williams Rey",
#         "teacher_id": '30217',
#         "department": "Science",
#         "email": "t1@gmail.com",
#         "password": "1234"
#     }
#     files = None
#     if Path("teacher_image.jpg").exists():
#         files = {
#             "image": ("teacher_image.jpg", open("teacher_image.jpg", "rb"), "image/png")
#         }
    
#     # Step 4: Make a POST request to add a teacher
#     response = requests.post(
#         f"{BASE_URL}/universityadmin/teacher",
#         headers=headers,
#         data=teacher_data,  # Send form data
#         files=files  # Send image file if it exists
#     )
    
#     # Step 5: Print response
#     print("Status Code:", response.status_code)
#     print("Response:", response.text)

# def test_create_course():
#     # Step 1: Teacher Login
#     login_data = {
#         'grant_type': 'password',
#         'username': 't1@gmail.com',  # Teacher email from previous test
#         'password': '1234',
#         'scope': '',
#         'client_id': '',
#         'client_secret': ''
#     }
    
#     headers = {
#         'accept': 'application/json',
#         'Content-Type': 'application/x-www-form-urlencoded'
#     }

#     login_response = requests.post(
#         f"{BASE_URL}/login",
#         data=login_data,
#         headers=headers
#     )
    
#     print("Login Response:", login_response.text)
#     if login_response.status_code != 200:
#         print("Teacher login failed!")
#         return
#     token = login_response.json()["access_token"]
    
#     # Step 2: Prepare headers with token
#     headers = {
#         "Authorization": f"Bearer {token}",
#         'accept': 'application/json',
#     }

#     # Step 3: Prepare course data and PDF
#     course_data = {
#         "name": "sqe 101",
#         "batch": "21B",
#         "group": "SE",
#         "section": "A",
#         "status": "Active"
#     }

#     pdf_path = "/home/samadpls/Downloads/Extra/Maira_Resume.pdf"
#     files = {
#         "pdfs": ("course_material.pdf", open(pdf_path, "rb"), "application/pdf")
#     }
    
#     # Step 4: Create course with PDF
#     response = requests.post(
#         f"{BASE_URL}/teacher/course",
#         headers=headers,
#         data=course_data,
#         files=files
#     )
    
#     # Step 5: Print response
#     print("Status Code:", response.status_code)
#     print("Response:", response.text)

# def test_create_assignment():
#     # Step 1: Teacher Login
#     login_data = {
#         'grant_type': 'password',
#         'username': 't1@gmail.com',  # Teacher email
#         'password': '1234',
#         'scope': '',
#         'client_id': '',
#         'client_secret': ''
#     }
    
#     headers = {
#         'accept': 'application/json',
#         'Content-Type': 'application/x-www-form-urlencoded'
#     }

#     login_response = requests.post(
#         f"{BASE_URL}/login",
#         data=login_data,
#         headers=headers
#     )
    
#     print("Login Response:", login_response.text)
#     if login_response.status_code != 200:
#         print("Teacher login failed!")
#         return
#     token = login_response.json()["access_token"]
    
#     # Step 2: Prepare headers with token
#     headers = {
#         "Authorization": f"Bearer {token}",
#         'accept': 'application/json',
#     }

#     # Step 3: Prepare assignment data and PDF
#     course_id = 1  # Replace with actual course ID
#     assignment_data = {
#         "name": "Quiz#1",
#         "description": "You need to solve it without using Google",
#         "deadline": "2024-10-16 12:00",  # YYYY-MM-DD HH:MM
#         "grade": 10
#     }

#     pdf_path = "/home/samadpls/Downloads/Extra/Maira_Resume.pdf"  # Replace with actual PDF path
#     files = {
#         "question_pdf": ("assignment.pdf", open(pdf_path, "rb"), "application/pdf")
#     }
    
#     # Step 4: Create assignment
#     response = requests.post(
#         f"{BASE_URL}/teacher/course/{course_id}/assignment",
#         headers=headers,
#         data=assignment_data,
#         files=files
#     )
    
#     # Step 5: Print response
#     print("Status Code:", response.status_code)
#     print("Response:", response.text)
# In test.py
def test_student_login_and_join_course():
    # Step 1: Student Login
    login_data = {
        'grant_type': 'password',
        'username': 'std1@gmail.com',  # Student email
        'password': '1234',
        'scope': '',
        'client_id': '',
        'client_secret': ''
    }
    
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    login_response = requests.post(
        f"{BASE_URL}/login",
        data=login_data,
        headers=headers
    )
    
    print("Login Response:", login_response.text)
    if login_response.status_code != 200:
        print("Student login failed!")
        return
    token = login_response.json()["access_token"]
    
    # Step 2: Join Course
    headers = {
        "Authorization": f"Bearer {token}",
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    join_data = {
        "course_code": "NLLR59" 
    }
    
    response = requests.post(
        f"{BASE_URL}/student/course/join",
        headers=headers,
        data=join_data
    )
    
    print("Join Course Status:", response.status_code)
    print("Join Course Response:", response.text)

def test_student_assignment_workflow():
    # Step 1: Student Login
    login_data = {
        'grant_type': 'password',
        'username': 'std1@gmail.com',
        'password': '1234',
        'scope': '',
        'client_id': '',
        'client_secret': ''
    }
    
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    login_response = requests.post(
        f"{BASE_URL}/login",
        data=login_data,
        headers=headers
    )
    
    token = login_response.json()["access_token"]
    headers = {
        "Authorization": f"Bearer {token}",
        'accept': 'application/json'
    }

    # Step 2: View Assignments
    course_id = 1  # Replace with actual course ID
    response = requests.get(
        f"{BASE_URL}/student/course/{course_id}/assignments",
        headers=headers
    )
    
    print("Get Assignments Status:", response.status_code)
    print("Assignments:", response.text)

    # Step 3: Submit Assignment
    assignment_id = 1  # Replace with actual assignment ID
    pdf_path = "./p3.pdf"  # Replace with actual PDF
    
    files = {
        "submission_pdf": ("answer.pdf", open(pdf_path, "rb"), "application/pdf")
    }
    
    response = requests.post(
        f"{BASE_URL}/student/assignment/{assignment_id}/submit",
        headers=headers,
        files=files
    )
    
    print("Submit Assignment Status:", response.status_code)
    print("Submit Response:", response.text)

    # Step 4: Delete Submission
    # response = requests.delete(
    #     f"{BASE_URL}/student/assignment/{assignment_id}/submission",
    #     headers=headers
    # )
    
    # print("Delete Submission Status:", response.status_code)
    # print("Delete Response:", response.text)

# if __name__ == "__main__":
#     # test_add_university()
#     # test_add_student()
#     # test_create_course()
#     # test_student_login_and_join_course()
#     test_student_assignment_workflow()
    # test_create_assignment()
    # test_create_course()
    # test_add_university()
    # test_add_student()  # Uncomment this line to test adding a student instead of a teacher.
    # test_add_teacher()
