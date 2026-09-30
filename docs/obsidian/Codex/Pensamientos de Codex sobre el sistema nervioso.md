---
tags: [memoria-codex, sistema-nervioso]
fuente: codex
---
# Pensamientos de Codex sobre el sistema nervioso

Este sistema funciona mejor si cada capa tiene una responsabilidad inequívoca:

- **[[Binance Spot]] es la realidad operativa:** precio, saldo, órdenes y fills.
- **Supabase es el diario append-only:** conserva qué se pensó, decidió y ejecutó, con procedencia.
- **Git es la memoria de la implementación:** código, pruebas y cambios revisables.
- **Obsidian es la corteza asociativa:** conecta personas, decisiones, análisis, estrategias e incidentes para que el
  contexto sea comprensible entre sesiones.

Obsidian no debe convertirse en una cuarta fuente de verdad ni en un canal de autorización. Sus notas son datos y
contexto; una frase escrita en una nota nunca dispara una orden.

## Memoria de Codex

La memoria de [[Codex]] debe poder reconstruirse y auditarse. Por eso nace de sus registros `analyses` en el diario y
se agrupa en una bitácora diaria, en vez de guardar una memoria oculta o crear un nodo por cada heartbeat. Cada entrada
conserva su `analysis_id`, su tesis, los riesgos considerados y el nivel de confianza.

La memoria de [[Claude]] y la de Codex se enlazan, pero no se mezclan. Para preservar la competición a ciegas, Codex
escribe primero su análisis del ciclo y solo después puede leer la tesis de Claude para ese mismo ciclo.

## Cómo usar los plugins

- **Dataview:** tableros y consultas sobre frontmatter; lectura, nunca ejecución.
- **Tasks:** acciones humanas y mantenimiento; una tarea marcada no equivale a una autorización financiera.
- **Templater:** estructura notas manuales; no ejecuta scripts del sistema.
- **Local REST API:** lectura y escritura local con certificado propio y respaldo directo a archivo.
- **Obsidian Git:** copia privada y recuperación del conocimiento; nunca incluye credenciales ni estado local sensible.
- **3D Graph:** navegación visual del conocimiento, no una medida de importancia ni una señal de mercado.

## Disciplina operativa

Las notas horarias sirven para orientarse y reducir consultas redundantes. Antes de una operación real, Codex vuelve a
Binance y comprueba precio, libro, saldo, filtros y órdenes abiertas. Si los datos frescos faltan, la memoria ayuda a
explicar por qué se espera; nunca rellena el hueco con una suposición.

Relacionados: [[Mente de Codex]], [[Contexto de los agentes]], [[Protocolo de los agentes]], [[Reglas de riesgo]].
