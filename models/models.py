import random
import string
from sqlalchemy import (
    Column,
    Float,
    Integer,
    String,
    DateTime,
    ForeignKey,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
from passlib.context import CryptContext

DATABASE_URL = (
    "sqlite:///./university_management.db"  # Change this to your database URL
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SuperAdmin(Base):
    __tablename__ = "super_admins"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    universities = relationship("University", back_populates="super_admin")


class UniversityAdmin(Base):
    __tablename__ = "university_admins"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    university_id = Column(Integer, ForeignKey("universities.id"))
    university = relationship("University", back_populates="admins")


class University(Base):
    __tablename__ = "universities"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone_number = Column(String, nullable=False)
    image_url = Column(String, nullable=True)
    street_address = Column(String, nullable=False)
    city = Column(String, nullable=False)
    state = Column(String, nullable=False)
    zipcode = Column(String, nullable=False)
    super_admin_id = Column(Integer, ForeignKey("super_admins.id"))
    super_admin = relationship("SuperAdmin", back_populates="universities")
    admins = relationship(
        "UniversityAdmin", back_populates="university", cascade="all, delete-orphan"
    )
    students = relationship(
        "Student", back_populates="university", cascade="all, delete-orphan"
    )
    teachers = relationship(
        "Teacher", back_populates="university", cascade="all, delete-orphan"
    )


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    student_id = Column(String, unique=True, index=True, nullable=False)
    department = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    batch = Column(String, nullable=False)
    section = Column(String, nullable=False)
    password = Column(String, nullable=False)
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    university_id = Column(Integer, ForeignKey("universities.id"))
    university = relationship("University", back_populates="students")
    courses = relationship("StudentCourse", back_populates="student")
    submissions = relationship("AssignmentSubmission", back_populates="student")


class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    teacher_id = Column(String, unique=True, index=True, nullable=True)
    department = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    university_id = Column(Integer, ForeignKey("universities.id"))
    university = relationship("University", back_populates="teachers")
    courses = relationship("Course", back_populates="teacher")  # Add this line


def generate_course_code():
    letters = "".join(random.choices(string.ascii_uppercase, k=4))
    numbers = "".join(random.choices(string.digits, k=2))
    return f"{letters}{numbers}"


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    batch = Column(String, nullable=False)
    group = Column(String, nullable=True)
    pdf_urls = Column(String, default="[]")
    section = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Active")
    course_code = Column(String(6), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    collection_name = Column(String, unique=True, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    teacher = relationship("Teacher", back_populates="courses")
    assignments = relationship(
        "Assignment", back_populates="course", cascade="all, delete-orphan"
    )
    students = relationship("StudentCourse", back_populates="course")


@event.listens_for(Course, "before_insert")
def set_course_code(mapper, connection, target):
    if not target.course_code:
        while True:
            code = generate_course_code()
            exists = connection.execute(
                select(Course.id).where(Course.course_code == code)
            ).first()
            if not exists:
                target.course_code = code
                break


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    deadline = Column(DateTime, nullable=False)
    grade = Column(Integer, nullable=False)
    question_pdf_url = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    course_id = Column(Integer, ForeignKey("courses.id"))
    course = relationship("Course", back_populates="assignments")
    submissions = relationship("AssignmentSubmission", back_populates="assignment")


class StudentCourse(Base):
    __tablename__ = "student_courses"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    course_id = Column(Integer, ForeignKey("courses.id"))
    status = Column(String, default="pending")  # pending, accepted, rejected
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="courses")
    course = relationship("Course", back_populates="students")


class AssignmentSubmission(Base):
    __tablename__ = "assignment_submissions"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"))
    student_id = Column(Integer, ForeignKey("students.id"))
    submission_pdf_url = Column(String, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)

    assignment = relationship("Assignment", back_populates="submissions")
    student = relationship("Student", back_populates="submissions")
    evaluations = relationship("AssignmentEvaluation", back_populates="submission")


class AssignmentEvaluation(Base):
    __tablename__ = "assignment_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(
        Integer, ForeignKey("assignment_submissions.id"), nullable=False
    )
    total_score = Column(Float, nullable=False)
    plagiarism_score = Column(Float, nullable=True)
    ai_detection_score = Column(Float, nullable=True)
    grammar_score = Column(Float, nullable=True)
    feedback = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    submission = relationship("AssignmentSubmission", back_populates="evaluations")


@event.listens_for(AssignmentEvaluation, "before_update")
def set_updated_at(mapper, connection, target):
    target.updated_at = func.now()


Base.metadata.create_all(bind=engine)
