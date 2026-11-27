"""Run the app as one service: uv run python -m api (API + built frontend at API_HOST:API_PORT)."""
import uvicorn

from config import settings

if __name__ == "__main__":
    if not (settings.frontend_dist / "index.html").exists():
        print(f"Note: no built frontend in {settings.frontend_dist}; run `npm run build` in frontend/ for the UI.")
    print(f"ShopHelp on http://{settings.api_host}:{settings.api_port}  (staff view: /#staff, API docs: /docs)")
    uvicorn.run("api.app:create_app", factory=True, host=settings.api_host, port=settings.api_port)
