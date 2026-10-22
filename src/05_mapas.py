"""Paso 5 · Mapas y gráficos para el README y el dashboard (carpeta outputs/)."""

import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from config import CLASES_DNBR

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
OUT = RAIZ / "outputs"
OUT.mkdir(exist_ok=True)

plt.rcParams.update({"figure.dpi": 130, "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})

COLORES_SEV = ["#1a9850", "#fee08b", "#fdae61", "#f46d43", "#a50026"]
info = json.load(open(PROC / "incendio_info.json"))
res = json.load(open(PROC / "resumen_dnbr.json"))


def leer(nombre):
    with rasterio.open(PROC / nombre) as src:
        return src.read(), src.bounds, src.crs


def estirar(rgb):
    """Estira el contraste al percentil 2-98 para que la imagen se vea natural."""
    rgb = np.moveaxis(rgb, 0, -1)
    lo, hi = np.nanpercentile(rgb, [2, 98])
    return np.clip((rgb - lo) / (hi - lo), 0, 1)


antes, b, crs = leer("rgb_antes.tif")
despues, _, _ = leer("rgb_despues.tif")
dnbr = leer("dnbr.tif")[0][0]
sev = leer("severidad.tif")[0][0]
ext = [b.left, b.right, b.bottom, b.top]

focos = gpd.read_file(PROC / "focos_peru.geojson")
focos = focos[focos["incendio_id"] == info["incendio_id"]].to_crs(crs)
quemado = gpd.read_file(PROC / "quemado.geojson").to_crs(crs)
aoi = gpd.read_file(PROC / "aoi.geojson").to_crs(crs)

# 1 · Antes / después / dNBR --------------------------------------------------------
fig, ax = plt.subplots(1, 3, figsize=(13, 4.6))
ax[0].imshow(estirar(antes), extent=ext)
ax[0].set_title("Antes · Sentinel-2, 5 oct 2026")
ax[1].imshow(estirar(despues), extent=ext)
ax[1].set_title("Después · Sentinel-2, 17 oct 2026")
im = ax[2].imshow(dnbr, extent=ext, cmap="RdYlGn_r", vmin=-0.2, vmax=0.7)
ax[2].set_title("dNBR = NBR antes − NBR después")
fig.colorbar(im, ax=ax[2], fraction=0.046, label="dNBR")
for a in ax:
    aoi.boundary.plot(ax=a, color="white", lw=0.8, ls="--")
    a.set_xticks([]); a.set_yticks([]); a.set_xlabel(""); a.set_ylabel("")
fig.suptitle("Incendio de Huanoquite (Paruro, Cusco) · octubre 2026", fontsize=11, weight="bold")
fig.tight_layout()
fig.savefig(OUT / "01_antes_despues_dnbr.png", bbox_inches="tight")
plt.close(fig)

# 2 · Severidad + focos VIIRS -------------------------------------------------------
fig, ax = plt.subplots(figsize=(7.5, 6))
sev_m = np.ma.masked_equal(sev, 0)
ax.imshow(estirar(despues), extent=ext, alpha=0.55)
ax.imshow(sev_m, extent=ext, cmap=ListedColormap(COLORES_SEV), vmin=0.5, vmax=5.5,
          alpha=np.where(sev_m.filled(0) >= 3, 0.9, 0.35))
quemado.boundary.plot(ax=ax, color="black", lw=0.6)
focos.plot(ax=ax, color="cyan", edgecolor="black", markersize=14, lw=0.4, zorder=5)
leyenda = [Patch(color=c, label=n) for c, (_, _, n) in zip(COLORES_SEV, CLASES_DNBR)]
leyenda.append(plt.Line2D([], [], marker="o", ls="", color="cyan", mec="black", label=f"Foco VIIRS ({len(focos)})"))
ax.legend(handles=leyenda, loc="lower left", fontsize=7.5, title="Severidad dNBR", title_fontsize=8)
ax.set_title(f"Área quemada: {res['ha_quemadas']:,.0f} ha (dNBR ≥ {res['umbral']})", weight="bold")
ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(""); ax.set_ylabel("")
fig.tight_layout()
fig.savefig(OUT / "02_mapa_severidad.png", bbox_inches="tight")
plt.close(fig)

# 3 · ¿Qué se quemó? ----------------------------------------------------------------
cob = pd.read_csv(PROC / "cobertura_quemada.csv")
cob = cob[cob["ha_quemadas"] > 0]
colores_cob = {"Pastizal": "#d9b44a", "Bosque": "#2d6a2d", "Matorral": "#8a9a3b", "Cultivo": "#e07b39",
               "Urbano": "#7a7a7a"}
fig, ax = plt.subplots(figsize=(6.5, 3))
ax.barh(cob["cobertura"], cob["ha_quemadas"], color=[colores_cob.get(c, "#999") for c in cob["cobertura"]])
for y, (ha, pct) in enumerate(zip(cob["ha_quemadas"], cob["pct_de_lo_quemado"])):
    ax.text(ha + 4, y, f"{ha:,.0f} ha · {pct:.0f} %", va="center", fontsize=8)
ax.invert_yaxis()
ax.set_xlabel("Hectáreas quemadas (ESA WorldCover 2021)")
ax.set_title("¿Qué se quemó?", weight="bold", loc="left")
ax.set_xlim(0, cob["ha_quemadas"].max() * 1.3)
fig.tight_layout()
fig.savefig(OUT / "03_que_se_quemo.png", bbox_inches="tight")
plt.close(fig)

# 4 · Sensibilidad: el número depende de las decisiones -----------------------------
sens = pd.read_csv(PROC / "sensibilidad.csv")
piv = sens.pivot(index="umbral_dnbr", columns="imagen_despues", values="hectareas")
fig, ax = plt.subplots(figsize=(6.5, 3.2))
piv.plot.bar(ax=ax, color=["#9ecae1", "#08519c"], rot=0, width=0.75)
for c in ax.containers:
    ax.bar_label(c, fmt="%.0f", fontsize=7.5)
ax.set_xlabel("Umbral de dNBR para llamar «quemado» a un píxel")
ax.set_ylabel("Hectáreas")
ax.set_title("Mismo incendio, otras decisiones: 14 a 923 ha", weight="bold", loc="left")
ax.legend(fontsize=7.5, title=None)
fig.tight_layout()
fig.savefig(OUT / "04_sensibilidad.png", bbox_inches="tight")
plt.close(fig)

# 5 · Población a 5 km ----------------------------------------------------------------
pob = json.load(open(PROC / "poblacion.json"))
buf = gpd.read_file(PROC / "buffer_5km.geojson")
distritos = gpd.read_file(RAIZ / "data" / "raw" / "peru_distrital_simple.geojson")
with rasterio.open(RAIZ / "data" / "raw" / "per_ppp_2020_1km.tif") as src:
    x0, y0, x1, y1 = buf.total_bounds + np.array([-0.08, -0.08, 0.08, 0.08])
    ventana = rasterio.windows.from_bounds(x0, y0, x1, y1, transform=src.transform)
    wp = src.read(1, window=ventana)
    wb = rasterio.windows.bounds(ventana, src.transform)
wp = np.ma.masked_less(wp, 0)
fig, ax = plt.subplots(figsize=(6.5, 5.5))
im = ax.imshow(wp, extent=[wb[0], wb[2], wb[1], wb[3]], cmap="Purples", vmax=np.percentile(wp.compressed(), 99))
fig.colorbar(im, ax=ax, fraction=0.04, label="Personas por km² (WorldPop 2020)")
distritos.boundary.plot(ax=ax, color="gray", lw=0.5)
buf.boundary.plot(ax=ax, color="black", lw=1.2, ls="--")
gpd.read_file(PROC / "quemado.geojson").plot(ax=ax, color="#d7301f")
for _, d in distritos.dropna(subset=["geometry"]).iterrows():
    c = d.geometry.representative_point()
    if x0 < c.x < x1 and y0 < c.y < y1:
        ax.annotate(d["NOMBDIST"].title(), (c.x, c.y), fontsize=7, ha="center", color="#333")
ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
ax.set_title(f"{pob['a_5km']:,} personas viven a ≤ 5 km del área quemada", weight="bold", loc="left")
ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(""); ax.set_ylabel("")
fig.tight_layout()
fig.savefig(OUT / "05_poblacion_5km.png", bbox_inches="tight")
plt.close(fig)

print("Gráficos guardados en outputs/:", sorted(p.name for p in OUT.glob("*.png")))
