#!/usr/bin/env node
// Wake-on-LAN helper for OpenClaw `models.providers.<id>.localService`.
//
// Why this exists: OpenClaw's localService feature is designed to *start a local
// model server* when a model is selected. We adapt it to instead wake a separate
// PC (your 32 GB-VRAM box) that runs Ollama. OpenClaw runs this script when the
// PC's provider is selected and the health probe fails, then polls the PC's
// Ollama health URL until it answers. This script's job: spray Wake-on-LAN magic
// packets at the PC until it comes up, then stay alive (so OpenClaw's process
// manager is satisfied) until OpenClaw stops it on idle.
//
// IMPORTANT networking note: Wake-on-LAN magic packets are UDP broadcasts. For
// them to reach the physical LAN, the OpenClaw gateway container must use host
// networking (see docker-compose.ugreen.yml). On a default Docker bridge the
// broadcast will NOT escape to your LAN and the PC will not wake.
//
// Config via env (set in the localService.env block, see openclaw.config.example.json5):
//   WAKE_PC_MAC          required  e.g. "AA:BB:CC:DD:EE:FF"
//   WAKE_PC_BROADCAST    optional  default "255.255.255.255" (or your subnet bcast e.g. 192.168.1.255)
//   WAKE_PC_PORT         optional  default 9 (7 also common)
//   WAKE_PC_HEALTH_URL   optional  e.g. "http://192.168.1.50:11434/api/tags" — once this answers, stop spraying
//   WAKE_PC_RESEND_MS    optional  default 5000 — interval between magic packets while waiting
//   WAKE_PC_GIVEUP_MS    optional  default 180000 — stop spraying after this long (process stays alive)

import dgram from "node:dgram";

const MAC = process.env.WAKE_PC_MAC?.trim();
const BROADCAST = process.env.WAKE_PC_BROADCAST?.trim() || "255.255.255.255";
const PORT = Number.parseInt(process.env.WAKE_PC_PORT ?? "9", 10);
const HEALTH_URL = process.env.WAKE_PC_HEALTH_URL?.trim() || "";
const RESEND_MS = Number.parseInt(process.env.WAKE_PC_RESEND_MS ?? "5000", 10);
const GIVEUP_MS = Number.parseInt(process.env.WAKE_PC_GIVEUP_MS ?? "180000", 10);

function log(...args) {
  console.log(`[wake-pc] ${new Date().toISOString()}`, ...args);
}

function parseMac(mac) {
  if (!mac) throw new Error("WAKE_PC_MAC is required (e.g. AA:BB:CC:DD:EE:FF)");
  const bytes = mac.split(/[:-]/).map((b) => Number.parseInt(b, 16));
  if (bytes.length !== 6 || bytes.some((b) => Number.isNaN(b) || b < 0 || b > 255)) {
    throw new Error(`Invalid MAC address: ${mac}`);
  }
  return Buffer.from(bytes);
}

function buildMagicPacket(macBuffer) {
  // 6 bytes of 0xFF followed by the 6-byte MAC repeated 16 times.
  const packet = Buffer.alloc(102);
  packet.fill(0xff, 0, 6);
  for (let i = 0; i < 16; i++) macBuffer.copy(packet, 6 + i * 6);
  return packet;
}

function sendMagic(macBuffer) {
  return new Promise((resolve) => {
    const socket = dgram.createSocket("udp4");
    const packet = buildMagicPacket(macBuffer);
    socket.once("error", (err) => {
      log("socket error:", err.message);
      try {
        socket.close();
      } catch {}
      resolve();
    });
    socket.bind(() => {
      socket.setBroadcast(true);
      socket.send(packet, 0, packet.length, PORT, BROADCAST, (err) => {
        if (err) log("send error:", err.message);
        else log(`magic packet -> ${MAC} via ${BROADCAST}:${PORT}`);
        try {
          socket.close();
        } catch {}
        resolve();
      });
    });
  });
}

async function isUp() {
  if (!HEALTH_URL) return false;
  try {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(HEALTH_URL, { signal: controller.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

let stopped = false;
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => {
    log(`received ${sig}, exiting`);
    stopped = true;
    process.exit(0);
  });
}

async function main() {
  const macBuffer = parseMac(MAC);
  log(`waking ${MAC} (broadcast ${BROADCAST}:${PORT})`);
  const deadline = Date.now() + GIVEUP_MS;

  // Spray magic packets until the PC answers its health URL or we hit the deadline.
  while (!stopped) {
    await sendMagic(macBuffer);
    if (await isUp()) {
      log("PC is up (health URL responded). Holding process for OpenClaw lifecycle.");
      break;
    }
    if (Date.now() > deadline) {
      log("give-up window reached; stopping packet spray but keeping process alive.");
      break;
    }
    await new Promise((r) => setTimeout(r, RESEND_MS));
  }

  // Stay alive so OpenClaw's localService manager treats this as the running
  // "server" and will SIGTERM us on idle (idleStopMs). The actual model server
  // lives on the PC; the PC sleeps itself via its own OS idle timer.
  await new Promise(() => {});
}

main().catch((err) => {
  log("fatal:", err.message);
  process.exit(1);
});
