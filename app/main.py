import os
from datetime import date
from typing import Optional, Tuple

import psycopg
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from groq import Groq
from lxml import etree
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

load_dotenv(override=True)

TOKEN_API = os.getenv("API_TOKEN", "dev-token")
DSN_BD = os.getenv("DB_DSN", "postgresql://user:pass@localhost:5432/db")
RUTA_XSD = os.getenv("C1_XSD_PATH", "./schemas/c1.xsd")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

seguridad = HTTPBearer()
app = FastAPI(title="Validador CNMC C1 PoC")


# -----------------------------
# Base de datos (psycopg)
# -----------------------------

def obtener_conexion_bd():
    # Conexión simple por petición (PoC). En producción, usar un pool.
    return psycopg.connect(DSN_BD)


def asegurar_tabla(conn) -> None:
    # Crea la tabla si no existe en el esquema actual
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.solicitudes_c1 (
              id BIGSERIAL PRIMARY KEY,
              recibido_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              xml_recibido TEXT NOT NULL,
              xsd_valido BOOLEAN,
              contenido_valido BOOLEAN,
              analisis_ia TEXT,
              estado_respuesta INTEGER
            );
            """
        )


def insertar_solicitud(xml_recibido: str) -> int:
    # Inserta el registro inicial y devuelve su ID
    with obtener_conexion_bd() as conn:
        asegurar_tabla(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.solicitudes_c1 (xml_recibido)
                VALUES (%s)
                RETURNING id
                """,
                (xml_recibido,),
            )
            return cur.fetchone()[0]


def actualizar_solicitud(
    solicitud_id: int,
    *,
    xsd_valido: Optional[bool] = None,
    contenido_valido: Optional[bool] = None,
    analisis_ia: Optional[str] = None,
    estado_respuesta: Optional[int] = None,
):
    # Actualiza solo los campos indicados
    campos = []
    valores = []

    if xsd_valido is not None:
        campos.append("xsd_valido = %s")
        valores.append(xsd_valido)
    if contenido_valido is not None:
        campos.append("contenido_valido = %s")
        valores.append(contenido_valido)
    if analisis_ia is not None:
        campos.append("analisis_ia = %s")
        valores.append(analisis_ia)
    if estado_respuesta is not None:
        campos.append("estado_respuesta = %s")
        valores.append(estado_respuesta)

    if not campos:
        return

    valores.append(solicitud_id)

    with obtener_conexion_bd() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE public.solicitudes_c1 SET {', '.join(campos)} WHERE id = %s",
                tuple(valores),
            )


# -----------------------------
# Autenticación (Bearer token)
# -----------------------------

def requerir_token(
    credenciales: HTTPAuthorizationCredentials = Depends(seguridad),
) -> bool:
    # Validación simple de token (PoC). Sustituir por JWT si aplica.
    if (
        credenciales.scheme.lower() != "bearer"
        or credenciales.credentials != TOKEN_API
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token bearer inválido",
        )
    return True


# -----------------------------
# Reglas de negocio (Pydantic)
# -----------------------------

class DatosNegocioC1(BaseModel):
    # Campos mínimos a validar del contenido XML
    cups: str = Field(..., min_length=20, max_length=20)
    fecha_solicitud: date

    @field_validator("cups")
    @classmethod
    def validar_formato_cups(cls, valor: str) -> str:
        # Regla simple de CUPS para PoC
        import re

        patron = r"^ES[A-Z0-9]{18}$"
        if not re.match(patron, valor):
            raise ValueError("Formato de CUPS inválido (ES + 18 alfanum)")
        return valor

    @field_validator("fecha_solicitud")
    @classmethod
    def validar_fecha_no_pasada(cls, valor: date) -> date:
        # La fecha debe ser hoy o futura
        if valor < date.today():
            raise ValueError("FechaSolicitud no puede estar en el pasado")
        return valor


# -----------------------------
# Validación XSD (lxml)
# -----------------------------

def validar_con_xsd(bytes_xml: bytes) -> Tuple[bool, str]:
    # Devuelve (es_valido, mensaje_error)
    try:
        xml_doc = etree.fromstring(bytes_xml)
    except Exception as exc:
        return False, f"Error de parseo XML: {exc}"

    try:
        with open(RUTA_XSD, "rb") as archivo_xsd:
            xsd_doc = etree.parse(archivo_xsd)
        esquema = etree.XMLSchema(xsd_doc)
        esquema.assertValid(xml_doc)
        return True, ""
    except Exception as exc:
        return False, f"Error XSD: {exc}"


# -----------------------------
# Extracción de campos mínimos
# -----------------------------

def extraer_campos_minimos(bytes_xml: bytes) -> DatosNegocioC1:
    # Para PoC, se buscan etiquetas por nombre sin namespaces
    raiz = etree.fromstring(bytes_xml)

    cups_el = raiz.find(".//CUPS")
    fecha_el = raiz.find(".//FechaSolicitud")

    if cups_el is None or fecha_el is None:
        raise ValueError("Faltan campos requeridos: CUPS o FechaSolicitud")

    texto_cups = (cups_el.text or "").strip()
    texto_fecha = (fecha_el.text or "").strip()

    try:
        fecha = date.fromisoformat(texto_fecha)
    except Exception as exc:
        raise ValueError(f"FechaSolicitud inválida: {exc}") from exc

    return DatosNegocioC1(cups=texto_cups, fecha_solicitud=fecha)


# -----------------------------
# Análisis IA (Groq)
# -----------------------------

def analizar_error_groq(xml_texto: str, mensaje_error: str) -> str:
    # Si no hay API key, devolver mensaje mínimo
    if not GROQ_API_KEY:
        return "Análisis IA no disponible (falta GROQ_API_KEY)."

    cliente = Groq(api_key=GROQ_API_KEY)

    try:
        with open(RUTA_XSD, "r", encoding="utf-8", errors="replace") as archivo_xsd:
            texto_xsd = archivo_xsd.read()
    except Exception as exc:
        texto_xsd = f"(No se pudo leer el XSD en {RUTA_XSD}: {exc})"

    mensaje_prompt = (
        "Ayudas a depurar una petición XML del proceso C1 de la CNMC.\n"
        "Dado el error de validación, explica en 1-2 viñetas qué puede estar mal.\n"
        "No inventes campos; céntrate en estructura/etiquetas/formatos de fecha.\n\n"
        f"Error de validación:\n{mensaje_error}\n\n"
        f"XSD:\n{texto_xsd}\n\n"
        f"XML:\n{xml_texto}"
    )

    try:
        respuesta = cliente.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": mensaje_prompt}],
            temperature=0.2,
        )
        return respuesta.choices[0].message.content.strip()
    except Exception as exc:
        return f"Análisis IA no disponible (error Groq: {exc.__class__.__name__})."


# -----------------------------
# Endpoint
# -----------------------------

@app.post("/c1/validate")
async def validar_c1(
    _: bool = Depends(requerir_token),
    archivo: UploadFile = File(..., alias="file"),
):
    bytes_xml = await archivo.read()
    xml_texto = bytes_xml.decode("utf-8", errors="replace")

    # Paso 1: persistir recepción
    solicitud_id = insertar_solicitud(xml_texto)

    # Paso 2: validación XSD
    xsd_valido, error_xsd = validar_con_xsd(bytes_xml)
    actualizar_solicitud(solicitud_id, xsd_valido=xsd_valido)

    if not xsd_valido:
        texto_ia = analizar_error_groq(xml_texto, error_xsd)
        actualizar_solicitud(
            solicitud_id,
            contenido_valido=False,
            analisis_ia=texto_ia,
            estado_respuesta=400,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "request_id": solicitud_id,
                "ok": False,
                "error_code": "XSD_INVALID",
                "message": "El XML no cumple con el XSD.",
                "ai": texto_ia,
            },
        )

    # Paso 3: reglas de negocio (CUPS + FechaSolicitud)
    try:
        _ = extraer_campos_minimos(bytes_xml)
        actualizar_solicitud(solicitud_id, contenido_valido=True)
    except Exception as exc:
        error_contenido = f"Error de reglas de negocio: {exc}"
        texto_ia = analizar_error_groq(xml_texto, error_contenido)
        actualizar_solicitud(
            solicitud_id,
            contenido_valido=False,
            analisis_ia=texto_ia,
            estado_respuesta=400,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "request_id": solicitud_id,
                "ok": False,
                "error_code": "CONTENT_INVALID",
                "message": "El contenido no cumple reglas mínimas.",
                "ai": texto_ia,
            },
        )

    # Paso 4: éxito
    actualizar_solicitud(solicitud_id, estado_respuesta=200)
    return {"request_id": solicitud_id, "ok": True, "error_code": "OK"}
