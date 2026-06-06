#!/usr/bin/env python3
"""
Actualiza monitor_data.json leyendo datos desde Google Sheets (CSV público).

Tabs confirmados:
  GID 428953227  → Daily KPIs (FECHA, ORDERS, GMV_MXN … ~889 filas)
  GID 1492498804 → WTD Brands (KAM_NOMBRE, GMV_CURR, GMV_PREV … ~174 filas)
  Pareto         → derivado del WTD (mismas marcas, campos renombrados)

Requiere que la hoja sea pública ("Cualquier persona con el enlace puede ver").
Si la hoja es privada, define GOOGLE_CREDENTIALS con el JSON de una
cuenta de servicio que tenga acceso a la hoja.
"""

import csv, io, json, os, sys, urllib.request, urllib.error
from datetime import date, timedelta

SHEET_ID   = "1Pa3xqvL4nZQ0hGERpo4QLQFBO9abXSuLGHAO_Gu98ns"
GID_DAILY  = "428953227"
GID_WTD    = "1492498804"
OUT_FILE   = os.path.join(os.path.dirname(__file__), "..", "monitor_data.json")

def csv_url(gid: str) -> str:
    return (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
            f"/export?format=csv&gid={gid}")

# ── Fetch ────────────────────────────────────────────────────────────────────

def fetch_public(url: str) -> str:
    req = urllib.request.Request(url,
          headers={"User-Agent": "Mozilla/5.0 (dashboard-updater/2.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8-sig")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("ERROR 401 – La hoja NO es pública.\n"
                  "Solución: Compartir → 'Cualquier persona con el enlace' = Lector.")
            sys.exit(1)
        raise

def fetch_service_account(url: str, creds_json: str) -> str:
    try:
        import google.auth.transport.requests, google.oauth2.service_account as sa, requests
    except ImportError:
        os.system(f"{sys.executable} -m pip install google-auth requests -q")
        import google.auth.transport.requests, google.oauth2.service_account as sa, requests
    creds = sa.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    creds.refresh(google.auth.transport.requests.Request())
    r = requests.get(url, headers={"Authorization": f"Bearer {creds.token}"})
    r.raise_for_status()
    return r.text

def get_csv(gid: str) -> str:
    url   = csv_url(gid)
    creds = os.environ.get("GOOGLE_CREDENTIALS")
    return fetch_service_account(url, creds) if creds else fetch_public(url)

# ── Parsing ───────────────────────────────────────────────────────────────────

SKIP_FIRST = {"Data Warehouse Connection", "Query", "Rows", "Result Size",
              "Last Updated", "Aleph | Explore", ""}

def _is_skip(row: list[str]) -> bool:
    return not row or row[0] in SKIP_FIRST or row[0].startswith(":-")

def parse_table(csv_text: str, expected_first_col: str) -> list[dict]:
    """
    Encuentra la fila cuyo primer campo = expected_first_col (cabecera),
    luego acumula filas de datos hasta la primera fila vacía/metadata.
    Elimina celdas vacías iniciales de cada fila (quirk de Google Sheets CSV).
    """
    reader = csv.reader(io.StringIO(csv_text))
    header, records, in_table = None, [], False

    for raw in reader:
        # Eliminar celdas vacías iniciales
        row = [c.strip() for c in raw]
        while row and row[0] == "":
            row = row[1:]

        if not row or _is_skip(row):
            if in_table:
                break      # fin de la tabla
            continue

        if header is None and row[0] == expected_first_col:
            header = row
            in_table = True
            continue

        if in_table and header:
            records.append({header[i]: row[i] if i < len(row) else ""
                            for i in range(len(header))})

    return records

# ── Conversores ───────────────────────────────────────────────────────────────

def _f(v) -> float | None:
    s = str(v).replace("\\", "").replace(",", "").strip()
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def build_daily(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        fecha = r.get("FECHA", "")
        if " " in fecha:
            fecha = fecha.split(" ")[0]
        if not fecha:
            continue
        out.append({
            "FECHA":                 fecha,
            "ORDERS":                _f(r.get("ORDERS")),
            "GMV_MXN":               _f(r.get("GMV_MXN")),
            "SALES_USD":             _f(r.get("SALES_USD")),
            "AOV_MXN":               _f(r.get("AOV_MXN")),
            "MKD_PCT_GMV":           _f(r.get("MKD_PCT_GMV")),
            "MKD_PRIME_MXN":         _f(r.get("MKD_PRIME_MXN")),
            "TOTAL_RAPPI_SPEND_MXN": _f(r.get("TOTAL_RAPPI_SPEND_MXN")),
            "TRAFFIC_SS":            _f(r.get("TRAFFIC_SS")),
            "CVR_PCT":               _f(r.get("CVR_PCT")),
            "REVENUE_MXN":           _f(r.get("REVENUE_MXN")),
            "BURN_RAPPI_MXN":        _f(r.get("BURN_RAPPI_MXN")),
            "COMMISSION_PCT":        _f(r.get("COMMISSION_PCT")),
            "AVAILABILITY_PCT":      _f(r.get("AVAILABILITY_PCT")),
            "CANCEL_RATE_PCT":       _f(r.get("CANCEL_RATE_PCT")),
            "DEFECT_RATE_PCT":       _f(r.get("DEFECT_RATE_PCT")),
            "STORES_WITH_SALES":     _f(r.get("TIENDAS_CON_VENTA")),
            "BOOKINGS":              0.0,
        })
    return out

def build_wtd(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r.get("KAM_NOMBRE"):
            continue
        out.append({
            "KAM_NOMBRE":       r.get("KAM_NOMBRE", ""),
            "KAM_EMAIL":        r.get("KAM_EMAIL", ""),
            "BRAND_NAME":       r.get("BRAND_NAME", ""),
            "GMV_CURR":         _f(r.get("GMV_CURR")),
            "GMV_PREV":         _f(r.get("GMV_PREV")),
            "GMV_DELTA_PCT":    _f(r.get("GMV_DELTA_PCT")),
            "ORDERS_CURR":      _f(r.get("ORDERS_CURR")),
            "ORDERS_PREV":      _f(r.get("ORDERS_PREV")),
            "ORDERS_DELTA_PCT": _f(r.get("ORDERS_DELTA_PCT")),
            "CANCEL_CURR_PCT":  _f(r.get("CANCEL_CURR_PCT")),
            "DEFECT_CURR_PCT":  _f(r.get("DEFECT_CURR_PCT")),
        })
    return out

def build_pareto_from_wtd(wtd: list[dict]) -> list[dict]:
    """
    El tab de pareto MTD tiene sólo GMV y ORDERS actuales (sin prev/delta).
    Usamos WTD para tener prev/delta en Alertas, y GMV_CURR como GMV_MXN.
    """
    out = []
    for r in wtd:
        out.append({
            "BRAND_NAME":       r.get("BRAND_NAME", ""),
            "KAM_NOMBRE":       r.get("KAM_NOMBRE", ""),
            "KAM_EMAIL":        r.get("KAM_EMAIL", ""),
            "GMV_MXN":          r.get("GMV_CURR"),
            "GMV_PREV":         r.get("GMV_PREV"),
            "GMV_DELTA_PCT":    r.get("GMV_DELTA_PCT"),
            "ORDERS":           r.get("ORDERS_CURR"),
            "ORDERS_PREV":      r.get("ORDERS_PREV"),
            "ORDERS_DELTA_PCT": r.get("ORDERS_DELTA_PCT"),
        })
    return out

def build_meta(daily: list[dict], pareto: list[dict]) -> dict:
    today     = date.today()
    yesterday = today - timedelta(days=1)

    days_to_sat = (today.weekday() + 2) % 7
    curr_sat = today - timedelta(days=days_to_sat)
    curr_mon = curr_sat - timedelta(days=5)
    prev_sat = curr_sat - timedelta(days=7)
    prev_mon = prev_sat - timedelta(days=5)

    mtd_start       = date(today.year, today.month, 1)
    prev_month_end  = mtd_start - timedelta(days=1)
    prev_month_start= date(prev_month_end.year, prev_month_end.month, 1)

    last_date = yesterday.isoformat()
    if daily:
        fechas = [r["FECHA"] for r in daily if r.get("FECHA")]
        if fechas:
            last_date = max(fechas)

    return {
        "updated":       last_date,
        "wtd_curr":      [curr_mon.isoformat(), curr_sat.isoformat()],
        "wtd_prev":      [prev_mon.isoformat(), prev_sat.isoformat()],
        "mtd_curr":      [mtd_start.isoformat(), yesterday.isoformat()],
        "mtd_prev":      [prev_month_start.isoformat(), prev_month_end.isoformat()],
        "t90_start":     (yesterday - timedelta(days=89)).isoformat(),
        "t90_end":       yesterday.isoformat(),
        "pareto_brands": len(pareto),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("📥 Descargando Daily (GID 428953227)…")
    daily_csv = get_csv(GID_DAILY)
    daily_raw = parse_table(daily_csv, "FECHA")
    print(f"   Daily : {len(daily_raw)} filas")

    print("📥 Descargando WTD Brands (GID 1492498804)…")
    wtd_csv = get_csv(GID_WTD)
    wtd_raw = parse_table(wtd_csv, "KAM_NOMBRE")
    print(f"   WTD   : {len(wtd_raw)} filas")

    if len(daily_raw) == 0:
        print("❌ Sin datos en Daily. Revisa que la hoja sea pública.")
        sys.exit(1)
    if len(wtd_raw) == 0:
        print("❌ Sin datos en WTD. Revisa que la hoja sea pública.")
        sys.exit(1)

    daily  = build_daily(daily_raw)
    wtd    = build_wtd(wtd_raw)
    pareto = build_pareto_from_wtd(wtd)
    meta   = build_meta(daily, pareto)

    output = {"meta": meta, "daily": daily, "pareto": pareto, "wtd": wtd}

    out_path = os.path.normpath(OUT_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(out_path) / 1024
    print(f"✅ {out_path} actualizado ({size_kb:.0f} KB)")
    print(f"   Datos hasta : {meta['updated']}")
    print(f"   WTD curr    : {meta['wtd_curr'][0]} → {meta['wtd_curr'][1]}")
    print(f"   Marcas      : {meta['pareto_brands']}")

if __name__ == "__main__":
    main()
