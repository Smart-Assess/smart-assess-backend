import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Connection parameters
host = "proj-db.cn0824m6mgt7.us-east-1.rds.amazonaws.com"
port = "5432"
user = "postgres"
password = "admin1234"
dbname = "postgres"  # Connect to the default 'postgres' database initially

try:
    # Connect to the default 'postgres' database
    connection = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname
    )
    
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = connection.cursor()

    # Check if the database already exists
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'smartassess-db'")
    exists = cursor.fetchone()

    if not exists:
        # Create the new database if it doesn't exist
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier('smartassess-db')))
        print("Database 'smartassess-db' created successfully.")
    else:
        print("Database 'smartassess-db' already exists.")

except Exception as e:
    print(f"Error: {e}")

finally:
    # Clean up
    if cursor:
        cursor.close()
    if connection:
        connection.close()
