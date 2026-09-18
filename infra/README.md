# Infraestructura

## Opción A — Almacén local en Docker (por defecto, sin costo)

`docker compose up --build` levanta un PostgreSQL que cumple el rol del almacén.
La aplicación se conecta con `psycopg2`, un usuario de solo lectura, `search_path`
al esquema `analytics` y `statement_timeout`: exactamente el mismo camino de código
que contra Redshift. Sirve para desarrollar y demostrar el flujo completo.

Diferencias con Redshift real: no hay nodos, ni distribución/orden de columnas, ni
`COPY` desde S3. El SQL que genera el agente es portable entre ambos.

## Opción B — Redshift Serverless real (cuesta dinero en tu cuenta)

Requisitos: credenciales de AWS con permisos sobre Redshift Serverless, `terraform`
y `psql`.

```bash
cd infra/terraform
terraform init
terraform apply \
  -var="admin_password=UnaClaveSegura123!" \
  -var="mi_ip=$(curl -s ifconfig.me)/32"
```

El `apply` crea namespace, workgroup y un security group que solo abre el puerto 5439
a tu IP. `terraform output siguiente_paso` imprime qué hacer después.

Luego, cargar datos y crear el usuario de solo lectura:

```bash
WAREHOUSE_HOST=<endpoint del output> \
WAREHOUSE_ADMIN_PASSWORD='UnaClaveSegura123!' \
REDSHIFT_RO_PASSWORD='OtraClaveSegura123!' \
bash infra/bootstrap_redshift.sh
```

Apuntar la aplicación al cluster: copiar las variables que imprime el script en `.env`
y levantar solo la app, sin el almacén local:

```bash
docker compose up -d app
```

**Costo:** Redshift Serverless cobra por RPU-hora mientras atiende consultas, con un
mínimo de 8 RPU. Un workgroup ocioso no cobra cómputo, pero el almacenamiento sí.
Para dejar de pagar: `terraform destroy`.

## Opción C — Cluster provisionado

Si la organización ya tiene un cluster, no hace falta crear nada: basta un usuario de
solo lectura con `GRANT USAGE` sobre el esquema y `GRANT SELECT` sobre las tablas, y
completar `REDSHIFT_*` en el `.env`. La aplicación nunca escribe: la sesión se abre con
`readonly=True` y el validador rechaza cualquier sentencia que no sea `SELECT`/`WITH`.
