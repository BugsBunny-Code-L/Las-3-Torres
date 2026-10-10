#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Las 3 Torres — actualizador diario.

Qué hace, en orden:
  1. Trae de ESPN los partidos de las nueve ligas: los ya jugados (para aprender)
     y los que vienen (para pronosticar).
  2. Guarda todo en datos/partidos.json. Ese archivo crece con cada corrida y es
     la memoria del sistema: de ahí salen forma, localía, historial directo y descanso.
  3. Calcula el pronóstico de cada partido próximo.
  4. Mezcla las notas de ojo-reportero.json, con tope del 25%.
  5. Revisa los pronósticos viejos contra lo que realmente pasó y se califica.
  6. Escribe index.html.

Se corre así:
    python3 actualizar.py
    python3 actualizar.py --prueba      (sin internet, con datos inventados)

No necesita instalar nada: solo Python 3.9 o más nuevo.
"""

import argparse, json, math, os, random, re, sys, time, unicodedata
import urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Mexico_City")
except Exception:                                    # por si falta tzdata
    TZ = timezone(timedelta(hours=-6))

# ============================ CONFIGURACIÓN ============================
# Cambia estos números si quieres ajustar el comportamiento.

DIAS_ADELANTE   = 8      # cuántos días de partidos futuros traer
DIAS_ATRAS      = 4      # cuántos días recientes revisar en cada corrida
DIAS_PRIMERA    = 150    # cuánta historia traer la primera vez (solo si no hay caché)
TOPE_REPORTERO  = 0.25   # peso máximo del ojo reportero sobre el ajuste total
PAUSA           = 0.25   # segundos entre consultas, para no atosigar al servidor

CARPETA   = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS = os.path.join(CARPETA, "datos")
F_PARTIDOS    = os.path.join(DIR_DATOS, "partidos.json")
F_PRONOSTICOS = os.path.join(DIR_DATOS, "pronosticos.json")
F_REPORTERO   = os.path.join(CARPETA, "ojo-reportero.json")
F_PLANTILLA   = os.path.join(CARPETA, "plantilla.html")
F_SALIDA      = os.path.join(CARPETA, "index.html")

# Las nueve ligas. El orden importa: las domésticas van antes que Champions
# para que un equipo quede etiquetado con su liga de casa.
LIGAS = [
    ("mex.1",          "soccer",     "Liga MX",          "poisson", None),
    ("eng.1",          "soccer",     "Premier League",   "poisson", None),
    ("esp.1",          "soccer",     "La Liga",          "poisson", None),
    ("ger.1",          "soccer",     "Bundesliga",       "poisson", None),
    ("ita.1",          "soccer",     "Serie A",          "poisson", None),
    ("uefa.champions", "soccer",     "Champions League", "poisson", None),
    ("nba",            "basketball", "NBA",              "margen",  11.5),
    ("mlb",            "baseball",   "MLB",              "margen",   4.1),
    ("nfl",            "football",   "NFL",              "margen",  13.2),
]
LIGA_POR_CLAVE = {l[0]: l for l in LIGAS}

VENTAJA_LOCAL = {"NBA": 2.2, "NFL": 1.6, "MLB": 0.22}
UNIDAD        = {"NBA": "puntos", "NFL": "puntos", "MLB": "carreras"}

MESES = ["enero","febrero","marzo","abril","mayo","junio","julio",
         "agosto","septiembre","octubre","noviembre","diciembre"]
DIAS_SEM = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]


# ============================== UTILIDADES ==============================
def log(msg):
    print(f"  {msg}", flush=True)

def leer_json(ruta, por_defecto):
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return por_defecto

def guardar_json(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, separators=(",", ":"))

def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower().strip()

def recortar(v, lim):
    return max(-lim, min(lim, v))

def fecha_larga(dt_local):
    return (f"{DIAS_SEM[dt_local.weekday()]} {dt_local.day} de "
            f"{MESES[dt_local.month-1]} · {dt_local:%H:%M} h")


# ============================= TRAER DATOS =============================
def pedir(url, intentos=3):
    for n in range(intentos):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Las3Torres/1.0)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if n == intentos - 1:
                log(f"no se pudo leer ({type(e).__name__}): {url[:90]}")
                return None
            time.sleep(1.5 * (n + 1))
    return None

def leer_dia(liga, deporte, fecha):
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{deporte}/{liga}"
           f"/scoreboard?dates={fecha:%Y%m%d}&limit=300")
    return pedir(url)

def extraer_eventos(cruda, liga_clave, equipos):
    """Convierte la respuesta de ESPN en partidos simples."""
    salida = []
    if not cruda:
        return salida
    for ev in cruda.get("events", []) or []:
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        lados = comp.get("competitors") or []
        if len(lados) != 2:
            continue
        casa = next((c for c in lados if c.get("homeAway") == "home"), None)
        fuera = next((c for c in lados if c.get("homeAway") == "away"), None)
        if not casa or not fuera:
            continue

        def registrar(lado):
            eq = lado.get("team") or {}
            tid = str(eq.get("id") or "")
            if not tid:
                return None
            clave = f"{liga_clave.split('.')[0]}:{tid}" if liga_clave in ("nba","mlb","nfl") else f"sc:{tid}"
            nombre = eq.get("displayName") or eq.get("name") or eq.get("shortDisplayName") or tid
            if clave not in equipos:
                equipos[clave] = {
                    "n": nombre,
                    "s": (eq.get("abbreviation") or nombre[:3]).upper(),
                    "l": LIGA_POR_CLAVE[liga_clave][2],
                    "c": eq.get("location") or "",
                }
            return clave

        kc, kf = registrar(casa), registrar(fuera)
        if not kc or not kf:
            continue

        estado = ((comp.get("status") or {}).get("type") or {})
        completado = bool(estado.get("completed"))
        def marcador(l):
            try:
                return int(l.get("score"))
            except Exception:
                return None
        sede = (comp.get("venue") or {}).get("fullName") or ""
        ciudad = ((comp.get("venue") or {}).get("address") or {}).get("city") or ""

        salida.append({
            "id": str(ev.get("id")),
            "liga": liga_clave,
            "fecha": ev.get("date"),
            "casa": kc, "fuera": kf,
            "mc": marcador(casa) if completado else None,
            "mf": marcador(fuera) if completado else None,
            "fin": completado,
            "sede": (sede + (", " + ciudad if ciudad and ciudad not in sede else "")).strip(", "),
            "nota": (ev.get("season") or {}).get("slug") or "",
        })
    return salida


def recolectar(cache, equipos):
    """Baja los días que faltan y actualiza la caché."""
    hoy = datetime.now(timezone.utc).date()
    primera_vez = len(cache) == 0
    desde = hoy - timedelta(days=DIAS_PRIMERA if primera_vez else DIAS_ATRAS)
    hasta = hoy + timedelta(days=DIAS_ADELANTE)
    if primera_vez:
        log(f"primera corrida: traeré {DIAS_PRIMERA} días de historia. Tardará unos minutos.")

    total_dias = (hasta - desde).days + 1
    nuevos = 0
    for liga, deporte, nombre, _m, _sd in LIGAS:
        cuenta = 0
        d = desde
        while d <= hasta:
            cruda = leer_dia(liga, deporte, d)
            for ev in extraer_eventos(cruda, liga, equipos):
                if ev["id"] not in cache or ev["fin"] or not cache[ev["id"]].get("fin"):
                    cache[ev["id"]] = ev
                    cuenta += 1
            d += timedelta(days=1)
            time.sleep(PAUSA)
        nuevos += cuenta
        log(f"{nombre}: {cuenta} partidos en {total_dias} días")
    return nuevos


# ====================== FUERZA DE CADA EQUIPO ======================
def jugados(cache):
    out = [p for p in cache.values() if p.get("fin") and p.get("mc") is not None]
    out.sort(key=lambda p: p["fecha"] or "")
    return out

def construir_fuerzas(cache):
    """Promedios por equipo y por liga, calculados del histórico guardado."""
    por_equipo, por_liga = {}, {}
    for p in jugados(cache):
        for clave, gf, ga, casa in ((p["casa"], p["mc"], p["mf"], True),
                                    (p["fuera"], p["mf"], p["mc"], False)):
            e = por_equipo.setdefault(clave, {"n":0,"gf":0,"ga":0,
                                              "nc":0,"gfc":0,"gac":0,
                                              "nf":0,"gff":0,"gaf":0,"juegos":[]})
            e["n"] += 1; e["gf"] += gf; e["ga"] += ga
            if casa:
                e["nc"] += 1; e["gfc"] += gf; e["gac"] += ga
            else:
                e["nf"] += 1; e["gff"] += gf; e["gaf"] += ga
            e["juegos"].append({"f": p["fecha"], "gf": gf, "ga": ga,
                                "casa": casa, "rival": p["fuera"] if casa else p["casa"]})
        L = por_liga.setdefault(p["liga"], {"n":0,"gc":0,"gf":0})
        L["n"] += 1; L["gc"] += p["mc"]; L["gf"] += p["mf"]
    for e in por_equipo.values():
        e["juegos"].sort(key=lambda j: j["f"] or "")
    return por_equipo, por_liga

def medias_liga(por_liga, liga):
    L = por_liga.get(liga)
    if not L or L["n"] < 8:
        # valores de respaldo razonables si todavía no hay muestra
        base = {"mex.1":(1.45,1.15),"eng.1":(1.55,1.25),"esp.1":(1.45,1.15),
                "ger.1":(1.70,1.35),"ita.1":(1.50,1.20),"uefa.champions":(1.55,1.30),
                "nba":(114.0,112.0),"mlb":(4.5,4.3),"nfl":(23.0,21.5)}
        return base.get(liga, (1.5, 1.2))
    return L["gc"]/L["n"], L["gf"]/L["n"]

def encoger(valor, neutro, n, k=4):
    """Con pocos partidos, acerca el valor al promedio. Evita conclusiones de 2 juegos."""
    peso = n / (n + k) if n else 0.0
    return neutro + (valor - neutro) * peso


# ============================== MOTOR ==============================
def poisson(k, lam):
    r = math.exp(-lam)
    for i in range(1, k+1):
        r *= lam / i
    return r

def ncdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))

def magnitud(f, futbol):
    return abs(f.get("dc",0)) + abs(f.get("df",0)) if futbol else abs(f.get("d",0))

def escala_reportero(factores, futbol):
    D = sum(magnitud(f, futbol) for f in factores if not f.get("rep"))
    H = sum(magnitud(f, futbol) for f in factores if f.get("rep"))
    maxH = TOPE_REPORTERO / (1 - TOPE_REPORTERO) * D
    k = maxH / H if (H > maxH and H > 0) else 1.0
    total = D + H * k
    return k, ((H * k) / total if total else 0.0), (k < 0.999)

def resolver(base, factores, futbol, sd=None, k=1.0):
    if futbol:
        xc, xf = base["xgC"], base["xgF"]
        for f in factores:
            m = k if f.get("rep") else 1.0
            xc += f.get("dc", 0) * m
            xf += f.get("df", 0) * m
        xc, xf = max(0.2, xc), max(0.2, xf)
        pC = pE = pV = 0.0
        mejor = (0.0, 0, 0)
        for i in range(10):
            pi = poisson(i, xc)
            for j in range(10):
                p = pi * poisson(j, xf)
                if i > j: pC += p
                elif i == j: pE += p
                else: pV += p
                if p > mejor[0]: mejor = (p, i, j)
        s = pC + pE + pV
        return {"pC":pC/s, "pE":pE/s, "pV":pV/s, "xgC":xc, "xgF":xf,
                "marcador":f"{mejor[1]}–{mejor[2]}", "marcadorP":mejor[0]/s}
    mg, tot = base["mg"], base["tot"]
    for f in factores:
        m = k if f.get("rep") else 1.0
        mg += f.get("d", 0) * m
        tot += f.get("dt", 0) * m
    pC = ncdf(mg / sd)
    # en estos deportes no hay empates: si al redondear quedan iguales,
    # el favorito se queda con la unidad extra
    mc, mf = round((tot + mg) / 2), round((tot - mg) / 2)
    if mc == mf:
        if mg >= 0: mc += 1
        else: mf += 1
    return {"pC":pC, "pE":0.0, "pV":1-pC, "mg":mg, "tot":tot,
            "marcador":f"{mc}–{mf}", "marcadorP":None}


# ============================ FACTORES ============================
def ultimos(e, n, solo=None):
    js = e["juegos"]
    if solo == "casa":  js = [j for j in js if j["casa"]]
    if solo == "fuera": js = [j for j in js if not j["casa"]]
    return js[-n:]

def resumen_forma(js):
    g = sum(1 for j in js if j["gf"] > j["ga"])
    e = sum(1 for j in js if j["gf"] == j["ga"])
    p = len(js) - g - e
    return g, e, p, sum(j["gf"] for j in js), sum(j["ga"] for j in js)

def dias_descanso(e, fecha_partido):
    if not e["juegos"]:
        return None
    try:
        ult = datetime.fromisoformat(e["juegos"][-1]["f"].replace("Z", "+00:00"))
        return max(0, (fecha_partido - ult).days)
    except Exception:
        return None

def h2h(cache, a, b, limite=8):
    out = []
    for p in jugados(cache):
        if {p["casa"], p["fuera"]} == {a, b}:
            out.append(p)
    return out[-limite:]


def factores_futbol(cache, eq, nomC, nomF, kc, kf, fecha_utc):
    """Construye la lista de factores del partido, con su texto en español."""
    F = []
    C, Fu = eq.get(kc), eq.get(kf)
    if not C or not Fu:
        return F

    # 1 y 2 — forma reciente de cada equipo contra su propio promedio
    for e, nom, es_casa in ((C, nomC, True), (Fu, nomF, False)):
        js = ultimos(e, 5)
        if len(js) >= 3:
            dg5 = sum(j["gf"]-j["ga"] for j in js) / len(js)
            dgT = (e["gf"] - e["ga"]) / e["n"]
            delta = recortar(0.17 * (dg5 - dgT), 0.20)
            g, emp, p, gf, ga = resumen_forma(js)
            pts = g*3 + emp
            F.append({
                "c": "Forma",
                "t": f"{nom} suma {pts} de {len(js)*3} puntos posibles en sus últimos {len(js)}",
                "e": f"{g} ganados, {emp} empatados y {p} perdidos, con {gf} goles a favor y {ga} en contra. "
                     f"Su promedio de la temporada es {dgT:+.2f} de diferencia por partido y en este tramo va {dg5:+.2f}.",
                "dc": delta*0.5 if es_casa else -delta*0.5,
                "df": -delta*0.5 if es_casa else delta*0.5,
            })

    # 3 — qué tan fuerte es el local en su casa
    if C["nc"] >= 3:
        casa_dg = (C["gfc"] - C["gac"]) / C["nc"]
        tot_dg  = (C["gf"] - C["ga"]) / C["n"]
        delta = recortar(0.20 * (casa_dg - tot_dg), 0.18)
        gan = sum(1 for j in ultimos(C, 99, "casa") if j["gf"] > j["ga"])
        F.append({
            "c": "Localía",
            "t": f"{nomC} gana el {round(gan/C['nc']*100)}% de sus partidos como local",
            "e": f"{gan} de {C['nc']} ganados en casa, con {C['gfc']/C['nc']:.1f} goles anotados "
                 f"y {C['gac']/C['nc']:.1f} recibidos por partido.",
            "dc": delta*0.6, "df": -delta*0.4,
        })

    # 4 — cómo le va al visitante lejos de casa
    if Fu["nf"] >= 3:
        vis_dg = (Fu["gff"] - Fu["gaf"]) / Fu["nf"]
        tot_dg = (Fu["gf"] - Fu["ga"]) / Fu["n"]
        delta = recortar(0.20 * (vis_dg - tot_dg), 0.18)
        gan = sum(1 for j in ultimos(Fu, 99, "fuera") if j["gf"] > j["ga"])
        F.append({
            "c": "Localía",
            "t": f"{nomF} gana el {round(gan/Fu['nf']*100)}% de sus partidos de visita",
            "e": f"{gan} de {Fu['nf']} ganados fuera, con {Fu['gff']/Fu['nf']:.1f} goles anotados "
                 f"y {Fu['gaf']/Fu['nf']:.1f} recibidos por partido.",
            "dc": -delta*0.4, "df": delta*0.6,
        })

    # 5 — sequía de gol del visitante
    secos = ultimos(Fu, 3, "fuera")
    if len(secos) == 3 and sum(j["gf"] for j in secos) == 0:
        F.append({
            "c": "Forma",
            "t": f"{nomF} no marca de visita en sus últimos 3 partidos fuera",
            "e": "Tres juegos seguidos lejos de casa sin anotar.",
            "dc": 0.0, "df": -0.14,
        })

    # 6 — historial directo
    duelos = h2h(cache, kc, kf)
    if len(duelos) >= 3:
        dif = sum((d["mc"]-d["mf"]) if d["casa"] == kc else (d["mf"]-d["mc"]) for d in duelos) / len(duelos)
        delta = recortar(0.08 * dif, 0.13)
        gC = sum(1 for d in duelos if (d["mc"] > d["mf"]) == (d["casa"] == kc) and d["mc"] != d["mf"])
        emp = sum(1 for d in duelos if d["mc"] == d["mf"])
        F.append({
            "c": "Historial directo",
            "t": (f"{nomC} domina el historial reciente" if dif > 0.4 else
                  f"{nomF} domina el historial reciente" if dif < -0.4 else
                  "El historial directo está parejo"),
            "e": f"En los últimos {len(duelos)} duelos: {gC} para {nomC}, {emp} empates y "
                 f"{len(duelos)-gC-emp} para {nomF}. Diferencia promedio de {dif:+.2f} goles para {nomC}.",
            "dc": delta*0.5, "df": -delta*0.5,
        })

    # 7 — descanso
    dC, dF = dias_descanso(C, fecha_utc), dias_descanso(Fu, fecha_utc)
    if dC is not None and dF is not None and abs(dC - dF) >= 2:
        delta = recortar(0.025 * (dC - dF), 0.12)
        mas, menos = (nomC, nomF) if dC > dF else (nomF, nomC)
        F.append({
            "c": "Calendario",
            "t": f"{mas} llega con más descanso que {menos}",
            "e": f"{nomC} lleva {dC} días sin jugar y {nomF} lleva {dF}.",
            "dc": delta*0.5, "df": -delta*0.5,
        })
    return F


def factores_margen(cache, eq, nomC, nomF, kc, kf, fecha_utc, liga_nom):
    F = []
    C, Fu = eq.get(kc), eq.get(kf)
    if not C or not Fu:
        return F
    uni = UNIDAD[liga_nom]

    for e, nom, es_casa in ((C, nomC, True), (Fu, nomF, False)):
        js = ultimos(e, 5)
        if len(js) >= 3:
            m5 = sum(j["gf"]-j["ga"] for j in js) / len(js)
            mT = (e["gf"] - e["ga"]) / e["n"]
            tope = 3.0 if liga_nom != "MLB" else 0.8
            delta = recortar(0.45 * (m5 - mT), tope)
            g = sum(1 for j in js if j["gf"] > j["ga"])
            F.append({
                "c": "Forma",
                "t": f"{nom} ganó {g} de sus últimos {len(js)}",
                "e": f"Diferencia de {m5:+.1f} {uni} por juego en ese tramo, contra {mT:+.1f} "
                     f"de su promedio de temporada.",
                "d": delta if es_casa else -delta, "dt": 0.0,
            })

    if C["nc"] >= 4:
        dif = (C["gfc"]-C["gac"])/C["nc"] - (C["gf"]-C["ga"])/C["n"]
        delta = recortar(0.5 * dif, 3.0 if liga_nom != "MLB" else 0.7)
        gan = sum(1 for j in ultimos(C, 99, "casa") if j["gf"] > j["ga"])
        F.append({
            "c": "Localía",
            "t": f"{nomC} gana el {round(gan/C['nc']*100)}% de sus juegos en casa",
            "e": f"{gan} de {C['nc']} como local, con {(C['gfc']-C['gac'])/C['nc']:+.1f} {uni} de diferencia por juego.",
            "d": delta, "dt": 0.0,
        })
    if Fu["nf"] >= 4:
        dif = (Fu["gff"]-Fu["gaf"])/Fu["nf"] - (Fu["gf"]-Fu["ga"])/Fu["n"]
        delta = recortar(0.5 * dif, 3.0 if liga_nom != "MLB" else 0.7)
        gan = sum(1 for j in ultimos(Fu, 99, "fuera") if j["gf"] > j["ga"])
        F.append({
            "c": "Localía",
            "t": f"{nomF} gana el {round(gan/Fu['nf']*100)}% de sus juegos de visita",
            "e": f"{gan} de {Fu['nf']} fuera de casa, con {(Fu['gff']-Fu['gaf'])/Fu['nf']:+.1f} {uni} de diferencia por juego.",
            "d": -delta, "dt": 0.0,
        })

    duelos = h2h(cache, kc, kf)
    if len(duelos) >= 3:
        dif = sum((d["mc"]-d["mf"]) if d["casa"] == kc else (d["mf"]-d["mc"]) for d in duelos) / len(duelos)
        delta = recortar(0.22 * dif, 2.0 if liga_nom != "MLB" else 0.5)
        gC = sum(1 for d in duelos if (d["mc"] > d["mf"]) == (d["casa"] == kc))
        F.append({
            "c": "Historial directo",
            "t": (f"{nomC} domina la serie reciente" if dif > 0 else f"{nomF} domina la serie reciente"),
            "e": f"{gC} de {len(duelos)} para {nomC} en los duelos guardados, con {dif:+.1f} {uni} de diferencia promedio.",
            "d": delta, "dt": 0.0,
        })

    dC, dF = dias_descanso(C, fecha_utc), dias_descanso(Fu, fecha_utc)
    if liga_nom == "NBA" and dC is not None and dF is not None:
        if dF <= 1 and dC >= 2:
            F.append({"c":"Calendario","t":f"{nomF} juega su segundo partido en dos noches",
                      "e":f"{nomC} descansó {dC} días. Los equipos sin descanso rinden por debajo de lo normal.",
                      "d":2.5,"dt":-2.0})
        elif dC <= 1 and dF >= 2:
            F.append({"c":"Calendario","t":f"{nomC} juega su segundo partido en dos noches",
                      "e":f"{nomF} descansó {dF} días.","d":-2.5,"dt":-2.0})
    elif dC is not None and dF is not None and abs(dC-dF) >= 3:
        delta = recortar(0.25*(dC-dF), 1.5 if liga_nom != "MLB" else 0.4)
        mas, menos = (nomC, nomF) if dC > dF else (nomF, nomC)
        F.append({"c":"Calendario","t":f"{mas} llega con más descanso que {menos}",
                  "e":f"{nomC} lleva {dC} días sin jugar y {nomF} lleva {dF}.","d":delta,"dt":0.0})
    return F


# ========================= OJO REPORTERO =========================
FUERZA_FUTBOL = {"poco": 0.07, "algo": 0.14, "bastante": 0.22}
FUERZA_PUNTOS = {"poco": 1.0,  "algo": 2.0,  "bastante": 3.2}
FUERZA_CARRERAS = {"poco": 0.15, "algo": 0.30, "bastante": 0.50}

def notas_reportero(notas, equipos, kc, kf, futbol, liga_nom, hoy):
    """Convierte las notas escritas a mano en factores del modelo."""
    salida = []
    for nota in notas:
        nombre = sin_acentos(nota.get("equipo", ""))
        if not nombre:
            continue
        hasta = nota.get("hasta")
        if hasta:
            try:
                if datetime.strptime(hasta, "%Y-%m-%d").date() < hoy:
                    continue                                  # la nota ya venció
            except Exception:
                pass
        objetivo = None
        for clave in (kc, kf):
            eq = equipos.get(clave, {})
            candidatos = [sin_acentos(eq.get("n","")), sin_acentos(eq.get("s",""))]
            if nombre in candidatos or any(nombre in c for c in candidatos if c):
                objetivo = clave
                break
        if not objetivo:
            continue

        fuerza = (nota.get("fuerza") or "algo").lower()
        perjudica = (nota.get("efecto") or "perjudica").lower().startswith("perj")
        # un factor que perjudica al local empuja el resultado hacia el visitante
        hacia_local = -1 if ((objetivo == kc) == perjudica) else 1

        f = {"c": "Ojo reportero", "rep": True,
             "t": nota.get("titulo") or "Nota de reportero",
             "e": nota.get("detalle") or "Agregado a mano en ojo-reportero.json."}
        if futbol:
            u = FUERZA_FUTBOL.get(fuerza, 0.14)
            f["dc"], f["df"] = (u, 0.0) if hacia_local > 0 else (0.0, u)
        else:
            tabla = FUERZA_CARRERAS if liga_nom == "MLB" else FUERZA_PUNTOS
            f["d"], f["dt"] = tabla.get(fuerza, tabla["algo"]) * hacia_local, 0.0
        salida.append(f)
    return salida


# ======================= ARMAR UN PRONÓSTICO =======================
def pronosticar(cache, eq, por_liga, equipos, partido, notas, hoy):
    liga_clave = partido["liga"]
    _, _, liga_nom, modelo, sd = LIGA_POR_CLAVE[liga_clave]
    futbol = (modelo == "poisson")
    kc, kf = partido["casa"], partido["fuera"]
    nomC, nomF = equipos[kc]["n"], equipos[kf]["n"]
    C, Fu = eq.get(kc), eq.get(kf)
    if not C or not Fu or C["n"] < 2 or Fu["n"] < 2:
        return None

    try:
        fecha_utc = datetime.fromisoformat(partido["fecha"].replace("Z", "+00:00"))
    except Exception:
        return None
    fecha_local = fecha_utc.astimezone(TZ)

    # --- base ---
    mcasa, mfuera = medias_liga(por_liga, liga_clave)
    if futbol:
        neutro = (mcasa + mfuera) / 2
        atkC = encoger((C["gf"]/C["n"]) / neutro, 1.0, C["n"])
        defC = encoger((C["ga"]/C["n"]) / neutro, 1.0, C["n"])
        atkF = encoger((Fu["gf"]/Fu["n"]) / neutro, 1.0, Fu["n"])
        defF = encoger((Fu["ga"]/Fu["n"]) / neutro, 1.0, Fu["n"])
        base = {"xgC": max(0.25, mcasa*atkC*defF), "xgF": max(0.25, mfuera*atkF*defC)}
    else:
        prom = (mcasa + mfuera) / 2
        ofC = encoger(C["gf"]/C["n"], prom, C["n"]); daC = encoger(C["ga"]/C["n"], prom, C["n"])
        ofF = encoger(Fu["gf"]/Fu["n"], prom, Fu["n"]); daF = encoger(Fu["ga"]/Fu["n"], prom, Fu["n"])
        espC = (ofC + daF)/2; espF = (ofF + daC)/2
        base = {"mg": espC - espF + VENTAJA_LOCAL[liga_nom], "tot": espC + espF}

    # --- factores ---
    if futbol:
        factores = factores_futbol(cache, eq, nomC, nomF, kc, kf, fecha_utc)
    else:
        factores = factores_margen(cache, eq, nomC, nomF, kc, kf, fecha_utc, liga_nom)
    reporteros = notas_reportero(notas, equipos, kc, kf, futbol, liga_nom, hoy)
    factores += reporteros

    k, share, topado = escala_reportero(factores, futbol)
    r = resolver(base, factores, futbol, sd, k)

    # --- efecto de cada factor, en puntos de probabilidad del local ---
    lista = []
    for i, f in enumerate(factores):
        sin_este = factores[:i] + factores[i+1:]
        k2, _, _ = escala_reportero(sin_este, futbol)
        r2 = resolver(base, sin_este, futbol, sd, k2)
        pts = (r["pC"] - r2["pC"]) * 100
        m = k if f.get("rep") else 1.0
        if futbol:
            val, uni, dec = (f.get("dc",0) - f.get("df",0)) * m, "goles esperados", 2
        else:
            val, uni, dec = f.get("d",0) * m, UNIDAD[liga_nom], 1
        lista.append({"c": f["c"], "t": f["t"], "e": f["e"], "rep": bool(f.get("rep")),
                      "pts": round(pts, 2), "val": round(val, 3), "unidad": uni, "dec": dec})

    # --- confianza ---
    cobertura = 0.90
    if C["n"] < 6 or Fu["n"] < 6: cobertura -= 0.14
    elif C["n"] < 12 or Fu["n"] < 12: cobertura -= 0.06
    if len(h2h(cache, kc, kf)) < 3: cobertura -= 0.08
    if not reporteros: cobertura -= 0.03
    cobertura = max(0.40, min(0.95, cobertura))

    top = max(r["pC"], r["pE"], r["pV"])
    piso = 0.40 if futbol else 0.50
    separacion = max(0.0, (top - piso) / (1 - piso))
    conf = round(cobertura*55 + separacion*45)
    etiqueta = "Alta" if conf >= 70 else "Media" if conf >= 50 else "Baja"

    # --- traza del cálculo ---
    if futbol:
        traza = [
            (f"Goles esperados base — {nomC}", f"{base['xgC']:.2f}", False),
            (f"Goles esperados base — {nomF}", f"{base['xgF']:.2f}", False),
            ("Ajuste total por factores (local)", f"{r['xgC']-base['xgC']:+.2f}", False),
            ("Ajuste total por factores (visitante)", f"{r['xgF']-base['xgF']:+.2f}", False),
            ("Goles esperados finales", f"{r['xgC']:.2f} — {r['xgF']:.2f}", True),
            ("Marcador más probable", f"{r['marcador']} ({round(r['marcadorP']*100)}%)", False),
        ]
        nota_traza = ("Con esos dos números el modelo calcula qué tan probable es cada marcador posible, "
                      "de 0–0 a 9–9, y suma por separado los que dan victoria local, empate y victoria "
                      "visitante. Eso produce los tres porcentajes de arriba. La base sale de cuántos goles "
                      "anota y recibe cada equipo comparado con el promedio de su liga.")
    else:
        traza = [
            ("Margen base del local", f"{base['mg']:+.1f}", False),
            ("Ajuste total por factores", f"{r['mg']-base['mg']:+.1f}", False),
            ("Margen esperado del local", f"{r['mg']:+.1f}", True),
            (f"Total esperado (base {base['tot']:.1f})", f"{r['tot']:.1f}", False),
            (f"Desviación típica de la {liga_nom}", f"±{sd}", False),
            ("Probabilidad de victoria local", f"{round(r['pC']*100)}%", True),
        ]
        nota_traza = (f"La desviación típica dice qué tanto se suele alejar el resultado real del pronóstico: "
                      f"±{sd} en la {liga_nom}. El margen esperado se divide entre esa cifra y el resultado se "
                      f"lee en una curva normal, que convierte 'por cuánto esperamos que gane' en 'qué tan "
                      f"seguido gana'.")

    # --- qué no sabe el modelo ---
    incognitas = ["Esta versión no incorpora lesiones ni alineaciones confirmadas. "
                  "Si una baja importante se anuncia el día del partido, el pronóstico no la vio."]
    if C["n"] < 8 or Fu["n"] < 8:
        incognitas.append(f"Muestra corta: {nomC} lleva {C['n']} partidos guardados y {nomF} lleva {Fu['n']}. "
                          f"Con menos de ocho, el modelo se apoya más en el promedio de la liga que en el equipo.")
    if len(h2h(cache, kc, kf)) < 3:
        incognitas.append("No hay suficientes duelos directos en el histórico guardado, así que ese factor no entró. "
                          "Se irá llenando con cada corrida.")
    if reporteros:
        incognitas.append("Las notas de ojo reportero vienen de prensa, no de un dato medido. "
                          "Son las primeras que conviene revisar si el pronóstico falla.")
    else:
        incognitas.append("No hay notas de ojo reportero para este partido. Se agregan en ojo-reportero.json.")

    # --- de dónde salió cada cosa ---
    muestra = min(C["n"], Fu["n"])
    fuentes = [
        {"k":"Calendario, sede y resultados","v":"ESPN público","t":"medido","st":"ok"},
        {"k":"Fuerza ofensiva y defensiva","v":f"Calculado del histórico propio ({C['n']} y {Fu['n']} partidos)",
         "t":"medido" if muestra >= 8 else "muestra corta","st":"ok" if muestra >= 8 else "old"},
        {"k":"Forma y localía","v":"Calculado del histórico propio","t":"medido","st":"ok"},
        {"k":"Historial directo","v":f"Calculado del histórico propio ({len(h2h(cache,kc,kf))} duelos)",
         "t":"medido" if len(h2h(cache,kc,kf))>=3 else "sin muestra",
         "st":"ok" if len(h2h(cache,kc,kf))>=3 else "no"},
        {"k":"Lesiones y alineaciones","v":"No incluido en esta versión","t":"sin dato","st":"no"},
        {"k":"Ojo reportero","v":"ojo-reportero.json" if reporteros else "Sin notas para este partido",
         "t":f"{len(reporteros)} nota(s)" if reporteros else "sin dato","st":"ok" if reporteros else "no"},
    ]

    salida = {
        "id": partido["id"], "liga": liga_nom,
        "comp": f"{liga_nom}" + (f" · {partido['nota']}" if partido.get("nota") else ""),
        "dt": fecha_larga(fecha_local), "iso": partido["fecha"],
        "venue": partido.get("sede", ""),
        "local": kc, "visita": kf, "futbol": futbol,
        "unidad": "goles esperados" if futbol else UNIDAD[liga_nom],
        "unidadTotal": "" if futbol else UNIDAD[liga_nom],
        "pL": round(r["pC"], 4), "pE": round(r["pE"], 4), "pV": round(r["pV"], 4),
        "marcador": r["marcador"], "marcadorP": round(r["marcadorP"], 4) if r["marcadorP"] else None,
        "conf": conf, "confEtiqueta": etiqueta,
        "cobertura": round(cobertura, 3), "separacion": round(separacion, 3),
        "repShare": round(share, 3), "repTopado": topado,
        "factores": lista, "incognitas": incognitas, "fuentes": fuentes,
        "traza": traza, "trazaNota": nota_traza,
    }
    if futbol:
        salida["xgL"], salida["xgV"] = round(r["xgC"], 3), round(r["xgF"], 3)
    else:
        salida["total"] = round(r["tot"], 2)
    return salida


# ========================== CALIFICACIÓN ==========================
def actualizar_calificacion(cache, equipos, pronos, nuevos):
    """Guarda los pronósticos de hoy y cierra los que ya se jugaron."""
    for p in nuevos:
        if p["id"] not in pronos:
            pronos[p["id"]] = {
                "liga": p["liga"], "casa": p["local"], "fuera": p["visita"],
                "iso": p["iso"], "pL": p["pL"], "pE": p["pE"], "pV": p["pV"],
                "conf": p["conf"],
                "cats": {f["c"]: round(sum(x["pts"] for x in p["factores"] if x["c"] == f["c"]), 2)
                         for f in p["factores"]},
                "cerrado": False,
            }

    for eid, pr in pronos.items():
        if pr.get("cerrado"):
            continue
        real = cache.get(eid)
        if not real or not real.get("fin") or real.get("mc") is None:
            continue
        mc, mf = real["mc"], real["mf"]
        real_res = "L" if mc > mf else ("V" if mf > mc else "E")
        probs = {"L": pr["pL"], "E": pr["pE"], "V": pr["pV"]}
        elegido = max(probs, key=probs.get)
        pr["cerrado"] = True
        pr["resultado"] = real_res
        pr["marcador"] = f"{mc}-{mf}"
        pr["acierto"] = (elegido == real_res)
        pr["pElegido"] = probs[elegido]
        pr["brier"] = round(sum((probs[k] - (1.0 if k == real_res else 0.0))**2
                                for k in ("L","E","V")) / 2, 4)
    return pronos


def resumir_calificacion(pronos, equipos):
    cerrados = [p for p in pronos.values() if p.get("cerrado")]
    if not cerrados:
        return {"total": 0}
    cerrados.sort(key=lambda p: p.get("iso") or "")
    total = len(cerrados)
    acierto = sum(1 for p in cerrados if p["acierto"]) / total
    brier = sum(p["brier"] for p in cerrados) / total

    bandas = []
    for lo, hi, etiqueta in ((0.0,0.50,"menos de 50%"),(0.50,0.60,"50–60%"),(0.60,0.70,"60–70%"),
                             (0.70,0.80,"70–80%"),(0.80,0.90,"80–90%"),(0.90,1.01,"90%+")):
        grupo = [p for p in cerrados if lo <= p["pElegido"] < hi]
        if len(grupo) >= 5:
            bandas.append({"b": etiqueta, "n": len(grupo),
                           "mid": round(sum(p["pElegido"] for p in grupo)/len(grupo)*100, 1),
                           "real": round(sum(1 for p in grupo if p["acierto"])/len(grupo), 4)})

    ligas = {}
    for p in cerrados:
        L = ligas.setdefault(p["liga"], [0, 0])
        L[0] += 1; L[1] += 1 if p["acierto"] else 0
    ligas_out = sorted(({"l": k, "n": v[0], "a": round(v[1]/v[0], 4)} for k, v in ligas.items()),
                       key=lambda x: -x["a"])

    # acierto direccional por tipo de factor (se excluyen los empates)
    cats = {}
    for p in cerrados:
        if p["resultado"] == "E":
            continue
        for c, pts in (p.get("cats") or {}).items():
            if abs(pts) < 0.3:
                continue
            d = cats.setdefault(c, [0, 0])
            d[0] += 1
            apunta = "L" if pts > 0 else "V"
            d[1] += 1 if apunta == p["resultado"] else 0
    cats_out = sorted(({"c": k, "n": v[0], "v": round((v[1]/v[0] - 0.5)*100, 2)}
                       for k, v in cats.items() if v[0] >= 8), key=lambda x: -x["v"])

    nombre = lambda k: (equipos.get(k) or {}).get("n", "?")
    etiqueta_res = {"L": "local", "E": "empate", "V": "visitante"}
    ultimos = []
    for p in cerrados[-8:][::-1]:
        probs = {"L": p["pL"], "E": p["pE"], "V": p["pV"]}
        elegido = max(probs, key=probs.get)
        dijo = (f"{nombre(p['casa'])} {round(p['pL']*100)}%" if elegido == "L" else
                f"Empate {round(p['pE']*100)}%" if elegido == "E" else
                f"{nombre(p['fuera'])} {round(p['pV']*100)}%")
        gano = (nombre(p["casa"]) if p["resultado"] == "L" else
                nombre(p["fuera"]) if p["resultado"] == "V" else "Empate")
        ultimos.append({"p": f"{nombre(p['casa'])} vs {nombre(p['fuera'])}",
                        "d": dijo, "r": f"{gano} {p['marcador']}", "ok": p["acierto"]})

    primera = cerrados[0].get("iso", "")[:10]
    try:
        d = datetime.strptime(primera, "%Y-%m-%d")
        desde = f"{d.day} de {MESES[d.month-1]} de {d.year}"
    except Exception:
        desde = "el inicio del registro"

    return {"total": total, "acierto": round(acierto, 4), "brier": round(brier, 4),
            "bandas": bandas, "ligas": ligas_out, "cats": cats_out,
            "ultimos": ultimos, "desde": desde}


# ============================== SALIDA ==============================
def escribir_html(equipos, pronosticos, historial):
    # el buscador muestra todos los equipos conocidos, tengan partido o no
    eq_salida = {k: {"n": v["n"], "s": v["s"], "l": v["l"], "c": v.get("c", "")}
                 for k, v in equipos.items()}

    atajos = []
    for _, _, nombre, _, _ in LIGAS:
        cand = next((p for p in pronosticos if p["liga"] == nombre), None)
        if cand:
            atajos.append([nombre if nombre != "Champions League" else "Champions", cand["local"]])

    ahora = datetime.now(TZ)
    datos = {
        "generado": f"{ahora.day} de {MESES[ahora.month-1]}, {ahora:%H:%M} h",
        "tope": TOPE_REPORTERO,
        "equipos": eq_salida,
        "partidos": pronosticos,
        "historial": historial,
        "atajos": atajos,
    }
    with open(F_PLANTILLA, encoding="utf-8") as fh:
        plantilla = fh.read()
    html = plantilla.replace("/*__DATOS__*/", json.dumps(datos, ensure_ascii=False, separators=(",", ":")))
    with open(F_SALIDA, "w", encoding="utf-8") as fh:
        fh.write(html)
    return len(html)


# ========================== MODO DE PRUEBA ==========================
def datos_de_prueba(cache, equipos):
    """Inventa partidos para comprobar que todo el engranaje funciona sin internet."""
    random.seed(7)
    plantel = {
        "mex.1": ["América","Cruz Azul","Monterrey","Toluca","Tigres","Pumas"],
        "eng.1": ["Arsenal","Liverpool","Manchester City","Chelsea"],
        "nba":   ["Lakers","Nuggets","Celtics","Knicks"],
        "mlb":   ["Dodgers","Phillies","Yankees","Mariners"],
        "nfl":   ["Chiefs","Bills","49ers","Eagles"],
    }
    escala = {"mex.1":(1.4,1.1),"eng.1":(1.6,1.2),"nba":(114,112),"mlb":(4.5,4.2),"nfl":(23,21)}
    claves = {}
    for liga, nombres in plantel.items():
        pre = liga.split(".")[0] if liga in ("nba","mlb","nfl") else "sc"
        for i, n in enumerate(nombres):
            k = f"{pre}:{liga}{i}"
            claves.setdefault(liga, []).append(k)
            equipos[k] = {"n": n, "s": n[:3].upper(), "l": LIGA_POR_CLAVE[liga][2], "c": ""}
    hoy = datetime.now(timezone.utc)
    eid = 0
    for liga, ks in claves.items():
        mc, mf = escala[liga]
        for d in range(90, 1, -3):                       # partidos ya jugados
            a, b = random.sample(ks, 2)
            fuerza = {k: 0.75 + 0.5*(i/len(ks)) for i, k in enumerate(ks)}
            gc = max(0, round(random.gauss(mc*fuerza[a], mc*0.35)))
            gf = max(0, round(random.gauss(mf*fuerza[b], mf*0.35)))
            eid += 1
            cache[str(eid)] = {"id":str(eid),"liga":liga,
                               "fecha":(hoy-timedelta(days=d)).isoformat().replace("+00:00","Z"),
                               "casa":a,"fuera":b,"mc":gc,"mf":gf,"fin":True,
                               "sede":"Estadio de prueba","nota":"temporada-prueba"}
        for n in range(len(ks)//2):                       # partidos por jugar
            a, b = ks[2*n], ks[2*n+1]
            eid += 1
            cache[str(eid)] = {"id":str(eid),"liga":liga,
                               "fecha":(hoy+timedelta(days=2+n)).isoformat().replace("+00:00","Z"),
                               "casa":a,"fuera":b,"mc":None,"mf":None,"fin":False,
                               "sede":"Estadio de prueba","nota":"temporada-prueba"}


# ================================ MAIN ================================
def main():
    ap = argparse.ArgumentParser(description="Actualiza Las 3 Torres")
    ap.add_argument("--prueba", action="store_true",
                    help="corre sin internet, con partidos inventados")
    args = ap.parse_args()

    print("\nLAS 3 TORRES — actualizando\n" + "="*34)
    cache = leer_json(F_PARTIDOS, {}) if not args.prueba else {}
    equipos = leer_json(os.path.join(DIR_DATOS, "equipos.json"), {}) if not args.prueba else {}
    pronos_viejos = leer_json(F_PRONOSTICOS, {}) if not args.prueba else {}
    notas = leer_json(F_REPORTERO, [])
    if isinstance(notas, dict):
        notas = notas.get("notas", [])

    if args.prueba:
        log("modo prueba: inventando partidos, no se consulta internet")
        datos_de_prueba(cache, equipos)
    else:
        log("consultando ESPN…")
        recolectar(cache, equipos)

    jug = len([p for p in cache.values() if p.get("fin")])
    prox = [p for p in cache.values() if not p.get("fin")]
    log(f"histórico: {jug} partidos jugados · próximos: {len(prox)}")

    eq, por_liga = construir_fuerzas(cache)
    hoy = datetime.now(timezone.utc).date()

    prox.sort(key=lambda p: p.get("fecha") or "")
    pronosticos = []
    for p in prox:
        if p["liga"] not in LIGA_POR_CLAVE:
            continue
        r = pronosticar(cache, eq, por_liga, equipos, p, notas, hoy)
        if r:
            pronosticos.append(r)
    log(f"pronósticos calculados: {len(pronosticos)}")

    # el buscador muestra el partido más próximo de cada equipo
    por_equipo, filtrados = {}, []
    for r in pronosticos:
        for lado in (r["local"], r["visita"]):
            por_equipo.setdefault(lado, r)
    for r in pronosticos:
        if por_equipo.get(r["local"]) is r or por_equipo.get(r["visita"]) is r:
            filtrados.append(r)

    pronos = actualizar_calificacion(cache, equipos, pronos_viejos, pronosticos)
    historial = resumir_calificacion(pronos, equipos)
    if historial.get("total"):
        log(f"calificación: {historial['total']} pronósticos cerrados · "
            f"{round(historial['acierto']*100)}% de acierto")
    else:
        log("calificación: todavía no hay pronósticos cerrados")

    if not args.prueba:
        guardar_json(F_PARTIDOS, cache)
        guardar_json(os.path.join(DIR_DATOS, "equipos.json"), equipos)
        guardar_json(F_PRONOSTICOS, pronos)

    tam = escribir_html(equipos, filtrados, historial)
    log(f"index.html escrito ({tam//1024} KB) con {len(filtrados)} partidos y {len(equipos)} equipos")
    print("="*34 + "\nListo.\n")


if __name__ == "__main__":
    main()
