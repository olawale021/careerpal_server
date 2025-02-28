import io
import os
import uuid
from database import database
from dotenv import load_dotenv
from fastapi.security import OAuth2PasswordBearer
import jwt
from fastapi import APIRouter, Query, Body, UploadFile, File, Form, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel
from io import BytesIO
from supabase import create_client, Client

# Import the enhanced resume services
from app.services.resume_service import (
    extract_resume_text,
    score_resume,
    optimize_resume,
    generate_interview_questions,
    extract_job_requirements,
    segment_resume_sections
)

# Models for request/response
class DeleteResumeRequest(BaseModel):
    resume_id: str
    user_id: str

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), "../../.env")
load_dotenv(dotenv_path=dotenv_path)

# Authentication setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise ValueError("⚠️ Missing Supabase configuration!")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Create router
router = APIRouter(prefix="/resume", tags=["Resume Processing"])

# Authentication verification
def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/get-resumes")
async def get_user_resumes(user_id: str = Query(...)):
    """
    Fetches all resumes uploaded by a user and returns signed URLs for secure access.
    """
    try:
        query = """
            SELECT id, storage_path, file_name, uploaded_at, is_primary
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

        # Generate signed URLs for each resume
        resume_list = []
        for row in results:
            try:
                # Get signed URL from Supabase storage
                signed_url = supabase.storage.from_("careerpal").create_signed_url(
                    path=row["storage_path"],
                    expires_in=3600  # 1-hour expiry
                )

                resume_list.append({
                    "resume_id": row["id"],
                    "file_name": row["file_name"],
                    "uploaded_at": row["uploaded_at"],
                    "is_primary": row["is_primary"],
                    "signed_url": signed_url["signedURL"] if signed_url else None,
                })
            except Exception as e:
                print(f"Failed to generate signed URL for resume {row['id']}: {str(e)}")
                continue

        return {
            "message": "✅ Resumes retrieved successfully",
            "resumes": resume_list
        }

    except Exception as e:
        print(f"Error fetching resumes for user_id {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"❌ Error: {str(e)}")


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    is_primary: bool = Form(False)
):
    """
    Uploads a resume to Supabase Storage and saves metadata in database.
    """
    try:
        # Validate file type
        file_extension = file.filename.split(".")[-1].lower()
        if file_extension not in ["pdf", "doc", "docx"]:
            raise HTTPException(
                status_code=400, 
                detail="Unsupported file format. Please upload PDF, DOC, or DOCX files."
            )
            
        # Read file content
        file_content = await file.read()
        
        # Generate unique filename
        file_name = f"{uuid.uuid4()}.{file_extension}"
        storage_path = f"resumes/{file_name}"

        # Upload to Supabase Storage
        try:
            supabase.storage.from_("careerpal").upload(
                path=storage_path,
                file=file_content,
                file_options={"content-type": file.content_type}
            )
            
            # Generate signed URL
            signed_url = supabase.storage.from_("careerpal").create_signed_url(
                path=storage_path,
                expires_in=3600
            )

            # Update database
            async with database.transaction():
                if is_primary:
                    await database.execute(
                        "UPDATE resumes SET is_primary = FALSE WHERE user_id = :user_id",
                        {"user_id": user_id}
                    )

                query = """
                    INSERT INTO resumes (user_id, storage_path, file_name, is_primary)
                    VALUES (:user_id, :storage_path, :file_name, :is_primary)
                    RETURNING id
                """
                result = await database.fetch_one(
                    query,
                    {
                        "user_id": user_id,
                        "storage_path": storage_path,
                        "file_name": file.filename,
                        "is_primary": is_primary
                    }
                )

            return {
                "message": "Resume uploaded successfully",
                "file_url": signed_url["signedURL"],
                "storage_path": storage_path,
                "resume_id": result["id"] if result else None
            }

        except Exception as e:
            print(f"Storage error details: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file to storage: {str(e)}"
            )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/score")
async def score_user_resume(
    job_description: str = Form(...),
    file: Optional[UploadFile] = None,
    resume_id: Optional[str] = Form(None)
):
    """
    Enhanced resume scoring with detailed analysis and actionable recommendations.
    Accepts either a direct file upload or a resume_id of an existing resume.
    """
    if not file and not resume_id:
        raise HTTPException(
            status_code=400,
            detail="Either file or resume_id must be provided"
        )

    try:
        resume_data = None
        
        # If resume_id is provided, fetch from storage
        if resume_id:
            # Verify the resume exists in database
            query = """
                SELECT storage_path, file_name
                FROM resumes
                WHERE id = :resume_id
                LIMIT 1
            """
            record = await database.fetch_one(query, {"resume_id": resume_id})
            
            if not record:
                raise HTTPException(status_code=404, detail="Resume not found")

            try:
                # Download file from Supabase Storage
                storage_path = record["storage_path"]
                file_data = supabase.storage.from_("careerpal").download(storage_path)
                
                # Create a temporary file-like object
                file_like = BytesIO(file_data)
                
                # Create UploadFile with correct parameters
                temp_file = UploadFile(
                    filename=record["file_name"],
                    file=file_like,
                    headers={"content-type": "application/octet-stream"}
                )
                
                # Extract resume data
                resume_data = await extract_resume_text(temp_file)
            except Exception as storage_error:
                print(f"Storage Error: {str(storage_error)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch resume from storage: {str(storage_error)}"
                )
        else:
            # Use directly uploaded file
            resume_data = await extract_resume_text(file)
        
        # Check for extraction errors
        if "error" in resume_data:
            raise HTTPException(
                status_code=500, 
                detail=resume_data["error"]
            )

        # Get job requirements
        job_requirements = extract_job_requirements(job_description)
        
        # Score the resume
        score_result = score_resume(resume_data, job_description)
        
        # Create enhanced response with more details
        return {
            "message": "Resume scored successfully",
            "data": score_result,
            "job_requirements": job_requirements,
            "contact_details": resume_data.get("contact_details"),
            "segments": resume_data.get("segments", {})
        }

    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        print(f"Unexpected error during scoring: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )


@router.post("/optimize")
async def optimize_user_resume(
    job_description: str = Form(...),
    file: Optional[UploadFile] = File(None),
    resume_id: Optional[str] = Form(None)
):
    """
    Optimize a resume to better match a given job description.
    Returns an AI-enhanced resume with improved alignment to the job.
    Can accept either a file upload or an existing resume_id.
    """
    if not job_description:
        raise HTTPException(status_code=400, detail="Job description is required.")
        
    if not file and not resume_id:
        raise HTTPException(status_code=400, detail="Either file or resume_id is required.")
        
    if file and resume_id:
        raise HTTPException(status_code=400, detail="Cannot provide both file and resume_id.")

    try:
        if resume_id:
            # Fetch resume from storage using resume_id
            query = """
                SELECT storage_path, file_name FROM resumes WHERE id = :resume_id
            """
            record = await database.fetch_one(query, {"resume_id": resume_id})
            
            if not record:
                raise HTTPException(status_code=404, detail="Resume not found")
                
            # Get file from storage
            file_data = supabase.storage.from_("careerpal").download(record["storage_path"])
            file_like = io.BytesIO(file_data)
            file = UploadFile(
                filename=record["file_name"],
                file=file_like,
                headers={"content-type": "application/octet-stream"}
            )

        # Get optimized resume
        optimized_resume = await optimize_resume(file, job_description)
        
        if "error" in optimized_resume:
            raise HTTPException(status_code=500, detail=optimized_resume["error"])
        
        # Extract original resume text for comparison
        original_resume = await extract_resume_text(file)
        
        return {
            "message": "Resume optimized successfully",
            "data": optimized_resume,
            "original": original_resume.get("structured_resume", {})
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error optimizing resume: {str(e)}"
        )


@router.post("/analyze")
async def analyze_resume(file: UploadFile = File(...)):
    """
    Analyze a resume without job matching.
    Returns structured resume information with sections and contact details.
    """
    try:
        resume_data = await extract_resume_text(file)
        
        if "error" in resume_data:
            raise HTTPException(status_code=500, detail=resume_data["error"])
        
        # Return structured data
        return {
            "message": "Resume analyzed successfully",
            "data": {
                "contact_details": resume_data.get("contact_details", {}),
                "structured_resume": resume_data.get("structured_resume", {}),
                "segments": resume_data.get("segments", {})
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing resume: {str(e)}"
        )


@router.delete("/delete")
async def delete_resume(
    request: DeleteResumeRequest,
    token: str = Depends(oauth2_scheme),
):
    """
    Deletes a specific resume for a user, both from DB and from Supabase Storage.
    """
    try:
        # Verify JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Validate request payload
        if not request.resume_id or not request.user_id:
            raise HTTPException(status_code=400, detail="Missing resume_id or user_id")

        # Fetch the resume from DB
        query_resume = """
            SELECT id, user_id, storage_path
            FROM resumes
            WHERE id = :resume_id AND user_id = :user_id
            LIMIT 1
        """
        record = await database.fetch_one(
            query_resume,
            {"resume_id": request.resume_id, "user_id": request.user_id}
        )

        if not record:
            raise HTTPException(
                status_code=404,
                detail="Resume not found or not owned by this user"
            )

        # Delete from Supabase Storage
        storage_path = record["storage_path"]
        try:
            supabase.storage.from_("careerpal").remove([storage_path])
        except Exception as e:
            print(f"Failed to delete from storage: {str(e)}")

        # Delete from database
        delete_query = "DELETE FROM resumes WHERE id = :resume_id AND user_id = :user_id"
        await database.execute(
            delete_query,
            {"resume_id": request.resume_id, "user_id": request.user_id}
        )

        return {"message": "Resume deleted successfully"}

    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/interview-questions")
async def generate_questions(
    job_description: str = Form(...)
):
    """
    Generate AI-powered interview questions based on a job description.
    Returns a structured list of technical, behavioral, and situational questions.
    """
    if not job_description:
        raise HTTPException(status_code=400, detail="Job description is required.")

    try:
        questions = generate_interview_questions(job_description)
        
        if "error" in questions:
            raise HTTPException(status_code=500, detail=questions["error"])
        
        # Extract job requirements for context
        requirements = extract_job_requirements(job_description)
        
        return {
            "message": "Interview questions generated successfully",
            "data": questions,
            "job_requirements": requirements
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating questions: {str(e)}"
        )


@router.get("/job-requirements")
async def get_job_requirements(
    job_description: str = Query(..., min_length=50)
):
    """
    Extract key requirements from a job description.
    Useful for preliminary job analysis.
    """
    try:
        requirements = extract_job_requirements(job_description)
        
        if "error" in requirements:
            raise HTTPException(status_code=500, detail=requirements["error"])
            
        return {
            "message": "Job requirements extracted successfully",
            "data": requirements
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error extracting job requirements: {str(e)}"
        )