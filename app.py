import os
import json
import secrets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import anthropic
import httpx

load_dotenv()

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme123")

sessions: dict[str, bool] = {}


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

    async def stream():
        with anthropic_client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            system=system_prompt,
            messages=messages,
        ) as stream_obj:
            for text in stream_obj.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"
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
    model = body.get("model", "black-forest-labs/FLUX.1-schnell-Free")

    full_prompt = f"{style}, {prompt}" if style else prompt

    together_key = os.getenv("TOGETHER_API_KEY")
    if not together_key:
        raise HTTPException(
            status_code=503,
            detail="Image generation not configured. Add TOGETHER_API_KEY to your .env file."
        )

    async with httpx.AsyncClient(timeout=120.0) as http:
        resp = await http.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {together_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "prompt": full_prompt,
                "width": width,
                "height": height,
                "steps": 4,
                "n": 1,
                "response_format": "b64_json",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return JSONResponse(resp.json())


@app.post("/api/generate-video")
async def generate_video(request: Request):
    require_auth(request)
    body = await request.json()
    prompt = body.get("prompt", "")
    duration = body.get("duration", "5")

    fal_key = os.getenv("FAL_API_KEY")
    if not fal_key:
        raise HTTPException(
            status_code=503,
            detail="Video generation not configured. Add FAL_API_KEY to your .env file."
        )

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(
            "https://queue.fal.run/fal-ai/kling-video/v1.6/standard/text-to-video",
            headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
            json={"prompt": prompt, "duration": duration, "aspect_ratio": "16:9"},
        )
    if resp.status_code not in (200, 201, 202):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return JSONResponse(resp.json())


@app.get("/api/video-status")
async def video_status(request: Request, request_id: str):
    require_auth(request)
    fal_key = os.getenv("FAL_API_KEY")
    if not fal_key:
        raise HTTPException(status_code=503)

    model_path = "fal-ai/kling-video/v1.6/standard/text-to-video"
    async with httpx.AsyncClient(timeout=30.0) as http:
        status_resp = await http.get(
            f"https://queue.fal.run/{model_path}/requests/{request_id}/status",
            headers={"Authorization": f"Key {fal_key}"},
        )
        data = status_resp.json()

        if data.get("status") == "COMPLETED":
            result_resp = await http.get(
                f"https://queue.fal.run/{model_path}/requests/{request_id}",
                headers={"Authorization": f"Key {fal_key}"},
            )
            return JSONResponse({"status": "COMPLETED", "result": result_resp.json()})

    return JSONResponse(data)
