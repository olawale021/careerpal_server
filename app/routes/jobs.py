from fastapi import APIRouter, Query, Body
from uuid import UUID
from typing import Optional
from app.services.job_service import (
    fetch_jobs_from_db,
    fetch_job_by_id,
    scrape_and_save_jobs_service,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])  #  Add prefix and tags

@router.get("/")
async def get_jobs(
    page: int = Query(1, ge=1), 
    limit: int = Query(20, ge=1, le=50),
    title: Optional[str] = Query(None, description="Filter by job title"),
    job_type: Optional[str] = Query(None, description="Filter by job type (e.g., Full-time, Part-time)"),
    location: Optional[str] = Query(None, description="Filter by location"),
    remote: Optional[str] = Query(None, description="Filter by remote status (On-site, Remote, Hybrid)"),
    salary_min: Optional[int] = Query(None, description="Minimum salary filter"),
    salary_max: Optional[int] = Query(None, description="Maximum salary filter"),
    date_posted: Optional[str] = Query("Any time", description="Filter by date posted (e.g., 'Past 24 hours', 'Past week')")
):
    """
    Fetch jobs from the database with pagination and optional filters.
    """
    filters = {
        "title": title,
        "job_type": job_type,
        "location": location,
        "remote": remote,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "date_posted": date_posted,
    }
    
    return await fetch_jobs_from_db(page, limit, filters)


@router.get("/{job_id}")
async def get_job_by_id(job_id: UUID):
    """
    Fetch a single job by its ID.
    """
    return await fetch_job_by_id(job_id)


@router.post("/scrape")
async def scrape_jobs(query: str = Body(..., embed=True)):
    """
    Scrape jobs from external sources and save them to the database.
    """
    return await scrape_and_save_jobs_service(query)


# @router.post("/scrape-google/")
# async def scrape_jobs_google(
#     query: str = Body(..., embed=True), 
#     location: str = Body(..., embed=True)
# ):
#     """
#     Scrape jobs from Google Jobs and save them to the database.
#     """
#     return await scrape_and_save_jobs_google_service(query, location)
