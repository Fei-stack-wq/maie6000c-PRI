"""Test-only HTTP fault proxy; successful requests reach the actual rule AI service."""
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()
calls = {}


@app.get("/health/live")
def health():
    return {"status": "ok"}


@app.post("/extract-issues")
def extract(payload: dict):
    product = payload["product_id"]
    calls[product] = calls.get(product, 0) + 1
    if product.startswith("always-fail-") or (
        product.startswith("fail-once-") and calls[product] == 1
    ):
        return JSONResponse({"error": "simulated temporary outage"}, status_code=503)
    response = httpx.post("http://127.0.0.1:18100/extract-issues", json=payload, timeout=5)
    return JSONResponse(response.json(), status_code=response.status_code)
