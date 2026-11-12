// noesis's web client: keeps a library on noesis's server without the CLI.
// Writing is done elsewhere: a chat or document enters by Import, a source
// only by the CLI's sync, and a reply only from the CLI. Here the user's files
// are checked, fixed, indexed, downloaded and deleted; only the settings are
// edited in place.
//
// Signs in at auth (`auth.rvanegas.co`, named by the page's `auth` meta) as
// the public client `noesis-web` (authorization code with PKCE), then calls
// the same file and run API the CLI does (server.py). The refresh token is kept in
// localStorage so a sign-in lasts its ninety days; the access token only in
// memory. The page's CSP admits no script but this file.
//
// Everything a file or a run returns is put on the page as text, never as
// markup.

"use strict";

const CLIENT_ID = "noesis-web";
const AUTH = document.querySelector('meta[name="auth"]').content;
// Roxana's web app, for an argument's own discussion (`roxana_web_url`; empty
// where the server names none).
const ROXANA = document.querySelector('meta[name="roxana"]').content.replace(/\/$/, "");
const REDIRECT = `${location.origin}/web/`;
const REFRESH_KEY = "noesis.refresh";
const LIBRARY_KEY = "noesis.library";
const FILE_KEY = "noesis.file";
const SIGN_IN_KEY = "noesis.sign-in";
const TEXT = /\.(md|txt|toml|json|csv|tex|bib)$/i;
const DATED = /^(\d{4})-\d\d-\d\d-/;

// What a library holds besides the user's own files. The settings are the
// user's to edit, and every library has them; the rest noesis writes, and the
// page only shows them. These names copy noesis/library.py's SETTINGS,
// GENERATED_FILENAMES and RECORD_DIRS: change one, change both.
const SETTINGS = new Map([
  ["KEYS.md", "How Index names terms. Under ## Plural, a term that is the same as its plural; under " +
    "## Alias, a term, then - each other name for it; under ## Exclude, terms left out; under ## Group, " +
    "a term, then - the terms under it."],
  ["SYSTEM_PROMPT.md", "Added to what Claude is told in every reply in this library."],
]);
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
let open = null;             // {path, sha, blob, modified}
let running = false;
let exitCode = 0;            // the last run's, -1 if it never finished
let names = [];              // the chat headings, besides Prompt, that are the user
let user = null;             // who is signed in, whose own libraries are "<user>/…"
let libraries = [];          // [{id, name, users, documents}], as /libraries gives them

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
  location.assign(`${AUTH}/authorize?${query}`);
}

async function tokenRequest(fields) {
  const response = await fetch(`${AUTH}/token`, {
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

// The redirect back from auth's sign-in, with a code or a refusal.
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

// Revokes this client's grant, then ends the browser's session at auth (its
// /logout, which comes back here): otherwise the next sign-in would finish at
// once on that session, as if nobody had signed out. Other applications
// signed in through auth stay signed in.
async function signOut() {
  const refresh = recall(localStorage, REFRESH_KEY);
  if (refresh) {
    await fetch(`${AUTH}/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      // The SDK's revocation form requires the field even of a public client.
      body: new URLSearchParams({ client_id: CLIENT_ID, client_secret: "", token: refresh }),
    }).catch(() => {});
  }
  store(localStorage, REFRESH_KEY, null);
  access = null;
  show(false);
  const query = new URLSearchParams({ client_id: CLIENT_ID, post_logout_redirect_uri: REDIRECT });
  location.assign(`${AUTH}/logout?${query}`);
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

// Signed in with no library yet, the page offers only to make one: every
// other control acts on a library.
function show(signedIn) {
  const hasLibrary = libraries.length > 0;
  $("signed-in").hidden = !signedIn || !hasLibrary;
  $("first-library").hidden = !signedIn || hasLibrary;
  $("signed-out").hidden = signedIn;
  $("sign-out").hidden = !signedIn;
  $("new-library").hidden = !signedIn || !hasLibrary;
  $("your-names").hidden = !signedIn || !hasLibrary;
  $("library").hidden = !signedIn || !hasLibrary;
  if (!signedIn) $("usage").hidden = true;
}

function closePanel(id) {
  $(id).hidden = true;
  if (id === "file") open = null;
  if (id === "libraries") $("library").setAttribute("aria-expanded", "false");
}

// A free account's month so far: what its model commands have spent, and
// what it keeps. The operator's own account has no limits to show.
async function loadUsage() {
  const response = await api("/me");
  if (!response.ok) return;
  const me = await response.json();
  names = me.names;
  user = me.user;
  const usage = $("usage");
  usage.hidden = me.plan !== "free";
  if (usage.hidden) return;
  const mb = (bytes) => (bytes / 1024 / 1024).toFixed(1);
  usage.textContent = `${me.user}: $${me.spent_usd.toFixed(2)} of this month’s $${me.allowance_usd.toFixed(2)} ` +
    `for model commands; ${mb(me.stored_bytes)} of ${mb(me.storage_bytes)} MB stored.`;
}

async function loadLibraries() {
  const response = await api("/libraries");
  libraries = (await response.json()).libraries;
  if (!libraries.length) {
    library = null;
    return false;
  }
  const remembered = recall(localStorage, LIBRARY_KEY);
  library = libraries.some((l) => l.id === remembered) ? remembered : libraries[0].id;
  showGroup();
  return true;
}

function current() {
  return libraries.find((l) => l.id === library);
}

// The bar's button names the chosen library by the name its id only slugs;
// a group's library (The Floor's channel) is headed by its group's name too,
// or by who else is in it when the group has no name.
function showGroup() {
  const name = current()?.name;
  const group = library?.split("/")[0] !== user ? name : null;
  $("library").textContent = name || library;
  $("library").title = library;
  $("group").textContent = group ?? "";
  $("group").hidden = !group;
}

// Every library the user reaches, with what tells them apart: its id, the
// name it goes by, who else reaches it, and how many chats and documents it holds.
function pickLibrary() {
  if (!$("libraries").hidden) {
    closePanel("libraries");
    return;
  }
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  $("library-list").replaceChildren(...libraries.map((l) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.className = "library";
    button.setAttribute("aria-current", String(l.id === library));
    const title = document.createElement("span");
    title.className = "library-name";
    title.textContent = l.name || l.id.split("/")[1];
    const id = document.createElement("code");
    id.textContent = l.id;
    const about = document.createElement("span");
    about.className = "library-about";
    about.textContent = `${plural(l.documents, "document")} · ` +
      (l.users.length ? l.users.join(", ") : "no members");
    button.append(title, id, about);
    button.addEventListener("click", guard(() => chooseLibrary(l.id)));
    item.append(button);
    return item;
  }));
  $("libraries").hidden = false;
  $("library").setAttribute("aria-expanded", "true");
  $("libraries").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function chooseLibrary(id) {
  closePanel("libraries");
  if (id === library) return;
  library = id;
  store(localStorage, LIBRARY_KEY, library);
  showGroup();
  closePanel("file");
  await loadFiles();
}

// The chat headings that are the user's own voice, kept with their account.
function pickNames() {
  $("names-list").value = names.join("\n");
  $("names").hidden = false;
  $("names-list").focus();
}

async function saveNames(event) {
  event.preventDefault();
  const response = await api("/me/names", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names: $("names-list").value.split("\n").map((n) => n.trim()).filter(Boolean) }),
  });
  if (!response.ok) {
    say(`Your names: ${await detail(response)}`);
    return;
  }
  names = (await response.json()).names;
  closePanel("names");
  say(names.length ? `You are Prompt and ${names.join(", ")} in your chats.` : "You are Prompt in your chats.");
}

function pickLibraryName() {
  $("library-name").value = "";
  $("create-library").hidden = false;
  $("library-name").focus();
}

// From either form: New library's, or the first library's.
async function createLibrary(event) {
  event.preventDefault();
  const name = event.target.querySelector("input").value.trim();
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
  say(`Created ${name}, ${id}.`);
}

async function loadFiles() {
  const response = await api(libraryPath("/files"));
  if (!response.ok) throw new Error(await detail(response));
  files = (await response.json()).files;
  renderFiles();
}

// The library's own files first, folded but for the settings, so the
// user's own are never below a long list of noesis's.
function renderFiles() {
  const words = $("filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const paths = Object.keys(files)
    .filter((p) => !madePdf(p) && words.every((w) => p.toLowerCase().includes(w)))
    .sort((a, b) => sortKey(b).localeCompare(sortKey(a)));
  // A library made before it had its settings still lists them, to be written.
  fill("settings-files", [...SETTINGS.keys()].filter((p) => words.every((w) => p.toLowerCase().includes(w))));
  group("generated", paths.filter((p) => GENERATED.has(p)).sort(), words.length > 0);
  group("records", paths.filter((p) => RECORDS.test(p)), false);
  const own = (p) => !SETTINGS.has(p) && !GENERATED.has(p) && !RECORDS.test(p);
  fill("files", paths.filter(own));
  const total = Object.keys(files).filter((p) => own(p) && !madePdf(p)).length;
  const shown = paths.filter(own).length;
  $("filter").hidden = !total;
  $("count").textContent = !total
    ? "Nothing here yet. Import a chat or document, or a claude.ai export; then Index makes the library searchable."
    : shown === total ? `${total} files` : `${shown} of ${total} files`;
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

// A PDF that noesis pdf made of a Markdown file is shown with that file,
// whose PDF button fetches it, rather than listed beside it.
function madePdf(path) {
  return path.endsWith(".pdf") && files[path.replace(/\.pdf$/, ".md")] !== undefined;
}

// Why noesis keeps a file to itself, or null if it is the user's.
function writtenBy(path) {
  if (GENERATED.has(path)) return `Written by noesis ${GENERATED.get(path)}, which rewrites it; view only.`;
  if (RECORDS.test(path)) return "noesis's own record; view only.";
  for (const [pattern, command] of WRITTEN) {
    if (pattern.test(path)) return `Written by noesis ${command}, never by hand; view only.`;
  }
  return null;
}

// Newest first: a dated file by its date, the library's own files after.
function sortKey(path) {
  const name = path.split("/").pop();
  return DATED.test(name) ? `1${name}` : `0${path}`;
}

// A setting not yet written opens empty; saving it writes it.
async function openFile(path) {
  let blob, sha = null, modified = null;
  if (SETTINGS.has(path) && files[path] === undefined) {
    blob = new Blob([""]);
  } else {
    const response = await api(filePath(path));
    if (!response.ok) {
      say(`${path}: ${await detail(response)}`);
      return;
    }
    blob = await response.blob();
    sha = response.headers.get("ETag").replace(/"/g, "");
    modified = lastModified(response);
  }
  open = { path, sha, blob, modified };
  $("file-name").textContent = path;
  $("file-text").textContent = TEXT.test(path) ? await blob.text() : `${blob.size.toLocaleString()} bytes`;
  $("file-text").hidden = false;
  $("file-editor").hidden = true;
  const markdown = path.endsWith(".md");
  const setting = SETTINGS.has(path);
  const note = writtenBy(path);
  // A stem's argument is its .argument.md: Extract makes it, once, from the
  // chat or the document, and Send to Roxana sends it from the argument file
  // alone, where its stances can be read before they go.
  const source = /\.(document|chat)\.md$/;
  const argued = source.test(path) && files[path.replace(source, ".argument.md")] !== undefined;
  for (const button of $("file-actions").querySelectorAll("[data-run]")) {
    const run = button.dataset.run;
    button.hidden = setting ? !(run === "validate" && path === "KEYS.md" && sha)
      : !markdown || !!note || (run === "check" && !path.endsWith(".chat.md"))
        || (run === "argue" && (!source.test(path) || argued))
        || (run === "export" && !path.endsWith(".argument.md"));
  }
  // A chat without its document takes one written elsewhere (claude.ai, an
  // editor), as <stem>.document.md beside it: the position the conversation
  // came to, from which an argument is then extracted.
  $("file-document").hidden = !path.endsWith(".chat.md")
    || files[path.replace(/\.chat\.md$/, ".document.md")] !== undefined;
  $("file-claude").hidden = $("file-document").hidden;
  // An argument already sent says where, under its date (argue.Sent), and
  // opens that discussion; sending it again is refused unless it changed.
  const sent = path.endsWith(".argument.md") && ROXANA
    ? $("file-text").textContent.match(/^Sent to Roxana: (\w+),/m) : null;
  $("file-roxana").href = sent ? `${ROXANA}/discussions/${sent[1]}` : "";
  $("file-roxana").hidden = !sent;
  $("file-note").textContent = setting ? SETTINGS.get(path) : note || "";
  $("file-note").hidden = !setting && !note;
  $("file-edit").hidden = !setting;
  $("file-download").hidden = !sha;
  $("file-pdf").hidden = !markdown || setting || !sha;
  $("file-delete").hidden = !!note || setting;
  $("file-copy").hidden = !/\.(chat|document)\.md$/.test(path) || !sha || !ownLibraries().length;
  $("file-delete").textContent = "Delete";
  $("file").hidden = false;
  $("file").scrollIntoView({ behavior: "smooth", block: "start" });
  if (!$("file-pdf").hidden) await showPdf();
}

function download(blob = open.blob, path = open.path) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = path.split("/").pop();
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function lastModified(response) {
  return Date.parse(response.headers.get("Last-Modified"));
}

// The file's PDF is <stem>.pdf beside it: none, or older than the file
// ("stale"), or newer ("current"). Only its headers are read to tell.
async function pdfState(path, modified) {
  const target = path.replace(/\.md$/, ".pdf");
  if (files[target] === undefined) return { state: "none" };
  const response = await api(filePath(target), { method: "HEAD" });
  if (!response.ok) return { state: "none" };
  const made = lastModified(response);
  return { state: made > modified ? "current" : "stale", made };
}

const PDF_LABELS = { none: "Make PDF", stale: "Update PDF", current: "Download PDF" };

async function showPdf() {
  const path = open.path;
  const { state, made } = await pdfState(path, open.modified);
  if (open?.path !== path) return;
  $("file-pdf").textContent = PDF_LABELS[state];
  $("file-pdf").title = made ? `Its PDF was made ${new Date(made).toLocaleString()}` : "It has no PDF yet";
}

// Downloaded as it is if current, and otherwise made by noesis pdf first.
// The button is off meanwhile, so a second press waits for the first.
async function pdf() {
  if (running) {
    say("A run is in progress.");
    return;
  }
  const { path, modified } = open;
  const target = path.replace(/\.md$/, ".pdf");
  $("file-pdf").disabled = true;
  try {
    if ((await pdfState(path, modified)).state !== "current") {
      await run(["pdf", "--quiet", path.split("/").pop()]);
      if (exitCode) return;
    }
    const response = await api(filePath(target));
    if (!response.ok) {
      say(`${target}: ${await detail(response)}`);
      return;
    }
    download(await response.blob(), target);
  } finally {
    $("file-pdf").disabled = false;
    if (open?.path === path) await showPdf();
  }
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
  say(`Deleted ${open.path}. It is kept thirty days, and can be restored by asking.`);
  closePanel("file");
  await loadFiles();
}

// A setting, edited as plain text: written over the version opened, or
// refused if it has changed since.
async function edit() {
  $("file-draft").value = await open.blob.text();
  $("file-text").hidden = true;
  $("file-editor").hidden = false;
  $("file-draft").focus();
}

function cancelEdit() {
  $("file-editor").hidden = true;
  $("file-text").hidden = false;
}

async function save(event) {
  event.preventDefault();
  const path = open.path;
  const headers = open.sha ? { "If-Match": `"${open.sha}"` } : { "If-None-Match": "*" };
  const response = await api(filePath(path), { method: "PUT", headers, body: $("file-draft").value });
  if (!response.ok) {
    say(`${path}: ${response.status === 412 ? "it changed on the server; close it and open it again" : await detail(response)}.`);
    return;
  }
  say(`Saved ${path}.`);
  await loadFiles();
  await openFile(path);
}

// A chat or a document into another library of the user's own — from a
// channel's library at The Floor above all, whose transcripts are nobody's —
// as theirs: the server adds the name they go by there to their names, and
// asks which speaker they are when none of their names is in the chat.
function ownLibraries() {
  return libraries.map((l) => l.id).filter((id) => id !== library && id.startsWith(`${user}/`));
}

function pickCopy() {
  $("copy-name").textContent = open.path.split("/").pop();
  $("copy-to").replaceChildren(...ownLibraries().map((id) => new Option(id, id)));
  $("copy-who").hidden = true;
  $("copy-speakers").replaceChildren();
  $("copy").hidden = false;
  $("copy").scrollIntoView({ behavior: "smooth", block: "start" });
}

// The speakers to choose among, once the server has asked: any number, or none.
function askWho(speakers) {
  $("copy-speakers").replaceChildren(...speakers.map((speaker) => {
    const label = document.createElement("label");
    label.className = "check";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = speaker;
    label.append(box, ` ${speaker}`);
    return label;
  }));
  $("copy-who").hidden = false;
}

async function copyFile(event) {
  event.preventDefault();
  const to = $("copy-to").value;
  const body = { file: open.path, to: to.split("/")[1] };
  if (!$("copy-who").hidden) {
    body.names = [...$("copy-speakers").querySelectorAll("input:checked")].map((box) => box.value);
  }
  closePanel("copy");
  await stream(`copy ${body.file.split("/").pop()} to ${to}`, libraryPath("/copy"), {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    // Which speaker they are, asked before anything is copied: back to the panel.
    refused: async (response) => {
      if (response.status !== 409) return false;
      const asked = (await response.json()).detail;
      if (!asked || !asked.speakers) return false;
      closePanel("output");
      $("copy").hidden = false;
      askWho(asked.speakers);
      return true;
    },
  });
}

let importing = null;

function pickImport(file) {
  importing = file;
  $("import-name").textContent = file.name;
  $("import-only").value = "";
  $("import-replace").checked = false;
  $("import").hidden = false;
}

// Two steps, so the instructions come before claude.ai opens: Claude reads
// the chat through the noesis connector and writes the document with the
// person, who downloads it and imports it here as the chat's pair. noesis
// writes nothing for claude.ai; the document returns by Import.
function draftPrompt(path) {
  return [
    `Using noesis, read the chat \`${path.split("/").pop()}\` in my library \`${library}\` (read_file).`,
    "Help me write its document: the position this conversation came to, in my voice, as I would hold it now.",
    "Where it is unclear what I hold, ask me rather than settling it yourself.",
    "When we are done, give the whole document as a Markdown file starting with `# <title>`,",
    "so that I can import it into noesis as this chat's document.",
  ].join(" ");
}

function showDraft() {
  const prompt = draftPrompt(open.path);
  $("draft-chat").textContent = open.path;
  $("draft-prompt").textContent = prompt;
  $("draft-open").href = `https://claude.ai/new?q=${encodeURIComponent(prompt)}`;
  $("draft").hidden = false;
  $("draft").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function copyDraft() {
  await navigator.clipboard.writeText($("draft-prompt").textContent);
  $("draft-copy").textContent = "Copied";
  setTimeout(() => { $("draft-copy").textContent = "Copy the prompt"; }, 2000);
}

async function importDocument() {
  const file = $("document-pick").files[0];
  $("document-pick").value = "";
  if (!file || !open) return;
  const query = new URLSearchParams({ filename: file.name, document_of: open.path });
  await stream(`import ${file.name} as the document of ${open.path.split("/").pop()}`,
    libraryPath(`/import?${query}`), { body: file });
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

// fix asks before it applies anything, and a run on the server has nobody to
// answer, so a plain fix is a preview; Apply runs it again with --yes.
// export ends with the discussion's address, made a link here; an argument
// changed since it was sent is refused, since a discussion in Roxana belongs
// to no one and is never replaced, and Send as a new discussion asks again
// with --new.
async function run(argv) {
  await stream(`noesis ${argv.join(" ")}`, libraryPath("/run"), {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ argv }),
  });
  const output = $("output-text").textContent;
  const preview = argv[0] === "fix" && !argv.includes("--yes") && !argv.includes("-y");
  if (preview && output.includes("Skipped.")) {
    offer("Apply these fixes", ["fix", "--yes", ...argv.slice(1)]);
  }
  if (argv[0] === "export") {
    const address = output.match(/https:\/\/\S+\/discussions\/\w+/);
    if (address) {
      $("output-link").href = address[0];
      $("output-link").textContent = "Open in Roxana";
      $("output-link").hidden = false;
    }
    if (!argv.includes("--new") && output.includes("--new")) {
      offer("Send as a new discussion", ["export", "--new", ...argv.slice(1)]);
    }
  }
}

function offer(label, argv) {
  $("output-apply").textContent = label;
  $("output-apply").onclick = guard(() => run(argv));
  $("output-apply").hidden = false;
}

// refused(response), if given, may take a refusal before the run began as its
// own to answer, returning true.
async function stream(title, path, { refused, ...options }) {
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
  $("output-link").hidden = true;
  $("output").hidden = false;
  exitCode = -1;  // until its done event says otherwise
  $("output").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const response = await api(path, { method: "POST", ...options });
    if (!response.ok) {
      if (!(refused && await refused(response))) $("output-text").textContent = await detail(response);
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
    await loadUsage().catch(() => {});
    if (open && (files[open.path] ?? null) !== open.sha) {
      if (files[open.path] === undefined && !SETTINGS.has(open.path)) closePanel("file");
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
    exitCode = data.exit_code || 0;
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
  $("library").addEventListener("click", pickLibrary);
  $("new-library").addEventListener("click", pickLibraryName);
  $("create-library").addEventListener("submit", guard(createLibrary));
  $("your-names").addEventListener("click", pickNames);
  $("names").addEventListener("submit", guard(saveNames));
  $("first-library-form").addEventListener("submit", guard(createLibrary));
  $("filter").addEventListener("input", renderFiles);
  $("index").addEventListener("click", guard(() => run(["index"])));
  for (const button of $("file-actions").querySelectorAll("[data-run]")) {
    button.addEventListener("click", guard(() => run([button.dataset.run, open.path.split("/").pop()])));
  }
  $("file-edit").addEventListener("click", guard(edit));
  $("file-cancel").addEventListener("click", cancelEdit);
  $("file-editor").addEventListener("submit", guard(save));
  $("file-download").addEventListener("click", () => download());
  $("file-pdf").addEventListener("click", guard(pdf));
  $("file-delete").addEventListener("click", guard(remove));
  $("import-pick").addEventListener("change", (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    if (file) pickImport(file);
  });
  $("import").addEventListener("submit", guard(importFile));
  $("document-pick").addEventListener("change", guard(importDocument));
  $("file-copy").addEventListener("click", pickCopy);
  $("copy").addEventListener("submit", guard(copyFile));
  $("file-claude").addEventListener("click", showDraft);
  $("draft-copy").addEventListener("click", guard(copyDraft));
  for (const button of document.querySelectorAll("[data-close]")) {
    button.addEventListener("click", () => closePanel(button.closest(".panel").id));
  }
}

async function start() {
  wire();
  const query = new URLSearchParams(location.search);
  // ?library=<id> — The Floor's *Open in noesis* on a channel's settings — is
  // remembered as the library to show, so it outlasts a sign-in on the way;
  // one this person does not reach is passed over like any remembered one.
  if (query.has("library")) {
    store(localStorage, LIBRARY_KEY, query.get("library"));
    // &file=<path> — a segment's *Open in noesis* — is the document to open
    // there, kept for this tab alone, through a sign-in, as the library is.
    store(sessionStorage, FILE_KEY, query.get("file"));
    history.replaceState(null, "", REDIRECT);
  }
  if (query.has("code") || query.has("error")) await finishSignIn(query);
  if (!(await accessToken())) {
    show(false);
    return;
  }
  await loadUsage();
  const hasLibrary = await loadLibraries();
  show(true);
  if (hasLibrary) await loadFiles();
  else $("first-library-name").focus();
  const file = recall(sessionStorage, FILE_KEY);
  store(sessionStorage, FILE_KEY, null);
  // Only one this library holds: a document deleted since is passed over.
  if (hasLibrary && file && files[file] !== undefined) await openFile(file);
}

guard(start)();
