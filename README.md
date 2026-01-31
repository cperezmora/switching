# Validador CNMC C1 (PoC)

API REST en FastAPI para validar XML C1 (CNMC) con:
- Autenticación Bearer token simple.
- Validación XSD con `lxml`.
- Reglas de negocio mínimas con Pydantic (CUPS y FechaSolicitud).
- Análisis de errores con Groq (opcional).
- Persistencia en PostgreSQL por solicitud.

## Requisitos
- Python 3.10+
- PostgreSQL

## Instalación
```bash
pip install -r requirements.txt
```

## Configuración
1) Copia `.env` y ajusta los valores según tu entorno.
2) Revisa `env.txt` para la explicación de cada variable.
3) Si envías XML/XSD completos a Groq, usa un modelo con contexto grande (por ejemplo `openai/gpt-oss-20b`).

## Base de datos
Tabla mínima recomendada:
```sql
CREATE TABLE IF NOT EXISTS public.solicitudes_c1 (
  id BIGSERIAL PRIMARY KEY,
  recibido_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  xml_recibido TEXT NOT NULL,
  xsd_valido BOOLEAN,
  contenido_valido BOOLEAN,
  analisis_ia TEXT,
  estado_respuesta INTEGER
);
```
Nota: la API intenta crear automáticamente esta tabla si no existe. Para ello el usuario de la BD debe tener permisos de `CREATE` en el esquema `public`.

## XSD
Se incluye un XSD de ejemplo en `schemas/c1.xsd` con campos mínimos.
Sustitúyelo por el XSD oficial de CNMC o el que corresponda a tu entorno.

## Ejemplos XML
En `datos/` tienes archivos de prueba para validar distintos escenarios:
- `datos/c1_correcto.xml` → válido (XSD + reglas).
- `datos/c1_xsd_invalido.xml` → falla el XSD (falta nodo `Agentes`).
- `datos/c1_fecha_invalida.xml` → falla reglas por fecha en el pasado.
- `datos/c1_invalido_cups.xml` → falla reglas por CUPS inválido.

## Ejecutar
```bash
uvicorn app.main:app --reload --env-file .env
```

## Endpoint
**POST** `/c1/validate`

Headers:
- `Authorization: Bearer <API_TOKEN>`

Body (multipart/form-data):
- `file`: archivo XML

Respuesta (JSON):
- `200 OK` si todo bien
- `400 Bad Request` si falla XSD o reglas
- `401 Unauthorized` si el token es inválido

Ejemplo de uso en local (CLI o Postman):
```bash
curl --location "http://127.0.0.1:8000/c1/validate" \
  --header "Authorization: Bearer dev-token" \
  --form "file=@/path/to/file"
```

Ejemplo de error:
```json
{
  "request_id": 123,
  "ok": false,
  "error_code": "XSD_INVALID",
  "message": "El XML no cumple con el XSD.",
  "ai": "..."
}
```

## Respuestas típicas (ejemplos reales)
Estas pruebas se obtuvieron con el modelo **llama-3.3-70b-versatile** que ofrece Groq.

XSD inválido:
```json
{
  "detail": {
    "request_id": 1,
    "ok": false,
    "error_code": "XSD_INVALID",
    "message": "El XML no cumple con el XSD.",
    "ai": "Para depurar la petición XML del proceso C1 de la CNMC, se pueden considerar los siguientes puntos:\n\n* El error indica que falta el elemento `Agentes` dentro de `CambioComercializador`. Esto significa que el XML debe incluir un nodo `Agentes` con los elementos `ComercializadorEntrante` y `Distribuidor` para cumplir con la estructura definida en el XSD.\n* La fecha en el elemento `FechaSolicitud` está en el formato correcto (`aaaa-mm-dd`), que coincide con el tipo `xsd:date` definido en el XSD, por lo que no parece haber problemas con el formato de la fecha. El problema principal radica en la falta del nodo `Agentes`. \n\nPor ejemplo, el XML corregido podría tener una estructura similar a la siguiente:\n\n```xml\n<CambioComercializador>\n    <DatosSolicitud>\n        <CodigoProceso>C1</CodigoProceso>\n        <CUPS>ES0022000005180955CP</CUPS>\n        <FechaSolicitud>2026-01-31</FechaSolicitud>\n    </DatosSolicitud>\n    <Agentes>\n        <ComercializadorEntrante>NombreComercializadorEntrante</ComercializadorEntrante>\n        <Distribuidor>NombreDistribuidor</Distribuidor>\n    </Agentes>\n</CambioComercializador>\n```"
  }
}
```

Fecha inválida:
```json
{
  "detail": {
    "request_id": 2,
    "ok": false,
    "error_code": "CONTENT_INVALID",
    "message": "El contenido no cumple reglas mínimas.",
    "ai": "Para depurar la petición XML del proceso C1 de la CNMC, considera los siguientes puntos:\n\n* La fecha proporcionada en el campo `FechaSolicitud` es `2026-01-30`, lo que está en el pasado según el mensaje de error. Asegúrate de que la fecha sea posterior o igual a la fecha actual.\n* Verifica que el formato de la fecha sea correcto según el esquema XSD, que es `xsd:date`, lo que implica un formato `aaaa-mm-dd`, que en este caso parece estar bien. Sin embargo, el error indica un problema con la fecha en sí, no con el formato."
  }
}
```

CUPS inválido:
```json
{
  "detail": {
    "request_id": 3,
    "ok": false,
    "error_code": "CONTENT_INVALID",
    "message": "El contenido no cumple reglas mínimas.",
    "ai": "Para depurar la petición XML del proceso C1 de la CNMC, se pueden considerar los siguientes puntos:\n\n* El error indica que el campo `CUPS` tiene un valor demasiado corto, con solo 20 caracteres (`ES00INVALIDO0000000`). Sin embargo, el esquema XSD define el campo `CUPS` como un string sin una longitud mínima específica. Esto sugiere que el problema puede estar en la validación adicional implementada en el sistema que procesa el XML, que requiere un mínimo de 20 caracteres para el campo `CUPS`. Es posible que el valor proporcionado sea incorrecto o no cumpla con los requisitos del sistema.\n* La estructura y los formatos de fecha en el XML parecen correctos, ya que el campo `FechaSolicitud` tiene el formato `YYYY-MM-DD`, que coincide con el tipo `xsd:date` definido en el esquema XSD. Por lo tanto, el problema parece estar relacionado con el campo `CUPS` y no con la estructura o los formatos de fecha."
  }
}
```

Petición correcta:
```json
{
  "request_id": 4,
  "ok": true,
  "error_code": "OK"
}
```

## Notas de PoC
- La validación CUPS es solo de formato: `^ES[A-Z0-9]{18}$`.
- `FechaSolicitud` no puede ser anterior a hoy.
- El análisis IA solo se ejecuta si existe `GROQ_API_KEY`.

## Contexto y propósito (presentación)
Este proyecto forma parte de la presentación del **Talent Data Path de febrero de 2026 para Bluetab**.  
Basado en las láminas compartidas, el objetivo es explicar un caso tecnológico de **switching eléctrico** y cómo una API puede ayudar a validar y trazar el proceso.

¿Qué problema refleja la presentación?
- Muchos actores (generación, transporte, distribución, comercialización y consumidor) intercambian información.
- Existen múltiples tipos de comunicaciones, y el intercambio se realiza en **XML**.
- Validar formato y reglas de negocio es clave antes de procesar cambios de comercializador.

¿Qué solución muestra?
- Un flujo claro: **recepción** → **validación de origen** → **validación XSD** → **reglas de negocio** → **análisis IA** → **respuesta al cliente**.
- Persistencia de cada paso en base de datos para auditoría y trazabilidad.
- Uso de una API backend con FastAPI y PostgreSQL, y un apoyo de IA (Groq) para explicar errores.
- Capa de análisis con Power BI para informes y dashboards.

## Recursos y enlaces
- Guía informativa para consumidores de electricidad: https://www.cnmc.es/file/186215/download
- Formato de ficheros de intercambio: https://www.cnmc.es/expedientes/infde01119
- Python – Lenguaje: https://www.python.org
- FastAPI – Librería Python Endpoints: https://fastapi.tiangolo.com
- PostgreSQL – Base de datos: https://www.postgresql.org
- Render – Infraestructura en la nube como servicio: https://render.com
- Groq – IA como servicio: https://groq.com
- Power BI – Análisis de datos: https://www.microsoft.com/es-es/power-platform/products/power-bi

## Licencia
Este proyecto está bajo la licencia MIT. Consulte el archivo `LICENSE` para obtener más detalles.

MIT License
Copyright (c) 2026 Carmen Pérez

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
