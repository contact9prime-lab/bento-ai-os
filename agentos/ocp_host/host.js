/* AgentOS hosts an OpenClaw plugin — the plugin registers into US, not into OpenClaw.
 *
 * The other integration (`agentos/ocplugins.py`) governs plugins that run inside
 * OpenClaw's own gateway: AgentOS can decide whether one is installed and enabled,
 * and nothing more, because the code executes in somebody else's process. This
 * file is the opposite bargain and the reason it exists: we start the process, we
 * hand the plugin its `api` object, and every tool it registers becomes a tool in
 * AgentOS's own loop — which means every call is a PDP decision, an audit row, and
 * something quarantine can stop. Their ecosystem's reach, inside our permissions.
 *
 * It is deliberately thin, exactly like wa_bridge.js: it loads, it registers, it
 * invokes. Every decision about WHETHER a call may happen stays in Python, where
 * the grants and the ledger are. A host that started deciding would be a second
 * policy engine, which is the thing this whole design exists to avoid.
 *
 * Protocol: newline-delimited JSON over stdin/stdout, request/response by id.
 *
 *   out  {type:"ready", registrations, unsupported, errors}
 *        {type:"result", id, ok, value?, error?}
 *        {type:"host", id, call, args}     the plugin asking US for something
 *        {type:"log", level, message}
 *   in   {type:"invoke", id, tool, args}
 *        {type:"host_result", id, ok, value?, error?}
 *        {type:"shutdown"}
 *
 * stdout is the protocol channel and NOTHING else may write to it. A plugin's
 * stray console.log would corrupt a frame and Python would see a parse error
 * instead of a tool result, so console is rebound to stderr before the plugin is
 * loaded — see `muzzle()`. This is not tidiness; it is the difference between a
 * chatty plugin and a broken one.
 *
 * WHAT THIS IS NOT: a reimplementation of OpenClaw. We implement the part of the
 * plugin API that AgentOS can host truthfully and REFUSE the rest out loud —
 * `unsupported` in the ready frame is a first-class answer, not an omission. A
 * plugin that silently does 60% of its job is worse than one that says which 40%
 * it could not do here.
 */
'use strict';

const path = require('path');

// ---------------------------------------------------------------------------
// stdout discipline
// ---------------------------------------------------------------------------
const EMIT = process.stdout.write.bind(process.stdout);
function out(obj) { EMIT(JSON.stringify(obj) + '\n'); }
function log(level, message) { out({ type: 'log', level, message: String(message).slice(0, 2000) }); }

/** Point every console channel at stderr BEFORE any plugin code can run. */
function muzzle() {
  const toErr = (...a) => { try { process.stderr.write(a.map(String).join(' ') + '\n'); } catch (e) { /* nothing */ } };
  console.log = console.info = console.debug = console.warn = console.error = console.trace = toErr;
  process.stdout.write = (chunk, enc, cb) => { toErr(String(chunk)); if (typeof cb === 'function') cb(); return true; };
}

// ---------------------------------------------------------------------------
// Asking AgentOS for something (the plugin's only way out)
// ---------------------------------------------------------------------------
// The sandbox denies the plugin ambient filesystem and subprocess access (Node's
// own permission model), so anything it legitimately needs it must ASK for — and
// an ask is a round trip into Python, where the PDP gates it and the ledger
// records it. That inversion is the whole point: a capability the plugin takes is
// invisible, a capability it requests is governable.
let hostSeq = 0;
const hostWaiting = new Map();

function askHost(call, args) {
  const id = 'h' + (++hostSeq);
  return new Promise((resolve, reject) => {
    hostWaiting.set(id, { resolve, reject });
    out({ type: 'host', id, call, args: args || {} });
  });
}

// ---------------------------------------------------------------------------
// The api shim
// ---------------------------------------------------------------------------
// Our reading of OpenClaw's plugin API. It is deliberately TOLERANT about shape
// (a registration may arrive as one object or as name+handler) and deliberately
// LOUD about anything it does not host.
//
// The manifest is what keeps this honest. OpenClaw requires a plugin to declare
// every registered tool in `contracts.tools`, so Python can compare what we
// caught against what the plugin promised: a shim that missed a registration is
// then a visible discrepancy rather than a tool that quietly does not exist.

const tools = new Map();          // name -> {description, parameters, handler}
const unsupported = [];           // [{api, detail}] — refused, out loud
const errors = [];

function note(api, detail) {
  unsupported.push({ api, detail: String(detail || '') });
}

function normaliseTool(a, b) {
  // registerTool({name, description, parameters|inputSchema, handler|execute|run})
  // registerTool('name', handlerOrSpec)
  let spec = {};
  if (typeof a === 'string') spec = Object.assign({ name: a }, typeof b === 'function' ? { handler: b } : (b || {}));
  else spec = Object.assign({}, a || {});
  const name = String(spec.name || spec.id || '').trim();
  const handler = spec.handler || spec.execute || spec.run || spec.call || spec.invoke
    || (typeof b === 'function' ? b : null);
  const parameters = spec.parameters || spec.inputSchema || spec.input_schema || spec.schema
    || { type: 'object', properties: {} };
  return { name, description: String(spec.description || spec.summary || ''), parameters, handler };
}

function makeApi(pluginId) {
  const api = {
    pluginId,

    registerTool(a, b) {
      const t = normaliseTool(a, b);
      if (!t.name) { errors.push('registerTool called without a name'); return; }
      if (typeof t.handler !== 'function') {
        note('registerTool:' + t.name, 'registered without a callable handler this host could find');
        return;
      }
      tools.set(t.name, t);
      return { name: t.name };
    },

    // Things AgentOS can genuinely offer, each one a round trip into the PDP.
    // A plugin that uses these is a plugin whose reach is fully visible.
    host: {
      fetch: (url, opts) => askHost('fetch', { url: String(url), options: opts || {} }),
      readFile: (p) => askHost('read_file', { path: String(p) }),
      writeFile: (p, content) => askHost('write_file', { path: String(p), content: String(content) }),
      log: (message) => { log('info', message); },
    },

    // Config the person entered for this plugin, handed in rather than read off
    // disk — the plugin has no filesystem access to go and find it.
    config: {},
  };

  // Everything else OpenClaw's api exposes that we do NOT host. Declaring these
  // as functions that REFUSE is better than leaving them undefined: an undefined
  // property throws a TypeError deep inside the plugin with no explanation,
  // while this produces one sentence naming the API and reaches the ready frame.
  const refuse = [
    ['registerHook', 'AgentOS does not yet expose agent-loop hook points to a plugin'],
    ['registerCli', 'plugin-owned CLI commands are OpenClaw gateway surface, not hosted here'],
    ['registerGatewayMethod', 'the Gateway control plane is OpenClaw\'s, and is deliberately not emulated'],
    ['registerHttpRoute', 'a plugin does not get to serve HTTP inside AgentOS'],
    ['registerService', 'long-lived plugin services are not hosted yet'],
    ['registerProvider', 'model providers are AgentOS\'s own; a plugin-supplied one is not hosted'],
    ['registerChannel', 'a channel must be one AgentOS owns end to end — see CLAUDE.md'],
    ['registerAgentToolResultMiddleware', 'rewriting tool results before the model sees them is not offered'],
    ['registerTrustedToolPolicy', 'the host-trusted pre-tool tier is AgentOS\'s PDP and is not delegable'],
    ['registerEmbeddingProvider', 'not hosted yet'],
    ['registerWorkerProvider', 'not hosted yet'],
  ];
  for (const [name, why] of refuse) {
    api[name] = (...a) => {
      const which = (a[0] && (a[0].name || a[0].id || a[0].event)) || (typeof a[0] === 'string' ? a[0] : '');
      note(name + (which ? ':' + which : ''), why);
      return undefined;
    };
  }
  return api;
}

// ---------------------------------------------------------------------------
// Load and register
// ---------------------------------------------------------------------------

async function main() {
  const entry = process.env.OCP_ENTRY;
  const pluginId = process.env.OCP_PLUGIN_ID || 'plugin';
  let config = {};
  try { config = JSON.parse(process.env.OCP_CONFIG || '{}'); } catch (e) { /* leave empty */ }

  if (!entry) { out({ type: 'ready', registrations: [], unsupported: [], errors: ['no OCP_ENTRY given'] }); return; }

  muzzle();                       // before ANY plugin code runs

  const api = makeApi(pluginId);
  api.config = config;

  let mod = null;
  try {
    mod = require(path.resolve(entry));
  } catch (e) {
    out({ type: 'ready', registrations: [], unsupported: [], errors: ['could not load the plugin entry: ' + String(e && e.message || e)] });
    return;
  }

  // OpenClaw plugins export `register` (and some also `activate`). An ES module
  // transpiled to CJS puts them under `.default`, which is common enough that not
  // looking there would fail on a large share of real plugins for no good reason.
  const reg = mod.register || mod.activate || (mod.default && (mod.default.register || mod.default.activate))
    || (typeof mod === 'function' ? mod : null)
    || (typeof mod.default === 'function' ? mod.default : null);

  if (typeof reg !== 'function') {
    out({ type: 'ready', registrations: [], unsupported: [], errors: ['the plugin entry exports no register()/activate() this host could find'] });
    return;
  }

  try {
    await reg(api);
  } catch (e) {
    errors.push('register() threw: ' + String((e && e.message) || e));
  }

  out({
    type: 'ready',
    registrations: [...tools.entries()].map(([name, t]) => ({
      name, description: t.description, parameters: t.parameters,
    })),
    unsupported,
    errors,
  });
}

// ---------------------------------------------------------------------------
// Serving invocations
// ---------------------------------------------------------------------------

async function invoke(id, name, args) {
  const t = tools.get(name);
  if (!t) { out({ type: 'result', id, ok: false, error: `this plugin registered no tool called '${name}'` }); return; }
  try {
    const value = await t.handler(args || {}, { pluginId: process.env.OCP_PLUGIN_ID || '' });
    out({ type: 'result', id, ok: true, value: value === undefined ? null : value });
  } catch (e) {
    out({ type: 'result', id, ok: false, error: String((e && e.message) || e) });
  }
}

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buf += chunk;
  let nl;
  while ((nl = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
    if (!line.trim()) continue;
    let msg;
    try { msg = JSON.parse(line); } catch (e) { continue; }
    if (msg.type === 'invoke') { invoke(msg.id, msg.tool, msg.args); }
    else if (msg.type === 'host_result') {
      const w = hostWaiting.get(msg.id);
      if (w) {
        hostWaiting.delete(msg.id);
        if (msg.ok) w.resolve(msg.value);
        else w.reject(new Error(msg.error || 'refused'));
      }
    } else if (msg.type === 'shutdown') { process.exit(0); }
  }
});

// A plugin that throws asynchronously must not take the host down silently: the
// Python side would see the pipe close with no explanation and report "the host
// died", which is true and useless.
process.on('uncaughtException', (e) => log('error', 'uncaught in plugin: ' + String((e && e.stack) || e)));
process.on('unhandledRejection', (e) => log('error', 'unhandled rejection in plugin: ' + String((e && e.message) || e)));

main();
