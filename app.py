import os
import json
import base64
import secrets
import uuid
import urllib.parse
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from groq import AsyncGroq
import httpx

load_dotenv()

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme123")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

sessions: dict[str, bool] = {}
video_jobs: dict[str, dict] = {}


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get("session_token")
    return bool(token and sessions.get(token))


def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


@app.get("/")
async def home(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login")
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def do_login(request: Request):
    form = await request.form()
    password = form.get("password", "")
    if password == APP_PASSWORD:
        token = secrets.token_urlsafe(32)
        sessions[token] = True
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            "session_token", token,
            httponly=True, samesite="strict", max_age=86400 * 7
        )
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong password. Try again."})


@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        sessions.pop(token, None)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response


@app.post("/api/chat")
async def chat(request: Request):
    require_auth(request)
    body = await request.json()
    messages = body.get("messages", [])
    system_prompt = body.get("system", "You are a helpful AI assistant. Be creative, thorough, and engaging.")

    groq_messages = [{"role": "system", "content": system_prompt}] + messages

    async def stream():
        stream_obj = await groq_client.chat.completions.create(
            messages=groq_messages,
            model=GROQ_MODEL,
            stream=True,
            max_tokens=8000,
            temperature=0.7,
        )
        async for chunk in stream_obj:
            delta = chunk.choices[0].delta.content
            if delta:
                yield f"data: {json.dumps({'text': delta})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/generate-image")
async def generate_image(request: Request):
    require_auth(request)
    body = await request.json()
    prompt = body.get("prompt", "")
    width = int(body.get("width", 1024))
    height = int(body.get("height", 1024))
    style = body.get("style", "")

    full_prompt = f"{style}, {prompt}" if style else prompt
    encoded = urllib.parse.quote(full_prompt)
    seed = secrets.randbelow(999999)

    # Pollinations.ai — completely free, no API key needed
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?model=flux&nologo=true&width={width}&height={height}&seed={seed}"
    )

    async with httpx.AsyncClient(timeout=120.0) as http:
        resp = await http.get(url, follow_redirects=True)

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Image generation failed (HTTP {resp.status_code})")

    img_b64 = base64.b64encode(resp.content).decode()
    return JSONResponse({"data": [{"b64_json": img_b64}]})


@app.post("/api/generate-video")
async def generate_video(request: Request, background_tasks: BackgroundTasks):
    require_auth(request)
    body = await request.json()
    prompt = body.get("prompt", "")

    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        raise HTTPException(
            status_code=503,
            detail="Video generation not configured. Add HF_TOKEN to your .env file (free at huggingface.co)."
        )

    job_id = str(uuid.uuid4())
    video_jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(_run_video_generation, job_id, prompt, hf_token)
    return JSONResponse({"job_id": job_id})


async def _run_video_generation(job_id: str, prompt: str, hf_token: str):
    video_jobs[job_id] = {"status": "processing"}
    try:
        async with httpx.AsyncClient(timeout=300.0) as http:
            resp = await http.post(
                "https://api-inference.huggingface.co/models/damo-vilab/text-to-video-ms-1.7b",
                headers={"Authorization": f"Bearer {hf_token}"},
                json={"inputs": prompt},
            )

        if resp.status_code == 200:
            video_b64 = base64.b64encode(resp.content).decode()
            video_jobs[job_id] = {"status": "completed", "video_b64": video_b64}
        elif resp.status_code == 503:
            video_jobs[job_id] = {
                "status": "error",
                "error": "Model is loading on HuggingFace. Wait ~30 seconds and try again.",
            }
        else:
            video_jobs[job_id] = {"status": "error", "error": f"Generation failed (HTTP {resp.status_code})"}
    except httpx.TimeoutException:
        video_jobs[job_id] = {
            "status": "error",
            "error": "Request timed out (5 min). HuggingFace free tier can be slow — please try again.",
        }
    except Exception as e:
        video_jobs[job_id] = {"status": "error", "error": str(e)}


@app.get("/api/video-status")
async def video_status(request: Request, job_id: str):
    require_auth(request)
    job = video_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job)
