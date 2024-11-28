from sqlalchemy import (
    Column,
    Float,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    Table,
    create_engine,
    UniqueConstraint,
    Enum,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
from passlib.context import CryptContext


DATABASE_URL = "postgresql://postgres:samadpls123@smartassessdb.cn0824m6mgt7.us-east-1.rds.amazonaws.com:5432/fypdb"
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
    university_id = Column(Integer, ForeignKey('universities.id'))
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
    super_admin_id = Column(Integer, ForeignKey('super_admins.id'))
    super_admin = relationship("SuperAdmin", back_populates="universities")
    admins = relationship("UniversityAdmin", back_populates="university")
    students = relationship("Student", back_populates="university")
    teachers = relationship("Teacher", back_populates="university")  # Add this line
    
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
    university_id = Column(Integer, ForeignKey('universities.id'))
    university = relationship("University", back_populates="students")
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
    university_id = Column(Integer, ForeignKey('universities.id'))
    university = relationship("University", back_populates="teachers")
    courses = relationship("Course", back_populates="teacher")  # Add this line
class Course(Base):
    __tablename__ = "courses"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    batch = Column(String, nullable=False)
    group = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    section = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Active")
    created_at = Column(DateTime, default=datetime.utcnow)
    teacher_id = Column(Integer, ForeignKey('teachers.id'))
    teacher = relationship("Teacher", back_populates="courses")

# Create tables in the database
Base.metadata.create_all(bind=engine)