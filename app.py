import json
import re
import os
import bcrypt
import jwt
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from database import (
    init_db, get_user_by_email, get_all_users,
    create_user, delete_user, toggle_user_active,
    update_password, upsert_admin,
    get_user_api_keys, save_api_key, delete_api_key,
    increment_generation_count, set_user_permanent, reset_user_trial,
)

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
JWT_SECRET   = os.getenv("JWT_SECRET", "viralforge-change-this-secret-in-render")
PORT         = int(os.getenv("PORT", 8080))
ADMIN_EMAIL  = os.getenv("ADMIN_EMAIL", "")
ADMIN_PASS   = os.getenv("ADMIN_PASSWORD", "")

app = FastAPI(title="ViralForge Pro")

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    init_db()
    if ADMIN_EMAIL and ADMIN_PASS:
        hashed = bcrypt.hashpw(ADMIN_PASS.encode(), bcrypt.gensalt()).decode()
        upsert_admin(ADMIN_EMAIL, hashed)
        print(f"  Admin ready: {ADMIN_EMAIL}")

# ── Auth helpers ──────────────────────────────────────────────────────────────
def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_pw(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def make_token(user_id: int, email: str, role: str, trial_expires_at=None) -> str:
    jwt_exp   = datetime.now(timezone.utc) + timedelta(days=7)
    trial_exp = None
    if trial_expires_at:
        try:
            trial_dt  = datetime.fromisoformat(str(trial_expires_at))
            if trial_dt.tzinfo is None:
                trial_dt = trial_dt.replace(tzinfo=timezone.utc)
            jwt_exp   = min(jwt_exp, trial_dt)
            trial_exp = int(trial_dt.timestamp())
        except Exception:
            pass
    payload = {
        "sub":   str(user_id),
        "email": email,
        "role":  role,
        "exp":   jwt_exp,
    }
    if trial_exp:
        payload["trial_exp"] = trial_exp
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

async def get_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return decode_token(auth.split(" ")[1])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

async def get_admin(request: Request) -> dict:
    user = await get_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def mask_key(k: str) -> str:
    if not k:
        return ""
    if len(k) <= 12:
        return k[:4] + "***"
    return k[:8] + "..." + k[-4:]

ALLOWED_PROVIDERS = {"groq", "openai", "anthropic", "elevenlabs"}

# ── Auth endpoints ────────────────────────────────────────────────────────────
@app.post("/auth/register")
async def register(request: Request):
    body     = await request.json()
    email    = body.get("email", "").lower().strip()
    password = body.get("password", "")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    trial_expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    success = create_user(email, hash_pw(password), "user", trial_expires_at)
    if not success:
        raise HTTPException(status_code=409, detail="That email is already registered")
    user  = get_user_by_email(email)
    token = make_token(user["id"], user["email"], user["role"], trial_expires_at)
    return {"token": token, "email": user["email"], "role": user["role"], "trial_expires_at": trial_expires_at}

@app.post("/auth/login")
async def login(request: Request):
    body     = await request.json()
    email    = body.get("email", "").lower().strip()
    password = body.get("password", "")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    user = get_user_by_email(email)
    if not user or not check_pw(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user["active"]:
        raise HTTPException(status_code=403, detail="Account is disabled")
    # Check trial expiry — delete account and block if expired
    trial_exp = user.get("trial_expires_at")
    if trial_exp:
        try:
            exp_dt = datetime.fromisoformat(str(trial_exp))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if exp_dt < datetime.now(timezone.utc):
                delete_user(user["id"])
                raise HTTPException(status_code=403, detail="Your 24-hour free trial has expired.")
        except HTTPException:
            raise
        except Exception:
            pass
    token   = make_token(user["id"], user["email"], user["role"], trial_exp)
    gen_info = {}
    if trial_exp:
        gen_info = {"gens_used": user.get("generation_count") or 0, "gens_limit": 10}
    return {"token": token, "email": user["email"], "role": user["role"], "trial_expires_at": trial_exp, **gen_info}

# ── Admin endpoints ───────────────────────────────────────────────────────────
@app.get("/admin/users")
async def admin_list_users(request: Request):
    await get_admin(request)
    return get_all_users()

@app.post("/admin/users")
async def admin_add_user(request: Request):
    await get_admin(request)
    body     = await request.json()
    email    = body.get("email", "").lower().strip()
    password = body.get("password", "")
    role     = body.get("role", "user")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    success = create_user(email, hash_pw(password), role)
    if not success:
        raise HTTPException(status_code=409, detail="Email already exists")
    return {"message": "User created"}

@app.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    me = await get_admin(request)
    user = get_user_by_email(me["email"])
    if user and user["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    delete_user(user_id)
    return {"message": "User deleted"}

@app.put("/admin/users/{user_id}/toggle")
async def admin_toggle_user(user_id: int, request: Request):
    me = await get_admin(request)
    user = get_user_by_email(me["email"])
    if user and user["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot disable yourself")
    toggle_user_active(user_id)
    return {"message": "User toggled"}

@app.put("/admin/users/{user_id}/password")
async def admin_reset_password(user_id: int, request: Request):
    await get_admin(request)
    body = await request.json()
    password = body.get("password", "")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    update_password(user_id, hash_pw(password))
    return {"message": "Password updated"}

@app.put("/admin/users/{user_id}/set-permanent")
async def admin_set_permanent(user_id: int, request: Request):
    await get_admin(request)
    set_user_permanent(user_id)
    return {"message": "User set to permanent"}

@app.put("/admin/users/{user_id}/reset-trial")
async def admin_reset_trial_ep(user_id: int, request: Request):
    await get_admin(request)
    reset_user_trial(user_id)
    return {"message": "Trial reset — 24h + 10 gens"}

# ── User API key endpoints ────────────────────────────────────────────────────
@app.get("/user/api-keys")
async def get_my_keys(request: Request):
    user = await get_user(request)
    keys = get_user_api_keys(int(user["sub"]))
    return {p: {"saved": True, "masked": mask_key(k)} for p, k in keys.items()}

@app.put("/user/api-keys")
async def save_my_key(request: Request):
    user = await get_user(request)
    body     = await request.json()
    provider = body.get("provider", "").lower().strip()
    api_key  = body.get("api_key", "").strip()
    if not provider or not api_key:
        raise HTTPException(status_code=400, detail="provider and api_key required")
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    save_api_key(int(user["sub"]), provider, api_key)
    return {"message": "Key saved", "masked": mask_key(api_key)}

@app.delete("/user/api-keys/{provider}")
async def delete_my_key(provider: str, request: Request):
    user = await get_user(request)
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown provider")
    delete_api_key(int(user["sub"]), provider)
    return {"message": "Key removed"}

# ── AI prompts ────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an elite YouTube growth strategist, behavioral psychologist, viral content architect, dopamine-based storyteller, retention editor, and audience addiction specialist.

CORE FORMULA: PAIN + HOPE + PROOF + CURIOSITY + ASPIRATION + FOMO
The trigger fires when PAIN + HOPE + PROOF align simultaneously.

EMOTIONAL POWER RANKING (strongest to weakest):
1. Hope — people act for what they WANT
2. Social Proof — others succeeded, so it works
3. Aspiration — identity transformation
4. FOMO — urgency + scarcity
5. Technical Education — weakest alone

MANDATE: Engineer emotional addiction. Lead with emotion, never information.
Think: Netflix + MrBeast + TikTok psychology + cinematic documentary.
Re-engage viewers every 3–7 seconds. Make them feel incomplete without the next video.

Return ONLY valid JSON matching the schema you are given. No markdown. No extra text."""

PLATFORM_NOTES = {
    "YouTube Long Form": "Long-form video. Deep storytelling. Full emotional arc. All sections apply.",
    "YouTube Shorts":    "Under 60 seconds. Instant hook. No intros. Pure dopamine. Fast cuts.",
    "Instagram Reel":    "Under 90 seconds. Hook in 1 second. Vertical. Aesthetic-first. Trend-aware.",
    "TikTok":            "Under 3 minutes. Native TikTok energy. Sound-first. Pattern interrupt every 5s.",
    "Commercial Ad":     "Paid advertisement. Every second costs money. Pain in 2s. Solution in 3s. Strong purchase/signup CTA at end. NO subscribe/like/comment language — this is a sales conversion ad.",
}

VIDEO_LENGTH_WORD_COUNTS = {
    "60 seconds": 130,
    "3 minutes":  390,
    "5 minutes":  650,
    "8 minutes": 1040,
    "10 minutes": 1300,
    "15 minutes": 1950,
    "20+ minutes": 2600,
}


def build_prompt(niche, audience, platform, emotion, topic, ad_length, video_length, language="English"):
    platform_note = PLATFORM_NOTES.get(platform, "")
    ad_note       = f"Ad length: {ad_length}." if ad_length else ""
    word_count    = VIDEO_LENGTH_WORD_COUNTS.get(video_length, 650)
    script_note   = f"The full_complete_script must be approximately {word_count} words — enough for a real {video_length} video."
    language_note = f"OUTPUT LANGUAGE: Write ALL content — titles, scripts, copy, hooks, CTAs, descriptions — in {language}. Adapt cultural references, idioms, humor, and emotional triggers to resonate authentically with native {language} speakers."

    commercial_override = ""
    if platform == "Commercial Ad":
        commercial_override = f"""
AD MODE — OVERRIDE RULES (apply to ALL sections):
- This is a PAID ADVERTISEMENT, not a YouTube video. NEVER use subscribe/like/follow/comment language.
- Every section must serve ONE goal: conversion (purchase, sign-up, booking, free trial, etc.)
- section7_voiceover.full_complete_script = complete word-for-word {ad_length} AD PRODUCTION SCRIPT with [SCENE], [VO], [ON SCREEN], [CTA] markers. Written exactly as an agency-ready production script.
- section10_comment_triggers → rewrite as 3 conversion CTAs (urgency, social proof, offer-based)
- section11_binge_strategy → rewrite as retargeting + ad sequencing strategy (cold → warm → hot audience)
- section12_shorts_strategy → rewrite as ad format variations (static image, carousel, story, reel versions)
- All hooks end with desire or curiosity, not "subscribe for more"
- Closing CTA must be specific and urgent: include an offer, deadline, or scarcity element
"""

    instagram_section = ""
    if platform == "Commercial Ad":
        instagram_section = f"""  "instagram_ad_creative": {{
    "ad_headline": "Short punchy headline (max 40 chars) — lead with pain or desire, no filler words",
    "primary_text": "Ad copy appearing above the creative — open with pain in 1 sentence, follow with hope or benefit, close with urgency or social proof. First 125 chars must hook instantly.",
    "cta_button": "Exact CTA button label — e.g. Learn More, Shop Now, Sign Up, Get Offer, Book Now",
    "hook_line": "First 3-second spoken line for this {ad_length} video ad — pattern interrupt, no greeting, instant pain or curiosity",
    "visual_concept": "What the ad creative shows — scene, subject, emotion, and composition that stops the scroll in 2 seconds",
    "image_prompt": "DALL-E 3 or Midjourney prompt for the ad creative — photorealistic or cinematic, 4:5 ratio (1080x1350), describe subject, emotion, colors, lighting, and mood in full detail",
    "story_format": "How to adapt for Instagram Story (9:16, 1080x1920) — headline position, text safe zones, and visual adjustments",
    "caption": "Full Instagram caption for a boosted organic post — hook opener, pain+solution body, soft CTA, 8-10 niche hashtags",
    "targeting_notes": "Meta Ads targeting — 3-5 interest categories, demographics, behaviors, and lookalike audience strategy for this niche and audience"
  }},

"""

    return f"""Generate a COMPLETE viral content system for:

PLATFORM: {platform} — {platform_note} {ad_note}
VIDEO LENGTH: {video_length}
NICHE: {niche}
TARGET AUDIENCE: {audience}
LEAD EMOTION: {emotion}
SPECIFIC TOPIC: {topic or "Choose the most viral angle for this niche"}
{language_note}
{commercial_override}
{script_note}

Return this EXACT JSON (all fields required, be specific and detailed for this niche):

{{
  "platform": "{platform}",
  "niche": "{niche}",
  "video_length": "{video_length}",

  "section1_foundation": {{
    "positioning": "One sentence channel identity",
    "unique_angle": "What makes this channel unlike all others",
    "emotional_promise": "What emotional transformation viewers get",
    "viewer_identity": "Who the viewer sees themselves as after watching",
    "content_pillars": ["pillar1", "pillar2", "pillar3"],
    "why_they_return": "Psychological reason for repeat visits",
    "ecosystem_strategy": "How content pieces connect and feed each other"
  }},

  "section2_psychology": {{
    "deep_fears": ["specific fear 1", "specific fear 2", "specific fear 3"],
    "secret_desires": ["desire 1", "desire 2", "desire 3"],
    "aspirations": ["aspiration 1", "aspiration 2"],
    "fomo_triggers": ["trigger 1", "trigger 2", "trigger 3"],
    "late_night_thoughts": ["thought 1", "thought 2"],
    "why_they_click": "Exact psychological reason",
    "why_they_stay": "Exact retention mechanism",
    "why_they_subscribe": "Identity/tribal reason",
    "binge_trigger": "What makes them watch 5 videos in a row"
  }},

  "section3_video_ideas": [
    {{
      "title": "Viral title",
      "pain_point": "Specific pain this addresses",
      "hope_element": "Transformation promised",
      "proof_hook": "Social proof or stat used",
      "primary_emotion": "Hope|FOMO|Aspiration|Social Proof|Fear",
      "curiosity_angle": "The mystery or gap that hooks them",
      "why_viral": "Why this specific combination spreads"
    }},
    {{
      "title": "Viral title 2",
      "pain_point": "Pain",
      "hope_element": "Hope",
      "proof_hook": "Proof",
      "primary_emotion": "Hope|FOMO|Aspiration|Social Proof|Fear",
      "curiosity_angle": "Curiosity",
      "why_viral": "Why viral"
    }},
    {{
      "title": "Viral title 3",
      "pain_point": "Pain",
      "hope_element": "Hope",
      "proof_hook": "Proof",
      "primary_emotion": "Hope|FOMO|Aspiration|Social Proof|Fear",
      "curiosity_angle": "Curiosity",
      "why_viral": "Why viral"
    }}
  ],

  "section4_titles": [
    "Title 1 — ultra-clickable, emotional, specific",
    "Title 2",
    "Title 3",
    "Title 4",
    "Title 5"
  ],

  "section5_thumbnails": [
    {{
      "concept": "Overall visual description",
      "text_overlay": "Bold text shown on thumbnail",
      "colors": "Specific color palette and why",
      "visual_elements": "What objects/faces/scenes appear",
      "hierarchy": "Where eye travels first, second, third",
      "psychology": "Why this stops the scroll"
    }},
    {{
      "concept": "Alternative concept",
      "text_overlay": "Bold text",
      "colors": "Color palette",
      "visual_elements": "Visual elements",
      "hierarchy": "Eye path",
      "psychology": "Stop-scroll reason"
    }}
  ],

  "thumbnail_ai_prompt": {{
    "midjourney": "Full ready-to-use /imagine prompt for a YouTube thumbnail for this specific video — ultra-detailed, photorealistic or cinematic style, include color, mood, subject, text hint, and --ar 16:9 --v 6.1",
    "dalle": "Full DALL-E 3 prompt for the same thumbnail — describe the scene, colors, text overlay area, mood, and style",
    "chatgpt": "Natural language ChatGPT image prompt (DALL-E 3 via ChatGPT) — write it conversationally as if asking ChatGPT to create the thumbnail. Describe subject, emotion, colors, composition, text to include, and desired mood in plain sentences",
    "ideogram": "Full Ideogram prompt optimized for text-heavy thumbnail with readable bold typography",
    "style_guide": "Visual style guide for the thumbnail: color palette hex codes, fonts, mood, what to avoid"
  }},

  "section6_structure": {{
    "hook_0_5s": "Exact words/visuals for the first 5 seconds",
    "open_curiosity_loop": "The unresolved question planted at start",
    "tension_escalation": "How tension builds through the video",
    "story_progression": "3-act structure outline",
    "social_proof_moment": "Where and how proof is delivered",
    "mid_reward": "What the viewer gets at the halfway point",
    "pattern_interrupt": "Unexpected moment that resets attention",
    "cliffhanger": "The unresolved tension before the end",
    "addictive_ending": "How the ending plants the next video hook",
    "reengagement_points": ["moment at 20s", "moment at 1min", "moment at 3min"]
  }},

  "section7_voiceover": {{
    "intro_hook": "Word-for-word opening 15 seconds — pattern interrupt, no intro",
    "act1_setup": "Pain establishment — spoken script sample (2-3 sentences)",
    "act2_escalation": "Hope + tension — spoken script sample (2-3 sentences)",
    "act3_payoff": "Proof + resolution — spoken script sample (2-3 sentences)",
    "outro_loop": "Exact words to hook them to the next video",
    "full_complete_script": "THE COMPLETE WORD-FOR-WORD SCRIPT FROM START TO FINISH. Use scene markers like [INTRO - 0:00], [ACT 1 - 0:30], [HOOK CALLBACK - mid], [OUTRO]. Write every single word a voiceover artist would speak. No placeholders. Real, specific content for this niche and topic. Approximately {word_count} words total. Make it cinematic, emotional, and retention-engineered."
  }},

  "section8_editing": {{
    "overall_pacing": "Cut timing and rhythm description",
    "sound_effects": "Specific SFX for specific moments",
    "music_guide": "Genre, energy level, when to swell, when to drop",
    "subtitle_style": "Font, size, position, animation style",
    "transitions": "Which transitions and when to use them",
    "pattern_breaks": "Exact moments to add visual interruptions",
    "slow_moments": "When to slow down and why",
    "fast_moments": "When to speed up and why",
    "cinematic_effects": "Color grading, overlays, effects",
    "ai_visuals": "What AI-generated visuals to use and when"
  }},

  "section9_storyboard": [
    {{ "scene": 1, "timestamp": "0:00-0:05", "visual": "Detailed visual", "text_on_screen": "Text overlay", "voiceover": "Spoken words", "audio": "Audio direction", "edit_note": "Edit instruction" }},
    {{ "scene": 2, "timestamp": "0:05-0:20", "visual": "Visual", "text_on_screen": "Text", "voiceover": "Spoken", "audio": "Audio", "edit_note": "Edit" }},
    {{ "scene": 3, "timestamp": "0:20-0:45", "visual": "Visual", "text_on_screen": "Text", "voiceover": "Spoken", "audio": "Audio", "edit_note": "Edit" }},
    {{ "scene": 4, "timestamp": "0:45-1:30", "visual": "Visual", "text_on_screen": "Text", "voiceover": "Spoken", "audio": "Audio", "edit_note": "Edit" }},
    {{ "scene": 5, "timestamp": "1:30-3:00", "visual": "Visual", "text_on_screen": "Text", "voiceover": "Spoken", "audio": "Audio", "edit_note": "Edit" }},
    {{ "scene": 6, "timestamp": "3:00-end",  "visual": "Visual", "text_on_screen": "Text", "voiceover": "Spoken", "audio": "Audio", "edit_note": "Edit" }}
  ],

  "section10_comment_triggers": [
    {{ "cta": "Exact CTA to say in video", "psychology": "Why this works", "expected_response": "What comments you get" }},
    {{ "cta": "Second CTA", "psychology": "Psychology", "expected_response": "Expected comments" }},
    {{ "cta": "Third CTA", "psychology": "Psychology", "expected_response": "Expected comments" }}
  ],

  "section11_binge_strategy": {{
    "series_architecture": "How to structure a series around this niche",
    "open_loops": "Narrative threads left unresolved across videos",
    "next_video_hook": "Exact teaser line for the next video",
    "emotional_continuity": "How to make each video feel part of something bigger",
    "recurring_themes": "Characters, phrases, or motifs that create loyalty"
  }},

  "section12_shorts_strategy": {{
    "how_shorts_feed_longform": "Exact funnel strategy",
    "short_hooks": ["Hook 1", "Hook 2", "Hook 3"],
    "pacing_differences": "How Short pacing differs from Long Form",
    "retention_tactics": "Specific Short retention techniques"
  }},

  "section13_ai_tools": [
    {{"category": "Script Writing",    "best_free": "tool", "best_paid": "tool", "tip": "usage tip"}},
    {{"category": "Voice Generation",  "best_free": "tool", "best_paid": "tool", "tip": "usage tip"}},
    {{"category": "AI Visuals/B-Roll", "best_free": "tool", "best_paid": "tool", "tip": "usage tip"}},
    {{"category": "Video Editing",     "best_free": "tool", "best_paid": "tool", "tip": "usage tip"}},
    {{"category": "Thumbnails",        "best_free": "tool", "best_paid": "tool", "tip": "usage tip"}},
    {{"category": "Research & Trends", "best_free": "tool", "best_paid": "tool", "tip": "usage tip"}}
  ],

  "section14_multiplication": {{
    "core_angle": "The single most viral angle",
    "shorts": ["Short 1", "Short 2", "Short 3", "Short 4", "Short 5"],
    "instagram_reel": "How to adapt for Instagram",
    "tiktok": "How to adapt for TikTok",
    "twitter_thread": "Thread hook + 3 tweet outline",
    "community_post": "YouTube community post text",
    "email_hook": "Email subject line + first sentence"
  }},

{instagram_section}  "section15_master_formula": "The reusable 1-paragraph formula for this niche combining Pain+Hope+Proof+Curiosity+Aspiration+FOMO into a repeatable viral system"
}}"""


# ── Models ────────────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    niche:           str
    audience:        str
    platform:        str   = "YouTube Long Form"
    emotional_focus: str   = "Hope"
    video_length:    str   = "8 minutes"
    topic:           Optional[str] = None
    ad_length:       Optional[str] = None
    language:        str   = "English"
    api_provider:    str   = "groq"
    model:           str   = "llama-3.3-70b-versatile"


def parse_json(content: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            return json.loads(match.group())
        raise ValueError("Could not parse JSON from model response")


async def call_groq(prompt: str, model: str, api_key: str) -> str:
    key = api_key or GROQ_API_KEY
    if not key:
        raise HTTPException(status_code=503, detail="No API key configured. Admin: add GROQ_API_KEY in Render environment.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 8192,
        "temperature": 0.82,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(GROQ_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def call_ollama(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.82, "top_p": 0.9, "num_predict": 8192},
    }
    async with httpx.AsyncClient(timeout=240.0) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse("static/landing.html")

@app.get("/app")
async def app_page():
    return FileResponse("static/index.html")


@app.get("/api/models")
async def get_models():
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            data = resp.json()
            return {"status": "connected", "models": [m["name"] for m in data.get("models", [])]}
    except Exception as e:
        return {"status": "disconnected", "models": [], "error": str(e)}


@app.post("/api/generate")
async def generate(request: Request):
    user     = await get_user(request)
    body     = await request.json()
    api_key  = body.pop("api_key", "").strip()
    req      = GenerateRequest(**{k: v for k, v in body.items() if k in GenerateRequest.model_fields})

    # Generation limit: free/trial users max 10
    is_free_user = False
    gen_count    = 0
    try:
        if user.get("role") != "admin":
            db_user = get_user_by_email(user["email"])
            if db_user and db_user.get("trial_expires_at"):
                is_free_user = True
                gen_count    = db_user.get("generation_count") or 0
                if gen_count >= 10:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Generation limit reached ({gen_count}/10). Contact the admin to upgrade your account."
                    )
    except HTTPException:
        raise
    except Exception:
        pass  # DB lookup failure doesn't block generation

    # Key priority: request body → user's saved DB key → server GROQ_API_KEY env var
    if not api_key:
        try:
            saved   = get_user_api_keys(int(user["sub"]))
            api_key = saved.get(req.api_provider, "") or ""
        except Exception:
            api_key = ""
    if not api_key:
        api_key = GROQ_API_KEY  # admin's server-level key used for all users

    prompt = build_prompt(
        niche        = req.niche,
        audience     = req.audience,
        platform     = req.platform,
        emotion      = req.emotional_focus,
        topic        = req.topic or "",
        ad_length    = req.ad_length or "",
        video_length = req.video_length,
        language     = req.language,
    )

    try:
        if req.api_provider == "groq":
            raw = await call_groq(prompt, req.model, api_key)
        else:
            raw = await call_ollama(prompt, req.model)
        data = parse_json(raw)
        # Increment count for free users after successful generation
        if is_free_user:
            try:
                increment_generation_count(int(user["sub"]))
                gen_count += 1
            except Exception:
                pass
        extra = {"gens_used": gen_count, "gens_limit": 10} if is_free_user else {}
        return {"result": data, "platform": req.platform, **extra}
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot connect. Check API settings.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"API error: {e.response.text}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    print(f"\n  ViralForge Pro → http://localhost:{PORT}\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
