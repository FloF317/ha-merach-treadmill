<img src="custom_components/merach_treadmill/brand/icon.png" alt="Logo" width="128" align="right">

# Merach Laufband (FitShow) für Home Assistant

Custom Home Assistant Integration für Merach-Laufbänder (getestet mit `MRK-T21-…`), die sich per Bluetooth über das **FitShow-Protokoll** steuern lassen (Service `FFF0`, Write `FFF2`, Notify `FFF1`).

Das Laufband meldet zwar FTMS (`0x1826`), lehnt FTMS-Steuerbefehle aber mit „Control Not Permitted“ ab. Die Merach-App steuert es stattdessen über FitShow, und genau das nutzt diese Integration.

## Funktionen
- **Buttons:** Start (mit Countdown), Stopp
- **Schieberegler:** Zielgeschwindigkeit (1,0–6,0 km/h)
- **Sensoren:** Status, Geschwindigkeit, Trainingszeit, Distanz, Verbunden

Die Geschwindigkeit kommt aus den FTMS-Daten (`0x2ACD`). Trainingszeit und Distanz zählt die Integration selbst mit, weil das Laufband dafür nur Nullen meldet.

## Installation über HACS
1. HACS → ⋮ → **Benutzerdefinierte Repositories** → `https://github.com/FloF317/ha-merach-treadmill`, Typ **Integration**
2. „Merach Laufband (FitShow)“ installieren und Home Assistant neu starten
3. Laufband einschalten. Es wird per Bluetooth automatisch gefunden, sonst über *Integration hinzufügen → Merach* einrichten

Die Merach-App und andere FTMS-Integrationen dürfen nicht gleichzeitig verbunden sein.

## Protokoll
Frame: `02 <cmd> <daten…> <xor(cmd+daten)> 03`

| Befehl | Bytes |
|---|---|
| Status abfragen | `02 51 51 03` |
| Start | `02 53 01 00 00 00 00 00 00 00 00 52 03` |
| Stopp | `02 53 03 50 03` |
| Geschwindigkeit (0,1 km/h) | `02 53 02 <speed> 00 <xor> 03` |

Statusantwort im Betrieb: `02 51 03 <speed> <incline> <zeit LE16> <distanz LE16> <kcal LE16> <schritte LE16> … <xor> 03`.
Beim MRK-T21 sind Zeit, Distanz, Kalorien und Schritte in der Statusantwort immer 0.

## Debug-Logs
```yaml
logger:
  logs:
    custom_components.merach_treadmill: debug
```
