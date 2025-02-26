import os
import jwt
import bcrypt
from databases import Database
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException
from dotenv import load_dotenv
import asyncpg
from fastapi import HTTPException

# Load environment variables
load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")

from database import database

# Initialize OAuth for Google authentication
oauth = OAuth()
oauth.register(
    "google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    access_token_url="https://oauth2.googleapis.com/token",
    client_kwargs={"scope": "openid email profile"},
)

async def create_jwt_token(user):
    """Generate JWT token for authentication"""
    payload = {"sub": str(user["id"]), "email": user["email"], "auth_provider": user["auth_provider"]}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

async def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

async def verify_password(password: str, hashed_password: str) -> bool:
    """Verify hashed password"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))

async def get_user_by_email(email: str):
    """Retrieve user by email from the database"""
    query = "SELECT * FROM users WHERE email = :email"
    return await database.fetch_one(query=query, values={"email": email})



async def register_user_with_password(email: str, full_name: str, password: str):
    """Register a new user with email/password"""
    hashed_password = await hash_password(password)
    query = """
    INSERT INTO users (email, full_name, password_hash, auth_provider, is_active, is_verified)
    VALUES (:email, :full_name, :password_hash, 'email', TRUE, FALSE)
    RETURNING *
    """
    try:
        new_user = await database.fetch_one(
            query=query,
            values={"email": email, "full_name": full_name, "password_hash": hashed_password}
        )
        return new_user

    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Email already exists")

    except asyncpg.PostgresError as e:
        print("Actual Database Error:", str(e))  # Log full error for debugging
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

async def register_user_with_google(email: str, full_name: str, google_id: str):
    """Register a new user with Google OAuth"""
    query = """
    INSERT INTO users (email, full_name, google_id, auth_provider, is_active, is_verified)
    VALUES (:email, :full_name, :google_id, 'google', TRUE, TRUE)
    RETURNING *
    """
    try:
        new_user = await database.fetch_one(
            query=query,
            values={"email": email, "full_name": full_name, "google_id": google_id}
        )
        return new_user

    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Email already exists")

    except asyncpg.PostgresError as e:
        print("Actual Database Error:", str(e))  # Log full error for debugging
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

async def authenticate_user(email: str, password: str):
    """Authenticate user by email and password"""
    user = await get_user_by_email(email)
    if not user or not await verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user
