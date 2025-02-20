from app.database import database
from fastapi import HTTPException

async def fetch_jobs_from_db(page: int, limit: int):
    """
    Fetch jobs from the database with pagination.
    """
    try:
        offset = (page - 1) * limit
        query = "SELECT * FROM jobs ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        jobs = await database.fetch_all(query=query, values={"limit": limit, "offset": offset})

        total_query = "SELECT COUNT(*) FROM jobs"
        total_jobs = await database.fetch_val(query=total_query)

        return {
            "page": page,
            "limit": limit,
            "total_jobs": total_jobs,
            "total_pages": (total_jobs // limit) + (1 if total_jobs % limit else 0),
            "jobs": jobs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


async def fetch_job_by_id(job_id: int):
    """
    Fetch a single job by ID from the database.
    """
    try:
        query = "SELECT * FROM jobs WHERE id = :job_id"
        job = await database.fetch_one(query=query, values={"job_id": job_id})

        if job:
            return job
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching job {job_id}: {str(e)}")


async def scrape_and_save_jobs_service(query: str):
    """
    Scrape jobs from external sources and save them to the database.
    """
    from app.scraper.scraper import scrape_and_save_jobs

    try:
        await scrape_and_save_jobs(query)
        return {"message": f"Jobs for '{query}' scraped and saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping error: {str(e)}")

