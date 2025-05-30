from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.models import SuperAdmin
from passlib.context import CryptContext
import requests
from pathlib import Path

DATABASE_URL = ""

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_superadmin(email: str, password: str):
    session = SessionLocal()
    
    try:
        hashed_password = get_password_hash(password)
        new_superadmin = SuperAdmin(email=email, password=hashed_password)
        session.add(new_superadmin)
        session.commit()
        
        print(f"SuperAdmin created with email: {email}")
    except Exception as e:
        session.rollback()
        print(f"Error creating SuperAdmin: {e}")
    finally:
        session.close()
        

# Config
BASE_URL = "http://127.0.0.1:8000"

def get_auth_token():
    login_data = {
        'grant_type': 'password',
        'username': 'sa@gmail.com',
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
        login_response = requests.post(
            f"{BASE_URL}/login",
            data=login_data,
            headers=headers
        )
        
        if login_response.status_code != 200:
            print(f"Login failed: {login_response.text}")
            return None
            
        return login_response.json()["access_token"]
    except Exception as e:
        print(f"Login error: {str(e)}")
        return None

def test_add_university():
    # Get token
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        return
    
    # Test data
    data = {
        "university_name": "Test University",
        "university_email": "u@gmail.com",
        "phone_number": "1234567890",
        "street_address": "123 Test St",
        "city": "Test City",
        "state": "Test State",
        "zipcode": "12345",
        "admin_name": "Admin Test",
        "admin_email": "ua@gmail.com",  # Updated admin email
        "admin_password": "12345"
    }

    # Handle image
    files = None
    image_path = Path("pfp.jpg")
    if image_path.exists():
        files = {
            'image': ('test_image.jpg', open(image_path, 'rb'), 'image/jpeg')
        }

    # Prepare form data
    form_data = {k: (None, v) for k, v in data.items()}
    if files:
        form_data.update(files)

    try:
        response = requests.post(
            f"{BASE_URL}/superadmin/university",
            files=form_data,
            headers={
                'Authorization': f'Bearer {token}'
            }
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
    except Exception as e:
        print(f"Error: {str(e)}")

def test_update_university():
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        return

    university_id = 116  # Replace with a valid university ID
    headers = {"Authorization": f"Bearer {token}"}

    data = {
        "zipcode": "75280",
    }

    response = requests.put(
        f"{BASE_URL}/superadmin/university/{university_id}",
        data=data,  # Use `data` for form fields
        headers=headers
    )

    # Debugging output in case of failure
    print("Response Status Code:", response.status_code)
    print("Response JSON:", response.json())

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"
    response_json = response.json()
    assert response_json["success"] is True
    assert response_json["university"]["street_address"] == data["street_address"]


def test_update_university_admin():
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        return

    university_id = 122  # Replace with a valid university ID
    headers = {"Authorization": f"Bearer {token}"}

    data = {
        "admin_name": "abdul samad",
        # "admin_email": "updated_admin@example.com",
        # "admin_password": "NewSecurePassword123"
    }

    response = requests.put(
        f"{BASE_URL}/superadmin/university/{university_id}",
        data=data,  # Use `data` for form fields
        headers=headers
    )

    # Debugging output in case of failure
    print("Response Status Code:", response.status_code)
    print("Response JSON:", response.json())

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"
    response_json = response.json()
    assert response_json["success"] is True
    assert response_json["admin"]["name"] == data["admin_name"]
    # assert response_json["admin"]["email"] == data["admin_email"]

if __name__ == "__main__":
    test_update_university_admin()
    # create_superadmin(email="sa@gmail.com", password="12345")
    




#################################
#use me in emergency
#################################
# from sqlalchemy import create_engine, MetaData, text
# from sqlalchemy.orm import sessionmaker

# DATABASE_URL = "

# # Create the database engine and session local
# engine = create_engine(DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# def drop_unwanted_tables(session):
#     metadata = MetaData()
#     metadata.reflect(bind=engine)
#     tables_to_keep = {"students", "conversations", "llm_conversations"}
#     all_tables = set(metadata.tables.keys())
#     tables_to_drop = all_tables - tables_to_keep

#     with engine.connect() as connection:
#         for table_name in tables_to_drop:
#             sql = text(f"DROP TABLE IF EXISTS {table_name} CASCADE")
#             connection.execute(sql)
#             print(f"Dropped table: {table_name}")

#     # Commit the transaction after dropping all tables
#     session.commit()


# # Example usage with session local
# with SessionLocal() as session:
#     drop_unwanted_tables(session)

# print("All unwanted tables dropped successfully!")
#or use
# DROP TABLE IF EXISTS ai_models CASCADE;
# DROP TABLE IF EXISTS school_admins CASCADE;
# DROP TABLE IF EXISTS super_admins CASCADE;
# DROP TABLE IF EXISTS subjects CASCADE;
# DROP TABLE IF EXISTS school_subject_association CASCADE;
# DROP TABLE IF EXISTS subject_ai_model_association CASCADE;
# DROP TABLE IF EXISTS metrics CASCADE;
# DROP TABLE IF EXISTS schools CASCADE;
# DROP TABLE IF EXISTS api_costs CASCADE;
####################################################
# my stuff

# /login
# add-school
# subject-list
# school-list
# school-profile

# -- UPDATE schools
# -- SET no_of_students = 10,
# --     no_of_teachers = 10
# -- WHERE user_defined_id = 'pk-1234';
#################################################

# Instantiate the class with just grade and book_name
# from vectordb.book_vector import BookVectorDB

# from utils.search_study_content import search_study_content
# from agents.prompts import STUDY_AGENT_PROMPT

# from agents.llm_base import LLM
# # results = search_study_content(grade=8, search_phrase="any question on algebra")
# import re
# import json
# from utils.jupyter_client_1 import jc

# def parse_response(response):
#     tags = {
#         "response": None,
#         "python_code": None,
#         "tool_name": None,
#         "tool_args": None
#     }
    
#     # Define regular expressions to capture the content within tags
#     tag_patterns = {
#         "response": r"<response>(.*?)</response>",
#         "python_code": r"<python_code>(.*?)</python_code>",
#         "tool_name": r"<tool_name>(.*?)</tool_name>",
#         "tool_args": r"<tool_args>(.*?)</tool_args>"
#     }
    
#     # Extract content for each tag
#     for tag, pattern in tag_patterns.items():
#         match = re.search(pattern, response, re.DOTALL)
#         if match:
#             tags[tag] = match.group(1).strip()

#     return tags

# messages = [{'role': 'system', 'content': STUDY_AGENT_PROMPT}]

# llm = LLM()
# parsed_response = None

# while True:
#     user_input = input("> ")
#     messages.append({"role": 'user', "content": user_input})
#     while True:
#         response = llm.step(messages=messages)
#         parsed_response = parse_response(response=response)
#         if parsed_response['python_code']:
#             print("Python code > ", parsed_response['python_code'])
#             code_execution_result = jc.execute_code(parsed_response['python_code'])
#             print("Python code execution result > ",code_execution_result)
#             messages.append({"role": "user", "content": f"Code Execution Result: {code_execution_result}"})
#             continue
            
#         if parsed_response['tool_name'] and parsed_response['tool_args']:
#             print("Tool Call wtth args > ", parsed_response['tool_args'])
#             result = search_study_content(**json.loads(parsed_response['tool_args']))
#             images = {
#                     "role": "user",
#                     "content": [
#                         {
#                         "type": "image_url",
#                         "image_url": {
#                             "url": x
#                         },
#                         } for x in result
#                     ],
#                     }
#             messages.append(images)
#             continue

#         print("Final Response: ", parsed_response['response'])
#         messages.append({"role": "assistant", "content": response})
#         break


    # print(parsed_response)
    




























# db_interface = BookVectorDB(8, "maths")
# db_interface.embed_books(["Books/math-grade8-combined.pdf"])
# print(db_interface.search_books(grade=8, page_number=186))
# dont use below code
# from qdrant_client import QdrantClient
# client = QdrantClient("http://13.51.160.103/:6333")
# collection_name = "grade_8_subject_maths_vectors"
# client.delete_collection(collection_name)
# print(client.get_collections())




# from vectordb.pdf_page_finder import PDFPageFinderAgent
# import pymupdf

# agent = PDFPageFinderAgent()
# file_path = "math-grade8-combined.pdf"
# document = pymupdf.open("Books/"+file_path)
# starting_page = agent.find_starting_page(document)
# if starting_page:
#     print(f"The content starts at page {starting_page}")
# else:
#     print("No content found in the specified range.")





























# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker
# from model import Base, Student, get_password_hash

# # Database connection setup
# engine = create_engine(DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # Function to insert a student
# def insert_student(email: str, plain_password: str, username: str):
#     # Create a new database session
#     session = SessionLocal()
    
#     # Hash the password
#     hashed_password = get_password_hash(plain_password)
    
#     # Create a new Student object
#     new_student = Student(email=email, password=hashed_password, username=username)
    
#     # Add the new student to the session
#     session.add(new_student)
    
#     # Commit the transaction to save the student in the database
#     session.commit()
    
#     # Close the session
#     session.close()
    
#     print(f"Student with email '{email}' has been successfully added.")

# # Test the insertion
# if __name__ == "__main__":
#     # Replace with your test data
#     test_email = "osafh486@gmail.com"
#     test_username= "osaf"
#     test_password = "1234"
    
#     insert_student(test_email, test_password, username=test_username)