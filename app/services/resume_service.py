import json
import os
import openai
import PyPDF2
import docx2txt
import re
from io import BytesIO
from fastapi import UploadFile
from dotenv import load_dotenv
import pycountry
from difflib import SequenceMatcher

# Load environment variables from .env file
load_dotenv()

# Get OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI Client
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Extract text from resumes (PDF/DOCX)
async def extract_resume_text(file: UploadFile):
    """Extract and parse text from resume files"""
    file_extension = file.filename.split(".")[-1].lower()
    
    try:
        if file_extension == "pdf":
            pdf_reader = PyPDF2.PdfReader(BytesIO(await file.read()))
            text = "\n".join([page.extract_text() for page in pdf_reader.pages if page.extract_text()])
        
        elif file_extension in ["docx", "doc"]:
            text = docx2txt.process(BytesIO(await file.read()))
        
        else:
            return {"error": f"Unsupported file format: {file_extension}. Please upload PDF or DOCX files."}
        
        # Process the extracted text
        contact_details = extract_contact_details(text)
        structured_resume = structure_resume(text)
        segments = segment_resume_sections(text)
        
        return {
            "raw_text": text,
            "contact_details": contact_details, 
            "structured_resume": structured_resume,
            "segments": segments
        }
    except Exception as e:
        return {"error": f"Error extracting text from resume: {str(e)}"}

def extract_contact_details(text: str):
    """Extract contact information from resume text with improved social media detection"""
    # Extract Name
    name = extract_name(text)

    # Extract Phone Number
    phone_regex = r'\+?[\d\s\(\)-]{7,20}'
    phone_match = re.search(phone_regex, text)
    phone_number = phone_match.group(0).strip() if phone_match else "Not Provided"

    # Extract Email
    email_regex = r'[\w\.-]+@[\w\.-]+\.\w+'
    email_match = re.search(email_regex, text)
    email = email_match.group(0) if email_match else "Not Provided"

    # LinkedIn detection - multiple patterns
    linkedin_patterns = [
        # Full URL in text
        r'https?://(?:www\.)?linkedin\.com/in/[\w-]+/?',
        # URL with www in text
        r'www\.linkedin\.com/in/[\w-]+/?',
        # Just the profile format
        r'linkedin\.com/in/[\w-]+/?',
        # Lines with "LinkedIn:" format
        r'LinkedIn:?\s*(https?://(?:www\.)?linkedin\.com/in/[\w-]+/?|[\w-]+)',
    ]
    
    linkedin = "Not Provided"
    for pattern in linkedin_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            linkedin = match.group(0)
            break
    
    # If no match found but LinkedIn is mentioned, check nearby lines
    if linkedin == "Not Provided" and re.search(r'\bLinkedIn\b', text, re.IGNORECASE):
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if re.search(r'\bLinkedIn\b', line, re.IGNORECASE):
                # Check current line, previous line and next line for URLs
                nearby_lines = [line]
                if i > 0:
                    nearby_lines.append(lines[i-1])
                if i < len(lines)-1:
                    nearby_lines.append(lines[i+1])
                
                for nearby in nearby_lines:
                    url_match = re.search(r'https?://[^\s]+', nearby)
                    if url_match and 'linkedin' in url_match.group(0).lower():
                        linkedin = url_match.group(0)
                        break
    
    # GitHub detection - similar approach
    github_patterns = [
        # Full URL in text
        r'https?://(?:www\.)?github\.com/[\w-]+/?',
        # Just the profile format
        r'github\.com/[\w-]+/?',
        # Lines with "GitHub:" format
        r'GitHub:?\s*(https?://(?:www\.)?github\.com/[\w-]+/?|[\w-]+)',
    ]
    
    github = "Not Provided"
    for pattern in github_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            github = match.group(0)
            break
    
    # If no match found but GitHub is mentioned, check nearby lines
    if github == "Not Provided" and re.search(r'\bGitHub\b', text, re.IGNORECASE):
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if re.search(r'\bGitHub\b', line, re.IGNORECASE):
                # Check nearby lines
                nearby_lines = [line]
                if i > 0:
                    nearby_lines.append(lines[i-1])
                if i < len(lines)-1:
                    nearby_lines.append(lines[i+1])
                
                for nearby in nearby_lines:
                    url_match = re.search(r'https?://[^\s]+', nearby)
                    if url_match and 'github' in url_match.group(0).lower():
                        github = url_match.group(0)
                        break
    
    # Extract Location
    location = extract_location(text)

    # If social media still not found, try AI-based extraction as a last resort
    if linkedin == "Not Provided" or github == "Not Provided":
        social_profiles = extract_social_profiles(text)
        if social_profiles:
            linkedin = social_profiles.get("linkedin", linkedin)
            github = social_profiles.get("github", github)

    return {
        "name": name,
        "phone_number": phone_number,
        "email": email,
        "location": location,
        "linkedin": linkedin,
        "github": github
    }

def extract_social_profiles(text):
    """Extract social profiles using AI if regex fails"""
    prompt = f"""
    Carefully extract LinkedIn and GitHub profiles from this resume text.
    Look for both URLs and mentions without URLs.
    
    Resume text:
    {text}
    
    Return a JSON object with only these keys:
    - "linkedin": The full LinkedIn URL if found, or "Mentioned but URL not found" if only the word LinkedIn appears
    - "github": The full GitHub URL if found, or "Mentioned but URL not found" if only the word GitHub appears
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You extract social media links from resume text with high precision."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
    
    try:
        clean_response = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        profiles = json.loads(clean_response)
        return profiles
    except:
        return None

def extract_name(text: str):
    """Extract candidate's name from resume"""
    # First try with heuristics (first few lines)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    potential_names = []
    
    for line in lines[:5]:  # Check only first 5 lines
        # A name usually has 2-4 words with proper capitalization
        if 2 <= len(line.split()) <= 4 and all(word[0].isupper() for word in line.split() if word):
            potential_names.append(line)
    
    if potential_names:
        return potential_names[0]
    
    # If heuristics fail, use AI to extract name
    prompt = f"""
    Extract ONLY the person's full name from this resume text.
    - Return ONLY the name (e.g., "John Doe")
    - If no name is found, return "Unknown"

    Resume text:
    {text[:1000]}  # First 1000 chars should include the name
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Extract only the name from text. No explanations."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=20  # Name should be short
    )

    name = response.choices[0].message.content.strip()
    
    # Clean up any extra text
    name = re.sub(r'name:?\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'the name is\s*', '', name, flags=re.IGNORECASE)
    
    return name if name and name.lower() != "unknown" else "Not Provided"

def extract_location(text: str):
    """Extract location information from resume"""
    # Try multiple regex patterns for location
    patterns = [
        # City, State/Province Format
        r'\b([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*),\s*([A-Z]{2}|[A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*)\b',
        # City, Country Format
        r'\b([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*),\s*([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*)\b',
    ]
    
    for pattern in patterns:
        location_match = re.search(pattern, text)
        if location_match:
            return location_match.group(0)
    
    # Try to match common city names
    common_cities = [
        "New York", "Los Angeles", "London", "Berlin", "Paris", "Tokyo", 
        "Toronto", "Sydney", "Singapore", "Dubai", "Mumbai", "Lagos",
        "Manchester", "Birmingham", "San Francisco", "Chicago", "Boston",
        "Seattle", "Austin", "Madrid", "Barcelona", "Rome", "Amsterdam",
        "Brussels", "Copenhagen", "Stockholm", "Oslo", "Zurich", "Geneva",
        "Vienna", "Warsaw", "Prague", "Budapest", "Athens", "Dublin"
    ]
    
    for city in common_cities:
        if re.search(rf'\b{re.escape(city)}\b', text, re.IGNORECASE):
            return city
    
    # Try to match country names
    for country in pycountry.countries:
        if re.search(rf'\b{re.escape(country.name)}\b', text, re.IGNORECASE):
            return country.name
    
    # Return default if nothing found
    return "Not Provided"

def structure_resume(text: str):
    """Structure raw resume text into organized JSON format"""
    prompt = f"""
    Structure this resume text into these sections:
    - Summary
    - Work Experience (including company, role, date range, accomplishments)
    - Technical Skills
    - Education (including institution, degree, graduation date)
    - Certifications
    - Projects
    
    Return as JSON with these exact keys. If a section isn't present, include the key with an empty value.
    
    Resume Text:
    {text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a resume parser that converts text to structured JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    # Try to parse the response as JSON
    try:
        structured_data = json.loads(response.choices[0].message.content.strip())
        return structured_data
    except json.JSONDecodeError:
        # Try to clean up the response by removing markdown and other formatting
        clean_response = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        try:
            return json.loads(clean_response)
        except:
            return {"error": "Failed to structure resume"}

def segment_resume_sections(text: str):
    """Identify and separate different sections of the resume"""
    # Common section headers in resumes
    section_patterns = [
        r'(?i)(?:^|\n)[\s]*(?:professional\s+)?summary[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*(?:career\s+)?objective[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*work\s+(?:experience|history)[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*professional\s+experience[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*employment(?:\s+history)?[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*education(?:al background)?[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*skills(?:\s+&\s+abilities)?[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*technical\s+skills[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*(?:key\s+)?competencies[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*(?:professional\s+)?certifications[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*projects[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*publications[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*awards(?:\s+(?:&|and)\s+honors)?[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*languages[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*interests[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*volunteer(?:\s+experience)?[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*additional\s+information[\s:]*(?:\n|$)',
        r'(?i)(?:^|\n)[\s]*references[\s:]*(?:\n|$)'
    ]
    
    # Use AI to identify sections
    prompt = f"""
    Identify all distinct sections in this resume and extract each section's content.
    
    For each section:
    1. Identify the section title (e.g., "Work Experience", "Skills", "Education")
    2. Extract the entire section's content
    
    Return as JSON with section titles as keys and section content as values.
    
    Resume:
    {text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a resume section extractor."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    # Try to parse the result
    try:
        sections = json.loads(response.choices[0].message.content)
        return sections
    except json.JSONDecodeError:
        # Clean and try again
        clean_response = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        try:
            return json.loads(clean_response)
        except:
            # Fall back to regex-based extraction
            sections = {}
            last_section_end = 0
            last_section_name = "Header"
            
            # Sort all matches by position
            matches = []
            for pattern in section_patterns:
                for match in re.finditer(pattern, text):
                    matches.append((match.start(), match.end(), match.group().strip()))
            
            matches.sort()
            
            # Extract sections
            for i, (start, end, section_name) in enumerate(matches):
                # Save previous section
                if i > 0:
                    previous_end = matches[i-1][1]
                    sections[last_section_name] = text[previous_end:start].strip()
                
                last_section_name = section_name.strip(':').strip()
                
                # Handle the last section
                if i == len(matches) - 1:
                    sections[last_section_name] = text[end:].strip()
            
            return sections or {"Full Resume": text}

def extract_skills_from_text(text: str):
    """Extract skills from text using AI"""
    prompt = f"""
    Extract ALL skills from this text. Include:
    - Technical skills (programming languages, tools, frameworks)
    - Soft skills (leadership, communication, etc.)
    - Domain knowledge (industries, methodologies)
    
    Return as a JSON array with no explanations.
    
    Text:
    {text}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Extract only skills as a JSON array. No explanations."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
    
    try:
        skills = json.loads(response.choices[0].message.content)
        return skills
    except json.JSONDecodeError:
        # Try to clean the response
        clean_content = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        try:
            return json.loads(clean_content)
        except:
            # Try to extract a list format like "- Skill1\n- Skill2"
            skills_list = re.findall(r'[-•*]\s*([^•\n]+)', response.choices[0].message.content)
            if skills_list:
                return [skill.strip() for skill in skills_list]
            return []

def extract_job_requirements(job_description: str):
    """Extract key requirements and skills from job description"""
    prompt = f"""
    Analyze this job description and extract:
    1. Required technical skills
    2. Preferred technical skills
    3. Required soft skills
    4. Experience level required
    5. Key responsibilities
    6. Required qualifications
    
    Return as JSON with these exact field names.
    
    Job Description:
    {job_description}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You extract job requirements into structured JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
    
    try:
        requirements = json.loads(response.choices[0].message.content)
        return requirements
    except json.JSONDecodeError:
        # Try to clean up the response
        clean_response = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        try:
            return json.loads(clean_response)
        except:
            return {"error": "Failed to parse job requirements"}

def similar_enough(skill1, skill2, threshold=0.7):
    """Check if two skills are similar enough using sequence matcher"""
    # Convert to lowercase for comparison
    s1 = skill1.lower()
    s2 = skill2.lower()
    
    # Direct substring match
    if s1 in s2 or s2 in s1:
        return True
        
    # Check similarity ratio
    similarity = SequenceMatcher(None, s1, s2).ratio()
    return similarity >= threshold

def score_resume(resume_data, job_description):
    """
    Enhanced resume scoring with detailed analysis
    
    Args:
        resume_data: Dictionary containing structured resume information
        job_description: String containing the job description
    
    Returns:
        Dictionary with score details
    """
    # Extract skills from both resume and job description
    resume_text = resume_data.get("raw_text", "")
    structured_resume = resume_data.get("structured_resume", {})
    
    # Use AI to do the scoring with structured data
    prompt = f"""
    Evaluate this resume against the job description using these scoring criteria:
    
    1. Skills Match (40%):
       - Technical skills alignment
       - Soft skills alignment
       - Experience level match
       - Domain knowledge
    
    2. Experience Relevance (30%):
       - Years of relevant experience
       - Similar role responsibilities
       - Industry alignment
       - Project relevance
    
    3. Education & Certifications (10%):
       - Required qualifications
       - Relevant certifications
       - Specialized training
    
    4. Additional Factors (20%):
       - Keyword match
       - Achievement metrics
       - Leadership experience
       - Location/arrangement compatibility
    
    Return JSON with:
    - "match_score": overall percentage (0-100)
    - "category_scores": detailed breakdown by category
    - "missing_skills": skills in job description not found in resume
    - "matched_skills": skills that appear in both
    - "key_matches": strongest matching points
    - "recommendations": specific improvements (3-5 items)
    
    Resume Data:
    {json.dumps(structured_resume, indent=2)}
    
    Full Resume Text:
    {resume_text[:3000]}  # Limit to first 3000 chars for token reasons
    
    Job Description:
    {job_description}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system", 
                "content": """You are an expert resume analyst that evaluates resumes against job descriptions.
                Be specific, accurate, and actionable in your feedback. Only return properly formatted JSON."""
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )
    
    try:
        # Extract and clean the response
        raw_response = response.choices[0].message.content.strip()
        clean_response = re.sub(r"```json\n|\n```", "", raw_response).strip()
        
        # Parse the JSON response
        score_data = json.loads(clean_response)
        
        # Validate the result
        if "match_score" not in score_data:
            score_data["match_score"] = 50  # Default score
            
        if "category_scores" not in score_data:
            score_data["category_scores"] = {
                "skills_match": 20,
                "experience_relevance": 15,
                "education_certifications": 7,
                "additional_factors": 8
            }
            
        if "recommendations" not in score_data:
            score_data["recommendations"] = ["Enhance resume with more specific skills and experience"]
            
        if "missing_skills" not in score_data:
            score_data["missing_skills"] = []
            
        if "matched_skills" not in score_data:
            score_data["matched_skills"] = []
        
        # Ensure scores are within bounds
        score_data["match_score"] = max(0, min(100, score_data["match_score"]))
        
        # Add timestamp for tracking
        from datetime import datetime
        score_data["timestamp"] = datetime.now().isoformat()
        
        return score_data
        
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {str(e)}")
        return {
            "error": "Failed to parse scoring response",
            "match_score": 50,  # Default score
            "recommendations": ["Try uploading a more detailed resume"],
            "missing_skills": [],
            "matched_skills": []
        }
    except Exception as e:
        print(f"Scoring Error: {str(e)}")
        return {
            "error": f"Scoring error: {str(e)}",
            "match_score": 50,  # Default score
            "recommendations": ["An error occurred during scoring. Please try again."]
        }

async def optimize_resume(file: UploadFile, job_description: str):
    """Optimize resume to better match job description"""
    # Extract resume text and structure
    resume_data = await extract_resume_text(file)
    
    if "error" in resume_data:
        return resume_data
        
    # Get job requirements
    job_requirements = extract_job_requirements(job_description)
    
    prompt = f"""
    Optimize this resume to match the job description. For each section:
    
    1. Summary: Rewrite to highlight relevant experience and skills for this job
    2. Work Experience: Enhance bullet points to emphasize relevant achievements
    3. Skills: Reorganize to prioritize skills mentioned in the job description
    
    Return the optimized resume as JSON with these sections:
    - summary
    - work_experience (array of positions with company, title, dates, bullets)
    - skills (object with technical_skills and soft_skills arrays) 
    - education (array with school, degree, dates)
    - certifications (array)
    - projects (array with title, description, technologies)
    
    Resume Data:
    {json.dumps(resume_data, indent=2)}
    
    Job Description:
    {job_description}
    
    Job Requirements:
    {json.dumps(job_requirements, indent=2)}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You optimize resumes to match job descriptions. Return structured JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )
    
    # Process the response
    try:
        optimized_resume = json.loads(response.choices[0].message.content)
        return optimized_resume
    except json.JSONDecodeError as e:
        # Try to clean up the response
        clean_response = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        try:
            return json.loads(clean_response)
        except:
            return {
                "error": "Failed to parse optimization response",
                "message": "The resume optimization service encountered an error. Please try again."
            }

def generate_interview_questions(job_description: str):
    """Generate custom interview questions based on job description"""
    prompt = f"""
    Create a set of interview questions for this job description:
    
    1. 5 technical questions that assess specific skills required
    2. 5 behavioral questions related to key responsibilities
    3. 3 situational questions to evaluate problem-solving for this role
    
    Return as JSON with these categories:
    - technical (array)
    - behavioral (array)
    - situational (array)
    
    Job Description:
    {job_description}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You create customized interview questions based on job descriptions."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    
    try:
        questions = json.loads(response.choices[0].message.content)
        return questions
    except json.JSONDecodeError:
        # Try to clean up the response
        clean_response = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        try:
            return json.loads(clean_response)
        except:
            return {"error": "Failed to parse interview questions"}