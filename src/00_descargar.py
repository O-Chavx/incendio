"""Paso 0 · Descargar los datos crudos a data/raw/ (no requieren clave ni pago).

Ojo: FIRMS publica solo los ÚLTIMOS 7 DÍAS. Si lo corres otro día, los focos
cambian y el id del incendio en config.py ya no será el mismo.
"""

from pathlib import Path

import requests

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

ARCHIVOS = {
    "firms_snpp_sa_7d.csv": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_America_7d.csv",
    "firms_noaa20_sa_7d.csv": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_America_7d.csv",
    "peru_distrital_simple.geojson": "https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_distrital_simple.geojson",
    "per_ppp_2020_1km.tif": "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2020/PER/per_ppp_2020_1km_Aggregated.tif",
}

for nombre, url in ARCHIVOS.items():
    destino = RAW / nombre
    if destino.exists():
        print(f"ya existe  {nombre}")
        continue
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    destino.write_bytes(r.content)
    print(f"descargado {nombre} ({len(r.content) / 1e6:.1f} MB)")
