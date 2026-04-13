/**
 * Kindr About-page assistant — calls POST /api/ai/chat (Google Gemini server-side).
 * Requires <meta name="csrf-token"> from base layout.
 */
(function () {
  function csrfHeaders() {
    const t = document.querySelector('meta[name="csrf-token"]');
    const h = { "Content-Type": "application/json" };
    const token = t && t.getAttribute("content");
    if (token) {
      h["X-CSRFToken"] = token;
      h["X-CSRF-Token"] = token;
    }
    return h;
  }

  async function postChat(apiBase, body) {
    const res = await fetch(apiBase, {
      method: "POST",
      credentials: "include",
      headers: csrfHeaders(),
      body: JSON.stringify(body),
    });
    const text = await res.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { message: text.slice(0, 200) || res.statusText };
    }
    return { res, data };
  }

  function appendBubble(container, role, text) {
    const wrap = document.createElement("div");
    wrap.className = "kindr-ai-msg kindr-ai-msg--" + role;
    const inner = document.createElement("div");
    inner.className = "kindr-ai-msg-inner";
    inner.textContent = text;
    wrap.appendChild(inner);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  function appendTyping(container) {
    const wrap = document.createElement("div");
    wrap.className = "kindr-ai-msg kindr-ai-msg--model kindr-ai-typing";
    wrap.innerHTML =
      '<div class="kindr-ai-msg-inner" aria-hidden="true"><span class="kindr-ai-dot"></span><span class="kindr-ai-dot"></span><span class="kindr-ai-dot"></span></div>';
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
    return wrap;
  }

  function mount(selector, opts) {
    const root = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (!root) return;
    const apiBase = (opts && opts.apiBase) || "/api/ai/chat";
    const context = (opts && opts.context) || "";

    root.innerHTML = "";
    root.classList.add("kindr-ai-chat");

    const msgs = document.createElement("div");
    msgs.className = "kindr-ai-messages";
    msgs.setAttribute("aria-live", "polite");

    const errEl = document.createElement("p");
    errEl.className = "kindr-ai-err";
    errEl.hidden = true;

    const form = document.createElement("form");
    form.className = "kindr-ai-form";
    const ta = document.createElement("textarea");
    ta.className = "kindr-ai-input";
    ta.rows = 3;
    ta.placeholder = "Ask about Kindr, fundraising, or how the platform works…";
    ta.setAttribute("aria-label", "Message to Kindr assistant");

    const btn = document.createElement("button");
    btn.type = "submit";
    btn.className = "btn btn-primary kindr-ai-send";
    btn.textContent = "Send";

    let history = [];

    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      const text = ta.value.trim();
      if (!text) return;
      errEl.hidden = true;
      btn.disabled = true;
      appendBubble(msgs, "user", text);
      ta.value = "";
      const typing = appendTyping(msgs);
      const { res, data } = await postChat(apiBase, {
        message: text,
        history: history,
        context: context,
      });
      typing.remove();
      btn.disabled = false;
      if (!res.ok) {
        var friendly =
          res.status === 503 || res.status === 502
            ? "We couldn’t reach the assistant just now. Please try again in a little while."
            : data.message || "Something went wrong. Please try again.";
        errEl.textContent = friendly;
        errEl.hidden = false;
        return;
      }
      const reply = (data.reply || "").trim();
      if (!reply) {
        errEl.textContent = "Empty reply. Try again.";
        errEl.hidden = false;
        return;
      }
      history.push({ role: "user", text: text });
      history.push({ role: "model", text: reply });
      if (history.length > 24) history = history.slice(-24);
      appendBubble(msgs, "model", reply);
      msgs.scrollTop = msgs.scrollHeight;
    });

    form.appendChild(ta);
    form.appendChild(btn);
    root.appendChild(msgs);
    root.appendChild(errEl);
    root.appendChild(form);

    appendBubble(
      msgs,
      "model",
      "Hi! I’m Kindr’s assistant. Ask me how fundraising works, what makes a strong campaign, or how to give safely.",
    );
  }

  window.kindrAI = { mount: mount };
})();
