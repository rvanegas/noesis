// mdc's web client: keeps a library on mdc's server without the CLI.
//
// Signs in through mdc's own OAuth server as the built-in public client
// `mdc-web` (authorization code with PKCE; oauth.py), then calls the same
// file and run API the CLI does (server.py). The refresh token is kept in
// localStorage so a sign-in lasts its ninety days; the access token only in
// memory. The page's CSP admits no script but this file.
//
// Everything a file or a run returns is put on the page as text, never as
// markup.

"use strict";

const CLIENT_ID = "mdc-web";
const REDIRECT = `${location.origin}/web/`;
const REFRESH_KEY = "mdc.refresh";
const LIBRARY_KEY = "mdc.library";
const SIGN_IN_KEY = "mdc.sign-in";
const TEXT = /\.(md|txt|toml|json|csv|tex|bib)$/i;
const DATED = /^(\d{4})-\d\d-\d\d-/;

// What a library holds besides the user's own files. The settings are the
// user's to edit; the rest mdc writes, and the page only shows them. These
// names copy mdc/library.py's KEYS_FILENAME, GENERATED_FILENAMES and
// RECORD_DIRS, and SYSTEM_PROMPT.md in mdc/config.py: change one, change both.
const SETTINGS = new Set(["KEYS.md", "SYSTEM_PROMPT.md"]);
const GENERATED = new Map([
  ["MANIFEST.md", "index"], ["INDEX.md", "index"], ["REFERENCES.md", "index"], ["RELATED.md", "index"],
  ["INTRODUCTION.md", "review"], ["AFTERWORD.md", "review"], ["FINAL_ASSESSMENT.md", "review"],
  ["APPENDIX.md", "review"], ["COMPILED.md", "review"],
]);
const RECORDS = /^(REVISIONS|ASSESSMENTS)\//;
const WRITTEN = [[/\.analysis\.md$/, "analyze"], [/\.review\.md$/, "review"]];

const $ = (id) => document.getElementById(id);

let access = null;           // {token, expires}
let library = null;          // "<user>/<library>"
let files = {};              // {rel_path: sha256}
let open = null;             // {path, sha, blob}
let running = false;

// ---------------------------------------------------------------------------
// Storage that may be refused (a private window): the page works without it,
// at the cost of signing in again.
// ---------------------------------------------------------------------------

function store(kind, key, value) {
  try {
    if (value === null) kind.removeItem(key);
    else kind.setItem(key, value);
  } catch {}
}

function recall(kind, key) {
  try { return kind.getItem(key); } catch { return null; }
}

// ---------------------------------------------------------------------------
// Signing in
// ---------------------------------------------------------------------------

function base64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function random() {
  return base64url(crypto.getRandomValues(new Uint8Array(32)));
}

async function signIn() {
  const verifier = random();
  const state = random();
  const challenge = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  store(sessionStorage, SIGN_IN_KEY, JSON.stringify({ verifier, state }));
  const query = new URLSearchParams({
    response_type: "code", client_id: CLIENT_ID, redirect_uri: REDIRECT,
    code_challenge: challenge, code_challenge_method: "S256", state,
  });
  location.assign(`/authorize?${query}`);
}

async function tokenRequest(fields) {
  const response = await fetch("/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: CLIENT_ID, ...fields }),
  });
  if (!response.ok) return false;
  const body = await response.json();
  access = { token: body.access_token, expires: Date.now() + (body.expires_in - 60) * 1000 };
  if (body.refresh_token) store(localStorage, REFRESH_KEY, body.refresh_token);
  return true;
}

// The redirect back from /oauth/login, with a code or a refusal.
async function finishSignIn(query) {
  history.replaceState(null, "", REDIRECT);
  const pending = JSON.parse(recall(sessionStorage, SIGN_IN_KEY) || "null");
  store(sessionStorage, SIGN_IN_KEY, null);
  if (query.get("error")) {
    say(query.get("error") === "access_denied" ? "Sign-in declined." : `Sign-in failed: ${query.get("error")}`);
    return;
  }
  if (!pending || pending.state !== query.get("state")) {
    say("That sign-in was not started here; sign in again.");
    return;
  }
  const ok = await tokenRequest({
    grant_type: "authorization_code", code: query.get("code"),
    redirect_uri: REDIRECT, code_verifier: pending.verifier,
  });
  if (!ok) say("Sign-in failed; try again.");
}

async function accessToken() {
  if (access && access.expires > Date.now()) return access.token;
  const refresh = recall(localStorage, REFRESH_KEY);
  if (refresh && await tokenRequest({ grant_type: "refresh_token", refresh_token: refresh })) {
    return access.token;
  }
  store(localStorage, REFRESH_KEY, null);
  access = null;
  return null;
}

async function signOut() {
  const refresh = recall(localStorage, REFRESH_KEY);
  if (refresh) {
    await fetch("/revoke", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      // The SDK's revocation form requires the field even of a public client.
      body: new URLSearchParams({ client_id: CLIENT_ID, client_secret: "", token: refresh }),
    }).catch(() => {});
  }
  store(localStorage, REFRESH_KEY, null);
  access = null;
  show(false);
}

// ---------------------------------------------------------------------------
// The API
// ---------------------------------------------------------------------------

class SignedOut extends Error {}

async function api(path, options = {}) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const token = await accessToken();
    if (!token) throw new SignedOut();
    const response = await fetch(path, {
      ...options,
      headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
    });
    if (response.status !== 401) return response;
    access = null;  // expired early, or revoked: refresh once
  }
  throw new SignedOut();
}

async function detail(response) {
  try { return (await response.json()).detail || response.statusText; } catch { return response.statusText; }
}

function libraryPath(rest = "") {
  return `/libraries/${library}${rest}`;
}

function filePath(rel) {
  return libraryPath(`/files/${rel.split("/").map(encodeURIComponent).join("/")}`);
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

function say(text) {
  $("message").textContent = text;
  $("message").hidden = !text;
}

function show(signedIn) {
  $("signed-in").hidden = !signedIn;
  $("signed-out").hidden = signedIn;
  $("sign-out").hidden = !signedIn;
  $("new-library").hidden = !signedIn;
  $("library").hidden = !signedIn || $("library").options.length < 2;
}

function closePanel(id) {
  $(id).hidden = true;
  if (id === "file") open = null;
}

async function loadLibraries() {
  const response = await api("/libraries");
  const ids = (await response.json()).libraries;
  const select = $("library");
  select.replaceChildren(...ids.map((id) => new Option(id, id)));
  if (!ids.length) {
    say("No library on the server for this account yet; make one with New library.");
    return false;
  }
  const remembered = recall(localStorage, LIBRARY_KEY);
  library = ids.includes(remembered) ? remembered : ids[0];
  select.value = library;
  return true;
}

function pickLibraryName() {
  $("library-name").value = "";
  $("create-library").hidden = false;
  $("library-name").focus();
}

async function createLibrary(event) {
  event.preventDefault();
  const name = $("library-name").value.trim();
  const response = await api("/libraries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    say(`${name}: ${await detail(response)}`);
    return;
  }
  const id = (await response.json()).library;
  closePanel("create-library");
  closePanel("file");
  store(localStorage, LIBRARY_KEY, id);
  await loadLibraries();
  show(true);
  await loadFiles();
  say(`Created ${id}.`);
}

async function loadFiles() {
  const response = await api(libraryPath("/files"));
  if (!response.ok) throw new Error(await detail(response));
  files = (await response.json()).files;
  renderFiles();
}

// The library's own files first, folded but for the settings, so the
// user's own are never below a long list of mdc's.
function renderFiles() {
  const words = $("filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const paths = Object.keys(files)
    .filter((p) => words.every((w) => p.toLowerCase().includes(w)))
    .sort((a, b) => sortKey(b).localeCompare(sortKey(a)));
  fill("settings-files", paths.filter((p) => SETTINGS.has(p)).sort());
  group("generated", paths.filter((p) => GENERATED.has(p)).sort(), words.length > 0);
  group("records", paths.filter((p) => RECORDS.test(p)), false);
  fill("files", paths.filter((p) => !SETTINGS.has(p) && !GENERATED.has(p) && !RECORDS.test(p)));
  const total = Object.keys(files).length;
  $("count").textContent = paths.length === total ? `${total} files` : `${paths.length} of ${total} files`;
}

// A folded group, hidden when empty; a filter opens the generated files,
// which are few, but not the records, which are many.
function group(id, paths, open) {
  fill(`${id}-files`, paths);
  $(id).hidden = !paths.length;
  $(`${id}-count`).textContent = `(${paths.length})`;
  if (open) $(id).open = true;
}

function fill(id, paths) {
  $(id).replaceChildren(...paths.map((p) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.className = "file";
    button.textContent = p;
    button.addEventListener("click", () => openFile(p));
    item.append(button);
    return item;
  }));
}

// Why mdc keeps a file to itself, or null if it is the user's.
function writtenBy(path) {
  if (GENERATED.has(path)) return `Written by mdc ${GENERATED.get(path)}, which rewrites it; view only.`;
  if (RECORDS.test(path)) return "mdc's own record; view only.";
  for (const [pattern, command] of WRITTEN) {
    if (pattern.test(path)) return `Written by mdc ${command}, never by hand; view only.`;
  }
  return null;
}

// Newest first: a dated file by its date, the library's own files after.
function sortKey(path) {
  const name = path.split("/").pop();
  return DATED.test(name) ? `1${name}` : `0${path}`;
}

async function openFile(path) {
  const response = await api(filePath(path));
  if (!response.ok) {
    say(`${path}: ${await detail(response)}`);
    return;
  }
  const blob = await response.blob();
  open = { path, sha: response.headers.get("ETag").replace(/"/g, ""), blob };
  $("file-name").textContent = path;
  $("file-text").textContent = TEXT.test(path) ? await blob.text() : `${blob.size.toLocaleString()} bytes`;
  const markdown = path.endsWith(".md");
  const note = writtenBy(path);
  for (const button of $("file-actions").querySelectorAll("[data-run]")) {
    button.hidden = !markdown || !!note || (button.dataset.run === "check" && !path.endsWith(".chat.md"));
  }
  $("file-note").textContent = note || "";
  $("file-note").hidden = !note;
  $("file-replace").parentElement.hidden = !!note;
  $("file-delete").hidden = !!note;
  $("file-delete").textContent = "Delete";
  $("file").hidden = false;
  $("file").scrollIntoView({ behavior: "smooth", block: "start" });
}

function download() {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(open.blob);
  link.download = open.path.split("/").pop();
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

// Two presses, rather than a dialog.
async function remove() {
  const button = $("file-delete");
  if (button.textContent === "Delete") {
    button.textContent = "Delete it?";
    setTimeout(() => { button.textContent = "Delete"; }, 4000);
    return;
  }
  const response = await api(filePath(open.path), { method: "DELETE", headers: { "If-Match": `"${open.sha}"` } });
  if (!response.ok) {
    say(`${open.path}: ${await detail(response)}`);
    return;
  }
  say(`Deleted ${open.path}.`);
  closePanel("file");
  await loadFiles();
}

async function put(path, body, replace) {
  const headers = {};
  if (files[path] !== undefined && replace) headers["If-Match"] = `"${files[path]}"`;
  else headers["If-None-Match"] = "*";
  const response = await api(filePath(path), { method: "PUT", headers, body });
  if (response.status === 412 && files[path] === undefined) {
    return "it already exists; reload and choose Replace";
  }
  if (response.status === 412) return replace ? "it changed on the server; reload it first" : "it already exists";
  return response.ok ? null : await detail(response);
}

// A dated name goes in its year's directory, as `mdc new` and import put it.
function defaultPath(name) {
  const dated = DATED.exec(name);
  return dated ? `${dated[1]}/${name}` : name;
}

let uploading = null;

function pickUpload(file) {
  uploading = file;
  $("upload-path").value = defaultPath(file.name);
  $("upload-replace").checked = false;
  $("upload").hidden = false;
  $("upload-path").focus();
}

async function upload(event) {
  event.preventDefault();
  const path = $("upload-path").value.trim().replace(/^\/+/, "");
  const problem = await put(path, uploading, $("upload-replace").checked);
  if (problem) {
    say(`${path}: ${problem}.`);
    return;
  }
  say(`Uploaded ${path}.`);
  closePanel("upload");
  await loadFiles();
}

async function replaceOpen(file) {
  const path = open.path;
  files[path] = open.sha;
  const problem = await put(path, file, true);
  if (problem) {
    say(`${path}: ${problem}.`);
    return;
  }
  say(`Replaced ${path}.`);
  await loadFiles();
  await openFile(path);
}

let importing = null;

function pickImport(file) {
  importing = file;
  $("import-name").textContent = file.name;
  $("import-only").value = "";
  $("import-replace").checked = false;
  $("import").hidden = false;
}

async function importFile(event) {
  event.preventDefault();
  const query = new URLSearchParams({ filename: importing.name });
  if ($("import-only").value.trim()) query.set("only", $("import-only").value.trim());
  if ($("import-replace").checked) query.set("replace", "true");
  closePanel("import");
  await stream(`import ${importing.name}`, libraryPath(`/import?${query}`), { body: importing });
}

// ---------------------------------------------------------------------------
// Runs: server-sent events, read from fetch since EventSource sends no header
// ---------------------------------------------------------------------------

function split(line) {
  return (line.match(/"[^"]*"|\S+/g) || []).map((w) => w.replace(/^"(.*)"$/, "$1"));
}

// fix asks before it applies anything, and a run on the server has nobody to
// answer, so a plain fix is a preview; Apply runs it again with --yes.
async function run(argv) {
  await stream(`mdc ${argv.join(" ")}`, libraryPath("/run"), {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ argv }),
  });
  const preview = argv[0] === "fix" && !argv.includes("--yes") && !argv.includes("-y");
  if (preview && $("output-text").textContent.includes("Skipped.")) {
    $("output-apply").onclick = guard(() => run(["fix", "--yes", ...argv.slice(1)]));
    $("output-apply").hidden = false;
  }
}

async function stream(title, path, options) {
  if (running) {
    say("A run is in progress.");
    return;
  }
  running = true;
  say("");
  $("output-title").textContent = title;
  $("output-text").textContent = "";
  $("output-changes").replaceChildren();
  $("output-apply").hidden = true;
  $("output").hidden = false;
  $("output").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const response = await api(path, { method: "POST", ...options });
    if (!response.ok) {
      $("output-text").textContent = await detail(response);
      return;
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        event(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
    }
  } finally {
    running = false;
    await loadFiles().catch(() => {});
    if (open && files[open.path] !== open.sha) {
      if (files[open.path] === undefined) closePanel("file");
      else await openFile(open.path);
    }
  }
}

function event(block) {
  const fields = {};
  for (const line of block.split("\n")) {
    const at = line.indexOf(": ");
    if (at > 0) fields[line.slice(0, at)] = line.slice(at + 2);
  }
  const data = JSON.parse(fields.data || "{}");
  const out = $("output-text");
  if (fields.event === "output") {
    out.textContent += data.text;
  } else if (fields.event === "error") {
    out.textContent += `\n${data.message}\n`;
  } else if (fields.event === "done") {
    const changed = Object.keys(data.changed || {}).map((p) => `changed ${p}`);
    const deleted = (data.deleted || []).map((p) => `deleted ${p}`);
    const lines = [...changed, ...deleted];
    if (data.exit_code) lines.unshift(`exit ${data.exit_code}`);
    $("output-changes").replaceChildren(...lines.map((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      return item;
    }));
  }
}

// ---------------------------------------------------------------------------

function guard(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (error) {
      if (error instanceof SignedOut) {
        show(false);
        say("Signed out; sign in again.");
      } else {
        say(String(error.message || error));
      }
    }
  };
}

function wire() {
  $("sign-in").addEventListener("click", guard(signIn));
  $("sign-out").addEventListener("click", guard(signOut));
  $("library").addEventListener("change", guard(async () => {
    library = $("library").value;
    store(localStorage, LIBRARY_KEY, library);
    closePanel("file");
    await loadFiles();
  }));
  $("new-library").addEventListener("click", pickLibraryName);
  $("create-library").addEventListener("submit", guard(createLibrary));
  $("filter").addEventListener("input", renderFiles);
  $("index").addEventListener("click", guard(() => run(["index"])));
  $("command").addEventListener("submit", guard(async (event) => {
    event.preventDefault();
    const argv = split($("argv").value.trim().replace(/^mdc\s+/, ""));
    if (argv.length) await run(argv);
  }));
  for (const button of $("file-actions").querySelectorAll("[data-run]")) {
    button.addEventListener("click", guard(() => run([button.dataset.run, open.path.split("/").pop()])));
  }
  $("file-download").addEventListener("click", download);
  $("file-delete").addEventListener("click", guard(remove));
  $("file-replace").addEventListener("change", guard(async (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    if (file) await replaceOpen(file);
  }));
  $("upload-pick").addEventListener("change", (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    if (file) pickUpload(file);
  });
  $("upload").addEventListener("submit", guard(upload));
  $("import-pick").addEventListener("change", (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    if (file) pickImport(file);
  });
  $("import").addEventListener("submit", guard(importFile));
  for (const button of document.querySelectorAll("[data-close]")) {
    button.addEventListener("click", () => closePanel(button.closest(".panel").id));
  }
}

async function start() {
  wire();
  const query = new URLSearchParams(location.search);
  if (query.has("code") || query.has("error")) await finishSignIn(query);
  if (!(await accessToken())) {
    show(false);
    return;
  }
  if (await loadLibraries()) {
    show(true);
    await loadFiles();
  } else {
    show(true);
  }
}

guard(start)();
