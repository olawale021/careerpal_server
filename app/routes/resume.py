import os
import boto3
import uuid
from app.database import database
from dotenv import load_dotenv
from fastapi.security import OAuth2PasswordBearer
import jwt
from fastapi import APIRouter, Query, Body, UploadFile, File, Form, HTTPException, Depends
from app.services.resume_service import (
    extract_resume_text,
    score_resume,
    optimize_resume,
    generate_interview_questions,
)
from pydantic import BaseModel
from typing import Optional



class DeleteResumeRequest(BaseModel):
    resume_id: str
    user_id: str



dotenv_path = os.path.join(os.path.dirname(__file__), "../../.env")
load_dotenv(dotenv_path=dotenv_path)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"



AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET")

if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_S3_BUCKET_NAME]):
    raise ValueError("⚠️ Missing AWS S3 environment variables!")

# Initialize AWS S3 Client
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)


router = APIRouter(prefix="/resume", tags=["Resume Processing"])  # Add Prefix and Tags

def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/uploads/")
async def upload_resume(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    is_primary: bool = Form(False)
):
    """
    Uploads a resume to AWS S3, saves the URL in Supabase, and returns the file URL.
    """
    try:
        #  Generate unique filename
        file_extension = file.filename.split(".")[-1]
        file_key = f"resumes/{uuid.uuid4()}.{file_extension}"

        #  Upload file to S3
        s3_client.upload_fileobj(file.file, AWS_S3_BUCKET_NAME, file_key)

        #  Generate public S3 URL
        s3_url = f"https://{AWS_S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{file_key}"

        # Start database transaction
        async with database.transaction():
            if is_primary:
                await database.execute(
                    "UPDATE resumes SET is_primary = FALSE WHERE user_id = :user_id",
                    {"user_id": user_id}
                )

            
            query = """
                INSERT INTO resumes (user_id, s3_url, file_name, is_primary)
                VALUES (:user_id, :s3_url, :file_name, :is_primary)
            """
            await database.execute(
                query,
                {
                    "user_id": user_id,
                    "s3_url": s3_url,
                    "file_name": file.filename,
                    "is_primary": is_primary
                }
            )

        return {
            "message": "Resume uploaded successfully",
            "s3_url": s3_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"❌ Error: {str(e)}")
    

@router.get("/get-resumes/")
async def get_user_resumes(user_id: str = Query(...)):
    """
    Fetches all resumes uploaded by a user and returns pre-signed URLs for secure access.
    """
    try:
        query = """
            SELECT id, s3_url, file_name, uploaded_at, is_primary
            FROM resumes
            WHERE user_id = :user_id
            ORDER BY uploaded_at DESC
        """
        results = await database.fetch_all(query, {"user_id": user_id})

        if not results:
            return {
                "message": "No resumes found for this user",
                "resumes": []
            }

        # ✅ Generate pre-signed URLs for each resume
        resume_list = []
        for row in results:
            file_key = row["s3_url"].replace(
                f"https://{AWS_S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/", ""
            )
            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": AWS_S3_BUCKET_NAME, "Key": file_key},
                ExpiresIn=3600,  # 1-hour expiry
            )
            resume_list.append({
                "resume_id": row["id"],
                "file_name": row["file_name"],
                "uploaded_at": row["uploaded_at"],
                "is_primary": row["is_primary"],
                "presigned_url": presigned_url,
            })

        return {
            "message": "✅ Resumes retrieved successfully",
            "resumes": resume_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"❌ Error: {str(e)}")



@router.post("/upload/")
async def upload_resume(file: UploadFile = File(...)):
    """
    Upload a resume and extract text from PDF or DOCX files.
    """
    extracted_data = await extract_resume_text(file)

    if "error" in extracted_data:
        raise HTTPException(status_code=400, detail=extracted_data["error"])

    return {"message": "Resume text extracted successfully", "data": extracted_data}


@router.post("/score/")
async def score_user_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    """
    Score a user's resume against a given job description.
    Returns a match score, missing skills, and recommendations.
    """
    if not job_description:
        raise HTTPException(status_code=400, detail="Job description is required.")

    score_result = score_resume(file, job_description)

    if "error" in score_result:
        raise HTTPException(status_code=500, detail=score_result["error"])

    return {"message": "Resume scored successfully", "data": score_result}


@router.post("/optimize/")
async def optimize_user_resume(
    file: UploadFile = File(...), 
    job_description: str = Form(...)
):
    """
    Optimize a resume to better match a given job description.
    Returns an AI-enhanced resume with improved alignment to the job.
    """
    if not job_description:
        raise HTTPException(status_code=400, detail="Job description is required.")

    optimized_resume = await optimize_resume(file, job_description)

    if "error" in optimized_resume:
        raise HTTPException(status_code=500, detail=optimized_resume["error"])

    return {"message": "Resume optimized successfully", "data": optimized_resume}

@router.delete("/delete")
async def delete_resume(
    request: DeleteResumeRequest,
    token: str = Depends(oauth2_scheme),
):
    """
    Deletes a specific resume for a user, both from DB and from S3.
    """
    try:
        # Verify JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Validate `request` payload
        if not request.resume_id or not request.user_id:
            raise HTTPException(status_code=400, detail="Missing resume_id or user_id")

        # Fetch the resume from DB
        query_resume = """
            SELECT id, user_id, s3_url, is_primary
            FROM resumes
            WHERE id = :resume_id AND user_id = :user_id
            LIMIT 1
        """
        record = await database.fetch_one(query_resume, {"resume_id": request.resume_id, "user_id": request.user_id})

        if not record:
            raise HTTPException(status_code=404, detail="Resume not found or not owned by this user")

        # Delete from S3
        s3_url = record["s3_url"]
        prefix = f"https://{AWS_S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/"
        file_key = s3_url.replace(prefix, "")

        try:
            s3_client.delete_object(Bucket=AWS_S3_BUCKET_NAME, Key=file_key)
        except Exception as e:
            print(f"Failed to delete from S3: {str(e)}")

        # Delete from database
        delete_query = "DELETE FROM resumes WHERE id = :resume_id AND user_id = :user_id"
        await database.execute(delete_query, {"resume_id": request.resume_id, "user_id": request.user_id})

        return {"message": "Resume deleted successfully"}

    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/generate-interview-questions/")
async def generate_questions(
    job_description: str = Form(...)
):
    """
    Generate AI-powered interview questions based on a job description.
    Returns a structured list of technical, behavioral, and situational questions.
    """
    if not job_description:
        raise HTTPException(status_code=400, detail="Job description is required.")

    questions = await generate_interview_questions(job_description)

    if "error" in questions:
        raise HTTPException(status_code=500, detail=questions["error"])

    return {"message": "Interview questions generated successfully", "data": questions}
