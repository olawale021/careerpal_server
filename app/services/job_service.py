from database import database
from typing import Dict, Optional, Any
from fastapi import HTTPException

async def fetch_jobs_from_db(page: int, limit: int, filters: Optional[Dict[str, Any]] = None):
    """
    Fetch jobs from the database with pagination and optional filtering.
    """
    try:
        offset = (page - 1) * limit
        query = "SELECT * FROM jobs WHERE 1=1"  # Ensure a valid WHERE clause
        params: Dict[str, Any] = {"limit": limit, "offset": offset}

        if filters:
            if "title" in filters and filters["title"]:
                query += " AND title ILIKE :title"
                params["title"] = f"%{filters['title']}%"  # Case-insensitive partial match

            if "job_type" in filters and filters["job_type"]:
                query += " AND job_type = :job_type"
                params["job_type"] = filters["job_type"]

            if "location" in filters and filters["location"]:
                query += " AND location ILIKE :location"
                params["location"] = f"%{filters['location']}%"  # Case-insensitive search

            if "remote" in filters and filters["remote"]:
                query += " AND remote_working = :remote"
                params["remote"] = filters["remote"]

            if "salary_min" in filters and filters["salary_min"] is not None:
                query += " AND salary >= :salary_min"
                params["salary_min"] = str(filters["salary_min"])  # Convert to string

            if "salary_max" in filters and filters["salary_max"] is not None:
                query += " AND salary <= :salary_max"
                params["salary_max"] = str(filters["salary_max"])  # Convert to string

            if "date_posted" in filters and filters["date_posted"] and filters["date_posted"] != "Any time":
                if filters["date_posted"] == "Past 24 hours":
                    query += " AND created_at >= NOW() - INTERVAL '1 day'"
                elif filters["date_posted"] == "Past week":
                    query += " AND created_at >= NOW() - INTERVAL '7 days'"
                elif filters["date_posted"] == "Past month":
                    query += " AND created_at >= NOW() - INTERVAL '30 days'"

        # Apply sorting, pagination
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"

        jobs = await database.fetch_all(query=query, values=params)

        # Count total jobs with filters
        count_params = params.copy()
        # Remove pagination parameters as they're not needed for the count
        count_params.pop('limit', None)
        count_params.pop('offset', None)

        total_query = "SELECT COUNT(*) FROM jobs WHERE 1=1"
        if filters:
            # Only use the WHERE conditions, not the ORDER BY and LIMIT clauses
            where_conditions = query.split("ORDER BY")[0].split("WHERE 1=1")[1]
            total_query += where_conditions

        total_jobs = await database.fetch_val(query=total_query, values=count_params)

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

