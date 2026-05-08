import streamlit as st
from datetime import datetime, timedelta
from anthropic import Anthropic
import os
from dotenv import load_dotenv
import csv
import pandas as pd
import gspread
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

if "chat" not in st.session_state:
    st.session_state.chat = []
if "mostrar_form_cita" not in st.session_state:
    st.session_state.mostrar_form_cita = False
if "nombre_para_cita" not in st.session_state:
    st.session_state.nombre_para_cita = ""
if "errores_cita" not in st.session_state:
    st.session_state.errores_cita = []

# Cliente Claude
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Rutas absolutas para que funcionen desde cualquier directorio
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUTA_CREDENCIALES = os.path.join(BASE_DIR, "credentials", "google_credentials.json")
RUTA_CSV = os.path.join(BASE_DIR, "..", "leads.csv")

# Conexión con Google Sheets (cacheada para no reconectar en cada rerun)
@st.cache_resource
def conectar_sheets():
    SHEET_ID = "1KrBxM1JAJ5ipDnvLB88vMOwCP_aYvMkPiVE1a7I-In0"
    gc = gspread.service_account(filename=RUTA_CREDENCIALES)
    return gc.open_by_key(SHEET_ID).sheet1

try:
    hoja = conectar_sheets()
    sheets_ok = True
except Exception as e:
    st.warning(f"Google Sheets no disponible: {e}")
    hoja = None
    sheets_ok = False


def crear_evento_calendar(nombre, fecha_hora, email_paciente=None):
    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    creds = service_account.Credentials.from_service_account_file(
        RUTA_CREDENCIALES, scopes=SCOPES
    )
    service = build("calendar", "v3", credentials=creds)

    fin = fecha_hora + timedelta(hours=1)
    evento = {
        "summary": f"Cita fisioterapia — {nombre}",
        "description": f"Paciente: {nombre}\nEmail: {email_paciente or ''}",
        "start": {"dateTime": fecha_hora.isoformat(), "timeZone": "Europe/Madrid"},
        "end": {"dateTime": fin.isoformat(), "timeZone": "Europe/Madrid"},
    }

    CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()


def enviar_email_confirmacion(email_paciente, nombre, fecha_hora):
    GMAIL_USER = os.getenv("GMAIL_USER")
    GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = email_paciente
    msg["Subject"] = "Confirmación de cita — Clínica de Fisioterapia"

    cuerpo = f"""Hola {nombre},

Tu cita ha sido confirmada para el {fecha_hora.strftime('%d/%m/%Y a las %H:%M')}.

Si necesitas cancelar o cambiar la cita, responde a este email.

Un saludo,
Clínica de Fisioterapia
"""
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, email_paciente, msg.as_string())


# Crear CSV si no existe
if not os.path.exists(RUTA_CSV):
    with open(RUTA_CSV, "w", newline="", encoding="utf-8") as archivo_csv:
        writer = csv.writer(archivo_csv)
        writer.writerow(["fecha", "nombre", "mensaje", "tipo", "estado", "respuesta_ia"])

# Título app
st.title("Asistente Clínica de Fisioterapia")

if st.session_state.errores_cita:
    for err in st.session_state.errores_cita:
        st.error(f"Error al agendar: {err}")
    st.session_state.errores_cita = []

if st.button("🧹 Limpiar conversación"):
    st.session_state.chat = []
    st.session_state.mostrar_form_cita = False
    st.session_state.nombre_para_cita = ""
    st.rerun()

# Inputs
nombre = st.text_input("Tu nombre")
mensaje = st.text_area("Escribe tu mensaje")

# Mostrar historial
st.markdown("### 💬 Conversación")
for user, msg, resp in st.session_state.chat:
    st.markdown(
        f"""
        <div style='text-align: right; background-color:#DCF8C6; padding:10px; border-radius:10px; margin:10px 0'>
        <b>{user}</b><br>{msg}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div style='text-align: left; background-color:#F1F0F0; padding:10px; border-radius:10px; margin:10px 0'>
        <b>Asistente</b><br>{resp}
        </div>
        """,
        unsafe_allow_html=True,
    )

# Botón enviar
if st.button("Enviar"):
    if mensaje and nombre:
        mensaje_lower = mensaje.lower()
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

        prompt = f"""
Eres un asistente de una clínica de fisioterapia.

Responde de forma profesional, cercana y útil.
NO uses HTML ni etiquetas como <div>, <br>, etc.
No diagnostiques de forma concluyente.
Invita a reservar valoración si procede.

Paciente: {nombre}
Mensaje: {mensaje}

Respuesta:
"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        respuesta = response.content[0].text
        respuesta = respuesta.replace("</div>", "")

        st.session_state.chat.append((nombre, mensaje, respuesta))

        # Clasificación
        if "cita" in mensaje_lower:
            archivo_nombre = "citas.txt"
            tipo = "cita"
            st.session_state.mostrar_form_cita = True
            st.session_state.nombre_para_cita = nombre
        elif "dolor" in mensaje_lower:
            archivo_nombre = "dolor.txt"
            tipo = "dolor"
        else:
            archivo_nombre = "otros.txt"
            tipo = "otro"

        # Guardado en TXT
        ruta_txt = os.path.join(BASE_DIR, "..", archivo_nombre)
        with open(ruta_txt, "a", encoding="utf-8") as archivo:
            archivo.write(f"[{fecha}] {nombre}: {mensaje}\n")
            archivo.write(f"Respuesta IA: {respuesta}\n")
            archivo.write("-" * 50 + "\n")

        # Guardado en CSV
        with open(RUTA_CSV, "a", newline="", encoding="utf-8") as archivo_csv:
            writer = csv.writer(archivo_csv)
            writer.writerow([fecha, nombre, mensaje, tipo, "nuevo", respuesta])

        # Guardado en Google Sheets
        if sheets_ok:
            try:
                hoja.append_row([fecha, nombre, mensaje, tipo, "nuevo", respuesta])
            except Exception as e:
                st.warning(f"No se pudo guardar en Sheets: {e}")

        st.rerun()
    else:
        st.warning("Por favor, completa todos los campos.")

# Formulario de agendado de cita
if st.session_state.mostrar_form_cita:
    st.markdown("---")
    st.markdown("### 📅 Agendar cita")
    st.info(f"Hola **{st.session_state.nombre_para_cita}**, completa los datos para confirmar tu cita.")

    col_fecha, col_hora = st.columns(2)
    with col_fecha:
        fecha_cita = st.date_input("Fecha", min_value=datetime.today().date())
    with col_hora:
        hora_cita = st.time_input("Hora", value=datetime.strptime("09:00", "%H:%M").time())

    email_paciente = st.text_input("Tu email para la confirmación")

    if st.button("✅ Confirmar cita"):
        if not email_paciente:
            st.warning("Introduce tu email para recibir la confirmación.")
        else:
            fecha_hora_cita = datetime.combine(fecha_cita, hora_cita)
            errores = []

            # Google Calendar
            try:
                crear_evento_calendar(
                    st.session_state.nombre_para_cita, fecha_hora_cita, email_paciente
                )
            except Exception as e:
                errores.append(f"Google Calendar: {e}")

            # Email de confirmación
            try:
                enviar_email_confirmacion(
                    email_paciente, st.session_state.nombre_para_cita, fecha_hora_cita
                )
            except Exception as e:
                errores.append(f"Email: {e}")

            # Actualizar estado en CSV
            try:
                df_tmp = pd.read_csv(RUTA_CSV)
                mask = (df_tmp["nombre"] == st.session_state.nombre_para_cita) & (
                    df_tmp["tipo"] == "cita"
                )
                df_tmp.loc[mask, "estado"] = "cita agendada"
                df_tmp.to_csv(RUTA_CSV, index=False)
            except Exception as e:
                errores.append(f"CSV: {e}")

            # Actualizar estado en Google Sheets
            if sheets_ok:
                try:
                    registros = hoja.get_all_records()
                    for i, fila in enumerate(registros, start=2):
                        if (
                            fila.get("nombre") == st.session_state.nombre_para_cita
                            and fila.get("tipo") == "cita"
                        ):
                            hoja.update_cell(i, 5, "cita agendada")
                            break
                except Exception as e:
                    errores.append(f"Sheets estado: {e}")

            if errores:
                st.session_state.errores_cita = errores
                st.session_state.mostrar_form_cita = False
                st.session_state.nombre_para_cita = ""
                st.rerun()
            else:
                st.session_state.errores_cita = []
                st.session_state.mostrar_form_cita = False
                st.session_state.nombre_para_cita = ""
                st.success(
                    f"Cita confirmada para el {fecha_hora_cita.strftime('%d/%m/%Y a las %H:%M')}. "
                    f"Se ha enviado confirmación a {email_paciente}."
                )
                st.rerun()

# Tabla de leads
st.markdown("## 📋 Leads guardados")

df = pd.read_csv(RUTA_CSV)

# Métricas
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total leads", len(df))
col2.metric("Citas", len(df[df["tipo"] == "cita"]))
col3.metric("Dolor", len(df[df["tipo"] == "dolor"]))
col4.metric("Otros", len(df[df["tipo"] == "otro"]))

# Filtro
tipo_filtro = st.selectbox("Filtrar por tipo", ["todos", "cita", "dolor", "otro"])

if tipo_filtro != "todos":
    df_filtrado = df[df["tipo"] == tipo_filtro]
else:
    df_filtrado = df


def colorear_estado(val):
    if val == "nuevo":
        return "background-color: #FFE082"
    elif val == "contactado":
        return "background-color: #81D4FA"
    elif val == "cita agendada":
        return "background-color: #A5D6A7"
    return ""


st.dataframe(
    df_filtrado.style.map(colorear_estado, subset=["estado"]),
    use_container_width=True,
)

# Botón descargar CSV
with open(RUTA_CSV, "rb") as archivo_csv:
    st.download_button(
        label="📥 Descargar CSV",
        data=archivo_csv,
        file_name="leads.csv",
        mime="text/csv",
    )

# Actualizar estado manual
st.markdown("## ✏️ Actualizar estado de lead")

if not df.empty:
    indice_lead = st.selectbox("Selecciona el lead por índice", df.index.tolist())
    nuevo_estado = st.selectbox(
        "Nuevo estado", ["nuevo", "contactado", "cita agendada"]
    )

    if st.button("Actualizar estado"):
        df.loc[indice_lead, "estado"] = nuevo_estado
        df.to_csv(RUTA_CSV, index=False)
        st.success("Estado actualizado correctamente")
        st.rerun()
else:
    st.info("No hay leads para actualizar todavía.")
