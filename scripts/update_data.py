#!/usr/bin/env python3
"""
Actualiza monitor_data.json leyendo datos desde Google Sheets.

Requiere que la hoja sea pública ("Cualquier persona con el enlace puede ver")
O que exista la variable de entorno GOOGLE_CREDENTIALS con el JSON
de una cuenta de servicio que tenga acceso a la hoja.

Sheet ID : 1Pa3xqvL4nZQ0hGERpo4QLQFBO9abXSuLGHAO_Gu98ns
GID tab  : 1492498804
"""

import csv
import io
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import date, timedelta

# ── Configuración ────────────────────────────────────────────────
SHEET_ID = "1Pa3xqvL4nZQ0hGERpo4QLQFBO9abXSuLGHAO_Gu98ns"
GID      = "1492498804"
OUT_FILE = os.path.join(os.path.dirname(__file__), "..", "monitor_data.json")

CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={GID}"
)

# ── Fetch ────────────────────────────────────────────────────────
def fetch_csv_public(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (dashboard-updater/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8-sig")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(
                "ERROR 401 – La hoja NO es pública.\n"
                "Solución: en Google Sheets ve a Archivo → Compartir → "
                "Compartir con otros → cambia a 'Cualquier persona con el enlace' = Lector.\n"
                "O configura GOOGLE_CREDENTIALS con una cuenta de servicio."
            )
            sys.exit(1)
        raise


def fetch_csv_service_account(url: str, creds_json: str) -> str:
    """Usa google-auth + requests si GOOGLE_CREDENTIALS está definido."""
    try:
        import google.auth.transport.requests
        import google.oauth2.service_account as sa
        import requests
    except ImportError:
        print("Instalando dependencias para cuenta de servicio…")
        os.system(f"{sys.executable} -m pip install google-auth requests -q")
        import google.auth.transport.requests
        import google.oauth2.service_account as sa
        import requests

    creds_info = json.loads(creds_json)
    creds = sa.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    resp = requests.get(url, headers={"Authorization": f"Bearer {creds.token}"})
    resp.raise_for_status()
    return resp.text


def get_csv() -> str:
    creds = os.environ.get("GOOGLE_CREDENTIALS")
    if creds:
        print("Usando cuenta de servicio (GOOGLE_CREDENTIALS)")
        return fetch_csv_service_account(CSV_URL, creds)
    print("Usando acceso público")
    return fetch_csv_public(CSV_URL)


# ── Parsing ──────────────────────────────────────────────────────
def _float(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace("\\", "").replace(",", "").strip()
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_metadata_row(row: list[str]) -> bool:
    if not row:
        return True
    f = row[0].strip()
    return f in (
        "Data Warehouse Connection", "Query", "Rows",
        "Result Size", "Last Updated", ":-:", "",
    ) or f.startswith(":-")


def parse_sections(csv_text: str):
    reader = csv.reader(io.StringIO(csv_text))
    rows = [r for r in reader]

    daily_raw, wtd_raw, pareto_raw = [], [], []
    section, header = None, []

    for row in rows:
        # Normalizar
        row = [c.strip() for c in row]

        # Saltar filas vacías / metadatos → resetean sección
        if not row or all(c == "" for c in row) or _is_metadata_row(row):
            section = None
            continue

        first = row[0]

        # ── Detectar cabeceras de sección ──
        if first == "FECHA":
            section, header = "daily", row
            continue

        if (first == "KAM_NOMBRE"
                and len(row) > 3
                and row[3] in ("GMV_CURR", "GMV_PREV")):
            section, header = "wtd", row
            continue

        # Pareto: BRAND_NAME | KAM_NOMBRE | KAM_EMAIL | GMV_MXN | ORDERS
        if (first == "BRAND_NAME"
                and len(row) > 1
                and row[1] == "KAM_NOMBRE"):
            section, header = "pareto", row
            continue

        # ── Acumular filas de datos ──
        if section and header:
            obj = {header[i]: row[i] if i < len(row) else ""
                   for i in range(len(header))}
            if section == "daily":
                daily_raw.append(obj)
            elif section == "wtd":
                wtd_raw.append(obj)
            elif section == "pareto":
                pareto_raw.append(obj)

    return daily_raw, wtd_raw, pareto_raw


# ── Transformaciones ─────────────────────────────────────────────
def build_daily(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        fecha = r.get("FECHA", "")
        if " " in fecha:                       # "2024-01-01 00:00:00.000" → "2024-01-01"
            fecha = fecha.split(" ")[0]
        if not fecha or fecha == "FECHA":
            continue
        out.append({
            "FECHA":                  fecha,
            "ORDERS":                 _float(r.get("ORDERS")),
            "GMV_MXN":                _float(r.get("GMV_MXN")),
            "SALES_USD":              _float(r.get("SALES_USD")),
            "AOV_MXN":                _float(r.get("AOV_MXN")),
            "MKD_PCT_GMV":            _float(r.get("MKD_PCT_GMV")),
            "MKD_PRIME_MXN":          _float(r.get("MKD_PRIME_MXN")),
            "TOTAL_RAPPI_SPEND_MXN":  _float(r.get("TOTAL_RAPPI_SPEND_MXN")),
            "TRAFFIC_SS":             _float(r.get("TRAFFIC_SS")),
            "CVR_PCT":                _float(r.get("CVR_PCT")),
            "REVENUE_MXN":            _float(r.get("REVENUE_MXN")),
            "BURN_RAPPI_MXN":         _float(r.get("BURN_RAPPI_MXN")),
            "COMMISSION_PCT":         _float(r.get("COMMISSION_PCT")),
            "AVAILABILITY_PCT":       _float(r.get("AVAILABILITY_PCT")),
            "CANCEL_RATE_PCT":        _float(r.get("CANCEL_RATE_PCT")),
            "DEFECT_RATE_PCT":        _float(r.get("DEFECT_RATE_PCT")),
            # TIENDAS_CON_VENTA en la hoja → STORES_WITH_SALES en el JSON
            "STORES_WITH_SALES":      _float(r.get("TIENDAS_CON_VENTA")),
            "BOOKINGS":               0.0,
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
            "GMV_CURR":         _float(r.get("GMV_CURR")),
            "GMV_PREV":         _float(r.get("GMV_PREV")),
            "GMV_DELTA_PCT":    _float(r.get("GMV_DELTA_PCT")),
            "ORDERS_CURR":      _float(r.get("ORDERS_CURR")),
            "ORDERS_PREV":      _float(r.get("ORDERS_PREV")),
            "ORDERS_DELTA_PCT": _float(r.get("ORDERS_DELTA_PCT")),
            "CANCEL_CURR_PCT":  _float(r.get("CANCEL_CURR_PCT")),
            "DEFECT_CURR_PCT":  _float(r.get("DEFECT_CURR_PCT")),
        })
    return out


def build_pareto(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r.get("BRAND_NAME"):
            continue
        out.append({
            "BRAND_NAME":         r.get("BRAND_NAME", ""),
            "KAM_NOMBRE":         r.get("KAM_NOMBRE", ""),
            "KAM_EMAIL":          r.get("KAM_EMAIL", ""),
            "GMV_MXN":            _float(r.get("GMV_MXN")),
            "GMV_PREV":           None,      # no disponible en sección pareto
            "GMV_DELTA_PCT":      None,
            "ORDERS":             _float(r.get("ORDERS")),
            "ORDERS_PREV":        None,
            "ORDERS_DELTA_PCT":   None,
        })
    return out


def build_meta(daily: list[dict], pareto: list[dict]) -> dict:
    today = date.today()
    yesterday = today - timedelta(days=1)

    # ── WTD: lun-sáb semana actual vs semana anterior ────────────
    # weekday(): Mon=0 … Sun=6  →  días desde el último sábado = (weekday+2)%7
    days_to_sat = (today.weekday() + 2) % 7
    curr_sat  = today - timedelta(days=days_to_sat)
    curr_mon  = curr_sat - timedelta(days=5)
    prev_sat  = curr_sat - timedelta(days=7)
    prev_mon  = prev_sat - timedelta(days=5)

    # ── MTD ──────────────────────────────────────────────────────
    mtd_start      = date(today.year, today.month, 1)
    prev_month_end = mtd_start - timedelta(days=1)
    prev_month_sta = date(prev_month_end.year, prev_month_end.month, 1)

    # ── T90 ──────────────────────────────────────────────────────
    t90_start = yesterday - timedelta(days=89)

    # Fecha más reciente en datos diarios
    last_date = yesterday.isoformat()
    if daily:
        fechas = [r["FECHA"] for r in daily if r.get("FECHA")]
        if fechas:
            last_date = max(fechas)

    return {
        "updated":    last_date,
        "wtd_curr":   [curr_mon.isoformat(), curr_sat.isoformat()],
        "wtd_prev":   [prev_mon.isoformat(), prev_sat.isoformat()],
        "mtd_curr":   [mtd_start.isoformat(), yesterday.isoformat()],
        "mtd_prev":   [prev_month_sta.isoformat(), prev_month_end.isoformat()],
        "t90_start":  t90_start.isoformat(),
        "t90_end":    yesterday.isoformat(),
        "pareto_brands": len(pareto),
    }


# ── Main ─────────────────────────────────────────────────────────
def main():
    print(f"📥 Descargando datos de Google Sheets…")
    csv_text = get_csv()

    print("🔍 Procesando secciones…")
    daily_raw, wtd_raw, pareto_raw = parse_sections(csv_text)
    print(f"   Daily  : {len(daily_raw)} filas")
    print(f"   WTD    : {len(wtd_raw)} filas")
    print(f"   Pareto : {len(pareto_raw)} filas")

    if len(daily_raw) == 0:
        print("❌ No se encontraron datos en la sección DAILY. Revisa que la hoja sea pública.")
        sys.exit(1)

    daily  = build_daily(daily_raw)
    wtd    = build_wtd(wtd_raw)
    pareto = build_pareto(pareto_raw)
    meta   = build_meta(daily, pareto)

    output = {"meta": meta, "daily": daily, "pareto": pareto, "wtd": wtd}

    out_path = os.path.normpath(OUT_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(out_path) / 1024
    print(f"✅ {out_path} actualizado")
    print(f"   Datos hasta   : {meta['updated']}")
    print(f"   WTD curr      : {meta['wtd_curr'][0]} → {meta['wtd_curr'][1]}")
    print(f"   MTD curr      : {meta['mtd_curr'][0]} → {meta['mtd_curr'][1]}")
    print(f"   Tamaño archivo: {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
