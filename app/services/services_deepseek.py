import json
import os
import requests
from fastapi import UploadFile
from server.app.services.resume_service import extract_resume_text  # ✅ Import function for extracting resume text

# ✅ Load DeepSeek API Key
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# ✅ DeepSeek API Endpoint
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"

async def optimize_resume_deepseek(file: UploadFile, job_description: str):
    """
    Optimize resume using DeepSeek AI.
    :param file: Uploaded resume file (PDF/DOCX)
    :param job_description: Job description text
    :return: Optimized resume JSON
    """
    extracted_data = await extract_resume_text(file)

    if "error" in extracted_data:
        return extracted_data

    prompt = f"""
    Optimize the given resume to match the job description as closely as possible.

    ### **Instructions:**
    - Rewrite **summary, work experience, and skills** to align with the job description.
    - Optimize **contact details** to reflect a professional standard.
    - Fill in missing details based on the job requirements.
    - Use **strong action verbs** and **ATS-friendly formatting**.
    - Return only the **optimized structured resume** in JSON format.

    ### **Extracted Resume:**
    {json.dumps(extracted_data["structured_resume"], indent=2)}

    ### **Job Description:**
    {job_description}
    """

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a resume optimization assistant."},
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(DEEPSEEK_ENDPOINT, headers=headers, json=payload)

    # ✅ Debugging: Print and return raw response
    print("DeepSeek Raw Response:", response.text)

    try:
        deepseek_response = response.json()
        optimized_resume = deepseek_response["choices"][0]["message"]["content"]
        return json.loads(optimized_resume)  # ✅ Return structured JSON
    except (json.JSONDecodeError, KeyError):
        return {
            "error": "Failed to parse DeepSeek AI response",
            "raw_response": response.text  # ✅ Return raw response for debugging
        }
