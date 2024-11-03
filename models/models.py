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
    # university = relationship("School", back_populates="created_by")

# Create tables in the database
Base.metadata.create_all(bind=engine)