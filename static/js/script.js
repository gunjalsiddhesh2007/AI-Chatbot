(() => {
  const form = document.querySelector("#chat-form");
  const input = document.querySelector("#message-input");
  const sendButton = document.querySelector("#send-button");
  const messages = document.querySelector("#messages");
  const conversation = document.querySelector(".conversation");
  const sidebar = document.querySelector("#sidebar");
  const shell = document.querySelector("#app-shell");
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const mobileQuery = window.matchMedia("(max-width: 700px)");

  let activeConversationId = null;
  let activeConversationHasMessages = false;
  let conversationItems = [];
  let busy = false;
  let toastTimer = null;

  function showToast(message) {
    const toast = document.querySelector("#toast");
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 3000);
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (["POST", "DELETE"].includes((options.method || "GET").toUpperCase())) {
      headers["X-CSRF-Token"] = csrfToken;
    }
    let response;
    try {
      response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    } catch (error) {
      throw new Error("Unable to connect. Check your connection and try again.");
    }
    let payload;
    try { payload = await response.json(); }
    catch {
      const status = response.status ? ` (HTTP ${response.status})` : "";
      payload = {
        success: false,
        error: `The server returned an unexpected response${status}. Please try again shortly.`,
      };
    }
    if (!response.ok || !payload.success) {
      const error = new Error(payload.error || "The request could not be completed.");
      error.payload = payload;
      throw error;
    }
    return payload.data;
  }

  function scrollToLatest() {
    requestAnimationFrame(() => { conversation.scrollTop = conversation.scrollHeight; });
  }

  function showWelcome() {
    messages.replaceChildren();
    const welcome = document.createElement("div");
    welcome.id = "welcome";
    welcome.className = "welcome";
    const icon = document.createElement("div");
    icon.className = "welcome-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "✦";
    const heading = document.createElement("h2");
    heading.textContent = "Hello! How can I help you today?";
    const subtitle = document.createElement("p");
    subtitle.textContent = "Ask a question, explore an idea, or get help with a task.";
    welcome.append(icon, heading, subtitle);
    messages.append(welcome);
    scrollToLatest();
  }

  function addUserMessage(text) {
    document.querySelector("#welcome")?.remove();
    const row = document.createElement("article");
    row.className = "message user";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.append(bubble);
    messages.append(row);
    scrollToLatest();
  }

  function addCopyButton(container, text, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = label === "Copy code" ? "copy-code" : "copy-button";
    button.textContent = label;
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Copied";
        setTimeout(() => { button.textContent = label; }, 1400);
      } catch {
        button.textContent = "Copy unavailable";
        setTimeout(() => { button.textContent = label; }, 1400);
      }
    });
    container.append(button);
  }

  function renderMarkdown(container, markdown) {
    if (!window.marked || !window.DOMPurify) {
      container.textContent = markdown;
      return;
    }

    const rawHtml = window.marked.parse(markdown, { gfm: true, breaks: false });
    const safeHtml = window.DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } });
    container.innerHTML = safeHtml;

    container.querySelectorAll("a[href]").forEach((link) => {
      link.rel = "noopener noreferrer";
      link.target = "_blank";
    });
    container.querySelectorAll("table").forEach((table) => {
      const wrapper = document.createElement("div");
      wrapper.className = "table-wrap";
      table.replaceWith(wrapper);
      wrapper.append(table);
    });
    container.querySelectorAll("pre > code").forEach((code) => {
      if (window.hljs) window.hljs.highlightElement(code);
      const text = code.textContent;
      addCopyButton(code.parentElement, text, "Copy code");
    });
  }

  function addAssistantMessage(text, { markdown = true, copy = true } = {}) {
    document.querySelector("#welcome")?.remove();
    const row = document.createElement("article");
    row.className = "message assistant";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (markdown) {
      const content = document.createElement("div");
      content.className = "assistant-content";
      renderMarkdown(content, text);
      bubble.append(content);
    } else {
      bubble.textContent = text;
    }
    row.append(bubble);
    if (copy) {
      const tools = document.createElement("div");
      tools.className = "assistant-tools";
      addCopyButton(tools, text, "Copy response");
      bubble.append(tools);
    }
    messages.append(row);
    scrollToLatest();
    return row;
  }

  function addTypingIndicator() {
    document.querySelector("#welcome")?.remove();
    const row = document.createElement("article");
    row.className = "message assistant";
    const bubble = document.createElement("div");
    bubble.className = "bubble typing";
    bubble.setAttribute("aria-label", "AI is responding");
    for (let i = 0; i < 3; i += 1) bubble.append(document.createElement("span"));
    row.append(bubble);
    messages.append(row);
    scrollToLatest();
    return row;
  }

  function setBusy(value) {
    busy = value;
    sendButton.disabled = value;
    input.disabled = value;
    document.querySelectorAll(".conversation-select, .delete-conversation, #new-chat-button, #new-chat-inline").forEach((button) => {
      button.disabled = value;
    });
  }

  function setSidebar(open) {
    if (mobileQuery.matches) {
      shell.classList.toggle("sidebar-open", open);
      document.querySelector("#sidebar-toggle").setAttribute("aria-expanded", String(open));
    } else {
      shell.classList.toggle("sidebar-collapsed", !open);
      document.querySelector("#sidebar-toggle").setAttribute("aria-expanded", String(open));
    }
  }

  function closeSidebarOnMobile() {
    if (mobileQuery.matches) setSidebar(false);
  }

  function renderConversationList() {
    const list = document.querySelector("#conversation-list");
    const search = document.querySelector("#conversation-search").value.trim().toLocaleLowerCase();
    const visible = conversationItems.filter((item) => item.title.toLocaleLowerCase().includes(search));
    list.replaceChildren();
    document.querySelector("#history-count").textContent = visible.length ? String(visible.length) : "";

    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = search ? "No conversations match your search." : "Your recent chats will appear here.";
      list.append(empty);
      return;
    }

    visible.forEach((item) => {
      const row = document.createElement("div");
      row.className = "conversation-item";
      if (String(item.id) === String(activeConversationId)) row.classList.add("active");
      const select = document.createElement("button");
      select.type = "button";
      select.className = "conversation-select";
      select.textContent = item.title;
      select.title = item.title;
      if (String(item.id) === String(activeConversationId)) select.setAttribute("aria-current", "page");
      select.addEventListener("click", () => loadConversation(item.id));

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "delete-conversation";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Delete ${item.title}`);
      remove.title = "Delete conversation";
      remove.addEventListener("click", () => removeConversation(item.id, row));
      row.append(select, remove);
      list.append(row);
    });
  }

  async function refreshConversations() {
    const result = await api("/api/conversations");
    conversationItems = result.conversations || [];
    renderConversationList();
  }

  async function loadConversation(id) {
    if (busy) return;
    try {
      const result = await api(`/api/conversations/${encodeURIComponent(id)}`);
      const item = result.conversation;
      activeConversationId = item.id;
      activeConversationHasMessages = item.messages.length > 0;
      document.querySelector("#active-title").textContent = item.title;
      messages.replaceChildren();
      if (!item.messages.length) {
        showWelcome();
      } else {
        item.messages.forEach((message) => {
          if (message.role === "user") addUserMessage(message.content);
          else addAssistantMessage(message.content);
        });
      }
      renderConversationList();
      closeSidebarOnMobile();
      scrollToLatest();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function startNewChat() {
    if (busy) return;
    if (activeConversationId && !activeConversationHasMessages) {
      messages.replaceChildren();
      showWelcome();
      document.querySelector("#active-title").textContent = "New chat";
      closeSidebarOnMobile();
      input.focus();
      return;
    }
    try {
      const result = await api("/api/conversations", { method: "POST", body: "{}" });
      activeConversationId = result.conversation.id;
      activeConversationHasMessages = false;
      document.querySelector("#active-title").textContent = "New chat";
      showWelcome();
      await refreshConversations();
      closeSidebarOnMobile();
      input.focus();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function removeConversation(id, row) {
    if (busy) return;
    const item = conversationItems.find((entry) => String(entry.id) === String(id));
    if (!item || !window.confirm(`Delete “${item.title}”? This also deletes its messages.`)) return;
    try {
      await api(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
      row.classList.add("deleting");
      await new Promise((resolve) => setTimeout(resolve, 180));
      if (String(activeConversationId) === String(id)) {
        activeConversationId = null;
        activeConversationHasMessages = false;
        document.querySelector("#active-title").textContent = "New chat";
        showWelcome();
      }
      await refreshConversations();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || busy) return;
    addUserMessage(message);
    input.value = "";
    input.style.height = "auto";
    const waiting = addTypingIndicator();
    setBusy(true);

    try {
      // Create the conversation before the slower provider call so the browser
      // keeps its ID even if a proxy or network timeout interrupts the reply.
      if (!activeConversationId) {
        const created = await api("/api/conversations", { method: "POST", body: "{}" });
        activeConversationId = created.conversation.id;
        activeConversationHasMessages = false;
        document.querySelector("#active-title").textContent = "New chat";
      }
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ conversation_id: activeConversationId, message }),
      });
      activeConversationId = data.conversation_id;
      activeConversationHasMessages = true;
      document.querySelector("#active-title").textContent = data.conversation.title;
      waiting.remove();
      addAssistantMessage(data.response);
      await refreshConversations();
    } catch (error) {
      const conversationId = error.payload?.data?.conversation_id || error.payload?.conversation_id;
      if (conversationId) {
        activeConversationId = conversationId;
        activeConversationHasMessages = true;
      }
      waiting.remove();
      addAssistantMessage(error.message, { markdown: false, copy: false });
      try { await refreshConversations(); } catch { /* Keep the chat error visible if history cannot refresh. */ }
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", sendMessage);
  document.querySelector("#new-chat-button").addEventListener("click", startNewChat);
  document.querySelector("#new-chat-inline").addEventListener("click", startNewChat);
  document.querySelector("#conversation-search").addEventListener("input", renderConversationList);
  document.querySelector("#sidebar-toggle").addEventListener("click", () => {
    const isOpen = mobileQuery.matches ? shell.classList.contains("sidebar-open") : !shell.classList.contains("sidebar-collapsed");
    setSidebar(!isOpen);
  });
  document.querySelector("#sidebar-close").addEventListener("click", () => setSidebar(false));
  document.querySelector("#sidebar-backdrop").addEventListener("click", () => setSidebar(false));
  mobileQuery.addEventListener("change", () => setSidebar(!mobileQuery.matches));

  setSidebar(!mobileQuery.matches);
  refreshConversations().catch((error) => showToast(error.message));
})();
