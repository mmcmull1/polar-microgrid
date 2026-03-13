"""
Polar Microgrid Simulation — FastAPI Backend
Run with: uvicorn server:app --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import simulation

app = FastAPI(title="Polar Microgrid Simulator")

# Allow cross-origin requests (needed for local development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class SimParams(BaseModel):
    station: str = "Casey"
    solar_kw: float = 100.0
    wind_kw: float = 200.0
    diesel_kw: float = 600.0
    battery_kwh: float = 500.0
    tracking_mode: str = "dual_axis"
    dispatch_mode: str = "renewable_priority"
    year: int = 2023
    personnel_summer: Optional[int] = None
    personnel_winter: Optional[int] = None

@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/stations")
def get_stations():
    return {"stations": list(simulation.STATIONS.keys())}

@app.post("/simulate")
def simulate(params: SimParams):
    try:
        result = simulation.run_simulation(params.dict())
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "ok"}
