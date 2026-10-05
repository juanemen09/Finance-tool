// Arranca el proxy (con el emulador de RuView) y el servidor de desarrollo de Vite; Ctrl+C cierra ambos.
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const raiz = join(dirname(fileURLToPath(import.meta.url)), '..');
const hijos = [
  spawn(process.execPath, ['server.js'], { cwd: raiz, stdio: 'inherit' }),
  spawn(process.execPath, [join(raiz, 'node_modules', 'vite', 'bin', 'vite.js')], { cwd: raiz, stdio: 'inherit' }),
];

let cerrando = false;
const cerrar = (codigo = 0) => {
  if (cerrando) return;
  cerrando = true;
  for (const h of hijos) h.kill('SIGTERM');
  process.exit(codigo);
};
for (const h of hijos) h.on('exit', (c) => cerrar(c ?? 0));
process.on('SIGINT', () => cerrar(0));
process.on('SIGTERM', () => cerrar(0));
