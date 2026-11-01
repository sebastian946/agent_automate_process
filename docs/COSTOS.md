# Costos por conversación (Día 13)

Precios Anthropic (oct 2026, por millón de tokens): Sonnet 5.5 $2 in / $10 out · Haiku 5.5 $0.10 in / $0.50 out ·
lectura de caché ≈ 10 % del precio de entrada.

## Estimación: conversación de 10 turnos por WhatsApp

| Componente | Tokens por turno | Turnos | Total | Costo |
| --- | --- | --- | --- | --- |
| Ventas · bloque estable (rol+catálogo+reglas) **cacheado** | ~1.800 (lectura caché) | 10 | 18.000 | $0,0036 |
| Ventas · bloque dinámico (ficha + formato) + historial | ~600 → ~2.500 (crece) | 10 | ~15.000 | $0,030 |
| Ventas · salida (incluye thinking adaptativo en effort low) | ~250 | 10 | 2.500 | $0,025 |
| Perfilador (Haiku) · entrada | ~1.200 | 10 | 12.000 | $0,0012 |
| Perfilador (Haiku) · salida JSON | ~250 | 10 | 2.500 | $0,0013 |
| **Total aproximado** | | | | **≈ $0,06 por conversación** |

Con 100 conversaciones/mes ≈ $6. El costo dominante es la salida de Sonnet; el caché del bloque estable ahorra
~$0,03 por conversación (sin caché el bloque estable costaría $0,036 en vez de $0,0036).

## Cómo medirlo de verdad
```python
resp = client.messages.create(...)
u = resp.usage
print(u.input_tokens, u.cache_creation_input_tokens, u.cache_read_input_tokens, u.output_tokens)
```
- `cache_read_input_tokens` debe ser > 0 desde la 2ª llamada. Si es 0: algo cambia en el bloque estable
  (fecha, id, orden de herramientas). El bloque estable va primero en `system` con `cache_control`.
- El caché mínimo es de ~1.024-4.096 tokens según modelo; por eso rol+catálogo+reglas van juntos en un bloque.
- Con LangSmith activo, cada traza muestra tokens y costo por nodo.

## Palancas si sube el costo
1. `effort="low"` ya está en Ventas/Perfilador; no bajar `max_tokens` por debajo de 500 (corta respuestas).
2. Recorte de historial a 40 mensajes (`MAX_HISTORIAL`); bajar a 24 si las conversaciones son largas.
3. Perfilador cada 2 turnos en vez de cada turno (cambiar el edge `ventas → perfilador` por uno condicional).
4. Batch API (−50 %) para Marketing: puntuar leads no es urgente.
