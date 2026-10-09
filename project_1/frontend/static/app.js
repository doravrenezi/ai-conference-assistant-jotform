// This file powers the chat UI, sends requests to the backend, and renders result cards and action buttons.
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const messageFeed = document.getElementById("messageFeed");
const sendButton = document.getElementById("sendButton");
const resultPanel = document.getElementById("resultPanel");
const resultActionBar = document.getElementById("resultActionBar");
const chatSessionId = crypto.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const conversationHistory = [];
const INITIAL_ASSISTANT_MESSAGE = "Hi, how may I assist you today?";

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatMessageText(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function appendMessage(role, text) {
  const article = document.createElement("article");
  article.className = role === "system" ? "message message-assistant message-system" : `message message-${role}`;

  const roleLabel = document.createElement("span");
  roleLabel.className = "message-role";
  roleLabel.textContent = role === "assistant" ? "Assistant" : role === "system" ? "System" : "You";

  const content = document.createElement("p");
  content.innerHTML = formatMessageText(text);

  article.append(roleLabel, content);
  messageFeed.append(article);
  if (role === "assistant" || role === "system") {
    scrollMessageIntoView(article, "start");
  } else {
    scrollWindowToBottom();
  }
  return article;
}

function scrollWindowToBottom() {
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  });
}

function scrollMessageIntoView(messageElement, block = "start") {
  window.requestAnimationFrame(() => {
    messageElement.scrollIntoView({ behavior: "smooth", block, inline: "nearest" });
  });
}

function initializeConversation() {
  appendMessage("assistant", INITIAL_ASSISTANT_MESSAGE);
  conversationHistory.push({ role: "assistant", content: INITIAL_ASSISTANT_MESSAGE });
}

function setComposerPendingState(isPending) {
  sendButton.disabled = isPending;
  messageInput.disabled = isPending;
  sendButton.textContent = isPending ? "Thinking" : "Send";
}

function renderResultCard(result) {
  if (!result) {
    resultPanel.hidden = true;
    resultPanel.innerHTML = "";
    resultActionBar.hidden = true;
    resultActionBar.innerHTML = "";
    return;
  }

  const detailRows = Object.entries(result.details || {})
    .map(([label, value]) => `<div class="result-row"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");

  resultPanel.innerHTML = `
    <article class="result-card">
      <p class="result-kicker">${result.type.replaceAll("_", " ")}</p>
      <h3>${result.title}</h3>
      ${result.subtitle ? `<p class="result-subtitle">${result.subtitle}</p>` : ""}
      <div class="result-details">${detailRows}</div>
    </article>
  `;
  resultPanel.hidden = false;

  if (result.action_label && result.action_value) {
    const actionLabel = result.action_label.toLowerCase();
    const actionCopy = actionLabel.includes("cancel")
      ? "Everything looks ready. Confirm before we cancel this registration."
      : actionLabel.includes("update")
        ? "Everything looks ready. Confirm before we save your registration update."
        : "Everything looks ready. Confirm before we submit your registration.";

    resultActionBar.innerHTML = `
      <div class="result-action-shell">
        <p class="result-action-copy">${actionCopy}</p>
        <button
          class="result-action-button"
          id="resultActionButton"
          type="button"
          data-action-value="${result.action_value}"
        >
          ${result.action_label}
        </button>
      </div>
    `;
    resultActionBar.hidden = false;

    const actionButton = document.getElementById("resultActionButton");
    actionButton.addEventListener("click", async () => {
      const actionLabelText = actionButton.textContent.trim();
      actionButton.disabled = true;
      actionButton.textContent = "Thinking...";
      await sendMessage(actionButton.dataset.actionValue, {
        displayMessage: actionLabelText,
        clearResultUi: true,
      });
    });
    return;
  }

  resultActionBar.hidden = true;
  resultActionBar.innerHTML = "";
}

async function sendMessage(message, options = {}) {
  const displayMessage = options.displayMessage ?? message;
  appendMessage("user", displayMessage);
  const requestHistory = [...conversationHistory];
  messageInput.value = "";
  setComposerPendingState(true);
  const thinkingMessage = appendMessage("assistant", "Thinking...");
  thinkingMessage.classList.add("message-thinking");

  if (options.clearResultUi) {
    resultActionBar.hidden = true;
    resultActionBar.innerHTML = "";
  }

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Chat-Session-Id": chatSessionId,
      },
      body: JSON.stringify({
        message,
        history: requestHistory,
      }),
    });

    const responseText = await response.text();
    let data = null;

    if (responseText) {
      try {
        data = JSON.parse(responseText);
      } catch {
        data = null;
      }
    }

    if (!response.ok) {
      const message =
        data?.detail ||
        responseText ||
        `Request failed with status ${response.status}.`;
      throw new Error(message);
    }

    if (!data) {
      throw new Error("Backend returned an invalid response.");
    }

    thinkingMessage.remove();
    conversationHistory.push({ role: "user", content: message });
    conversationHistory.push({ role: "assistant", content: data.reply });
    const assistantMessage = appendMessage("assistant", data.reply);
    renderResultCard(data.result);
    scrollMessageIntoView(assistantMessage, "start");
  } catch (error) {
    thinkingMessage.remove();
    appendMessage("system", error.message);
  } finally {
    setComposerPendingState(false);
    messageInput.focus();
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) {
    return;
  }
  await sendMessage(message);
});

initializeConversation();
