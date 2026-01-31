CREATE TABLE IF NOT EXISTS solicitudes_c1 (
  id BIGSERIAL PRIMARY KEY,
  recibido_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  xml_recibido TEXT NOT NULL,
  xsd_valido BOOLEAN,
  contenido_valido BOOLEAN,
  analisis_ia TEXT,
  estado_respuesta INTEGER
);