/* The WhatsApp Web bridge: Baileys on one side, AgentOS on the other.
 *
 * Baileys is a Node library and there is no Python equivalent that speaks the
 * WhatsApp multi-device protocol, so this process exists purely to be the part of
 * AgentOS that can import it. It is deliberately thin: it pairs, it receives, it
 * sends. Every decision about WHAT to say — pairing an owner, refusing an unknown
 * number, running a turn, asking for approval — stays in Python, where the
 * permissions and the ledger are. A bridge that started making those decisions
 * would be a second agent, which is the thing we just finished removing.
 *
 * Protocol: newline-delimited JSON, both ways, over stdin/stdout.
 *
 *   out  {type:"qr", qr}          a pairing code to show a human
 *        {type:"ready", me}       paired and connected
 *        {type:"message", from, text, name, id, kind}
 *        {type:"status", state, reason?}
 *        {type:"sent", to, id} | {type:"error", where, message}
 *   in   {type:"send", to, text, id?}
 *        {type:"logout"}
 *
 * stdout is the protocol channel and nothing else may write to it — Baileys' own
 * logger is pointed at stderr for exactly that reason. A stray console.log here
 * corrupts a frame and the Python side sees a parse error instead of a message.
 */
'use strict';

const path = require('path');
const fs = require('fs');

const SESSION_DIR = process.env.WA_SESSION_DIR
  || path.join(process.env.HOME || '.', '.agentos', 'whatsapp', 'session');

function out(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }
function fail(where, e) { out({ type: 'error', where, message: String((e && e.message) || e) }); }

let baileys;
try {
  baileys = require('baileys');
} catch (e) {
  // The one error that is not a bug: the component was never installed. Say which
  // command fixes it rather than printing a module-resolution stack trace.
  out({ type: 'error', where: 'require', message: 'baileys is not installed', fatal: true });
  process.exit(2);
}

const QRCode = require('qrcode');

const {
  makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion,
} = baileys;

let sock = null;
let stopping = false;

async function start() {
  fs.mkdirSync(SESSION_DIR, { recursive: true, mode: 0o700 });
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

  sock = makeWASocket({
    version,
    auth: state,
    // Never true: printing the QR to stdout would corrupt the JSON protocol, and
    // the QR belongs on whichever surface the user is actually looking at.
    printQRInTerminal: false,
    syncFullHistory: false,
    markOnlineOnConnect: false,   // do not steal presence from the user's phone
    logger: require('pino')({ level: 'silent' }),
    browser: ['AgentOS', 'Chrome', '1.0.0'],
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (u) => {
    const { connection, lastDisconnect, qr } = u;
    if (qr) {
      // Rendered here, once, in both the forms the two surfaces need: SVG for a
      // browser and block-art for a terminal. Encoding a QR is not something to
      // implement twice in two languages for one pairing screen.
      let svg = '', ascii = '';
      try { svg = await QRCode.toString(qr, { type: 'svg', margin: 1 }); } catch (e) {}
      try { ascii = await QRCode.toString(qr, { type: 'terminal', small: true }); } catch (e) {}
      out({ type: 'qr', qr, svg, ascii });
    }
    if (connection === 'open') {
      out({ type: 'ready', me: (sock.user && sock.user.id) || '' });
    } else if (connection === 'close') {
      const code = (((lastDisconnect || {}).error || {}).output || {}).statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      out({ type: 'status', state: 'closed', reason: loggedOut ? 'logged_out' : String(code || '') });
      // Logged out means the session is void — reconnecting would spin forever on a
      // credential WhatsApp has already revoked. Anything else is worth retrying.
      if (!loggedOut && !stopping) setTimeout(() => start().catch(e => fail('restart', e)), 3000);
      else process.exit(loggedOut ? 3 : 0);
    }
  });

  sock.ev.on('messages.upsert', async (ev) => {
    if (ev.type !== 'notify') return;      // 'append' is history sync, not new mail
    for (const m of ev.messages || []) {
      try {
        if (!m.message || m.key.fromMe) continue;
        const jid = m.key.remoteJid || '';
        if (jid.endsWith('@g.us') || jid === 'status@broadcast') continue;  // DMs only
        const msg = m.message;
        const text = msg.conversation
          || (msg.extendedTextMessage && msg.extendedTextMessage.text)
          || (msg.imageMessage && msg.imageMessage.caption)
          || (msg.videoMessage && msg.videoMessage.caption)
          || '';
        const kind = text ? 'text' : Object.keys(msg)[0] || 'unknown';
        out({
          type: 'message',
          from: jid.split('@')[0],
          jid,
          text: String(text || ''),
          name: m.pushName || '',
          id: (m.key && m.key.id) || '',
          kind,
        });
      } catch (e) { fail('messages.upsert', e); }
    }
  });
}

// ---- commands from Python -------------------------------------------------

let buf = '';
process.stdin.on('data', async (chunk) => {
  buf += chunk;
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    let cmd;
    try { cmd = JSON.parse(line); } catch (e) { fail('parse', e); continue; }
    try {
      if (cmd.type === 'send') {
        if (!sock) throw new Error('not connected');
        const jid = String(cmd.to).includes('@') ? cmd.to : `${cmd.to}@s.whatsapp.net`;
        const r = await sock.sendMessage(jid, { text: String(cmd.text || '') });
        out({ type: 'sent', to: cmd.to, id: (r && r.key && r.key.id) || '', ref: cmd.id || '' });
      } else if (cmd.type === 'logout') {
        stopping = true;
        if (sock) await sock.logout().catch(() => {});
        out({ type: 'status', state: 'logged_out' });
        process.exit(0);
      }
    } catch (e) { fail(cmd.type || 'command', e); }
  }
});

process.on('uncaughtException', (e) => fail('uncaught', e));
process.on('unhandledRejection', (e) => fail('unhandled', e));

start().catch((e) => { fail('start', e); process.exit(1); });
