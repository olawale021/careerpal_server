from fastapi import APIRouter, HTTPException, Query
from database import database
from app.services.users_services import (
    fetch_users_from_db, 
    fetch_user_by_id, 
    fetch_user_id_by_email,
    insert_user_service
)
import logging


# Initialize logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

# Fetch paginated users
@router.get("/")
async def get_users(page: int = Query(1, alias="page"), limit: int = Query(10, alias="limit")):
    return await fetch_users_from_db(page, limit)


# # Fetch user by ID
@router.get("/{user_id}")
async def get_user_by_id(user_id: str):
    return await fetch_user_by_id(user_id)


@router.get("/lookup/email")
async def get_user_id_by_email(email: str = Query(..., description="User email")):
    """
    Fetch a user's ID using their email.
    """
    try:
        logger.info(f" Fetching user ID for email: {email}") 
        print(f" Fetching user ID for email: {email}")  

        result = await fetch_user_id_by_email(email) 

        if not result:
            logger.warning(f"⚠️ No user found for email: {email}")
            raise HTTPException(status_code=404, detail="User not found")

        user_id = result["user_id"] 
        logger.info(f" User ID retrieved: {user_id}")
        
        return {"user_id": user_id}

    except Exception as e:
        logger.error(f"❌ Error fetching user ID: {str(e)}", exc_info=True)
        print(f"❌ Error fetching user ID: {str(e)}")  # Print for debugging
        raise HTTPException(status_code=500, detail=f"Error fetching user ID: {str(e)}")



#  Insert user if they don't exist
@router.post("/register")
async def register_user(email: str, full_name: str, google_id: str):
    return await insert_user_service(email, full_name, google_id)
