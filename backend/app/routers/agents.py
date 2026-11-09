from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import agents as svc

router = APIRouter(prefix="/api/agents", tags=["agents"])

Market = Literal["amazon", "flipkart", "meesho"]


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class AskAllIn(ChatIn):
    marketplaces: list[Market] = list(svc.MARKETPLACES)


@router.get("/status")
def status():
    return svc.status()


@router.get("/{marketplace}/messages")
def messages(marketplace: Market):
    return {"messages": svc.history(marketplace)}


@router.delete("/{marketplace}/messages")
def clear(marketplace: Market):
    svc.clear_history(marketplace)
    return {"ok": True}


@router.post("/{marketplace}/chat")
def chat(marketplace: Market, body: ChatIn):
    return svc.chat(marketplace, body.message.strip())


@router.post("/ask-all")
def ask_all(body: AskAllIn):
    """Send the same message to several marketplace agents at once; each works on its own data."""
    mps = list(dict.fromkeys(body.marketplaces))
    with ThreadPoolExecutor(max_workers=len(mps) or 1) as pool:
        results = list(pool.map(lambda m: svc.chat(m, body.message.strip()), mps))
    return {"results": dict(zip(mps, results))}


@router.get("/proposals")
def proposals(status: str | None = None, marketplace: Market | None = None):
    return {"proposals": svc.list_proposals(status, marketplace)}


class DecideIn(BaseModel):
    approve: bool


@router.post("/proposals/{proposal_id}/decide")
def decide(proposal_id: int, body: DecideIn):
    try:
        return svc.decide(proposal_id, body.approve)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/daily-summary")
def daily_summary():
    """Start the agents' summary of today's order check in the background; answers appear in each agent's chat."""
    import threading
    threading.Thread(target=svc.daily_summary, daemon=True).start()
    return {"started": True}
