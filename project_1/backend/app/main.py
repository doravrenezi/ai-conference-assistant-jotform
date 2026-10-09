# This file defines the FastAPI app, API routes, startup setup, and frontend serving.
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
load_dotenv(PROJECT_ROOT / ".env", override=True)

from chat_service import ChatService
from database import init_database
from knowledge_base import load_knowledge_base
from registration_service import create_registration_response, lookup_registration_response
from schemas import ChatRequest, ChatResponse, RegistrationLookupRequest, RegistrationRequest


app = FastAPI()
chat_service = ChatService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup_event():
    init_database()
    load_knowledge_base()


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/registrations")
async def create_registration_route(reg: RegistrationRequest):
    return create_registration_response(reg)


@app.post("/registrations/lookup")
async def lookup_registration_route(lookup: RegistrationLookupRequest):
    return lookup_registration_response(lookup)


@app.post("/chat", response_model=ChatResponse)
async def chat_route(chat: ChatRequest, request: Request):
    return chat_service.process_chat(chat, request.headers.get("X-Chat-Session-Id"))
