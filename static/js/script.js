(() => {
  const form = document.querySelector("#chat-form");
  const input = document.querySelector("#message-input");
  const sendButton = document.querySelector("#send-button");
  const messages = document.querySelector("#messages");
  const conversation = document.querySelector(".conversation");
  const clearButton = document.querySelector("#clear-button");
  let history = [];
  let busy = false;

  function scrollToLatest() { conversation.scrollTop = conversation.scrollHeight; }
  function addMessage(role, text) {
    document.querySelector("#welcome")?.remove();
    const row = document.createElement("article");
    row.className = `message ${role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.append(bubble);
    if (role === "assistant") {
      const tools = document.createElement("div");
      tools.className = "assistant-tools";
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "copy-button";
      copy.textContent = "Copy response";
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(text); copy.textContent = "Copied"; setTimeout(() => { copy.textContent = "Copy response"; }, 1400); }
        catch { copy.textContent = "Copy unavailable"; }
      });
      tools.append(copy);
      bubble.append(tools);
    }
    messages.append(row);
    scrollToLatest();
    return row;
  }

  function setBusy(value) { busy = value; sendButton.disabled = value; input.disabled = value; }
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 180)}px`; });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || busy) return;
    addMessage("user", message);
    input.value = ""; input.style.height = "auto";
    const waiting = addMessage("assistant", "");
    const bubble = waiting.querySelector(".bubble");
    bubble.classList.add("typing");
    bubble.innerHTML = "<span></span><span></span><span></span>";
    setBusy(true);
    try {
      const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, history }) });
      const data = await response.json();
      waiting.remove();
      if (!response.ok || !data.success) throw new Error(data.error || "The request could not be completed.");
      history.push({ role: "user", content: message }, { role: "assistant", content: data.response });
      history = history.slice(-20);
      addMessage("assistant", data.response);
    } catch (error) {
      waiting.remove();
      const friendly = error instanceof TypeError ? "Unable to connect. Check your connection and try again." : error.message;
      addMessage("assistant", friendly);
    } finally { setBusy(false); input.focus(); }
  });
  clearButton.addEventListener("click", () => {
    if (busy) return;
    history = [];
    messages.innerHTML = '<div id="welcome" class="welcome"><div class="welcome-icon" aria-hidden="true">✦</div><h1>Hello! How can I help you today?</h1><p>Ask anything and get intelligent answers powered by Gemini AI.</p></div>';
    input.focus();
  });
})();
