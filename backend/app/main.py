from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import connections, content, extension, listings, media, orders, products, setup, templates

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Seller Desk", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_origin_regex=r"chrome-extension://[a-p]{32}", allow_methods=["*"], allow_headers=["*"])

for r in (setup.router, products.router, listings.router, templates.router, connections.router, content.router,
          extension.router, media.router, orders.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


STATIC = Path(__file__).parent / "static"


@app.get("/ext-demo")
def ext_demo():
    """Practice form that imitates a seller panel, for trying the extension safely."""
    return FileResponse(STATIC / "ext-demo.html")


@app.get("/ext-demo-{page}")
def ext_demo_page(page: str):
    """Practice pages: catalog (variants), inventory, orders."""
    if page not in ("catalog", "inventory", "orders"):
        from fastapi import HTTPException
        raise HTTPException(404)
    return FileResponse(STATIC / f"ext-demo-{page}.html")


# Serve the built React app (frontend/dist) when present
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
