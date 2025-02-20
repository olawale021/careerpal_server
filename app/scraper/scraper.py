from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
import datetime
import time
from databases import Database
from app import database
from datetime import datetime

# Define headers to mimic a browser request
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

async def scrape_and_save_jobs(query):
    """Scrapes jobs from all available pages and saves them to the database."""
    try:
        await database.connect()  # Use the database instance to connect
        total_jobs_saved = 0
        encoded_query = quote(query)  # URL encode the query parameter

        # Determine the total number of pages
        url = f"https://findajob.dwp.gov.uk/search?q={encoded_query}&p=1"
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract total number of jobs
        total_jobs_text = soup.find("h1", class_="govuk-heading-l").text
        total_jobs = int(total_jobs_text.split()[0].replace(',', ''))

        jobs_per_page = 10
        total_pages = (total_jobs + jobs_per_page - 1) // jobs_per_page  # Ceiling division

        print(f"Total pages found: {total_pages}")

        for page in range(1, total_pages + 1):
            url = f"https://findajob.dwp.gov.uk/search?q={encoded_query}&p={page}"
            print(f" Scraping page {page}: {url}")
            
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            job_listings = soup.find_all("div", class_="search-result")

            if not job_listings:
                print(f"No jobs found on page {page}")
                continue

            print(f" Found {len(job_listings)} jobs on page {page}")
            
            jobs = []
            for job in job_listings:
                try:
                    title_tag = job.find("h3", class_="govuk-heading-s").find("a")
                    if not title_tag:
                        continue

                    title = title_tag.text.strip()
                    job_href = title_tag.get("href")
                    job_link = job_href if job_href.startswith("https") else f"https://findajob.dwp.gov.uk{job_href}"

                    #  Fetch full job details from the job details page
                    job_details = fetch_job_details(job_link)

                    # Check if job already exists
                    existing_job_query = "SELECT COUNT(*) FROM jobs WHERE link = :link"
                    existing_job_count = await database.fetch_val(
                        query=existing_job_query, 
                        values={"link": job_link}
                    )

                    if existing_job_count == 0:
                        jobs.append(job_details)
                        print(f"🆕 Found new job: {title}")

                except Exception as e:
                    print(f" Error processing job listing: {str(e)}")
                    continue

            # Insert jobs into database
            if jobs:
                query = """
                INSERT INTO jobs (title, company, location, salary, description, posting_date, closing_date, hours, job_type, remote_working, link, created_at)
                VALUES (:title, :company, :location, :salary, :description, :posting_date, :closing_date, :hours, :job_type, :remote_working, :link, :created_at)
                ON CONFLICT (link) DO NOTHING
                """
                await database.execute_many(query=query, values=jobs)
                total_jobs_saved += len(jobs)
                print(f"Inserted {len(jobs)} new jobs from page {page}")

    except Exception as e:
        print(f"Error during scraping: {str(e)}")
    finally:
        await database.disconnect()
        print(f"Total jobs saved: {total_jobs_saved}")

def fetch_job_details(job_url):
    """Fetches full job details from the job details page with improved parsing."""
    try:
        response = requests.get(job_url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title from h1
        title = soup.find("h1", class_="govuk-heading-l")
        title = title.text.strip() if title else "N/A"

        # Initialize job details dictionary
        job_details = {}

        # Extract job details from the table more robustly
        job_table = soup.find("table", class_="govuk-table")
        if job_table:
            rows = job_table.find_all("tr", class_="govuk-table__row")
            for row in rows:
                header = row.find("th", class_="govuk-table__header")
                value = row.find("td", class_="govuk-table__cell")
                
                if header and value:
                    key = header.text.strip().rstrip(':').lower()
                    val = value.text.strip()
                    job_details[key] = val

        # Extract description
        description_section = soup.find("div", itemprop="description")
        description = description_section.get_text("\n", strip=True) if description_section else "No description available."

        # Parse dates with better error handling
        posting_date = convert_to_date(job_details.get('posting date', 'N/A'))
        closing_date = convert_to_date(job_details.get('closing date', 'N/A'))

        # Extract additional salary information if available
        additional_salary = job_details.get('additional salary information', '')
        salary = job_details.get('salary', 'N/A')
        if additional_salary:
            salary = f"{salary} - {additional_salary}"

        # Construct and return the job data
        return {
            "title": title,
            "company": job_details.get('company', 'N/A'),
            "location": job_details.get('location', 'N/A'),
            "salary": salary.strip(),
            "description": description,
            "posting_date": posting_date,
            "closing_date": closing_date,
            "hours": job_details.get('hours', 'N/A'),
            "job_type": job_details.get('job type', 'N/A'),
            "remote_working": job_details.get('remote working', 'N/A'),
            "link": job_url,
            "created_at": datetime.utcnow()
        }

    except Exception as e:
        print(f" Error fetching job details from {job_url}: {str(e)}")
        # Return default values if scraping fails
        return {
            "title": "N/A",
            "company": "N/A",
            "location": "N/A",
            "salary": "N/A",
            "description": "Error retrieving job description.",
            "posting_date": None,
            "closing_date": None,
            "hours": "N/A",
            "job_type": "N/A",
            "remote_working": "N/A",
            "link": job_url,
            "created_at": datetime.utcnow()
        }

def convert_to_date(date_str):
    """Converts various date formats to a datetime object with better error handling."""
    if not date_str or date_str == 'N/A':
        return None
    
    try:
        # Handle different date formats
        formats = [
            "%d %B %Y",           # e.g., "10 February 2025"
            "%d/%m/%Y",           # e.g., "10/02/2025"
            "%Y-%m-%d",           # e.g., "2025-02-10"
            "%d-%m-%Y"            # e.g., "10-02-2025"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
                
        print(f" Could not parse date: {date_str}")
        return None
    except Exception as e:
        print(f" Error converting date {date_str}: {str(e)}")
        return None