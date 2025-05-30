from sqlalchemy import create_engine, text

# Change this to your database URL
DATABASE_URL = "sqlite:///./university_management.db"


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
