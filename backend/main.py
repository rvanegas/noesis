"""root python from uvicorn"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.argument import router as argument_router
from api.agents import router as agents_router

# Initialize GPT instances at server startup
from services.startup_init import run_startup_initialization
from core.utils import logger

run_startup_initialization()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(argument_router, prefix="/api/argument")
app.include_router(agents_router, prefix="/api/agents")

logger.info("Server is ready and accepting requests.")
