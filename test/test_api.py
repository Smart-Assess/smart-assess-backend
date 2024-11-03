from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.models import SuperAdmin
from passlib.context import CryptContext

DATABASE_URL = "postgresql://postgres:samadpls123@smartassessdb.cn0824m6mgt7.us-east-1.rds.amazonaws.com:5432/fypdb"

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

if __name__ == "__main__":
    create_superadmin(email="abdulsamadsid1@gmail.com", password="12345")



#################################
#use me in emergancy
#################################
# from sqlalchemy import create_engine, MetaData, text
# from sqlalchemy.orm import sessionmaker

# DATABASE_URL = "postgresql://postgres:anas98522@smart-study.cpm2acy4iul8.eu-north-1.rds.amazonaws.com/smartstudy"

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
# DATABASE_URL = "postgresql://postgres:anas98522@smart-study.cpm2acy4iul8.eu-north-1.rds.amazonaws.com/smartstudy"
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