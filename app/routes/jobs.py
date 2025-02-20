from fastapi import APIRouter, Query, Body
from uuid import UUID
from app.services.job_service import (
    fetch_jobs_from_db,
    fetch_job_by_id,
    scrape_and_save_jobs_service,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])  #  Add prefix and tags

@router.get("/")
async def get_jobs(
    page: int = Query(1, ge=1), 
    limit: int = Query(20, ge=1, le=50)
):
    """
    Fetch jobs from the database with pagination.
    """
    return await fetch_jobs_from_db(page, limit)


@router.get("/{job_id}")
async def get_job_by_id(job_id: UUID):
    """
    Fetch a single job by its ID.
    """
    return await fetch_job_by_id(job_id)


@router.post("/scrape/")
async def scrape_jobs(query: str = Body(..., embed=True)):
    """
    Scrape jobs from external sources and save them to the database.
    """
    return await scrape_and_save_jobs_service(query)


@router.post("/scrape-google/")
async def scrape_jobs_google(
    query: str = Body(..., embed=True), 
    location: str = Body(..., embed=True)
):
    """
    Scrape jobs from Google Jobs and save them to the database.
    """
    return await scrape_and_save_jobs_google_service(query, location)
