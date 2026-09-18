# Canal de WhatsApp

Permite preguntar por los datos desde WhatsApp, con el mismo agente, las mismas validaciones y
el mismo enmascaramiento de PII que la web. La conexión con WhatsApp la resuelve
[Evolution API](https://doc.evolution-api.com), que corre como un contenedor más.

```
Teléfono ──► WhatsApp ──► Evolution API ──► webhook ──► agente ──► almacén / copia local
   ▲                                                       │
   └───────────── respuesta en texto plano ◄───────────────┘
```

## Levantarlo

```bash
docker compose --profile whatsapp up -d          # Evolution API + su base y su caché
docker compose up -d app                         # la aplicación, si no estaba
```

Evolution queda en http://localhost:8089 (su panel, en `/manager`) y la aplicación lo alcanza
como `http://evolution-api:8080` dentro de la red de compose.

Luego, en **Configuración → WhatsApp**:

1. **Vincular teléfono**: genera el código QR. Se escanea desde WhatsApp en el teléfono
   (Dispositivos vinculados → Vincular dispositivo). El estado pasa de `connecting` a `open`.
2. **Aplicar webhook**: registra `http://app:8000/api/canales/whatsapp/webhook` en Evolution
   para que los mensajes lleguen a la aplicación.
3. **Números autorizados**: la lista de quienes pueden usar el canal, con código de país.
4. **Canal activo**: enciende el canal.

Todo eso también se puede dejar fijo en el `.env`:

```bash
WHATSAPP_ENABLED=true
EVOLUTION_URL=http://evolution-api:8080
EVOLUTION_API_KEY=optimiza-evolution-key
EVOLUTION_INSTANCE=optimiza
WHATSAPP_AUTORIZADOS=51999888777,51988777666
PUBLIC_BASE_URL=https://optimiza.tu-dominio.com
```

## Seguridad

WhatsApp es un canal abierto: cualquiera que consiga el número puede escribir. Por eso:

- **Lista de autorizados obligatoria.** Sin `WHATSAPP_AUTORIZADOS` el canal no responde a
  nadie; a un número desconocido se le contesta que no tiene acceso y queda registrado en la
  auditoría. Es una decisión deliberada: es preferible un canal mudo a uno que filtre datos.
- **Los grupos se ignoran**, igual que los mensajes propios y los que no son texto.
- **La auditoría guarda solo los últimos cuatro dígitos** del número, nunca el mensaje completo
  ni el número entero.
- Se mantienen todas las defensas de la web: consulta de solo lectura, validación del SQL,
  límite de filas y enmascaramiento de PII antes de responder.
- La `AUTHENTICATION_API_KEY` de Evolution protege su API. Cámbiala antes de exponer el
  servicio: con esa clave se pueden crear instancias y enviar mensajes.
- **No publiques el puerto de Evolution en internet.** Si hace falta acceso remoto, ponlo
  detrás del mismo proxy que la aplicación, con TLS y autenticación.

## Formato de la respuesta

WhatsApp no tiene tarjetas, tablas ni paneles plegables, así que la respuesta se reescribe:

```
Ingreso total de los 7 primeros: *S/ 121.8 millones*. Lidera *Trujillo* con
S/ 21.4 millones, el 17.5% del total mostrado.

*Ingreso por región*
• Trujillo: S/ 21.4 M
• Santiago: S/ 18.0 M
• Bogotá: S/ 17.1 M
…y 4 más.

Descarga el detalle: https://optimiza.tu-dominio.com/api/export/wa:51999888777.csv

_Respuesta en 61 ms_
```

Reglas: negritas con un asterisco (formato de WhatsApp), hasta ocho filas en viñetas, el resto
se anuncia como "…y N más", enlace de descarga solo si `PUBLIC_BASE_URL` está definida, y un
máximo de 3 500 caracteres. Cuando el agente pide confirmación, las opciones van numeradas para
que el usuario conteste con un número.

El gráfico no se envía: es la diferencia real con la web. Está anotado como pendiente de diseño
en [design/diseno-ui.md](../design/diseno-ui.md), sección 11.

## Sesiones

Cada número es una sesión del agente (`wa:<número>`), así que el historial, la caché del último
resultado y la exportación funcionan igual que en la web. Un "exporta eso a Excel" después de
una consulta reutiliza el resultado anterior sin volver a consultar la base.

## Probarlo sin teléfono

En **Configuración → WhatsApp**, el campo de prueba responde con el texto exacto que saldría
por WhatsApp, sin enviarlo. También por API:

```bash
curl -s -X POST localhost:8000/api/canales/whatsapp/probar \
  -H 'Content-Type: application/json' \
  -d '{"texto":"ingreso por región"}' | jq -r .texto
```

Y se puede simular un mensaje entrante como si viniera de Evolution:

```bash
curl -s -X POST localhost:8000/api/canales/whatsapp/webhook \
  -H 'Content-Type: application/json' \
  -d '{"event":"messages.upsert","instance":"optimiza",
       "data":{"key":{"remoteJid":"51999888777@s.whatsapp.net","fromMe":false,"id":"X1"},
               "message":{"conversation":"ventas por mes"}}}'
```

## API

| Endpoint | Para qué |
|---|---|
| `GET /api/canales/whatsapp/estado` | Estado del servicio, de la sesión y del webhook |
| `POST /api/canales/whatsapp/instancia` | Crea la instancia y devuelve el QR |
| `POST /api/canales/whatsapp/configurar` | Autorizados, URL pública, webhook y encendido |
| `POST /api/canales/whatsapp/probar` | Previsualiza o envía una respuesta |
| `POST /api/canales/whatsapp/webhook` | Lo llama Evolution con cada evento |

El webhook **siempre responde 200**, incluso ante un cuerpo inválido: si devolviera un error,
Evolution reintentaría el mismo mensaje indefinidamente. La consulta al agente ocurre en
segundo plano, porque puede tardar más que el margen de reintento.

## Operación

- **El QR caduca.** Si la sesión pasa a `close`, hay que volver a vincular desde el panel.
- **Los datos de la sesión** viven en el volumen `evolution-instances`; borrarlo obliga a
  vincular de nuevo.
- **Fijar la versión**: la imagen por defecto es `evoapicloud/evolution-api:latest`. En
  producción conviene fijarla con `EVOLUTION_IMAGE=evoapicloud/evolution-api:v2.3.7`.
- **Puerto**: `EVOLUTION_PORT` (8089 por omisión) por si el 8080 está ocupado.
- Los eventos quedan en la auditoría: `whatsapp_recibido`, `whatsapp_respondido`,
  `whatsapp_no_autorizado`, `whatsapp_error`.

## Limitaciones conocidas

- Evolution API usa una sesión de WhatsApp Web (Baileys), no la API oficial de WhatsApp
  Business. Es lo adecuado para un piloto interno; para uso masivo o comercial hay que evaluar
  la API oficial, que exige plantillas aprobadas y una ventana de 24 horas para responder.
- Un solo número por instancia. Para varios equipos, varias instancias.
- Sin gráficos ni archivos adjuntos: solo texto y enlaces.
- La lista de autorizados es por número, no por rol. El control de acceso por fila y columna
  está en la fase 2 del [plan de trabajo](../PLAN_DE_TRABAJO.md).
