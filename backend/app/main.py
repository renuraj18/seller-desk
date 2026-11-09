from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import image_links as image_links_router
from .routers import agents, connections, content, extension, learn, listings, media, order_sync, orders, product_templates, products, setup, stock_push, templates, uploads

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Seller Desk", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_origin_regex=r"chrome-extension://[a-p]{32}", allow_methods=["*"], allow_headers=["*"])

for r in (setup.router, products.router, product_templates.router, listings.router, templates.router, connections.router, content.router,
          extension.router, media.router, orders.router, learn.router, agents.router, order_sync.router, uploads.router, stock_push.router, image_links_router.router):
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
        # Port 8000 is also the usual port for local model servers, and tools probe it for /health and /v1/models.
        # Answer those (and unknown API paths) with 404 instead of the app page so nothing mistakes us for one.
        if path == "health" or path.startswith(("api/", "v1/", "assets/")):
            from fastapi import HTTPException
            raise HTTPException(404)
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
