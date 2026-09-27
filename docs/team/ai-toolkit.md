# Kit de IA del equipo: skills, conectores y plugins

Lo que usa la startup en Claude y cómo lo configura cada persona nueva. Inventario sacado de la cuenta del fundador
el 2026-09-27.

**Esto no se copia de una cuenta a otra.** Skills, conectores y plugins se activan en la cuenta de cada persona, y
cada conector se autoriza con **su propia** cuenta del servicio. Nunca compartas contraseñas, tokens ni la sesión
del fundador: sus conectores llegan a Binance, Supabase y Gmail. Si la startup pasa a un plan Team o Enterprise de
Claude, el owner puede gestionar conectores y skills para toda la organización desde un solo sitio. Hoy cada persona
lo hace a mano con esta lista.

## 1. Skills

En claude.ai: **Settings → Capabilities → Skills**. Todas las de la lista son de Anthropic, así que cualquier cuenta
puede activarlas. La startup no tiene skills propias todavía (se crearían con `skill-creator`).

| Skill | Para qué | Observador | Analista | Desarrollador |
|---|---|:-:|:-:|:-:|
| `docx`, `pdf`, `xlsx`, `pptx` | Crear y leer Word, PDF, Excel y PowerPoint | ✓ | ✓ | ✓ |
| `docs` | Documentos vivos para compartir y comentar | ✓ | ✓ | ✓ |
| `deep-research` | Investigación con varias fuentes y un informe | | ✓ | ✓ |
| `google-workspace` | Crear y editar Docs, Sheets y Slides de Google | | ✓ | ✓ |
| `skill-creator` | Crear y probar skills propias del equipo | | | ✓ |
| `chrome-browser`, `built-in-browser` | Que Claude navegue (extensión de Chrome o navegador de la app de escritorio) | | ✓ | ✓ |
| `computer-use` | Que Claude use apps de tu PC desde la app de escritorio | | | opcional |
| `setup-writing-style`, `import-memory`, `morning` | Personales: tu estilo al escribir, importar memoria de otro asistente, resumen de la mañana | opcional | opcional | opcional |

**Claude Code** (programar): trae de serie `code-review`, `security-review`, `simplify`, `init`, `run`, `loop`,
`claude-api`, `session-start-hook` y `fewer-permission-prompts`, entre otras. No hay que activarlas. Antes de pedir
revisión de un pull request, pasa `/code-review` y, si tocas algo de seguridad, `/security-review`.

## 2. Conectores

En claude.ai: **Settings → Connectors**. Cada persona conecta **su** cuenta, y solo los de su rol.

| Conector | Qué hace | Para el equipo |
|---|---|---|
| **GitHub** | Repos, pull requests y revisión desde Claude y Claude Code | ✓ Todos, con su cuenta y 2FA. Solo verás los repos a los que te invite el fundador. |
| **Google Drive** | Buscar, leer y subir archivos | ✓ Opcional, con tu cuenta. |
| **Gmail** | Borradores, resúmenes y búsqueda en tu correo | ✓ Opcional, **con tu correo**. El Gmail del fundador recibe las alertas de los agentes: no lo toques. |
| **Slack** | Mensajes, canvases y datos de Slack | ✓ Recomendado si abrimos un Slack del equipo (en la cuenta del fundador está pendiente de reconectar). |
| **Canva** | Buscar, crear y exportar diseños | Opcional, para diseño. |
| **Wix** | Sitios y apps en Wix | Solo si el fundador te asigna la web. |
| **Supabase** | Gestionar bases, autenticación y almacenamiento | ✗ No. Da acceso de administrador al proyecto. El equipo lee el diario con su rol `team_<handle>` (ver `adding-a-member.md`). |
| **Binance MCP Server** | Cuenta de Binance: precios, saldos, órdenes | ✗ **Nunca.** Solo lo usan los agentes; la base rechaza darte ese acceso. |
| **Stripe** | Pagos | ✗ No. Dinero: solo el fundador. |
| **Inkbox** | Correo, SMS e iMessage para agentes | ✗ No. Habla en nombre de la startup: solo el fundador. |
| **Indeed** | Búsqueda de empleo | No hace falta. |

Además, **Claude Docs** (documentos vivos) viene integrado en Claude, sin conectar nada.

**MCP del repositorio.** `Finance-tool/.mcp.json` declara el servidor MCP de Supabase para el fundador y sus agentes.
Si Claude Code te pregunta si quieres usarlo, **responde que no**: no tendrás acceso a esa organización y no lo
necesitas. PraxiGuard y Zyneath no declaran servidores MCP.

## 3. Plugins

La cuenta del fundador no tiene plugins activos en claude.ai (2026-09-27). Si más adelante se instala alguno para el
equipo, se añade aquí con su rol.

## 4. Checklist del primer día

- [ ] Cuenta propia de Claude y, si programas, Claude Code instalado (https://code.claude.com/docs).
- [ ] Skills de tu rol activadas (tabla 1).
- [ ] Conectores de tu rol conectados **con tus cuentas** (tabla 2). Ninguno marcado ✗.
- [ ] GitHub con 2FA y las invitaciones aceptadas.
- [ ] Si Claude Code ofrece el MCP de Supabase del repo, rechazado.
- [ ] Avisa al fundador: queda registrado como paso `kit-ia` de tu onboarding.
