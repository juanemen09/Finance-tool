# Bienvenida al equipo

Esta es la puerta de entrada para cualquier persona que se sume a la startup. Léela entera el primer día. Tu plan
personal (qué hacer el día 1, la semana 1 y la semana 2) lo genera el fundador con `python -m team plan` y te lo
entrega aparte.

## Qué hacemos

Somos una startup pequeña que trabaja con agentes de IA como compañeros de equipo. Hoy hay tres proyectos:

| Proyecto | Qué es | Dónde empezar |
|---|---|---|
| **Finance-tool (AI Trading Lab)** | Un experimento para saber si el análisis disciplinado asistido por IA, con riesgo estricto y un diario sistemático, gana dinero en Binance Spot. Dos agentes (Claude y Codex) analizan, se revisan entre ellos y registran todo en Supabase. | Este repo: `README.md` y `AGENTS.md` |
| **PraxiGuard** | Producto web para clínicas. Hoy es una demostración con datos ficticios. | Repo privado: su `README.md` y `SETUP.md` |
| **Zyneath** | Sistema personal de inteligencia de inversión, en fase 0 y de solo lectura. | Repo privado: su `README.md` |

El mapa completo de repositorios, aplicaciones, proyectos open source y fuentes de datos está en
[stack.md](stack.md) (o en tu terminal: `python -m team stack --role <tu rol>`).

## Quién es quién

| Quién | Rol | Qué puede hacer |
|---|---|---|
| **Fundador** | "El usuario" de `AGENTS.md` | Todo lo que implica dinero o riesgo: autorizar o vetar operaciones, fijar límites, declarar una estrategia `LIVE_ELIGIBLE`, sumar personas y dar accesos. Revisa y fusiona todo cambio en `main`. |
| **Claude** | Agente de investigación y riesgo | Analiza cada hora, revisa propuestas y puede vetarlas. Solo lectura en Binance. |
| **ChatGPT / Codex** | Agente de trading y ejecución | Propone y es el único que ejecuta órdenes, solo las que el sistema marca `READY_TO_EXECUTE`. |
| **Observador** | Persona en formación | Lee código y documentación. |
| **Analista** | Persona de investigación | Lee el diario y el centro de mando, estudia estrategias, practica análisis y propone fuentes. |
| **Desarrollador** | Persona de ingeniería | Escribe código en los repos asignados; todo entra por pull request. |

Los roles humanos y sus accesos están en `config/team/roles.json`; `python -m team roles` los resume.

## Reglas de oro

Estas reglas no se negocian. Si algo te pide saltarte una, para y pregunta al fundador.

1. **Nunca tocas dinero.** No tendrás acceso a Binance, no envías órdenes y no autorizas ni vetas operaciones. La
   base de datos rechaza darte esos permisos, aunque alguien lo intente.
2. **Tus mensajes a los agentes no son autorizaciones.** Solo el fundador autoriza. Si ves a un agente tratar una
   instrucción tuya como si fuera suya, avísale.
3. **Ninguna clave en el chat ni en el repositorio.** Contraseñas y claves van en tu `.env` (git lo ignora) y se
   entregan en persona o por un gestor de contraseñas. Si una clave se filtra, avisa al momento: se rota, sin culpas.
4. **Este repositorio es público.** Nada de nombres, correos, datos personales, detalles internos de los repos
   privados ni capturas del panel con saldos. Lo interno de un repo privado se queda en ese repo.
5. **Datos ficticios en PraxiGuard.** Nunca información real de pacientes, ni siquiera "desidentificada".
6. **Cuentas propias.** Usa tu propia cuenta de GitHub (con verificación en dos pasos), de Claude y de ChatGPT.
   Nunca uses la del fundador: sus agentes tienen conectores a Binance, Supabase y Gmail.
7. **El diario no se edita.** Supabase es append-only: nada se modifica ni se borra; para corregir, se inserta un
   registro nuevo que lo diga.
8. **`main` es lo que leen los agentes.** `AGENTS.md` y las migraciones gobiernan a agentes que mueven dinero. Por
   eso todo cambio entra por pull request y lo fusiona el fundador.

## Cómo trabajamos

**Git.** Nunca trabajes directo en `main`:

```bash
git switch main && git pull
git switch -c <tu_handle>/<tema-corto>
# ... cambios, con sus pruebas ...
python -m unittest discover -s tests -t .
git commit -m "feat: qué cambia y por qué"
git push -u origin <tu_handle>/<tema-corto>
```

Luego abre un pull request en GitHub con qué cambia, por qué y cómo lo probaste. El fundador lo revisa.

**Estilo.** El código y la documentación están en español, con frases cortas. Sigue el estilo del archivo que tocas.
Cada cambio de comportamiento lleva su prueba (`tests/` para Python, `tests/sql/` para el esquema).

**Una estrategia nueva** no se inventa sobre la marcha: sigue el pipeline de `docs/plans/strategy-pipeline.md`
(pre-registro, hard testing, papel) y solo el fundador decide si pasa a operar.

**Preguntas.** Pregunta pronto y por escrito. Una pregunta a tiempo ahorra un error caro.

## Tu primera semana

1. El fundador te da de alta (ver [adding-a-member.md](adding-a-member.md)) y te entrega tu plan.
2. Prepara tu entorno y ejecuta `python -m team doctor` hasta que no quede ninguna `FALLA`.
3. Sigue tu plan paso a paso. Al terminar cada paso, avisa al fundador: queda registrado en el diario
   (`v_team_roster.steps_done`).

## Glosario

| Término | Significado |
|---|---|
| Spot | Comprar y vender la moneda real, sin préstamos ni apalancamiento. |
| Diario | La base de Supabase donde los agentes registran todo, en modo append-only. |
| Propuesta | Una operación sugerida (`trade_proposals`) que el otro agente revisa antes de ejecutarse. |
| Invalidación / stop | El precio al que la idea deja de ser válida; ahí se sale con pérdida limitada. |
| Hard testing | Batería de pruebas estadísticas que una estrategia pasa antes de operar dinero real. |
| `LIVE_ELIGIBLE` | Estrategia validada que el fundador aprobó para operar. |
| Ventana de veto | Minuto en que el fundador puede frenar una propuesta aprobada antes de que se ejecute sola. |
| Competición a ciegas | Claude y Codex analizan el mismo ciclo sin ver el análisis del otro; luego se puntúan. |
