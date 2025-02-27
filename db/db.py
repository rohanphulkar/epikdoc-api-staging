from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from decouple import config
from sqlalchemy.pool import QueuePool
# Database connection string
DB_USER = config('DB_USER', 'rohanphulkar')
DB_PASSWORD = config('DB_PASSWORD', 'Rohan007')
DB_HOST = config('DB_HOST', 'localhost')
DB_PORT = config('DB_PORT', '3306')
DB_NAME = config('DB_NAME', 'fastapi')

# Using pymysql as the sync driver
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create sync engine
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
)

# Create session factory
SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False
)

Base = declarative_base()

def get_db():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
