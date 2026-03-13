"""
Polar Microgrid Simulation Engine
Python port of polar_microgrid_sim_v2.m by Matt McMullen
"""
import math
import random
import requests
from dataclasses import dataclass, field
from typing import Optional
import datetime as dt

# ──────────────────────────────────────────────────────────────────────────────
# Station data
# ──────────────────────────────────────────────────────────────────────────────
STATIONS = {
    "McMurdo":   dict(lat=-77.85, lon=166.67, alt=24,  summer=1000, winter=250),
    "Palmer":    dict(lat=-64.77, lon=-64.05, alt=15,  summer=46,   winter=20),
    "SouthPole": dict(lat=-90.00, lon=0.00,   alt=2835, summer=200,  winter=50),
    "Casey":     dict(lat=-66.28, lon=110.53, alt=42,  summer=120,  winter=20),
    "Rothera":   dict(lat=-67.57, lon=-68.13, alt=16,  summer=100,  winter=22),
    "Mawson":    dict(lat=-67.60, lon=62.87,  alt=16,  summer=60,   winter=20),
    "Davis":     dict(lat=-68.58, lon=77.97,  alt=18,  summer=120,  winter=22),
    "Halley":    dict(lat=-75.58, lon=-26.57, alt=30,  summer=70,   winter=16),
    "Neumayer":  dict(lat=-70.65, lon=-8.26,  alt=42,  summer=50,   winter=10),
    "Dumont":    dict(lat=-66.67, lon=140.00, alt=40,  summer=80,   winter=25),
}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _hours_of_year(year: int):
    """Return list of datetime objects for every hour in year."""
    start = dt.datetime(year, 1, 1)
    n = 8784 if year % 4 == 0 else 8760
    return [start + dt.timedelta(hours=i) for i in range(n)]

def _doy(d): return d.timetuple().tm_yday
def _hr(d):  return d.hour

# ──────────────────────────────────────────────────────────────────────────────
# Synthetic weather (used when NASA POWER fetch fails)
# ──────────────────────────────────────────────────────────────────────────────
def _generate_synthetic(lat: float, year: int):
    random.seed(42)
    hours = _hours_of_year(year)
    n = len(hours)
    lf = abs(lat) / 90
    lr = math.radians(lat)
    
    temp, ghi, ghi_clr, ws, wd, rh, pres = [], [], [], [], [], [], []
    for h in hours:
        doy = _doy(h); hr = _hr(h)
        # Temperature
        tc = ((-10 - 25*lf)
              - (10 + 15*lf)*math.cos(2*math.pi*(doy-15)/365)
              + 3*(1-0.5*lf)*math.cos(2*math.pi*(hr-14)/24)
              + (random.gauss(0, 3)))
        # Solar
        decl = math.radians(23.45*math.sin(math.radians(360/365*(doy-81))))
        ha = math.radians(15*(hr-12))
        sin_el = math.sin(lr)*math.sin(decl) + math.cos(lr)*math.cos(decl)*math.cos(ha)
        clr_v = max(0, 1361*sin_el*0.75)
        ghi_v = max(0, clr_v*(0.5 + 0.3*random.random()))
        # Wind (Weibull via inverse CDF)
        u = max(random.random(), 1e-9)
        v_base = (6 + 4*lf)*(1 + 0.3*math.cos(2*math.pi*(doy-180)/365))
        ws_v = min(max(v_base*(-math.log(u))**0.5, 0), 35)
        temp.append(tc); ghi.append(ghi_v); ghi_clr.append(clr_v)
        ws.append(ws_v); wd.append(360*random.random())
        rh.append(60 + 20*random.random())
        pres.append(98 - 0.012*abs(lat) + random.gauss(0, 1))
    return dict(datetime=hours, ghi=ghi, ghi_clr=ghi_clr,
                temp=temp, ws=ws, wd=wd, rh=rh, pres=pres)

# ──────────────────────────────────────────────────────────────────────────────
# NASA POWER fetch
# ──────────────────────────────────────────────────────────────────────────────
def fetch_weather(lat: float, lon: float, year: int):
    params = "ALLSKY_SFC_SW_DWN,CLRSKY_SFC_SW_DWN,T2M,WS10M,WD10M,RH2M,PS"
    url = (
        f"https://power.larc.nasa.gov/api/temporal/hourly/point"
        f"?parameters={params}&community=RE"
        f"&longitude={lon:.4f}&latitude={lat:.4f}"
        f"&start={year}0101&end={year}1231&format=JSON&time-standard=UTC"
    )
    try:
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
        data = resp.json()["properties"]["parameter"]
        keys = list(data["T2M"].keys())
        n = len(keys)

        def extract(field):
            out = []
            for k in keys:
                v = data[field][k]
                out.append(v if v > -900 else None)
            return out

        def fill(arr):
            # Linear interpolation for small gaps (≤6 hrs)
            out = list(arr)
            i = 0
            while i < len(out):
                if out[i] is None:
                    j = i
                    while j < len(out) and out[j] is None:
                        j += 1
                    if j - i <= 6:
                        v0 = out[i-1] if i > 0 else 0
                        v1 = out[j] if j < len(out) else v0
                        for k2 in range(i, j):
                            out[k2] = v0 + (v1 - v0)*(k2-i+1)/(j-i+1)
                    else:
                        for k2 in range(i, j):
                            out[k2] = 0
                    i = j
                else:
                    i += 1
            return out

        def parse_ts(k):
            s = k.lstrip("x")
            return dt.datetime.strptime(s, "%Y%m%d%H") if len(s) >= 10 else dt.datetime.strptime(s[:8], "%Y%m%d")

        hours = [parse_ts(k) for k in keys]
        ghi_raw = fill(extract("ALLSKY_SFC_SW_DWN"))
        ghi_clr = fill(extract("CLRSKY_SFC_SW_DWN"))
        temp    = fill(extract("T2M"))
        ws      = fill(extract("WS10M"))
        wd      = fill(extract("WD10M"))
        rh      = fill(extract("RH2M"))
        pres    = fill(extract("PS"))
        return dict(datetime=hours, ghi=ghi_raw, ghi_clr=ghi_clr,
                    temp=temp, ws=ws, wd=wd, rh=rh, pres=pres, source="nasa")
    except Exception as e:
        print(f"NASA POWER fetch failed: {e} — using synthetic data")
        return _generate_synthetic(lat, year)

# ──────────────────────────────────────────────────────────────────────────────
# Demand
# ──────────────────────────────────────────────────────────────────────────────
def calculate_demand(weather, stn_cfg):
    n = len(weather["datetime"])
    demand = []
    p_summer = stn_cfg["num_personnel_summer"]
    p_winter = stn_cfg["num_personnel_winter"]
    base_kw  = stn_cfg["base_load_kw_per_person"]
    pf       = stn_cfg["peak_factor"]
    hf       = stn_cfg["heating_fraction"]
    infra    = stn_cfg["infrastructure_base_kw"]

    for i in range(n):
        d = weather["datetime"][i]
        doy = _doy(d); hr = _hr(d)
        sf = 0.5*(1 - math.cos(2*math.pi*(doy-15)/365))
        personnel = p_winter + (p_summer - p_winter)*sf
        base = personnel * base_kw
        temp = weather["temp"][i] or -20
        heat = 0
        if temp < 0:
            heat = base * hf * (0.5 + 0.5*min(abs(temp)/50, 1))
        if 8 <= hr <= 20:
            df = 1 + (pf-1)*math.sin(math.pi*(hr-8)/12)
        else:
            df = 1 - (pf-1)*0.5
        demand.append(base*df + heat + infra)
    return demand

# ──────────────────────────────────────────────────────────────────────────────
# Solar PV
# ──────────────────────────────────────────────────────────────────────────────
def model_solar_pv(weather, sol_cfg):
    num_panels = math.ceil(sol_cfg["installed_capacity_kw"]*1000 / sol_cfg["panel_rated_power_w"])
    total_area = num_panels * sol_cfg["panel_area_m2"]

    tracking_boost = {"fixed": 1.0, "single_axis": 1.20, "dual_axis": 1.35}
    boost = tracking_boost.get(sol_cfg.get("tracking_mode","fixed"), 1.0)
    albedo = sol_cfg.get("albedo_boost_factor", 1.15)

    noct   = sol_cfg["noct_c"]
    eta0   = sol_cfg["panel_efficiency_stc"]
    tcoef  = sol_cfg["temp_coefficient_pmax"]
    tstc   = sol_cfg["stc_temperature_c"]
    derating = 0.77

    pv_out, temps, etas = [], [], []
    for i in range(len(weather["datetime"])):
        ghi_v = (weather["ghi"][i] or 0)
        ta    = (weather["temp"][i] or -20)
        G_eff = ghi_v * albedo * boost
        t_cell = ta + (noct-20)/800 * G_eff
        eta = eta0 * (1 + tcoef*(t_cell - tstc))
        eta = max(0, min(eta, 0.30))
        p_dc = eta * G_eff * total_area / 1000
        p_ac = max(0, p_dc * derating)
        pv_out.append(p_ac); temps.append(t_cell); etas.append(eta)

    return pv_out, dict(num_panels=num_panels, total_area=total_area)

# ──────────────────────────────────────────────────────────────────────────────
# Wind
# ──────────────────────────────────────────────────────────────────────────────
def model_wind(weather, wnd_cfg):
    num_turbines = math.ceil(wnd_cfg["installed_capacity_kw"] / wnd_cfg["turbine_rated_power_kw"])
    D = wnd_cfg["rotor_diameter_m"]
    A = math.pi*(D/2)**2
    h_hub  = wnd_cfg["hub_height_m"]
    h_meas = wnd_cfg.get("measurement_height_m", 10.0)
    alpha  = wnd_cfg.get("wind_shear_exponent", 0.12)
    v_cut_in  = wnd_cfg["cut_in_speed_ms"]
    v_rated   = wnd_cfg["rated_speed_ms"]
    v_cut_out = wnd_cfg["cut_out_speed_ms"]
    cp_max    = wnd_cfg.get("cp_max", 0.40)
    rated_kw  = wnd_cfg["turbine_rated_power_kw"]
    sys_eff   = 0.8

    wind_out = []
    for i in range(len(weather["datetime"])):
        v10 = (weather["ws"][i] or 0)
        tc  = (weather["temp"][i] or -20)
        p_kpa = (weather["pres"][i] or 101)
        v_hub = v10 * (h_hub/h_meas)**alpha
        rho = (p_kpa*1000) / (287.05 * max(tc+273.15, 200))
        if v_hub < v_cut_in:
            p_t = 0
        elif v_hub < v_rated:
            p_t = min(cp_max*0.5*rho*A*v_hub**3/1000, rated_kw)
        elif v_hub <= v_cut_out:
            p_t = rated_kw
        else:
            p_t = 0
        wind_out.append(p_t * sys_eff * num_turbines)

    return wind_out, dict(num_turbines=num_turbines, swept_area=A)

# ──────────────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────────────
def run_dispatch(weather, demand, pv_out, wind_out, batt_cfg, dsl_cfg, mode):
    n = len(demand)
    
    soc     = batt_cfg["initial_soc"] * batt_cfg["capacity_kwh"]
    max_e   = batt_cfg["max_soc"] * batt_cfg["capacity_kwh"]
    min_e   = batt_cfg["min_soc"] * batt_cfg["capacity_kwh"]
    chg_max = batt_cfg["capacity_kwh"] * batt_cfg["max_charge_rate_c"]
    dis_max = batt_cfg["capacity_kwh"] * batt_cfg["max_discharge_rate_c"]
    chg_eff = batt_cfg["charge_efficiency"]
    dis_eff = batt_cfg["discharge_efficiency"]
    self_dis = batt_cfg["self_discharge_per_hour"]
    dsl_cap = dsl_cfg["installed_capacity_kw"]
    fuel_rate = dsl_cfg["fuel_consumption_l_kwh"]
    cold_thr = batt_cfg.get("cold_threshold_c", -20)
    cold_derate = batt_cfg.get("cold_derating_factor", 0.85)

    # Cost priority thresholds
    batt_marginal = diesel_marginal = 0
    if mode == "cost_priority":
        usable = batt_cfg["capacity_kwh"] * (batt_cfg["max_soc"] - batt_cfg["min_soc"])
        if usable > 0:
            batt_marginal = 450 / (batt_cfg["cycle_life_80pct_dod"] * usable * batt_cfg["round_trip_efficiency"])
        else:
            batt_marginal = float("inf")  # no battery, never use it
        diesel_marginal = (dsl_cfg["fuel_cost_per_liter"] * fuel_rate
                           + dsl_cfg["maintenance_cost_per_kwh"])

    pv2l=[];  w2l=[];  bchg=[];  bdis=[];  bsoc=[]; dout=[];  dfuel=[];  curt=[];  unm=[]
    for i in range(n):
        soc *= (1 - self_dis)
        tc = weather["temp"][i] or -20
        eff_derate = cold_derate if tc < cold_thr else 1.0
        eff_max_e = max_e * eff_derate
        
        pv_kw = pv_out[i]; wnd_kw = wind_out[i]
        re = pv_kw + wnd_kw
        net = re - demand[i]
        re2l = min(re, demand[i])
        f = pv_kw / max(re, 0.001)
        pv2l.append(re2l*f); w2l.append(re2l*(1-f))

        if net >= 0:
            ac = min(net, chg_max, (eff_max_e - soc) / chg_eff)
            ac = max(ac, 0)
            soc += ac * chg_eff
            bchg.append(ac); curt.append(net - ac)
            bdis.append(0); dout.append(0); dfuel.append(0); unm.append(0)
        else:
            deficit = abs(net)
            bd = dp = 0
            if mode == "cost_priority" and diesel_marginal < batt_marginal:
                dp = min(deficit, dsl_cap)
                deficit -= dp
                if deficit > 0:
                    ad = min(deficit, dis_max, (soc - min_e) * dis_eff)
                    ad = max(ad, 0); soc -= ad/dis_eff; bd = ad; deficit -= ad
            else:
                ad = min(deficit, dis_max, (soc - min_e) * dis_eff)
                ad = max(ad, 0); soc -= ad/dis_eff; bd = ad; deficit -= ad
                if deficit > 0:
                    dp = min(deficit, dsl_cap); deficit -= dp
            bchg.append(0); bdis.append(bd); dout.append(dp)
            dfuel.append(dp * fuel_rate); curt.append(0); unm.append(max(deficit,0))

        soc = max(min_e, min(eff_max_e, soc))
        bsoc.append(soc)

    total_supply = [pv2l[i]+w2l[i]+bdis[i]+dout[i] for i in range(n)]
    return dict(
        demand=demand, pv=pv_out, wind=wind_out,
        pv2l=pv2l, w2l=w2l, bchg=bchg, bdis=bdis,
        bsoc=bsoc, dout=dout, dfuel=dfuel,
        curt=curt, unm=unm, total_supply=total_supply
    )

# ──────────────────────────────────────────────────────────────────────────────
# Costs
# ──────────────────────────────────────────────────────────────────────────────
def calculate_costs(cfg, dispatch):
    c = cfg["costs"]
    tracking_adder = {"single_axis": cfg["solar"].get("tracker_capex_adder",200),
                      "dual_axis":   cfg["solar"].get("tracker_capex_dual",500)}.get(
                      cfg["solar"].get("tracking_mode","fixed"), 0)

    pv_cx = cfg["solar"]["installed_capacity_kw"] * (c["pv_capex_per_kw"] + tracking_adder)
    w_cx  = cfg["wind"]["installed_capacity_kw"]  * c["wind_capex_per_kw"]
    d_cx  = cfg["diesel"]["installed_capacity_kw"] * c["diesel_capex_per_kw"]
    b_cx  = cfg["battery"]["capacity_kwh"]         * c["battery_capex_per_kwh"]
    tot_cx = pv_cx + w_cx + d_cx + b_cx

    pv_ox = cfg["solar"]["installed_capacity_kw"] * c["pv_opex_per_kw_year"]
    w_ox  = cfg["wind"]["installed_capacity_kw"]  * c["wind_opex_per_kw_year"]
    d_ox  = cfg["diesel"]["installed_capacity_kw"]* c["diesel_opex_per_kw_year"]
    b_ox  = cfg["battery"]["capacity_kwh"]         * c["battery_opex_per_kwh_year"]
    f_cost = sum(dispatch["dfuel"]) * cfg["diesel"]["fuel_cost_per_liter"]
    d_mnt  = sum(dispatch["dout"]) * cfg["diesel"]["maintenance_cost_per_kwh"]
    tot_ox = pv_ox + w_ox + d_ox + b_ox + f_cost + d_mnt

    life = c["project_lifetime_years"]
    r = c["discount_rate"]
    npv_f = sum(1/(1+r)**y for y in range(1, life+1))
    repl = sum(
        pv_cx/(1+r)**y for y in range(1,life+1) if y % c["pv_lifetime_years"] == 0 and y < life
    ) + sum(
        w_cx/(1+r)**y  for y in range(1,life+1) if y % c["wind_lifetime_years"] == 0 and y < life
    ) + sum(
        d_cx/(1+r)**y  for y in range(1,life+1) if y % c["diesel_lifetime_years"] == 0 and y < life
    ) + sum(
        b_cx/(1+r)**y  for y in range(1,life+1) if y % c["battery_lifetime_years"] == 0 and y < life
    )
    tot_life = tot_cx + tot_ox*npv_f + repl
    total_kwh = sum(dispatch["total_supply"]) * npv_f
    lcoe = tot_life / (total_kwh + 1e-9)

    return dict(
        pv_capex=pv_cx, wind_capex=w_cx, diesel_capex=d_cx, battery_capex=b_cx,
        total_capex=tot_cx,
        pv_opex=pv_ox, wind_opex=w_ox, diesel_opex=d_ox, fuel_cost=f_cost,
        diesel_maint=d_mnt, battery_opex=b_ox, total_opex=tot_ox,
        lifetime_cost=tot_life, lcoe=lcoe,
        annual_fuel_liters=sum(dispatch["dfuel"]),
        project_lifetime=life,
        discount_rate_pct=round(r * 100, 1),
        total_annual_kwh=round(sum(dispatch["total_supply"]), 0),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Monthly / daily aggregation helpers
# ──────────────────────────────────────────────────────────────────────────────
def _monthly(hours, arr):
    monthly = [0.0]*12
    for i, h in enumerate(hours):
        monthly[h.month-1] += arr[i]
    return [v/1000 for v in monthly]   # convert kWh → MWh

def _weekly_smooth(arr, window=168):
    out = []
    half = window//2
    n = len(arr)
    for i in range(n):
        lo = max(0, i-half); hi = min(n, i+half)
        out.append(sum(arr[lo:hi])/(hi-lo))
    return out

def _downsample(hours, arr, step=24):
    """Daily average → returns (day_indices_0_to_364, daily_avg)"""
    n_days = len(arr)//step
    days = list(range(n_days))
    avgs = []
    for d in days:
        chunk = arr[d*step:(d+1)*step]
        avgs.append(sum(chunk)/len(chunk))
    return days, avgs

# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────
def run_simulation(params: dict) -> dict:
    """
    Accepts all basic and advanced parameters from the GUI.
    All fields have sensible defaults matching the original MATLAB model.
    """
    p = params
    def fp(key, default): return float(p.get(key, default))
    def ip(key, default): return int(float(p.get(key, default)))

    station_name = p.get("station", "Casey")
    year         = ip("year", 2023)

    if station_name in STATIONS:
        s = STATIONS[station_name]
        lat, lon, alt = s["lat"], s["lon"], s["alt"]
        default_summer, default_winter = s["summer"], s["winter"]
    else:
        lat  = fp("latitude", -70)
        lon  = fp("longitude", 0)
        alt  = fp("altitude", 50)
        default_summer, default_winter = 50, 20

    cfg = {
        "station": {
            "name": station_name, "latitude": lat, "longitude": lon, "altitude_m": alt,
            "num_personnel_summer": ip("personnel_summer", default_summer),
            "num_personnel_winter": ip("personnel_winter", default_winter),
            "base_load_kw_per_person": fp("base_load_kw_per_person", 1.25),
            "peak_factor":            fp("peak_factor", 1.4),
            "heating_fraction":       fp("heating_fraction", 0.55),
            "infrastructure_base_kw": fp("infrastructure_base_kw", 50.0),
        },
        "solar": {
            "installed_capacity_kw":   fp("solar_kw", 100),
            "panel_rated_power_w":     fp("panel_rated_power_w", 400),
            "panel_area_m2":           fp("panel_area_m2", 1.95),
            "panel_efficiency_stc":    fp("panel_efficiency_stc", 0.205),
            "noct_c":                  fp("noct_c", 45.0),
            "temp_coefficient_pmax":   fp("temp_coefficient_pmax", -0.0035),
            "stc_temperature_c":       25.0,
            "albedo_boost_factor":     fp("albedo_boost_factor", 1.15),
            "tracking_mode":           p.get("tracking_mode", "dual_axis"),
            "tracker_capex_adder":     200,
            "tracker_capex_dual":      500,
        },
        "wind": {
            "installed_capacity_kw":  fp("wind_kw", 200),
            "turbine_rated_power_kw": fp("turbine_rated_power_kw", 100),
            "rotor_diameter_m":       fp("rotor_diameter_m", 33.4),
            "hub_height_m":           fp("hub_height_m", 50),
            "cut_in_speed_ms":        fp("cut_in_speed_ms", 3),
            "rated_speed_ms":         fp("rated_speed_ms", 13),
            "cut_out_speed_ms":       fp("cut_out_speed_ms", 31),
            "cp_max":                 fp("cp_max", 0.40),
            "wind_shear_exponent":    fp("wind_shear_exponent", 0.12),
            "measurement_height_m":   10.0,
        },
        "diesel": {
            "installed_capacity_kw":    fp("diesel_kw", 600),
            "min_load_fraction":        fp("diesel_min_load_fraction", 0.25),
            "fuel_consumption_l_kwh":   fp("fuel_consumption_l_kwh", 0.27),
            "fuel_cost_per_liter":      fp("fuel_cost_per_liter", 2.50),
            "maintenance_cost_per_kwh": fp("maintenance_cost_per_kwh", 0.03),
        },
        "battery": {
            "capacity_kwh":            fp("battery_kwh", 500),
            "round_trip_efficiency":   fp("round_trip_efficiency", 0.90),
            "charge_efficiency":       0.95,
            "discharge_efficiency":    0.95,
            "max_charge_rate_c":       fp("max_charge_rate_c", 0.5),
            "max_discharge_rate_c":    fp("max_discharge_rate_c", 1.0),
            "min_soc":                 fp("min_soc", 0.10),
            "max_soc":                 fp("max_soc", 0.95),
            "initial_soc":             0.50,
            "cycle_life_80pct_dod":    ip("cycle_life_80pct_dod", 5000),
            "cold_derating_factor":    fp("cold_derating_factor", 0.85),
            "cold_threshold_c":        fp("cold_threshold_c", -20.0),
            "self_discharge_per_hour": 0.0001,
        },
        "costs": {
            "pv_capex_per_kw":          fp("pv_capex_per_kw", 1600.0),
            "pv_opex_per_kw_year":       fp("pv_opex_per_kw_year", 18.0),
            "pv_lifetime_years":         ip("pv_lifetime_years", 25),
            "wind_capex_per_kw":         fp("wind_capex_per_kw", 3000.0),
            "wind_opex_per_kw_year":     fp("wind_opex_per_kw_year", 50.0),
            "wind_lifetime_years":       ip("wind_lifetime_years", 25),
            "diesel_capex_per_kw":       fp("diesel_capex_per_kw", 400.0),
            "diesel_opex_per_kw_year":   fp("diesel_opex_per_kw_year", 20.0),
            "diesel_lifetime_years":     ip("diesel_lifetime_years", 15),
            "battery_capex_per_kwh":     fp("battery_capex_per_kwh", 388.0),
            "battery_opex_per_kwh_year": fp("battery_opex_per_kwh_year", 7.5),
            "battery_lifetime_years":    ip("battery_lifetime_years", 15),
            "discount_rate":             fp("discount_rate", 0.05),
            "project_lifetime_years":    ip("project_lifetime_years", 25),
        },
    }
    dispatch_mode = p.get("dispatch_mode", "renewable_priority")

    # ── Fetch / generate weather ──────────────────────────────────────────────
    weather = fetch_weather(lat, lon, year)
    hours   = weather["datetime"]

    # ── Physics models ────────────────────────────────────────────────────────
    demand        = calculate_demand(weather, cfg["station"])
    pv_out, pv_info   = model_solar_pv(weather, cfg["solar"])
    wind_out, wnd_info = model_wind(weather, cfg["wind"])
    dispatch      = run_dispatch(weather, demand, pv_out, wind_out,
                                  cfg["battery"], cfg["diesel"], dispatch_mode)
    costs         = calculate_costs(cfg, dispatch)

    # ── Aggregate for charts ──────────────────────────────────────────────────
    n = len(hours)

    # Daily averages (365 points)
    days, dem_d  = _downsample(hours, dispatch["demand"])
    _, sup_d     = _downsample(hours, dispatch["total_supply"])
    _, pv_d      = _downsample(hours, dispatch["pv"])
    _, wind_d    = _downsample(hours, dispatch["wind"])
    _, bsoc_d    = _downsample(hours, dispatch["bsoc"])
    _, curt_d    = _downsample(hours, dispatch["curt"])
    _, pv2l_d    = _downsample(hours, dispatch["pv2l"])
    _, w2l_d     = _downsample(hours, dispatch["w2l"])
    _, bdis_d    = _downsample(hours, dispatch["bdis"])
    _, dsl_d     = _downsample(hours, dispatch["dout"])

    surplus_d = [sup_d[i]-dem_d[i] for i in range(len(days))]
    batt_cap = cfg["battery"]["capacity_kwh"]
    soc_pct_d = [bsoc_d[i] / batt_cap * 100 if batt_cap > 0 else 0.0 for i in range(len(days))]

    # Smooth weekly for weather
    temp_week = _weekly_smooth(weather["temp"])
    wind_week = _weekly_smooth(weather["ws"])
    _, temp_d  = _downsample(hours, temp_week)
    _, wind_spd_d = _downsample(hours, weather["ws"])

    # Monthly (12 points) MWh
    dem_monthly  = _monthly(hours, dispatch["demand"])
    re_monthly   = _monthly(hours, [dispatch["pv"][i]+dispatch["wind"][i] for i in range(n)])
    dsl_monthly  = _monthly(hours, dispatch["dout"])

    # KPIs
    td  = sum(dispatch["demand"])
    re_served = sum(dispatch["pv2l"]) + sum(dispatch["w2l"]) + sum(dispatch["bdis"])
    re_frac   = re_served / max(td, 1) * 100
    fuel_l    = sum(dispatch["dfuel"])
    unmet_mwh = sum(dispatch["unm"]) / 1000
    curt_mwh  = sum(dispatch["curt"]) / 1000
    avg_demand= sum(dispatch["demand"]) / n
    peak_dem  = max(dispatch["demand"])

    return {
        "station": cfg["station"]["name"],
        "lat": lat, "lon": lon,
        "kpis": {
            "annual_demand_mwh":  round(td/1000, 1),
            "re_fraction_pct":    round(re_frac, 1),
            "diesel_fraction_pct":round(100-re_frac, 1),
            "fuel_consumed_l":    round(fuel_l),
            "unmet_demand_mwh":   round(unmet_mwh, 2),
            "curtailed_mwh":      round(curt_mwh, 1),
            "avg_demand_kw":      round(avg_demand, 1),
            "peak_demand_kw":     round(peak_dem, 1),
            "pv_generation_mwh":  round(sum(pv_out)/1000, 1),
            "wind_generation_mwh":round(sum(wind_out)/1000, 1),
            "diesel_generation_mwh": round(sum(dispatch["dout"])/1000, 1),
            "curtailed_mwh":      round(curt_mwh, 1),
            "num_panels":         pv_info["num_panels"],
            "num_turbines":       wnd_info["num_turbines"],
        },
        "costs": costs,
        "charts": {
            "days": days,
            "demand_daily":   [round(v,2) for v in dem_d],
            "supply_daily":   [round(v,2) for v in sup_d],
            "pv_daily":       [round(v,2) for v in pv_d],
            "wind_daily":     [round(v,2) for v in wind_d],
            "surplus_daily":  [round(v,2) for v in surplus_d],
            "soc_pct_daily":  [round(v,1) for v in soc_pct_d],
            "pv2l_daily":     [round(v,2) for v in pv2l_d],
            "w2l_daily":      [round(v,2) for v in w2l_d],
            "bdis_daily":     [round(v,2) for v in bdis_d],
            "diesel_daily":   [round(v,2) for v in dsl_d],
            "temp_daily":     [round(v,1) for v in temp_d],
            "wind_spd_daily": [round(v,2) for v in wind_spd_d],
            "months": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
            "demand_monthly": [round(v,1) for v in dem_monthly],
            "re_monthly":     [round(v,1) for v in re_monthly],
            "diesel_monthly": [round(v,1) for v in dsl_monthly],
        },
        "weather_source": weather.get("source","synthetic"),
        "year": year,
    }
