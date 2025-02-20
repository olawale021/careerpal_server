from fastapi import HTTPException
from app.database import database
import logging

logger = logging.getLogger(__name__)

async def fetch_users_from_db(page: int, limit: int):
    """
    Fetch users from the database with pagination.
    """
    try:
        offset = (page - 1) * limit
        query = "SELECT * FROM users ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        users = await database.fetch_all(query=query, values={"limit": limit, "offset": offset})

        total_query = "SELECT COUNT(*) FROM users"
        total_users = await database.fetch_val(query=total_query)

        return {
            "page": page,
            "limit": limit,
            "total_users": total_users,
            "total_pages": (total_users // limit) + (1 if total_users % limit else 0),
            "users": users
        }
    except Exception as e:
        logger.error(f"Database error while fetching users: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


async def fetch_user_by_id(user_id: str):
    """
    Fetch a single user by ID from the database.
    """
    try:
        query = "SELECT * FROM users WHERE id = :user_id"
        user = await database.fetch_one(query=query, values={"user_id": user_id})

        if user:
            return user
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching user {user_id}: {str(e)}")


async def fetch_user_id_by_email(email: str):
    """
    Fetch user ID from the database using email.
    """
    try:
        logger.info(f" Running query for email: {email}")  

        query = "SELECT id FROM users WHERE email = :email"  
        values = {"email": email} 

        result = await database.fetch_one(query=query, values=values)

        if result:
            logger.info(f"Query executed successfully. User ID: {result['id']}")
            return {"user_id": result["id"]}

        logger.warning("⚠️ No user found with this email.")
        raise HTTPException(status_code=404, detail="User not found")

    except Exception as e:
        logger.error(f" Database query error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")




async def insert_user_service(email: str, full_name: str, google_id: str):
    """
    Insert a new user into the database if they do not already exist.
    """
    try:
        # Check if user already exists
        query = "SELECT id FROM users WHERE email = :email"
        existing_user = await database.fetch_one(query, {"email": email})

        if existing_user:
            return {"message": "User already exists", "user_id": existing_user["id"]}

        # Insert new user
        insert_query = """
        INSERT INTO users (email, full_name, google_id) 
        VALUES (:email, :full_name, :google_id) 
        RETURNING id
        """
        new_user = await database.fetch_one(insert_query, {"email": email, "full_name": full_name, "google_id": google_id})

        return {"message": "User created successfully", "user_id": new_user["id"]}
    except Exception as e:
        logger.error(f" Error inserting user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error inserting user: {str(e)}")
