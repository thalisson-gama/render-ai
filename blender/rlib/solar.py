"""Posicao solar a partir de data, hora, latitude e longitude.

Python puro, sem bpy. Da para testar fora do Blender:

    python3 blender/rlib/solar.py

Algoritmo de baixa precisao do NOAA (erro < 0.05 grau para os proximos
seculos), mais que suficiente para decidir por onde a luz entra na janela.
"""

import math
from datetime import datetime, timedelta


def _julian_day(dt_utc):
    y, m = dt_utc.year, dt_utc.month
    d = dt_utc.day + (dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600) / 24
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def sun_position(dt_local, tz_offset_hours, lat_deg, lon_deg):
    """Devolve (elevacao_graus, azimute_graus).

    Azimute e a bussola: 0 = Norte, 90 = Leste, 180 = Sul, 270 = Oeste.
    Elevacao negativa significa sol abaixo do horizonte.
    """
    dt_utc = dt_local - timedelta(hours=tz_offset_hours)
    n = _julian_day(dt_utc) - 2451545.0

    mean_long = math.radians((280.460 + 0.9856474 * n) % 360)
    mean_anom = math.radians((357.528 + 0.9856003 * n) % 360)

    ecl_long = mean_long + math.radians(
        1.915 * math.sin(mean_anom) + 0.020 * math.sin(2 * mean_anom)
    )
    obliquity = math.radians(23.439 - 0.0000004 * n)

    declination = math.asin(math.sin(obliquity) * math.sin(ecl_long))
    right_asc = math.atan2(
        math.cos(obliquity) * math.sin(ecl_long), math.cos(ecl_long)
    )

    gmst_hours = (18.697374558 + 24.06570982441908 * n) % 24
    local_sidereal = math.radians((gmst_hours * 15 + lon_deg) % 360)
    hour_angle = local_sidereal - right_asc

    lat = math.radians(lat_deg)
    elevation = math.asin(
        math.sin(lat) * math.sin(declination)
        + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    )
    azimuth = math.atan2(
        -math.sin(hour_angle),
        math.tan(declination) * math.cos(lat) - math.sin(lat) * math.cos(hour_angle),
    )

    return math.degrees(elevation), math.degrees(azimuth) % 360


def sun_direction(elevation_deg, azimuth_deg, north_angle_deg=0.0):
    """Vetor unitario que aponta DA cena PARA o sol, em coordenadas do modelo.

    Convencao: +Y do modelo aponta para a bussola `north_angle_deg`.
    Com north_angle_deg=0, +Y e o Norte e +X e o Leste.
    """
    az_model = math.radians(azimuth_deg - north_angle_deg)
    elev = math.radians(elevation_deg)
    horizontal = math.cos(elev)
    return (
        horizontal * math.sin(az_model),
        horizontal * math.cos(az_model),
        math.sin(elev),
    )


def resolve(lat, lon, tz_offset, date_str, hour, north_angle_deg=0.0):
    """Atalho: recebe 'YYYY-MM-DD' e hora decimal, devolve dict pronto."""
    year, month, day = (int(p) for p in date_str.split("-"))
    h = int(hour)
    minute = int(round((hour - h) * 60))
    if minute == 60:
        h, minute = h + 1, 0
    dt = datetime(year, month, day, min(h, 23), minute)

    elevation, azimuth = sun_position(dt, tz_offset, lat, lon)
    return {
        "elevation_deg": elevation,
        "azimuth_deg": azimuth,
        "direction": sun_direction(elevation, azimuth, north_angle_deg),
        "above_horizon": elevation > 0.0,
    }


if __name__ == "__main__":
    # Belo Horizonte, 21 de marco (equinocio), UTC-3.
    for hour in (7, 9, 12, 16, 18):
        r = resolve(-19.92, -43.94, -3, "2026-03-21", hour)
        print(
            f"{hour:>2}h  elevacao {r['elevation_deg']:6.1f}  "
            f"azimute {r['azimuth_deg']:6.1f}  sol_no_ceu={r['above_horizon']}"
        )
