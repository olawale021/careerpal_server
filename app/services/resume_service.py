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
from datetime import datetime

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
    segments = resume_data.get("segments", {})
    
    # First, extract and analyze the candidate's actual skills and experience
    # to prepare for alternative position recommendations independent of job description
    candidate_skills = []
    candidate_experience = []
    candidate_roles = []
    
    # Extract skills information safely
    skills_info = ""
    for key in ["Skills", "Technical Skills", "Areas of Expertise", "Additional Skills"]:
        segment = segments.get(key, "")
        if isinstance(segment, str):
            skills_info += segment + "\n\n"
            # Extract individual skills from these sections
            for line in segment.split('\n'):
                if line.strip() and len(line.strip()) > 3:  # Avoid empty lines and short items
                    candidate_skills.append(line.strip())
    
    # Extract experience information safely
    experience_info = ""
    for key in ["Professional Experience", "Experience", "Work Experience"]:
        segment = segments.get(key, "")
        if isinstance(segment, str):
            experience_info += segment + "\n\n"
            # Extract job titles and experience details
            lines = segment.split('\n')
            for i, line in enumerate(lines):
                # Look for job titles/roles (often at the beginning of sections or containing key terms)
                if any(title in line.lower() for title in ["manager", "director", "specialist", "engineer",
                                                        "developer", "analyst", "coordinator", "assistant",
                                                        "designer", "consultant", "lead", "head", "chief"]):
                    candidate_roles.append(line.strip())
                # Add 2-3 lines after a role as experience details
                if i > 0 and lines[i-1].strip() in candidate_roles and line.strip():
                    candidate_experience.append(line.strip())
    
    # Extract summary safely
    summary = ""
    for key in ["Summary", "Professional Summary", "Profile"]:
        segment = segments.get(key, "")
        if isinstance(segment, str):
            summary += segment + "\n"
    
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
    - "alternative_positions": [CRITICAL] For low match scores, suggest 2-3 positions based ONLY on the candidate's skills and experience from their resume. IGNORE the job description completely when suggesting alternative positions. Focus on what this person is qualified to do based on their skills, not what they're missing for this particular job.
    
    Resume Summary:
    {summary}
    
    Candidate Experience:
    {experience_info}
    
    Candidate Skills:
    {skills_info}
    
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
                Be specific, accurate, and actionable in your feedback.
                
                CRITICAL INSTRUCTIONS FOR ALTERNATIVE POSITIONS:
                
                When suggesting alternative positions for low-scoring matches:
                1. Look ONLY at the candidate's skills and experience from their RESUME
                2. COMPLETELY IGNORE the job description when suggesting alternative positions
                3. Suggest jobs they ARE qualified for based on their resume, not jobs they COULD be qualified for
                4. Base recommendations on their strongest demonstrated skills and most recent roles
                5. Match the seniority level of their previous roles
                6. Focus on their actual expertise, not what they're missing for the current job
                7. YOU MUST PROVIDE AT LEAST 2 SPECIFIC JOB TITLES they are qualified for
                
                Example - For a resume showing software development experience:
                - DO suggest: "Software Engineer", "Full Stack Developer", "Application Developer"
                - DON'T suggest: Care Assistant, Healthcare roles (unless their resume shows this experience)
                
                Example - For a resume showing teaching experience:
                - DO suggest: "Curriculum Developer", "Education Consultant", "Academic Coordinator"
                - DON'T suggest: Marketing Manager, Sales roles (unless their resume shows this experience)
                
                Only return properly formatted JSON with complete fields."""
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
        
        # For low scores, add recommendation for alternative positions
        if score_data["match_score"] < 40:
            # Get alternative positions from the model
            alternative_positions = score_data.get("alternative_positions", [])
            
            # If no positions provided, generate defaults based on resume data only
            if not alternative_positions or len(alternative_positions) == 0:
                # Use extracted candidate roles if available
                if candidate_roles:
                    # Select the most promising roles based on candidate's skills
                    alternative_positions = candidate_roles[:2]
                else:
                    # Generate positions based on extracted skills
                    skills_text = " ".join(candidate_skills).lower()
                    
                    if any(tech in skills_text for tech in ["programming", "software", "developer", "java", "python", "javascript", "code"]):
                        alternative_positions = ["Software Developer", "Application Engineer"]
                    elif any(design in skills_text for design in ["design", "photoshop", "illustrator", "ui", "ux"]):
                        alternative_positions = ["Graphic Designer", "UX/UI Designer"]
                    elif any(teach in skills_text for teach in ["teach", "education", "curriculum", "instruction", "classroom"]):
                        alternative_positions = ["Educational Consultant", "Curriculum Developer"]
                    elif any(care in skills_text for care in ["care", "nurse", "patient", "health", "medical"]):
                        alternative_positions = ["Healthcare Specialist", "Patient Care Coordinator"]
                    elif any(market in skills_text for market in ["marketing", "social media", "branding", "content"]):
                        alternative_positions = ["Marketing Specialist", "Digital Marketing Coordinator"]
                    elif any(manage in skills_text for manage in ["manage", "leadership", "strategy", "team", "director"]):
                        alternative_positions = ["Project Manager", "Team Lead"]
                    else:
                        # Fallback based on general resume text
                        if "software" in resume_text.lower() or "developer" in resume_text.lower():
                            alternative_positions = ["Software Developer", "Application Engineer"]
                        elif "marketing" in resume_text.lower():
                            alternative_positions = ["Marketing Specialist", "Digital Marketing Coordinator"]
                        elif "teach" in resume_text.lower() or "education" in resume_text.lower():
                            alternative_positions = ["Educational Consultant", "Curriculum Developer"]
                        elif "care" in resume_text.lower() or "health" in resume_text.lower():
                            alternative_positions = ["Healthcare Specialist", "Patient Care Coordinator"]
                        else:
                            alternative_positions = ["Professional aligned with your skills", "Specialist in your field"]
            
            # Add the positions to the recommendations
            position_list = ", ".join(alternative_positions)
            score_data["recommendations"].insert(0, 
                f"Consider applying for positions that better match your experience, such as: {position_list}")
            
            # Ensure alternative_positions is in the response
            score_data["alternative_positions"] = alternative_positions
        
        # Add timestamp for tracking
        score_data["timestamp"] = datetime.now().isoformat()
        
        return score_data
        
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {str(e)}")
        return {
            "error": "Failed to parse scoring response",
            "match_score": 50,  # Default score
            "recommendations": ["Try uploading a more detailed resume"],
            "missing_skills": [],
            "matched_skills": [],
            "alternative_positions": ["Professional aligned with your skills", "Specialist in your field"]
        }
    except Exception as e:
        print(f"Scoring Error: {str(e)}")
        return {
            "error": f"Scoring error: {str(e)}",
            "match_score": 50,  # Default score
            "recommendations": ["An error occurred during scoring. Please try again."],
            "alternative_positions": ["Professional aligned with your skills", "Specialist in your field"]
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

async def create_tailored_resume_content(resume_data, job_description):
    """
    Create a tailored resume that better matches the job description
    when the original resume's match score is low.
    
    Args:
        resume_data: Dictionary containing parsed resume information
        job_description: String containing the job description
        
    Returns:
        Dictionary with tailored resume content optimized for the job
    """
    # Extract structured info from the resume
    structured_resume = resume_data.get("structured_resume", {})
    contact_details = resume_data.get("contact_details", {})
    
    # Extract job requirements for better tailoring
    job_requirements = extract_job_requirements(job_description)
    
    # Extract education to keep it unchanged - fix education extraction
    original_education = structured_resume.get("education", structured_resume.get("Education", []))
    
    # Extract key job-related terms for better matching
    job_keywords = extract_key_job_terms(job_description)
    
    prompt = f"""
    The user's resume scored below 40% match for this job description.
    Create a highly optimized resume specifically tailored for this job,
    with enhanced skills and work experience that would make the candidate
    an excellent match for the position.
    
    PRECISE INSTRUCTIONS FOR EACH SECTION:
    
    1. SUMMARY/PROFILE:
       Write a compelling 3-4 sentence professional summary that:
       - Presents the candidate as highly qualified for this exact role
       - Highlights 3-4 key skills that directly match the job requirements
       - Includes years of relevant experience appropriate for this position
       - Shows enthusiasm and career alignment with this specific position
    
    2. SKILLS (create comprehensive bullet-point lists):
       a) Technical Skills:
          - IMPORTANT: Always include a well-populated list of technical skills
          - Generate a complete list of technical skills NECESSARY for this job
          - Include software, tools, platforms, and methodologies required
          - Ensure all technical keywords from the job description are included
          - If the job requires non-technical roles, list relevant procedural skills here
       
       b) Soft Skills:
          - List interpersonal and professional skills essential for success in this role
          - Include leadership, communication, or team skills mentioned in the job posting
          - Add relevant traits like problem-solving, adaptability, attention to detail
       
       c) Industry Knowledge:
          - Include domain-specific knowledge relevant to the industry
          - Add awareness of regulations, best practices, or methodologies
    
    3. WORK EXPERIENCE:
       Keep the original job titles, companies, and dates, but:
       - Create 5-6 ENTIRELY NEW achievement-focused bullet points for each position
       - Begin each with a STRONG ACTION VERB appropriate for the industry
       - Structure bullets as: ACTION + JOB-RELEVANT TASK + IMPRESSIVE RESULT
       - Include specific metrics and quantifiable achievements (%, $, efficiency)
       - DIRECTLY incorporate keywords and requirements from the job description
       - Make each bullet point DIRECTLY relevant to the target job skills and duties
       - EVERY bullet point must demonstrate skills required in THIS SPECIFIC POSITION
    
    4. EDUCATION:
       - KEEP COMPLETELY UNCHANGED from the original resume
    
    5. CERTIFICATIONS & LICENSES:
       - Include certifications that would be valuable for this specific position
    
    DESIRED OUTPUT FORMAT:
    Return a JSON object with these fields:
    - contact_details (keep original exactly as provided)
    - summary (new compelling summary specific to this job)
    - skills (object with categories: technical_skills, soft_skills, industry_knowledge)
    - work_experience (array of positions with company, title, dates, and achievements array)
    - education (EXACTLY as provided in original resume)
    - certifications (relevant to job)
    
    Original Resume Structure (use same format but enhance content):
    {json.dumps(structured_resume, indent=2)}
    
    Contact Details:
    {json.dumps(contact_details, indent=2)}
    
    Job Description:
    {job_description}
    
    Key Job Keywords:
    {job_keywords}
    
    Job Requirements:
    {json.dumps(job_requirements, indent=2)}
    """
    
    # Use GPT-4o-mini for cost savings with improved prompt precision
    response = client.chat.completions.create(
        model="gpt-4o-mini",  # Using smaller model to save costs
        messages=[
            {
                "role": "system", 
                "content": """You are an expert in creating optimized resumes that perfectly match job requirements. Your specialty is enhancing resumes with relevant skills and accomplishments that make candidates appear highly qualified for specific positions. You know exactly what recruiters and ATS systems look for in each industry. You generate powerful bullet points that incorporate job keywords and showcase relevant capabilities. Return only properly formatted JSON with the exact structure requested. You ALWAYS ensure technical_skills array is populated even for non-technical roles."""
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,  # Slightly higher temperature for more creative responses
        response_format={"type": "json_object"}  # Ensure proper JSON
    )
    
    try:
        # Parse the response
        tailored_resume = json.loads(response.choices[0].message.content)
        
        # Handle education properly - first check original format in the resume
        if original_education:
            # If education exists, use it
            tailored_resume["education"] = original_education
        elif "Education" in structured_resume and isinstance(structured_resume["Education"], dict):
            # If education is in a different format (dict), convert it to expected format
            edu_dict = structured_resume["Education"]
            tailored_resume["education"] = [{
                "institution": edu_dict.get("institution", ""),
                "degree": edu_dict.get("degree", ""),
                "graduation_date": edu_dict.get("graduation_date", "")
            }]
        
        # Ensure skills are properly formatted as bullet points
        if "skills" in tailored_resume:
            # Ensure technical_skills is never empty
            if "technical_skills" not in tailored_resume["skills"] or not tailored_resume["skills"]["technical_skills"]:
                # If technical skills are empty, add job-specific technical skills
                tailored_resume["skills"]["technical_skills"] = [
                    "Job-specific procedures",
                    "Documentation techniques",
                    "Record keeping",
                    "Quality assurance protocols"
                ]
            
            for category in tailored_resume["skills"]:
                if isinstance(tailored_resume["skills"][category], list):
                    # Make sure each skill is properly formatted as a bullet point
                    tailored_resume["skills"][category] = [
                        skill.strip().replace("- ", "") if skill.startswith("- ") else skill.strip()
                        for skill in tailored_resume["skills"][category]
                    ]
        
        # Ensure work experience bullet points are properly formatted
        if "work_experience" in tailored_resume and isinstance(tailored_resume["work_experience"], list):
            for i, job in enumerate(tailored_resume["work_experience"]):
                if "achievements" in job and isinstance(job["achievements"], list):
                    # Clean up bullet points
                    tailored_resume["work_experience"][i]["achievements"] = [
                        achievement.strip().replace("- ", "") if achievement.startswith("- ") else achievement.strip()
                        for achievement in job["achievements"]
                    ]
                    
                    # Ensure each bullet point contains job-specific keywords
                    if job_keywords and len(job_keywords) > 0:
                        # Check if any bullet points contain job keywords
                        has_keywords = any(any(kw.lower() in achievement.lower() for kw in job_keywords) 
                                          for achievement in tailored_resume["work_experience"][i]["achievements"])
                        
                        # If no keywords found, add a relevant bullet point
                        if not has_keywords and len(tailored_resume["work_experience"][i]["achievements"]) > 0:
                            # Add a job-specific bullet point with keywords
                            tailored_resume["work_experience"][i]["achievements"].append(
                                f"Utilized {job_keywords[0]} skills to enhance overall performance and deliver exceptional results"
                            )
        
        # Add metadata
        tailored_resume["created_at"] = datetime.now().isoformat()
        tailored_resume["original_score"] = "Below 40%"
        tailored_resume["is_tailored"] = True
        
        return tailored_resume
        
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {str(e)}")
        # Try to clean up the response
        clean_response = re.sub(r"```json\n|\n```", "", response.choices[0].message.content.strip())
        try:
            return json.loads(clean_response)
        except:
            return {
                "error": "Failed to generate tailored resume",
                "message": "The system encountered an error while creating your tailored resume."
            }
    except Exception as e:
        print(f"Tailoring Error: {str(e)}")
        return {
            "error": f"Resume tailoring error: {str(e)}",
            "message": "An error occurred during resume tailoring. Please try again."
        }

def extract_key_job_terms(job_description):
    """
    Extract key terms from the job description to help with matching.
    
    Args:
        job_description: String containing the job description
        
    Returns:
        List of key terms relevant to the job
    """
    # Use GPT to extract the most important terms from the job description
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",  # Using cheaper model for this simpler task
        messages=[
            {
                "role": "system", 
                "content": "Extract the 15-20 most important skills, qualifications, and requirements from this job description. Return as a comma-separated list of keywords and phrases. Focus on both technical requirements and soft skills."
            },
            {"role": "user", "content": job_description}
        ],
        max_tokens=150,
        temperature=0.1
    )
    
    # Extract and clean the keywords
    keyword_text = response.choices[0].message.content
    keywords = [kw.strip() for kw in keyword_text.split(',')]
    
    return keywords