import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from database import database
from app.routes.auth import router as auth_router
from app.routes.jobs import router as jobs_router
from app.routes.resume import router as resume_router
from app.routes.users import router as users_router

# Set up logging
logging.basicConfig(level=logging.DEBUG)  # Set logging level
logger = logging.getLogger(__name__)  # Get the logger instance




@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await database.connect()
        logger.info("Database connected successfully.")
    except Exception as e:
        logger.error(f" Database connection failed: {str(e)}")

    yield  # Allow FastAPI to run

    try:
        await database.disconnect()
        logger.info(" Database disconnected successfully.")
    except Exception as e:
        logger.error(f"Database disconnection failed: {str(e)}")


app = FastAPI(lifespan=lifespan)

# Middleware for debugging requests
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET"))

origins = [
    "http://localhost:3000",  # React dev server

    "https://careerpalclient.vercel.app",  # vercel url
    "http://cp-v1-gfcvakcrdnd8gsgh.ukwest-01.azurewebsites.net",  # Backend URL
    "https://cp-v1-gfcvakcrdnd8gsgh.ukwest-01.azurewebsites.net",  # Secure backend URL
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

## Add debugging logs for request and response tracking
@app.middleware("http")
async def log_requests(request, call_next):
    logger.info(f"➡️ Incoming Request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f" Response: {response.status_code}")
    return response

#  Include Routers
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(resume_router)
app.include_router(users_router)


@app.get("/")
def root():
    logger.info("Root API is running!")
    return {"message": "API is running with Lifespan!"}

@app.get("/health")
async def root():
    return {"message": "Health Okay"}
