import os
import re
import streamlit as st
import pandas as pd
import requests
import PyPDF2
from io import BytesIO

# Leer API key desde variable de entorno para no exponerla en el repositorio
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

st.set_page_config(page_title="Análisis táctico de apuestas", layout="centered")
st.title("📊 Sistema táctico de apuestas deportivas")

bankroll = st.number_input("💰 Bankroll total (en pesos argentinos)", min_value=0.0, value=1000.0, step=100.0)
stake_maximo = st.number_input("📌 Stake máximo por pick (%)", min_value=0.0, max_value=100.0, value=5.0)
liga = st.selectbox("🏆 Liga a analizar", ["CL", "EL", "PL", "PD", "SA"])
equipo1 = st.text_input("🔍 Equipo local (opcional)").strip().lower()
equipo2 = st.text_input("🔍 Equipo visitante (opcional)").strip().lower()
mercados = st.multiselect(
    "🎯 Mercados a analizar (si no seleccionas, se consideran todos)",
    ["¿quién gana?", "gol primera mitad", "over 2.5", "under 2.5", "ambos anotan"]
)

@st.cache_data(ttl=600)
def obtener_resultados(liga_codigo: str):
    """Obtiene resultados de la API football-data.org, devuelve dict con claves (local, visitante)."""
    if not API_KEY:
        st.warning("No se encontró FOOTBALL_DATA_API_KEY en las variables de entorno. No se podrán obtener resultados desde la API.")
        return {}

    url = f"https://api.football-data.org/v4/competitions/{liga_codigo}/matches"
    headers = {"X-Auth-Token": API_KEY}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        st.error(f"No se pudieron obtener resultados desde la API: {e}")
        return {}

    resultados = {}
    for partido in data.get("matches", []):
        if partido.get("status") == "FINISHED":
            local = partido.get("homeTeam", {}).get("name", "").strip().lower()
            visitante = partido.get("awayTeam", {}).get("name", "").strip().lower()
            resultado = partido.get("score", {})
            if local and visitante:
                resultados[(local, visitante)] = resultado
    return resultados

resultados = obtener_resultados(liga)

csv_file = st.file_uploader("📁 Subí tu archivo CSV con picks", type="csv")
pdf_file = st.file_uploader("📘 Subí tu archivo PDF táctico", type="pdf")

df_picks = pd.DataFrame()
if csv_file:
    try:
        df_csv = pd.read_csv(csv_file)
        # Normalizar nombres de columnas a minúsculas para evitar KeyError
        df_csv.columns = [c.strip().lower() for c in df_csv.columns]
        df_picks = pd.concat([df_picks, df_csv], ignore_index=True)
    except Exception as e:
        st.error(f"Error leyendo CSV: {e}")

if pdf_file:
    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_file.read()))
        texto_pdf = ""
        for page in pdf_reader.pages:
            txt = page.extract_text()
            if txt:
                texto_pdf += txt + "\n"

        # Extraer líneas que contengan "vs" o " v " y que además incluyan alguno de los mercados (si se seleccionaron)
        picks_pdf = []
        for linea in texto_pdf.splitlines():
            linea_strip = linea.strip()
            linea_lower = linea_strip.lower()
            if not linea_lower:
                continue
            if (" vs " in linea_lower) or (" v " in linea_lower) or (" vs. " in linea_lower):
                # Si el usuario seleccionó mercados, filtrar líneas que no los contengan
                if mercados and not any(m.lower() in linea_lower for m in mercados):
                    continue
                # Regex flexible: nombre local vs visitante <mercado> <eleccion> <cuota> [stake]
                m = re.search(
                    r"(?P<local>.+?)\s+v(?:s)?\.\?\s+(?P<visitante>.+?)\s+(?P<mercado>\S+(?:\s*\S)?)\s+(?P<eleccion>\S+)\s+(?P<cuota>[\d.,]+)(?:\s+(?P<stake>[\d.,]+))?",
                    linea_strip,
                    flags=re.IGNORECASE
                )
                if m:
                    local = m.group("local").strip().lower()
                    visitante = m.group("visitante").strip().lower()
                    mercado = m.group("mercado").strip().lower()
                    eleccion = m.group("eleccion").strip().lower()
                    cuota_raw = m.group("cuota").replace(",", ".")
                    stake_raw = (m.group("stake") or "1").replace(",", ".")
                    try:
                        cuota = float(cuota_raw)
                    except:
                        cuota = 1.0
                    try:
                        stake = float(stake_raw)
                    except:
                        stake = 1.0
                    picks_pdf.append({
                        "fecha": "PDF",
                        "local": local,
                        "visitante": visitante,
                        "mercado": mercado,
                        "eleccion": eleccion,
                        "cuota": cuota,
                        "stake": stake
                    })
        if picks_pdf:
            df_pdf = pd.DataFrame(picks_pdf)
            df_picks = pd.concat([df_picks, df_pdf], ignore_index=True)
    except Exception as e:
        st.error(f"Error procesando PDF: {e}")

# Si no hay picks cargados, mostramos indicación
if df_picks.empty:
    st.info("Subí un CSV o PDF con picks para analizarlos.")
else:
    # Normalizar columnas esperadas para evitar KeyError y permitir flexibilidad en el CSV
    expected_cols = {
        "fecha": "fecha",
        "local": "local",
        "visitante": "visitante",
        "mercado": "mercado",
        "eleccion": "eleccion",
        "elección": "eleccion",
        "cuota": "cuota",
        "stake": "stake",
        "apuesta": "stake"
    }
    # Renombrar columnas si hay equivalentes
    cols_map = {}
    for col in df_picks.columns:
        c = col.strip().lower()
        if c in expected_cols:
            cols_map[col] = expected_cols[c]
    if cols_map:
        df_picks = df_picks.rename(columns=cols_map)

    historial = []
    repetidos = set()
    aciertos = 0
    rentabilidad_total = 0.0

    for _, fila in df_picks.iterrows():
        # Obtener campos con tolerancia a missing data
        local = str(fila.get("local", "")).strip().lower()
        visitante = str(fila.get("visitante", "")).strip().lower()
        mercado = str(fila.get("mercado", "")).strip().lower()
        eleccion = str(fila.get("eleccion", "")).strip().lower()
        fecha = fila.get("fecha", "")

        # Convertir cuota y stake con tolerancia a comas y errores
        try:
            cuota = float(str(fila.get("cuota", 1)).replace(",", "."))
        except:
            cuota = 1.0
        try:
            stake_raw = float(str(fila.get("stake", 1)).replace(",", "."))
        except:
            stake_raw = 1.0

        # Si el usuario especificó equipos, filtrar por ese enfrentamiento (cualquier orden)
        if equipo1 and equipo2:
            match_selected = (local == equipo1 and visitante == equipo2) or (local == equipo2 and visitante == equipo1)
            if not match_selected:
                continue

        # Buscar resultado en ambos órdenes por si la API tiene el orden invertido
        resultado_real = resultados.get((local, visitante)) or resultados.get((visitante, local))
        if not resultado_real:
            # No hay resultado para ese enfrentamiento, saltar
            continue

        goles_local = resultado_real.get("fullTime", {}).get("home", 0) or 0
        goles_visitante = resultado_real.get("fullTime", {}).get("away", 0) or 0
        goles_ht_local = resultado_real.get("halfTime", {}).get("home", 0) or 0
        goles_ht_visitante = resultado_real.get("halfTime", {}).get("away", 0) or 0
        total_goles = (goles_local or 0) + (goles_visitante or 0)

        acertado = False
        # Normalizar variantes del mercado "quién gana?"
        if mercado in ["¿quién gana?", "quién gana?", "quien gana?", "quien gana", "quién gana"]:
            if eleccion in ["local", "home"] and goles_local > goles_visitante:
                acertado = True
            elif eleccion in ["visitante", "away"] and goles_visitante > goles_local:
                acertado = True
            elif eleccion in ["empate", "draw", "tie"] and goles_local == goles_visitante:
                acertado = True
        elif mercado in ["gol primera mitad", "gol primera mitad?"]:
            goles_ht = (goles_ht_local or 0) + (goles_ht_visitante or 0)
            if eleccion in ["sí", "si", "yes"] and goles_ht > 0:
                acertado = True
            elif eleccion in ["no", "not"] and goles_ht == 0:
                acertado = True
        elif "over" in mercado or "under" in mercado:
            parts = mercado.split()
            umbral = None
            if len(parts) >= 2:
                try:
                    umbral = float(parts[1])
                except:
                    umbral = None
            if umbral is not None:
                if "over" in mercado and total_goles > umbral:
                    acertado = True
                elif "under" in mercado and total_goles < umbral:
                    acertado = True
        elif "ambos anotan" in mercado or mercado == "ambos anotan":
            if (goles_local > 0) and (goles_visitante > 0):
                acertado = True

        # Interpretación de stake:
        # - si stake_raw está entre 0 < stake_raw <= 100 lo consideramos porcentual (%) del bankroll
        # - en otro caso lo consideramos un importe en pesos
        if bankroll > 0 and 0 < stake_raw <= 100:
            stake_amount = bankroll * stake_raw / 100.0
        else:
            stake_amount = stake_raw

        estado = "✅ Acertado" if acertado else "❌ Fallado"
        rentabilidad = (cuota - 1) * stake_amount if acertado else -stake_amount
        rentabilidad_total += rentabilidad
        if acertado:
            aciertos += 1

        if stake_amount > (bankroll * stake_maximo / 100):
            estado += " ⚠️ Stake excedido"

        key_rep = (local, visitante, mercado)
        if key_rep in repetidos:
            estado += " 🔁 Pick repetido"
        else:
            repetidos.add(key_rep)

        historial.append({
            "fecha": fecha,
            "local": local.title(),
            "visitante": visitante.title(),
            "mercado": mercado,
            "elección": eleccion,
            "resultado": f"{goles_local}-{goles_visitante}",
            "estado": estado,
            "rentabilidad": round(rentabilidad, 2)
        })

    if len(historial) == 0:
        st.info("No hay picks procesables para los equipos/mercados seleccionados.")
    else:
        df_historial = pd.DataFrame(historial)
        st.subheader("📌 Historial táctico procesado")
        st.dataframe(df_historial)

        porcentaje_aciertos = round((aciertos / len(historial)) * 100, 2) if len(historial) > 0 else 0.0
        st.subheader("📅 Resumen del día")
        st.markdown(f"🎯 Picks totales: {len(historial)}")
        st.markdown(f"✅ Aciertos: {aciertos} ({porcentaje_aciertos}%)")
        st.markdown(f"💰 Rentabilidad total: {round(rentabilidad_total, 2)} pesos")

        if porcentaje_aciertos < 75:
            st.warning("⚠️ Tu porcentaje de aciertos está por debajo del 75%")

        st.download_button("💾 Descargar historial táctico", df_historial.to_csv(index=False), "historial_tactico.csv", "text/csv")
