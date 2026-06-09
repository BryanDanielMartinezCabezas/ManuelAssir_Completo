import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

files = {
    "btn_A":     "btn_A_20260609_003830.csv",
    "btn_B":     "btn_B_20260609_004958.csv",
    "btn_C":     "btn_C_20260609_010828.csv",
    "btn_D":     "btn_D_20260609_005927.csv",
    "abajo":     "abajo_20260609_012812.csv",
    "arriba":    "arriba_20260609_011937.csv",
    "derecha":   "derecha_20260609_013657.csv",
    "izquierda": "izquierda_20260609_014533.csv",
    "start":     "start_20260609_015854.csv",
    "reposo":    "reposo_20260609_034010.csv",
}

dedos = ["pulgar", "indice", "medio", "anular", "menique"]
ejes  = ["ax", "ay", "az", "gx", "gy", "gz"]

for gesto, fname in files.items():
    path = DATA_DIR / fname
    if not path.exists():
        print(f"\n=== {gesto.upper()} — ARCHIVO NO ENCONTRADO ===")
        continue
    df = pd.read_csv(path)
    print(f"\n{'='*60}")
    print(f"  {gesto.upper()}  ({len(df)} frames)")
    print(f"{'='*60}")
    for dedo in dedos:
        cols = [f"{dedo}_{e}" for e in ejes if f"{dedo}_{e}" in df.columns]
        if not cols:
            continue
        print(f"  [{dedo}]")
        for c in cols:
            eje = c.split("_")[1]
            mn  = df[c].min()
            mx  = df[c].max()
            med = df[c].mean()
            std = df[c].std()
            rng = mx - mn
            print(f"    {eje}:  min={mn:+.3f}  max={mx:+.3f}  rango={rng:.3f}  media={med:+.3f}  std={std:.3f}")
