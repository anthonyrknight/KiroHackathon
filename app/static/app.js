// Campus Form Assistant - frontend chat controller.

const el = (id) => document.getElementById(id);
const picker = el("picker");
const chat = el("chat");
const formList = el("formList");
const messages = el("messages");
const composer = el("composer");
const input = el("input");
const sendBtn = el("sendBtn");
const progressFill = el("progressFill");
const progressText = el("progressText");
const downloadArea = el("downloadArea");
const downloadLink = el("downloadLink");
const refText = el("refText");

let sessionId = null;

// --- tiny markdown-ish renderer (bold, italics, line breaks) ----------
function render(text) {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/_(.+?)_/g, "<em>$1</em>")
    .replace(/\n/g, "<br>");
}

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg msg--${who}`;
  div.innerHTML = render(text);
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

function showTyping() {
  const div = document.createElement("div");
  div.className = "msg msg--bot";
  div.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

function setProgress([done, total]) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  progressFill.style.width = pct + "%";
  progressText.textContent = total ? `${done}/${total}` : "";
}

function setBusy(busy) {
  input.disabled = busy;
  sendBtn.disabled = busy;
  if (!busy) input.focus();
}

// --- API ---------------------------------------------------------------
async function loadForms() {
  const res = await fetch("/api/forms");
  const data = await res.json();
  formList.innerHTML = "";
  data.forms.forEach((f) => {
    const card = document.createElement("button");
    card.className = "form-card";
    card.innerHTML = `<h3>${f.title}</h3><p>${f.description}</p>`;
    card.addEventListener("click", () => startForm(f.id));
    formList.appendChild(card);
  });
}

async function startForm(formId) {
  picker.classList.add("hidden");
  chat.classList.remove("hidden");
  messages.innerHTML = "";
  downloadArea.classList.add("hidden");
  setBusy(true);
  const typing = showTyping();
  try {
    const res = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ form_id: formId }),
    });
    const data = await res.json();
    sessionId = data.session_id;
    typing.remove();
    addMessage(data.message, "bot");
    setProgress(data.progress);
  } catch (e) {
    typing.remove();
    addMessage("Sorry, I couldn't start that form. Please try again.", "bot");
  } finally {
    setBusy(false);
  }
}

async function send(text) {
  addMessage(text, "user");
  setBusy(true);
  const typing = showTyping();
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    const data = await res.json();
    typing.remove();
    addMessage(data.message, "bot");
    setProgress(data.progress);
    if (data.done && data.download_url) {
      downloadLink.href = data.download_url;
      refText.textContent = data.reference ? `Reference: ${data.reference}` : "";
      downloadArea.classList.remove("hidden");
    }
  } catch (e) {
    typing.remove();
    addMessage("Something went wrong sending that. Please try again.", "bot");
  } finally {
    setBusy(false);
  }
}

// --- events ------------------------------------------------------------
composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  send(text);
});

el("restartBtn").addEventListener("click", () => {
  sessionId = null;
  chat.classList.add("hidden");
  picker.classList.remove("hidden");
});

loadForms();
