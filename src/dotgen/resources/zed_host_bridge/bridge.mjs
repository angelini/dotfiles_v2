#!/usr/bin/env node
import { constants as fsConstants } from "node:fs";
import {
  access,
  chmod,
  lstat,
  mkdir,
  open,
  realpath,
  stat,
  unlink,
} from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

const MAX_PAYLOAD = 64 * 1024;
const MAX_PATHS = 64;
const MAX_PATH_LENGTH = 4096;
const MAX_CONCURRENT = 8;
const MAX_STDERR = 8192;
const REQUEST_TIMEOUT_MS = 30_000;
const ACTIVE_CHILDREN = new Set();
const ALIAS_RE = /^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$/;
const BEHAVIORS = new Set(["default", "new", "add", "reuse", "existing"]);
const BEHAVIOR_FLAGS = {
  new: "--new",
  add: "--add",
  reuse: "--reuse",
  existing: "--existing",
};
const OPTION_BEHAVIORS = {
  "-n": "new",
  "--new": "new",
  "-a": "add",
  "--add": "add",
  "-r": "reuse",
  "--reuse": "reuse",
  "-e": "existing",
  "--existing": "existing",
};

class BridgeError extends Error {
  constructor(message, exitCode = 1) {
    super(message);
    this.exitCode = exitCode;
  }
}

function fail(message, exitCode = 1) {
  throw new BridgeError(message, exitCode);
}

function exactKeys(value, expected, label) {
  const keys = Object.keys(value).sort();
  const allowed = [...expected].sort();
  if (
    keys.length !== allowed.length ||
    keys.some((key, index) => key !== allowed[index])
  ) {
    fail(`${label} has unknown or missing fields`);
  }
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validateAlias(value) {
  if (
    typeof value !== "string" ||
    value.length > 255 ||
    !ALIAS_RE.test(value)
  ) {
    fail("invalid SSH host alias in bridge configuration");
  }
  return value;
}

function validateRelativePath(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > MAX_PATH_LENGTH
  )
    fail("invalid relative path");
  if (
    value.includes("\\") ||
    value.startsWith("/") ||
    /[\x00-\x1f\x7f]/u.test(value) ||
    /^(?:[A-Za-z][A-Za-z0-9+.-]*:\/\/|file:)/u.test(value)
  )
    fail("invalid relative path");
  const segments = value.split("/");
  if (
    segments.some(
      (segment) => segment === "" || segment === "." || segment === "..",
    )
  )
    fail("invalid relative path");
  return segments;
}

function validatePosition(value, label) {
  if (value === undefined) return undefined;
  if (!Number.isSafeInteger(value) || value < 1 || value > 2_147_483_647)
    fail(`invalid ${label}`);
  return value;
}

function validateRequest(value) {
  if (!isObject(value)) fail("request must be a JSON object");
  exactKeys(value, ["version", "behavior", "wait", "paths"], "request");
  if (value.version !== 1) fail("unsupported request version");
  if (typeof value.behavior !== "string" || !BEHAVIORS.has(value.behavior))
    fail("invalid open behavior");
  if (typeof value.wait !== "boolean") fail("invalid wait value");
  if (
    !Array.isArray(value.paths) ||
    value.paths.length === 0 ||
    value.paths.length > MAX_PATHS
  )
    fail("invalid path count");
  const paths = value.paths.map((item) => {
    if (!isObject(item)) fail("path entry must be an object");
    const allowed = new Set(["relativePath", "line", "column"]);
    if (
      !Object.hasOwn(item, "relativePath") ||
      Object.keys(item).some((key) => !allowed.has(key))
    )
      fail("path entry has unknown or missing fields");
    const segments = validateRelativePath(item.relativePath);
    const line = validatePosition(item.line, "line");
    const column = validatePosition(item.column, "column");
    if (column !== undefined && line === undefined)
      fail("column requires a line");
    return { relativePath: item.relativePath, segments, line, column };
  });
  return { behavior: value.behavior, wait: value.wait, paths };
}

function parseClientArguments(argv) {
  let behavior = "default";
  let wait = false;
  let options = true;
  const operands = [];
  for (const argument of argv) {
    if (options && argument === "--") {
      options = false;
      continue;
    }
    if (options && Object.hasOwn(OPTION_BEHAVIORS, argument)) {
      const next = OPTION_BEHAVIORS[argument];
      if (behavior !== "default" && behavior !== next)
        fail("conflicting Zed open behavior options");
      behavior = next;
      continue;
    }
    if (options && (argument === "-w" || argument === "--wait")) {
      wait = true;
      continue;
    }
    if (options && argument.startsWith("-")) {
      if (argument === "-") fail("stdin is not supported");
      if (argument === "--diff") fail("--diff is not supported");
      fail(`unsupported option: ${argument}`);
    }
    if (argument === "-") fail("stdin is not supported");
    if (/^(?:[A-Za-z][A-Za-z0-9+.-]*:\/\/|file:)/u.test(argument))
      fail("URL operands are not supported");
    operands.push(argument);
  }
  if (operands.length > MAX_PATHS) fail("too many path operands");
  return {
    behavior,
    wait,
    operands: operands.length === 0 ? [process.cwd()] : operands,
  };
}

async function pathExists(value) {
  try {
    await lstat(value);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ENOTDIR") return false;
    throw error;
  }
}

async function splitPosition(operand) {
  if (await pathExists(operand)) return { pathOperand: operand };
  const match = /^(.*?):([1-9][0-9]*)(?::([1-9][0-9]*))?$/u.exec(operand);
  if (!match || match[1] === "") {
    if (/:[0-9]+(?::[0-9]*)?$/u.test(operand))
      fail(`malformed line or column position: ${operand}`);
    return { pathOperand: operand };
  }
  const line = Number(match[2]);
  const column = match[3] === undefined ? undefined : Number(match[3]);
  validatePosition(line, "line");
  validatePosition(column, "column");
  return { pathOperand: match[1], line, column };
}

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    !relative.startsWith(`..${path.sep}`) &&
    relative !== ".." &&
    !path.isAbsolute(relative)
  );
}

async function canonicalizeOperand(root, operand) {
  const absolute = path.resolve(operand);
  let ancestor = absolute;
  const missing = [];
  while (!(await pathExists(ancestor))) {
    const parent = path.dirname(ancestor);
    if (parent === ancestor)
      fail(`path does not have an existing ancestor: ${operand}`);
    missing.unshift(path.basename(ancestor));
    ancestor = parent;
  }
  const canonicalAncestor = await realpath(ancestor);
  const candidate = path.join(canonicalAncestor, ...missing);
  if (!isWithin(root, candidate))
    fail(`path is outside $HOME/repos: ${operand}`);
  const relativePath = path.relative(root, candidate).split(path.sep).join("/");
  validateRelativePath(relativePath);
  return relativePath;
}

async function makeClientRequest(argv) {
  const parsed = parseClientArguments(argv);
  const home = process.env.HOME || os.homedir();
  const rootPath = path.join(home, "repos");
  let root;
  try {
    root = await realpath(rootPath);
  } catch {
    fail(`repository root is unavailable: ${rootPath}`);
  }
  const paths = [];
  for (const operand of parsed.operands) {
    const positioned = await splitPosition(operand);
    const relativePath = await canonicalizeOperand(
      root,
      positioned.pathOperand,
    );
    const entry = { relativePath };
    if (positioned.line !== undefined) entry.line = positioned.line;
    if (positioned.column !== undefined) entry.column = positioned.column;
    paths.push(entry);
  }
  return { version: 1, behavior: parsed.behavior, wait: parsed.wait, paths };
}

function readOneResponse(socket, wait) {
  return new Promise((resolve, reject) => {
    let payload = "";
    socket.setTimeout(wait ? 0 : REQUEST_TIMEOUT_MS);
    socket.on("data", (chunk) => {
      payload += chunk.toString("utf8");
      if (Buffer.byteLength(payload) > MAX_PAYLOAD) {
        reject(new BridgeError("bridge response is too large"));
        socket.destroy();
      }
    });
    socket.on("timeout", () =>
      reject(new BridgeError("macOS host bridge timed out")),
    );
    socket.on("error", (error) => reject(error));
    socket.on("end", () => {
      if (
        payload.length === 0 ||
        payload.indexOf("\n") !== payload.length - 1
      ) {
        reject(new BridgeError("invalid bridge response"));
        return;
      }
      try {
        resolve(JSON.parse(payload.slice(0, -1)));
      } catch {
        reject(new BridgeError("invalid bridge response"));
      }
    });
  });
}

async function runClient(argv) {
  const request = await makeClientRequest(argv);
  const encoded = `${JSON.stringify(request)}\n`;
  if (Buffer.byteLength(encoded) > MAX_PAYLOAD)
    fail("bridge request is too large");
  const home = process.env.HOME || os.homedir();
  const socketPath =
    process.env.ZED_HOST_BRIDGE_SOCKET ||
    path.join(home, ".cache", "dotgen", "zed-host-bridge.sock");
  const socket = net.createConnection(socketPath);
  const responsePromise = readOneResponse(socket, request.wait);
  socket.on("connect", () => socket.end(encoded));
  let response;
  try {
    response = await responsePromise;
  } catch (error) {
    if (["ENOENT", "ECONNREFUSED", "ECONNRESET", "EPIPE"].includes(error?.code))
      fail("macOS host bridge unavailable; attach with herd-agent <host>");
    throw error;
  }
  if (!isObject(response) || typeof response.ok !== "boolean")
    fail("invalid bridge response");
  if (!response.ok) {
    const exitCode =
      Number.isInteger(response.exitCode) &&
      response.exitCode > 0 &&
      response.exitCode <= 255
        ? response.exitCode
        : 1;
    fail(
      typeof response.error === "string" && response.error
        ? response.error
        : "macOS host bridge rejected the request",
      exitCode,
    );
  }
  if (!Number.isInteger(response.exitCode) || response.exitCode !== 0)
    fail(`Zed exited with status ${response.exitCode}`);
}

async function loadServerConfig(configPath) {
  let handle;
  let value;
  try {
    handle = await open(
      configPath,
      fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW,
    );
    const info = await handle.stat();
    if (!info.isFile() || info.uid !== process.getuid() || info.size > 4096)
      fail("unsafe bridge configuration file");
    value = JSON.parse(await handle.readFile("utf8"));
  } catch (error) {
    if (error instanceof BridgeError) throw error;
    fail(`cannot read bridge configuration: ${error.message}`);
  } finally {
    await handle?.close();
  }
  if (!isObject(value)) fail("bridge configuration must be a JSON object");
  exactKeys(value, ["sshHost"], "bridge configuration");
  return { sshHost: validateAlias(value.sshHost) };
}

async function resolveZed() {
  const searchPath =
    process.env.PATH || "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin";
  for (const directory of searchPath.split(path.delimiter)) {
    if (!directory || !path.isAbsolute(directory)) continue;
    const candidate = path.join(directory, "zed");
    try {
      const info = await stat(candidate);
      await access(candidate, fsConstants.X_OK);
      if (info.isFile()) return candidate;
    } catch {}
  }
  fail("Zed CLI is unavailable on the macOS host");
}

function makeUrls(sshHost, paths) {
  return paths.map((entry) => {
    let url = `ssh://${sshHost}/~/repos/${entry.segments.map(encodeURIComponent).join("/")}`;
    if (entry.line !== undefined) url += `:${entry.line}`;
    if (entry.column !== undefined) url += `:${entry.column}`;
    return url;
  });
}

function sendResponse(socket, response) {
  if (!socket.destroyed) socket.end(`${JSON.stringify(response)}\n`);
}

async function launchZed(socket, request, sshHost) {
  const executable = await resolveZed();
  const args = [];
  const behaviorFlag = BEHAVIOR_FLAGS[request.behavior];
  if (behaviorFlag) args.push(behaviorFlag);
  if (request.wait) args.push("--wait");
  args.push(...makeUrls(sshHost, request.paths));
  await new Promise((resolve) => {
    const child = spawn(executable, args, {
      shell: false,
      stdio: ["ignore", "ignore", "pipe"],
    });
    ACTIVE_CHILDREN.add(child);
    let stderr = "";
    let answered = false;
    const finish = (response) => {
      if (answered) return;
      answered = true;
      sendResponse(socket, response);
      resolve();
    };
    child.stderr.on("data", (chunk) => {
      if (stderr.length < MAX_STDERR)
        stderr += chunk.toString("utf8").slice(0, MAX_STDERR - stderr.length);
    });
    child.on("error", (error) => {
      ACTIVE_CHILDREN.delete(child);
      finish({ ok: false, error: `failed to start Zed: ${error.message}` });
    });
    child.on("close", (code, signal) => {
      ACTIVE_CHILDREN.delete(child);
      if (code === 0) finish({ ok: true, exitCode: 0 });
      else
        finish({
          ok: false,
          exitCode: code ?? 1,
          error:
            stderr.trim() ||
            `Zed exited with ${signal || `status ${code ?? 1}`}`,
        });
    });
    socket.on("close", () => {
      if (request.wait && child.exitCode === null && child.signalCode === null)
        child.kill("SIGTERM");
    });
  });
}

function receiveRequest(socket, sshHost, onDone) {
  let payload = Buffer.alloc(0);
  let handled = false;
  socket.setTimeout(REQUEST_TIMEOUT_MS);
  const reject = (message) => {
    if (handled) return;
    handled = true;
    sendResponse(socket, { ok: false, error: message });
    onDone();
  };
  socket.on("timeout", () => reject("request timed out"));
  socket.on("error", () => {
    if (!handled) {
      handled = true;
      onDone();
    }
  });
  socket.on("data", (chunk) => {
    if (handled) return;
    payload = Buffer.concat([payload, chunk]);
    if (payload.length > MAX_PAYLOAD) reject("request is too large");
  });
  socket.on("end", async () => {
    if (handled) return;
    if (payload.length === 0 || payload.indexOf(10) !== payload.length - 1)
      return reject("request must contain exactly one JSON line");
    handled = true;
    socket.setTimeout(0);
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(
        payload.subarray(0, payload.length - 1),
      );
      const request = validateRequest(JSON.parse(text));
      await launchZed(socket, request, sshHost);
    } catch (error) {
      sendResponse(socket, {
        ok: false,
        error:
          error instanceof BridgeError
            ? error.message
            : "invalid bridge request",
      });
    } finally {
      onDone();
    }
  });
}

async function prepareSocket(socketPath) {
  const parent = path.dirname(socketPath);
  try {
    const parentInfo = await lstat(parent);
    if (
      parentInfo.isSymbolicLink() ||
      !parentInfo.isDirectory() ||
      parentInfo.uid !== process.getuid()
    )
      fail(`unsafe socket directory: ${parent}`);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    await mkdir(parent, { recursive: true, mode: 0o700 });
    const parentInfo = await lstat(parent);
    if (
      parentInfo.isSymbolicLink() ||
      !parentInfo.isDirectory() ||
      parentInfo.uid !== process.getuid()
    )
      fail(`unsafe socket directory: ${parent}`);
  }
  await chmod(parent, 0o700);
  let info;
  try {
    info = await lstat(socketPath);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
  if (
    info.isSymbolicLink() ||
    !info.isSocket() ||
    info.uid !== process.getuid()
  )
    fail(`unsafe socket collision: ${socketPath}`);
  await unlink(socketPath);
}

async function runServer() {
  const home = process.env.HOME || os.homedir();
  const configPath =
    process.env.ZED_HOST_BRIDGE_CONFIG ||
    path.join(home, ".config", "dotgen", "zed-host-bridge.json");
  const socketPath =
    process.env.ZED_HOST_BRIDGE_SOCKET ||
    path.join(home, "Library", "Caches", "dotgen", "zed-host-bridge.sock");
  const config = await loadServerConfig(configPath);
  await prepareSocket(socketPath);
  let active = 0;
  const sockets = new Set();
  const server = net.createServer({ allowHalfOpen: true }, (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
    if (active >= MAX_CONCURRENT) {
      sendResponse(socket, {
        ok: false,
        error: "too many concurrent bridge requests",
      });
      return;
    }
    active += 1;
    receiveRequest(socket, config.sshHost, () => {
      active -= 1;
    });
  });
  const previousUmask = process.umask(0o077);
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(socketPath, resolve);
    });
  } finally {
    process.umask(previousUmask);
  }
  await chmod(socketPath, 0o600);
  const socketInfo = await lstat(socketPath);
  let stopping = false;
  const stop = () => {
    if (stopping) return;
    stopping = true;
    server.close();
    for (const socket of sockets) socket.destroy();
    for (const child of ACTIVE_CHILDREN) child.kill("SIGTERM");
  };
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
  await new Promise((resolve, reject) => {
    server.once("close", resolve);
    server.once("error", reject);
  });
  try {
    const current = await lstat(socketPath);
    if (
      current.isSocket() &&
      current.dev === socketInfo.dev &&
      current.ino === socketInfo.ino
    )
      await unlink(socketPath);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

async function main() {
  const [mode, ...argv] = process.argv.slice(2);
  if (mode === "client") await runClient(argv);
  else if (mode === "serve" && argv.length === 0) await runServer();
  else
    fail("usage: zed-host-bridge.mjs client [zed-options] [paths...] | serve");
}

try {
  await main();
} catch (error) {
  const message =
    error instanceof BridgeError
      ? error.message
      : error?.message || String(error);
  console.error(
    `${process.argv[2] === "client" ? "zed" : "zed-host-bridge"}: ${message}`,
  );
  process.exitCode = error instanceof BridgeError ? error.exitCode : 1;
}
