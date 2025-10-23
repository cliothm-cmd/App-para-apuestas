import streamlit as st
import pandas as pd
import requests
import PyPDF2
from io import BytesIO

API_KEY = "430ac074b10e42aeb776f65d06c51f54"

st.set_page_config(page_title="Análisis táctico de apuestas", layout="centered")
st.title("📊 Sistema táctico de apuestas deportivas")

bankroll = st.number_input("💰 Bankroll total (en pesos argentinos)", min_value=0.0)
stake_maximo = st.number_input("📌 Stake máximo por pick (%)", min_value=0.0, max_value=100.0, value=5.0)
liga = st.selectbox("🏆 Liga a analizar", ["CL", "EL", "PL", "PD", "SA"])
equipo1 = st.text_input("🔍 Equipo local").lower()
equipo2 = st.text_input("🔍 Equipo visitante").lower()
mercados = st.multiselect("🎯 Mercados a analizar", ["¿quién gana?", "gol primera mitad", "over 2.5", "under 2.5", "ambos anotan"])

@st.cache_data
def obtener_resultados(liga_codigo):
    url = f"https://api.football-data.org/v4/competitions/{liga_codigo}/matches"
    headers = {"X-Auth-Token": API_KEY}
    response = requests.get(url, headers=headers)
    data = response.json()
    resultados = {}
    for partido in data["matches"]:
        if partido["status"] == "FINISHED":
            local = partido["homeTeam"]["name"].lower()
            visitante = partido["awayTeam"]["name"].lower()
            resultado = partido["score"]
            resultados[(local, visitante)] = resultado
    return resultados

resultados = obtener_resultados(liga)

csv_file = st.file_uploader("📁 Subí tu archivo CSV con picks", type="csv")
pdf_file = st.file_uploader("📘 Subí tu archivo PDF táctico", type="pdf")

df_picks = pd.DataFrame()
if csv_file:
    df_csv = pd.read_csv(csv_file)
    df_picks = pd.concat([df_picks, df_csv], ignore_index=True)

if pdf_file:
    pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_file.read()))
    texto_pdf = ""
    for page in pdf_reader.pages:
        texto_pdf += page.extract_text()
    picks_pdf = []
    for linea in texto_pdf.split("\n"):
        if "vs" in linea and any(m in linea.lower() for m in mercados):
            partes = linea.split(" ")
            if len(partes) >= 6:
                picks_pdf.append({
                    "fecha": "PDF",
                    "local": partes[0].lower(),
                    "visitante": partes[2].lower(),
                    "mercado": partes[3].lower(),
                    "eleccion": partes[4].lower(),
                    "cuota": float(partes[5]),
                    "stake": float(partes[6]) if len(partes) > 6 else 1.0
                })
    df_pdf = pd.DataFrame(picks_pdf)
    df_picks = pd.concat([df_picks, df_pdf], ignore_index=True)
  if not df_picks.empty:
        historial = []
        repetidos = set()
        aciertos = 0
        rentabilidad_total = 0

        for _, fila in df_picks.iterrows():
            local = fila["local"].strip().lower()
            visitante = fila["visitante"].strip().lower()
            mercado = fila["mercado"].strip().lower()
            eleccion = fila["eleccion"].strip().lower()
            cuota = float(fila["cuota"])
            stake = float(fila["stake"])
            fecha = fila["fecha"]

            if (local != equipo1 and visitante != equipo2) and (local != equipo2 and visitante != equipo1):
                continue

            resultado_real = resultados.get((local, visitante))
            if not resultado_real:
                continue

            goles_local = resultado_real["fullTime"]["home"]
            goles_visitante = resultado_real["fullTime"]["away"]
            goles_ht_local = resultado_real["halfTime"]["home"]
            goles_ht_visitante = resultado_real["halfTime"]["away"]
            total_goles = goles_local + goles_visitante

            acertado = False
            if mercado == "¿quién gana?":
                if eleccion == "local" and goles_local > goles_visitante:
                    acertado = True
                elif eleccion == "visitante" and goles_visitante > goles_local:
                    acertado = True
                elif eleccion == "empate" and goles_local == goles_visitante:
                    acertado = True
            elif mercado == "gol primera mitad":
                if eleccion == "sí" and (goles_ht_local + goles_ht_visitante) > 0:
                    acertado = True
                elif eleccion == "no" and (goles_ht_local + goles_ht_visitante) == 0:
                    acertado = True
            elif "over" in mercado or "under" in mercado:
                try:
                    umbral = float(mercado.split(" ")[1])
                    if "over" in mercado and total_goles > umbral:
                        acertado = True
                    elif "under" in mercado and total_goles < umbral:
                        acertado = True
                except:
                    pass

            estado = "✅ Acertado" if acertado else "❌ Fallado"
            rentabilidad = (cuota - 1) * stake if acertado else -stake
            rentabilidad_total += rentabilidad
            if acertado:
                aciertos += 1

            if stake > (bankroll * stake_maximo / 100):
                estado += " ⚠️ Stake excedido"

            if (local, visitante, mercado) in repetidos:
                estado += " 🔁 Pick repetido"
            else:
                repetidos.add((local, visitante, mercado))

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

        df_historial = pd.DataFrame(historial)
        st.subheader("📌 Historial táctico procesado")
        st.dataframe(df_historial)

        porcentaje_aciertos = round((aciertos / len(historial)) * 100, 2)
        st.subheader("📅 Resumen del día")
        st.markdown(f"🎯 Picks totales: {len(historial)}")
        st.markdown(f"✅ Aciertos: {aciertos} ({porcentaje_aciertos}%)")
        st.markdown(f"💰 Rentabilidad total: {round(rentabilidad_total, 2)} pesos")

        if porcentaje_aciertos < 75:
            st.warning("⚠️ Tu porcentaje de aciertos está por debajo del 75%")

        st.download_button("💾 Descargar historial táctico", df_historial.to_csv(index=False), "historial_tactico.csv", "text/csv")
