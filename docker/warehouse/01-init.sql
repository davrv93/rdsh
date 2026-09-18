-- Inicialización del almacén analítico (stand-in de Redshift en local).
-- Crea el esquema, el usuario de solo lectura y los permisos que se usarían
-- en un cluster Redshift real.

CREATE SCHEMA IF NOT EXISTS analytics;

-- Usuario de solo lectura que utiliza la aplicación
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'optimiza_ro') THEN
    CREATE ROLE optimiza_ro LOGIN PASSWORD 'optimiza_ro_pwd';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE analytics TO optimiza_ro;
GRANT USAGE ON SCHEMA analytics TO optimiza_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO optimiza_ro;

-- Sin permisos de escritura en ningún caso
REVOKE CREATE ON SCHEMA analytics FROM optimiza_ro;
REVOKE ALL ON SCHEMA public FROM optimiza_ro;
