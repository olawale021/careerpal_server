import json
import os
import openai
import PyPDF2
import docx2txt
import re
from io import BytesIO
from fastapi import UploadFile
from dotenv import load_dotenv
import pycountry  # For recognizing country names dynamically

# Load environment variables from .env file
load_dotenv()

# Get OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI Client
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Extract text from resumes (PDF/DOCX)
async def extract_resume_text(file: UploadFile):
    file_extension = file.filename.split(".")[-1]

    if file_extension == "pdf":
        pdf_reader = PyPDF2.PdfReader(BytesIO(await file.read()))
        text = "\n".join([page.extract_text() for page in pdf_reader.pages if page.extract_text()])
    
    elif file_extension == "docx":
        text = docx2txt.process(BytesIO(await file.read()))
    
    else:
        return {"error": "Unsupported file format"}

    #  Extract Contact Details
    contact_details = extract_contact_details(text)

    # Ask OpenAI to format the extracted text properly
    prompt = f"""
    Structure the following resume text into JSON with these categories:
    - Summary
    - Work Experience
    - Personal Projects
    - Education
    - Certifications
    - Skills
    - Volunteering Experience
    - Leadership Experience

    If a category is missing, return an empty string for that field.

    **Resume Text:**
    {text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a professional resume parser. Structure the resume into JSON format."},
            {"role": "user", "content": prompt}
        ]
    )

    # Convert AI response to JSON
    try:
        structured_resume = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        structured_resume = {"error": "Failed to parse AI response"}

    return {"contact_details": contact_details, "structured_resume": structured_resume}

# **Updated Function for Contact Details Extraction**
def extract_contact_details(text: str):
    lines = text.split("\n")

    # Extract Name Using Heuristics
    name = extract_name(text)

    # Extract Phone Number
    phone_match = re.search(r'\(?\+?\d{1,3}?\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}', text)
    phone_number = phone_match.group(0) if phone_match else "Not Provided"

    # Extract Email
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    email = email_match.group(0) if email_match else "Not Provided"

    # Extract LinkedIn & GitHub
    linkedin_match = re.search(r'https?://(?:www\.)?linkedin\.com/\S+', text)
    github_match = re.search(r'https?://(?:www\.)?github\.com/\S+', text)
    linkedin = linkedin_match.group(0) if linkedin_match else "Not Provided"
    github = github_match.group(0) if github_match else "Not Provided"

    #  Extract Location (City, Country, or Country)
    location = extract_location(text)

    return {
        "name": name,
        "phone_number": phone_number,
        "email": email,
        "location": location,
        "linkedin": linkedin,
        "github": github
    }

#  **Extract Name More Accurately**
def extract_name(text: str):
    lines = text.split("\n")

    #  Use the first few lines (names are usually on top)
    potential_names = []
    for line in lines[:5]:  # Check only first 5 lines to avoid unnecessary text
        line = line.strip()
        if 2 <= len(line.split()) <= 5:  # A name usually consists of 2 to 4 words
            potential_names.append(line)

    if potential_names:
        return potential_names[0]  # Return the first detected name

    #   Use OpenAI GPT-4 to Extract Name
    prompt = f"""
    Extract **only** the person's full name from the following resume text.
    - Do NOT include additional text like "The person's name is ..."
    - Only return the name, e.g., "John Doe".
    - If no name is found, return "Unknown".

    **Resume Text:**
    {text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert at extracting names from text. Return only the name."},
            {"role": "user", "content": prompt}
        ]
    )

    try:
        name = response.choices[0].message.content.strip()

        # Ensure the name does not include extra text
        if "name is" in name.lower():
            name = name.split("name is")[-1].strip()

        return name if name else "Unknown"
    except:
        return "Unknown"


#  **Extract Location More Accurately**
def extract_location(text: str):
    # Match "City, Country" Format (Most Reliable)
    city_country_match = re.search(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?,\s?[A-Z][a-z]+)\b", text)
    if city_country_match:
        return city_country_match.group(0)  # Return exact match of "City, Country"

    #  Match Only a Country Name (Using `pycountry`)
    for country in pycountry.countries:
        if re.search(rf"\b{country.name}\b", text, re.IGNORECASE):
            return country.name  # Extracted Country Name

    #  Match Only a City Name (Common Cities)
    common_cities = [
        "New York", "Los Angeles", "Chicago", "London", "Berlin", "Lagos", "Accra", "Paris", "Toronto",
        "Manchester", "Dubai", "Tokyo", "Beijing", "Mumbai", "Sydney", "Barcelona", "Houston", "Boston",
        "San Francisco", "Washington", "Rome", "Madrid", "Nairobi", "Cape Town"
    ]
    for city in common_cities:
        if re.search(rf"\b{city}\b", text, re.IGNORECASE):
            return city  # Extracted City Name

    #  General City Extraction (Fallback for Less Common Cities)
    city_match = re.search(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b", text)
    if city_match:
        return city_match.group(0)  # Extracted City Name

    #  Use OpenAI GPT-4 as a Last Resort
    prompt = f"""
    Extract **only** the location (city, country, or just country) from the following resume text.
    - If only a city is available, return just the city (e.g., "Coventry").
    - If only a country is available, return just the country (e.g., "United Kingdom").
    - If both city and country are available, return "City, Country" (e.g., "Coventry, UK").
    - If no location is found, return "Not Provided".

    **Resume Text:**
    {text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert at extracting locations from text. Return only the location."},
            {"role": "user", "content": prompt}
        ]
    )

    try:
        location = response.choices[0].message.content.strip()
        return location if location else "Not Provided"
    except:
        return "Not Provided"




# **AI-Powered Resume Scoring**
import json
import re

def score_resume(resume_text: str, job_description: str):
    prompt = f"""
Compare the following resume to the job description and return JSON:
- "match_score": (0-100)
- "missing_skills": (list of skills)
- "recommendations": (list of suggestions)

**Resume:** {resume_text}
**Job Description:** {job_description}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a resume evaluation assistant. Return JSON only."},
            {"role": "user", "content": prompt}
        ]
    )

    #  Extract raw AI response
    raw_response = response.choices[0].message.content.strip()

    # Remove Markdown code block formatting (if any)
    clean_response = re.sub(r"```json\n|\n```", "", raw_response).strip()

    # Convert AI response to JSON
    try:
        return json.loads(clean_response)
    except json.JSONDecodeError:
        return {"error": "Failed to parse AI response", "raw_response": raw_response}



async def optimize_resume(file: UploadFile, job_description: str):
    extracted_data = await extract_resume_text(file)

    if "error" in extracted_data:
        return extracted_data

    prompt = f"""
Optimize the given resume to match the job description as closely as possible.

### **Instructions:**
- Rewrite **summary, work experience, and skills** to align with the job description.
- Fill in missing details based on the job requirements.
- Use **strong action verbs** and **ATS-friendly formatting**.
- Return only the **optimized structured resume** in the exact JSON format below.

### **JSON Response Format (Must Follow This Structure):**
{{
    "summary": "",
    "skills": {{
        "Technical Skills": [],
        "Soft Skills": []
    }},
    "work_experience": [
        {{
            "company": "",
            "location": "",
            "role": "",
            "period": "",
            "responsibilities": []
        }}
    ],
    "education": [
        {{
            "institution": "",
            "location": "",
            "degree": "",
            "period": ""
        }}
    ],
    "certifications": [
        {{
            "title": "",
            "year": ""
        }}
    ],
    "volunteering_experience": [
        {{
            "organization": "",
            "role": "",
            "period": "",
            "responsibilities": []
        }}
    ],
    "projects": [
        {{
            "title": "",
            "description": "",
            "technologies_used": []
        }}
    ]
}}

### **Extracted Resume:**
{json.dumps(extracted_data["structured_resume"], indent=2)}

### **Job Description:**
{job_description}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a resume optimization assistant. Return the structured optimized resume in JSON format."},
            {"role": "user", "content": prompt}
        ]
    )

    # ✅ Extract JSON response safely
    try:
        optimized_resume = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError as e:
        print(" JSON Decode Error:", str(e))
        optimized_resume = {"error": "Failed to parse AI response"}

    return optimized_resume


#  Generate AI Interview Questions Based on Job Description
def generate_interview_questions(job_description: str):
    prompt = f"""
    Based on the following job description, generate:
    - 5 technical interview questions.
    - 5 behavioral interview questions.
    - 3 situational questions.

    **Job Description:** {job_description}

    Format the response as JSON with categories: technical, behavioral, situational.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an AI interview coach. Return questions in JSON format."},
            {"role": "user", "content": prompt}
        ]
    )

    #  Convert AI response to JSON
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        return {"error": "Failed to parse AI response"}
