from fastapi import APIRouter

from backend.agent.graph import run_fitlife_agent
from backend.api.utils import ok
from backend.schemas import ChatRequest


router = APIRouter()


@router.post("/chat")
def chat(request: ChatRequest):
    result = run_fitlife_agent(request.question)
    return ok(
        {
            "answer_markdown": result["answer_markdown"],
            "intent": result["intent"],
            "trace": result["trace"],
            "sources": result["sources"],
        }
    )
