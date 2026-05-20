import json
import re
import os
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="ViralForge Pro")

GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"
OLLAMA_URL  = os.getenv("OLLAMA_URL", "http://localhost:11434")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT        = int(os.getenv("PORT", 8080))

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


PLATFORM_ADJUSTMENTS = {
    "YouTube Long Form": "8–20 minute video. Deep storytelling. Full emotional arc. All sections apply.",
    "YouTube Shorts": "Under 60 seconds. Instant hook. No intros. Pure dopamine delivery. Fast cuts.",
    "Instagram Reel": "Under 90 seconds. Hook in 1 second. Vertical format. Trend-aware. Aesthetic-first.",
    "TikTok": "Under 3 minutes. Native TikTok energy. Sound-first. Pattern interrupt every 5 seconds. Trend hooks.",
    "Commercial Ad": "Paid ad. Every second costs money. Immediate pain hit. Hope within 3s. CTA at end.",
}


def build_prompt(niche: str, audience: str, platform: str, emotion: str,
                 topic: str = "", ad_length: str = "") -> str:
    platform_note = PLATFORM_ADJUSTMENTS.get(platform, "")
    ad_note = f"Ad length: {ad_length}." if ad_length else ""

    return f"""Generate a COMPLETE viral content system for:

PLATFORM: {platform}
{platform_note} {ad_note}
NICHE: {niche}
TARGET AUDIENCE: {audience}
LEAD EMOTION: {emotion}
SPECIFIC TOPIC (if given): {topic or "Choose the most viral angle for this niche"}

Apply the Pain + Hope + Proof formula to EVERYTHING. Make every section actionable for a faceless creator.

Return this exact JSON structure (all fields required, be specific and detailed for this niche):

{{
  "platform": "{platform}",
  "niche": "{niche}",
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
    "why_they_click": "Exact psychological reason they click",
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
    "full_script_sample": "200-350 word complete sample script for this video"
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
    {{
      "scene": 1,
      "timestamp": "0:00–0:05",
      "visual": "Detailed description of what appears on screen",
      "text_on_screen": "Text overlay or subtitle shown",
      "voiceover": "Exact words spoken",
      "audio": "Music/SFX direction",
      "edit_note": "Editing instruction for this scene"
    }},
    {{
      "scene": 2,
      "timestamp": "0:05–0:20",
      "visual": "Visual description",
      "text_on_screen": "Text overlay",
      "voiceover": "Script line",
      "audio": "Audio direction",
      "edit_note": "Edit note"
    }},
    {{
      "scene": 3,
      "timestamp": "0:20–0:45",
      "visual": "Visual description",
      "text_on_screen": "Text overlay",
      "voiceover": "Script line",
      "audio": "Audio direction",
      "edit_note": "Edit note"
    }},
    {{
      "scene": 4,
      "timestamp": "0:45–1:30",
      "visual": "Visual description",
      "text_on_screen": "Text overlay",
      "voiceover": "Script line",
      "audio": "Audio direction",
      "edit_note": "Edit note"
    }},
    {{
      "scene": 5,
      "timestamp": "1:30–3:00",
      "visual": "Visual description",
      "text_on_screen": "Text overlay",
      "voiceover": "Script line",
      "audio": "Audio direction",
      "edit_note": "Edit note"
    }},
    {{
      "scene": 6,
      "timestamp": "3:00–end",
      "visual": "Visual description",
      "text_on_screen": "Text overlay",
      "voiceover": "Script line",
      "audio": "Audio direction",
      "edit_note": "Edit note"
    }}
  ],
  "section10_comment_triggers": [
    {{
      "cta": "Exact comment CTA to say in video",
      "psychology": "Why this triggers a response",
      "expected_response": "What comments you will get"
    }},
    {{
      "cta": "Second CTA",
      "psychology": "Psychology",
      "expected_response": "Expected comments"
    }},
    {{
      "cta": "Third CTA",
      "psychology": "Psychology",
      "expected_response": "Expected comments"
    }}
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
    "short_hooks": ["Hook 1 — under 3 words", "Hook 2", "Hook 3"],
    "pacing_differences": "How Short pacing differs from Long Form",
    "retention_tactics": "Specific Short retention techniques"
  }},
  "section13_ai_tools": [
    {{"category": "Script Writing", "best_free": "tool name", "best_paid": "tool name", "tip": "how to use it"}},
    {{"category": "Voice Generation", "best_free": "tool name", "best_paid": "tool name", "tip": "how to use it"}},
    {{"category": "AI Visuals / B-Roll", "best_free": "tool name", "best_paid": "tool name", "tip": "how to use it"}},
    {{"category": "Video Editing", "best_free": "tool name", "best_paid": "tool name", "tip": "how to use it"}},
    {{"category": "Thumbnails", "best_free": "tool name", "best_paid": "tool name", "tip": "how to use it"}},
    {{"category": "Research & Trends", "best_free": "tool name", "best_paid": "tool name", "tip": "how to use it"}}
  ],
  "section14_multiplication": {{
    "core_angle": "The single most viral angle from this content",
    "shorts": ["Short idea 1", "Short idea 2", "Short idea 3", "Short idea 4", "Short idea 5"],
    "instagram_reel": "How to adapt for Instagram Reel",
    "tiktok": "How to adapt for TikTok with native energy",
    "twitter_thread": "Thread hook + 3 tweet outline",
    "community_post": "YouTube community post text",
    "email_hook": "Email subject line + first sentence"
  }},
  "section15_master_formula": "The reusable 1-paragraph formula for this niche that combines Pain + Hope + Proof + Curiosity + Aspiration + FOMO into a repeatable viral system"
}}"""


class GenerateRequest(BaseModel):
    niche: str
    audience: str
    platform: str = "YouTube Long Form"
    emotional_focus: str = "Hope"
    topic: Optional[str] = None
    ad_length: Optional[str] = None
    api_provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"


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
        raise HTTPException(status_code=401, detail="Groq API key required. Set GROQ_API_KEY env var or pass it in settings.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 4096,
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
        "options": {"temperature": 0.82, "top_p": 0.9, "num_predict": 4096},
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/models")
async def get_models():
    """Check Ollama connection and list local models."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            return {"status": "connected", "models": models}
    except Exception as e:
        return {"status": "disconnected", "models": [], "error": str(e)}


@app.post("/api/generate")
async def generate(req: GenerateRequest, request: Request):
    body = await request.json()
    api_key = body.get("api_key", "")

    prompt = build_prompt(
        niche=req.niche,
        audience=req.audience,
        platform=req.platform,
        emotion=req.emotional_focus,
        topic=req.topic or "",
        ad_length=req.ad_length or "",
    )

    try:
        if req.api_provider == "groq":
            raw = await call_groq(prompt, req.model, api_key)
        else:
            raw = await call_ollama(prompt, req.model)

        data = parse_json(raw)
        return {"result": data, "platform": req.platform}

    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot connect. Check your API provider settings.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"API error: {e.response.text}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/groq-models")
async def groq_models():
    return {"models": [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]}


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    print(f"\n  ViralForge Pro -> http://localhost:{PORT}\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
