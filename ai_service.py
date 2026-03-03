from google import genai
import os
import json
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def safe_json_parse(text):
    try:
        return json.loads(text)
    except:
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
        except:
            return None


def generate_response(prompt):
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text


def detect_intent(user_message):
    prompt = f"""
    Classify the student's intent into ONE of:
    - skill_assessment
    - topic_exploration
    - certification_prep
    - research
    - course_completion

    Return ONLY valid JSON:
    {{
        "intent": ""
    }}

    Message:
    {user_message}
    """

    text = generate_response(prompt)
    return safe_json_parse(text)


def extract_missing_profile(user_message, missing_fields, existing_profile):
    prompt = f"""
    Student profile:
    {existing_profile}

    Extract ONLY these fields:
    {missing_fields}

    Return ONLY valid JSON.

    Message:
    {user_message}
    """

    text = generate_response(prompt)
    return safe_json_parse(text)


def generate_recommendation(profile_data):
    prompt = f"""
    Based on this student profile:

    {profile_data}

    Generate personalized recommendations.

    Return ONLY valid JSON:
    {{
        "recommended_courses": [
            {{
                "title": "",
                "difficulty": "",
                "priority": "",
                "estimated_time_weeks": ""
            }}
        ],
        "reasoning": ""
    }}
    """

    text = generate_response(prompt)
    return safe_json_parse(text)