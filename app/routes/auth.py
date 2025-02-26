from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from starlette.requests import Request
from database import database
from app.services.auth_service import (
    create_jwt_token, get_user_by_email, register_user_with_password, register_user_with_google, authenticate_user, oauth
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register")
async def register(email: str, full_name: str, password: str):
    """Register a new user with email/password"""
    user = await register_user_with_password(email, full_name, password)
    token = await create_jwt_token(user)
    return {"access_token": token, "token_type": "bearer", "user": user}

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login user with email and password"""
    user = await authenticate_user(form_data.username, form_data.password)
    token = await create_jwt_token(user)
    return {"access_token": token, "token_type": "bearer", "user": user}

@router.get("/google/login")
async def google_login(request: Request):
    """Redirect to Google login"""
    redirect_uri = f"{request.url.scheme}://{request.url.hostname}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.post("/google/callback")
async def google_callback_post(request: Request):
    """Handle Google authentication callback from NextAuth."""
    try:
        body = await request.json()
        print("Received request from NextAuth:", body)  # Log incoming request

        email = body.get("email")
        google_id = body.get("google_id")
        full_name = body.get("full_name")

        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Missing email or google_id")

        # ✅ Ensure Database is Connected
        if not database.is_connected:
            print("⚠️ Database is not connected. Reconnecting...")
            await database.connect()

        # ✅ Check if user already exists
        user = await get_user_by_email(email)

        if user:
            print(f"User {email} already exists. Logging in instead of registering.")
        else:
            print(f"Registering new user: {email}")
            user = await register_user_with_google(email, full_name, google_id)

        # ✅ Generate JWT Token
        jwt_token = await create_jwt_token(user)

        return {"access_token": jwt_token, "token_type": "bearer", "user": user}

    except Exception as e:
        print("Error processing Google callback:", str(e))
        raise HTTPException(status_code=500, detail="Internal Server Error")
        
# @router.get("/google/callback")
# async def google_callback(request: Request):
#     """Handle Google OAuth callback"""
#     try:
#         token = await oauth.google.authorize_access_token(request)
#         user_info = token.get("userinfo")

#         if not user_info:
#             raise HTTPException(status_code=400, detail="Failed to fetch user info from Google")

#         email = user_info["email"]
#         google_id = user_info["sub"]
#         full_name = user_info.get("name", "")

#         user = await register_user_with_google(email, full_name, google_id)  # Register or get existing user
#         jwt_token = await create_jwt_token(user)

#         return {"access_token": jwt_token, "token_type": "bearer", "user": user}
    
#     except Exception as e:
#         return JSONResponse(status_code=500, content={"error": str(e)})