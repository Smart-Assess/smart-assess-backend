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


# import re
import re
from spacy.cli import download
from spacy import load
# download("en_core_web_sm")

# Load the English NLP model from spaCy
nlp = load("en_core_web_sm")

# Function to clean, tokenize, and lemmatize text
def clean_and_lemmatize_text(data):
    cleaned_texts = ""

    for point in data.points:
        if 'text' in point.payload:
            # Extract raw text
            raw_text = point.payload['text']

            # Step 1: Remove unwanted characters (like bullet points)
            cleaned_text = re.sub(r'[●■○]', '', raw_text)  # Remove specific bullets
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()  # Normalize spaces

            # Step 2: Apply spaCy NLP pipeline
            doc = nlp(cleaned_text)

            # Step 3: Lemmatize and filter tokens
            lemmatized_tokens = [
                token.lemma_.lower()  # Lemmatize and lowercase
                for token in doc
                if not token.is_stop and not token.is_punct  # Remove stop words and punctuation
            ]

            # Step 4: Join lemmatized tokens back into a string
            lemmatized_text = ' '.join(lemmatized_tokens)

            # Append cleaned text to the list
            cleaned_texts+=lemmatized_text

    return cleaned_texts

from bestrag import BestRAG
from utils.bleurt.bleurt.score import BleurtScorer
checkpoint = "BLEURT-20"
scorer = BleurtScorer(checkpoint)

rag = BestRAG(
    url="https://846f5809-f781-4194-af40-e057b8f767d6.us-east4-0.gcp.cloud.qdrant.io",
    api_key="B0_ynUALyh2bQk0PlRQeihqbLPOB6xS5KL62khtrD_twV_awmMe8Kg",
    collection_name="fyptest"
)

data = rag.search("How is SPM different from traditional Project Management (PM)?")
cleaned_text = clean_and_lemmatize_text(data)
answer="""
Strategic Project Management (SPM) focuses on aligning projects with an organization’s long-term strategic goals, emphasizing broader business outcomes and competitive advantage. In contrast, traditional Project Management (PM) primarily centers on executing specific projects efficiently, managing scope, time, cost, and quality. SPM integrates strategic thinking into project selection and prioritization, ensuring projects contribute to organizational objectives, whereas PM focuses on delivering individual projects successfully within predefined constraints.
"""
scores = scorer.score(references=[cleaned_text], candidates=[answer], batch_size=32)
print(scores)

import requests
from pathlib import Path

# Base URL of your FastAPI application
BASE_URL = "http://localhost:8000"
def test_add_university():
    # Step 1: Get authentication token
    login_data = {
        'grant_type': 'password',
        'username': 'abdulsamadsid1@gmail.com',
        'password': '12345',
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
    
    # Extract token
    print("Login Response:", login_response.text)
    if login_response.status_code != 200:
        print("Login failed!")
        return
    token = login_response.json()["access_token"]
    
    # Step 2: Prepare headers with token
    headers = {
        "Authorization": f"Bearer {token}",
        'accept': 'application/json',
    }
    
    # Step 3: Prepare university data
    university_data = {
        "university_name": "Test University",
        "university_email": "test@university.com",
        "phone_number": "1234567890",
        "street_address": "123 Test Street",
        "city": "Test City",
        "state": "Test State",
        "zipcode": "12345",
        "admin_name": "Test Admin",
        "admin_email": "admin1@test.com",
        "admin_password": "admin123"
    }
    
    # Optional: Prepare image file if needed
    files = None
    if Path("university_logo.png").exists():
        files = {
            "image": ("university_logo.png", open("university_logo.png", "rb"), "image/png")
        }
    
    # Step 4: Make request to create university
    response = requests.post(
        f"{BASE_URL}/superadmin/university",
        data=university_data,
        headers=headers,
        files=files
    )
    
    # Step 5: Print response
    print("Status Code:", response.status_code)
    print("Response:", response.text)


def test_add_student():
    # Step 1: Get authentication token
    login_data = {
        'grant_type': 'password',
        'username': 'admin1@test.com',  # Replace with the admin's login credentials
        'password': 'admin123',
        'scope': '',
        'client_id': '',
        'client_secret': ''
    }
    
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    login_response = requests.post(
        f"{BASE_URL}/login",  # Replace with the actual login endpoint
        data=login_data,
        headers=headers
    )
    
    # Extract token
    print("Login Response:", login_response.text)
    if login_response.status_code != 200:
        print("Login failed!")
        return
    token = login_response.json()["access_token"]
    
    # Step 2: Prepare headers with token
    headers = {
        "Authorization": f"Bearer {token}",
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    # Step 3: Prepare student data
    student_data = {
        "full_name": "Ahsan Sajid",
        "student_id": '21B-003-SE',
        "department": "Computer Science",
        "email": "21b-003-se@students.uit.edu",
        "batch": "21B",
        "section": "B",
        "password": "12345"
    }
    files = None
    if Path("pfp.jpg").exists():
        files = {
            "image": ("pfp.jpg", open("pfp.jpg", "rb"), "image/png")
        }
    # Step 4: Make a POST request to add a student
    response = requests.post(
        f"{BASE_URL}/universityadmin/student",
        headers=headers,
        data=student_data  # Send form data
    )
    
    # Step 5: Print response
    print("Status Code:", response.status_code)
    print("Response:", response.text)
def test_add_teacher():
    # Step 1: Get authentication token
    login_data = {
        'grant_type': 'password',
        'username': 'admin1@test.com',  # Replace with the admin's login credentials
        'password': 'admin123',
        'scope': '',
        'client_id': '',
        'client_secret': ''
    }
    
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    login_response = requests.post(
        f"{BASE_URL}/login",  # Replace with the actual login endpoint
        data=login_data,
        headers=headers
    )
    
    # Extract token
    print("Login Response:", login_response.text)
    if login_response.status_code != 200:
        print("Login failed!")
        return
    token = login_response.json()["access_token"]
    
    # Step 2: Prepare headers with token
    headers = {
        "Authorization": f"Bearer {token}",
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    # Step 3: Prepare teacher data
    teacher_data = {
        "full_name": "Oliver Williams Rey",
        "teacher_id": '30216',
        "department": "Science",
        "email": "oliverrayyyy12@example.com",
        "password": "Smartassess1"
    }
    files = None
    if Path("teacher_image.jpg").exists():
        files = {
            "image": ("teacher_image.jpg", open("teacher_image.jpg", "rb"), "image/png")
        }
    
    # Step 4: Make a POST request to add a teacher
    response = requests.post(
        f"{BASE_URL}/universityadmin/teacher",
        headers=headers,
        data=teacher_data,  # Send form data
        files=files  # Send image file if it exists
    )
    
    # Step 5: Print response
    print("Status Code:", response.status_code)
    print("Response:", response.text)

if __name__ == "__main__":
    # test_add_university()
    test_add_student()  # Uncomment this line to test adding a student instead of a teacher.
    test_add_teacher()
