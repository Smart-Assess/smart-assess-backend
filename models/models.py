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


# Create tables in the database
Base.metadata.create_all(bind=engine)