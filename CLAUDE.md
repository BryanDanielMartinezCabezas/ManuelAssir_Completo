# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Manuel Assist** is a robotic assistive glove for people with reduced mobility. The glove translates finger movements from IMU sensors into keyboard/mouse commands on a PC via Wi-Fi UDP. This is an academic project (Robotics I — COM 480, USFX Bolivia). The AI/software responsibility belongs to Bryan Daniel Martínez Cabezas.

The full project context (hardware specs, gesture definitions, parsing examples) is in [Agente/Prompt_Global.md](Agente/Prompt_Global.md) — read it before writing any code.

## Setup

```bash
pip install torch numpy pandas scikit-learn matplotlib seaborn pyautogui pynput
```

## Hardware & Data Pipeline

```
5× MPU6050 → TCA9548A (I2C, canales 2-6) → ESP32 WROOM-32 → Wi-Fi UDP (port 5005) → PC Python
```

- **Discovery**: ESP32 broadcasts on port 4210 (`HOLA_SOY_ESP32;IP=x.x.x.x;PORT=5005`); Python replies `HOLA_LAPTOP;LISTA=1`
- **Data rate**: Currently 500ms/frame; target is 33ms (~30fps) — ask Atzel to change `INTERVALO_ENVIO`
- **Channel-to-finger mapping**: Canal 2=Pulgar, 3=Índice, 4=Medio, 5=Anular, 6=Meñique

### Parsing UDP data

Each UDP block contains 5 lines like:
```
Canal 2 -> Ax:0.87 | Ay:-0.00 | Az:0.60 | Gx:-1.3 | Gy:1.2 | Gz:-0.5 | T:43.5 C
```

Extract exactly 6 floats per line (ax, ay, az, gx, gy, gz) — **ignore T (temperature)**. A full frame = 30 floats. The `parse_canal()` and `parse_bloque()` functions with regex are defined in [Agente/Prompt_Global.md](Agente/Prompt_Global.md).

## AI Model

- **Architecture**: MLP — `Input(450) → FC(256) → BN → ReLU → Dropout(0.3) → FC(128) → BN → ReLU → Dropout(0.3) → FC(64) → BN → ReLU → Dropout(0.2) → FC(N_CLASSES) → Softmax`
- **Input**: 15 frames × 30 features = 450 values (no temperature, no EMG)
- **~20 gesture classes** (see full table in Prompt_Global.md)
- **Inference thresholds**: confidence ≥ 65%, hysteresis filter ≥ 200ms before executing an action
- **Training**: Adam (lr=1e-3, weight_decay=1e-4), CosineAnnealingLR, 60 epochs, batch 32, 70/15/15 split, StandardScaler normalization
- **Data augmentation**: Gaussian noise based on real per-sensor std; 100 real samples → 1000 per gesture

## Scripts to Build (in priority order)

| Script | Purpose | Output |
|--------|---------|--------|
| `grabar_datos.py` | Record UDP data + label gestures, apply DA | CSV file |
| `Manuel_Assist_Train.ipynb` | Train MLP (adapt from `Manuel_Assist_IA_Simulador.ipynb`) | `modelo.pth`, `scaler.pkl`, `metadata.json` |
| `receptor_manuel_assist.py` | Real-time inference + pyautogui/pynput PC control | — |

## CSV Format

```
timestamp, pulgar_ax..gz, indice_ax..gz, medio_ax..gz, anular_ax..gz, menique_ax..gz, gesto
```
32 columns total; one row = one frame; windows of 15 frames are assembled during training.

## Key Constraints

- The MLP runs on the **PC only** — the ESP32 sends raw text, nothing more.
- **Cursor control** is direct acelerometer mapping from the Índice sensor (canal 3) — not MLP classification.
- **EMG actions** (click, Windows key) use a fixed threshold, not the MLP — EMG sensor not yet connected.
- TCA9548A channels are **2,3,4,5,6** (not 0-4) — this is a hardware fact, do not "fix" it.
- Do not modify ESP32 firmware without coordinating with Atzel.
