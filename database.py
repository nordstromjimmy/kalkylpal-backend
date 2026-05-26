"""
database.py — Database connection and session management.

We use SQLAlchemy as our ORM (Object Relational Mapper).
This means we interact with the database using Python objects,
not raw SQL queries.

DATABASE_URL points to SQLite for now (just a local file).
To switch to PostgreSQL later, change this one line to:
    postgresql://user:password@localhost/vvs_app
Nothing else in the codebase needs to change.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = "sqlite:///./vvs_app.db"

# The engine is the actual connection to the database.
# check_same_thread=False is required for SQLite with FastAPI
# (FastAPI handles multiple requests at once).
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# A SessionLocal is a "unit of work" with the database.
# Each API request gets its own session, uses it, then closes it.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# All our database models will inherit from this Base class.
# SQLAlchemy uses this to know which classes represent database tables.
class Base(DeclarativeBase):
    pass

# This is a FastAPI "dependency" — a function that runs before
# each request that needs database access. It opens a session,
# gives it to the endpoint, then closes it when done.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()