from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://postgres:samadpls123@smartassessdb.cn0824m6mgt7.us-east-1.rds.amazonaws.com:5432/fypdb"

def reset_database():
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS university_admins CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS universities CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS super_admins CASCADE"))
        conn.commit()
        print("All tables dropped successfully")

if __name__ == "__main__":
    reset_database()