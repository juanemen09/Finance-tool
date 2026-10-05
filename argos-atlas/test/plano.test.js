import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HABITACIONES, PUERTAS, aLatLng, habitacionEn, rutaDePuertas } from '../shared/plano.js';
import { avanzar, crearObjetivo } from '../simulador_ruview.js';

function rngSemilla(semilla) {
  let s = semilla >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

test('cada puerta está sobre la pared común de sus dos habitaciones', () => {
  for (const p of PUERTAS) {
    for (const nombre of p.entre) {
      const h = HABITACIONES.find((x) => x.nombre === nombre);
      assert.ok(p.x >= h.x0 && p.x <= h.x1 && p.y >= h.y0 && p.y <= h.y1, `${nombre} no toca la puerta ${p.entre}`);
    }
  }
});

test('la ruta entre Sala y Habitación Principal pasa por el Pasillo', () => {
  const ruta = rutaDePuertas('Sala', 'Habitación Principal');
  assert.deepEqual(ruta.map((p) => p.entre), [['Sala', 'Pasillo'], ['Pasillo', 'Habitación Principal']]);
  assert.deepEqual(rutaDePuertas('Cocina', 'Cocina'), []);
});

test('aLatLng convierte metros a grados alrededor del origen', () => {
  const o = { lat: 0, lng: 0 };
  const [lat, lng] = aLatLng(o, 111.32, 111.32);
  assert.ok(Math.abs(lat - 0.001) < 1e-6 && Math.abs(lng - 0.001) < 1e-6);
});

test('el emulador nunca sale del plano y produce el esquema acordado', () => {
  const rng = rngSemilla(42);
  const origen = { lat: -0.18, lng: -78.48 };
  const objetivos = [crearObjetivo('target_01', rng), crearObjetivo('target_02', rng)];
  const salas = new Set();
  const estados = new Set();
  for (let i = 0; i < 5000; i++) {
    for (const o of objetivos) {
      const m = avanzar(o, origen, rng);
      assert.ok(habitacionEn(o.x, o.y), `fuera del plano en (${o.x}, ${o.y})`);
      assert.deepEqual(Object.keys(m), ['id', 'room', 'coords', 'state', 'resp']);
      assert.ok(m.resp >= 8 && m.resp <= 26, `respiración irreal: ${m.resp}`);
      salas.add(m.room);
      estados.add(m.state);
    }
  }
  assert.equal(salas.size, HABITACIONES.length, 'recorre todas las habitaciones');
  assert.deepEqual([...estados].sort(), ['movimiento', 'quieto']);
});

test('entre dos ticks solo se cambia a una habitación vecina (se cruza por puertas)', () => {
  const rng = rngSemilla(7);
  const o = crearObjetivo('t', rng);
  let antes = habitacionEn(o.x, o.y).nombre;
  for (let i = 0; i < 5000; i++) {
    avanzar(o, { lat: 0, lng: 0 }, rng);
    const ahora = habitacionEn(o.x, o.y).nombre;
    if (ahora !== antes) assert.ok(rutaDePuertas(antes, ahora).length <= 2, `${antes} → ${ahora}`);
    antes = ahora;
  }
});
