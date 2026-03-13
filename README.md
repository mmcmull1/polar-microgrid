# Polar Microgrid Simulator
**By Matt McMullen** — University of Michigan

A web-based simulation tool for Antarctic polar research station power system design and optimization. Models solar PV, wind turbines, battery storage, and diesel generators with real NASA POWER weather data.

---

## Project Structure

```
polar-microgrid/
├── simulation.py      # Physics engine (Python port of MATLAB model)
├── server.py          # FastAPI backend / REST API
├── index.html         # Frontend GUI
├── requirements.txt   # Python dependencies
├── Procfile           # For Heroku / Railway deployment
└── runtime.txt        # Python version pin
```

---

## Run Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server
uvicorn server:app --host 0.0.0.0 --port 8000

# 3. Open in browser
open http://localhost:8000
```

---

## Deploy to Railway (Recommended — Free Tier)

[Railway](https://railway.app) gives you a public URL in minutes.

1. Create a free account at https://railway.app
2. Click **New Project → Deploy from GitHub Repo**
   - Push this folder to a GitHub repo first (see below), or use Railway's CLI
3. Railway auto-detects the `Procfile` and runs `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Your public URL appears in the Railway dashboard (e.g. `https://polar-microgrid-xxxx.railway.app`)

**Push to GitHub first:**
```bash
cd polar-microgrid
git init
git add .
git commit -m "Initial polar microgrid simulator"
gh repo create polar-microgrid --public --push
```
Then import the repo into Railway.

---

## Deploy to Render (Also Free)

1. Create account at https://render.com
2. New → **Web Service** → connect GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
5. Choose **Free** instance type → Deploy

---

## Deploy to Heroku

```bash
heroku create your-app-name
git push heroku main
heroku open
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves the frontend GUI |
| GET | `/stations` | List available stations |
| POST | `/simulate` | Run simulation, returns JSON results |
| GET | `/health` | Health check |

### POST /simulate — Parameters

```json
{
  "station":        "Casey",
  "year":           2023,
  "solar_kw":       100.0,
  "wind_kw":        200.0,
  "diesel_kw":      600.0,
  "battery_kwh":    500.0,
  "tracking_mode":  "dual_axis",
  "dispatch_mode":  "renewable_priority"
}
```

**Stations:** McMurdo, Palmer, SouthPole, Casey, Rothera, Mawson, Davis, Halley, Neumayer, Dumont

**tracking_mode:** `fixed` | `single_axis` | `dual_axis`

**dispatch_mode:** `renewable_priority` | `cost_priority`

---

## Physics Models

- **Solar PV**: Temperature-corrected cell efficiency, tracking boost, albedo boost from snow, PVWatts derating (0.77)
- **Wind**: Hellmann wind shear to hub height, air density correction for temperature/pressure, power curve (cut-in/rated/cut-out)
- **Battery**: Round-trip efficiency, C-rate limits, SOC bounds, cold derating below −20°C, self-discharge
- **Dispatch**: Renewable-priority or cost-priority (marginal cost comparison)
- **Costs**: NREL ATB 2023 capital/O&M costs, NPV discounting, equipment replacements, LCOE

## Weather Data

Weather is fetched from [NASA POWER API](https://power.larc.nasa.gov/) (hourly, free). If the API is unavailable, a physics-based synthetic weather model is used as fallback.

---

## Key Parameters (Configurable in GUI)

| Parameter | Default | Range |
|-----------|---------|-------|
| Solar PV capacity | 100 kW | 0–1000 kW |
| Wind capacity | 200 kW | 0–2000 kW |
| Diesel capacity | 600 kW | 0–2000 kW |
| Battery storage | 500 kWh | 0–5000 kWh |
| Solar tracking | dual_axis | fixed / single_axis / dual_axis |
| Dispatch strategy | renewable_priority | renewable_priority / cost_priority |
