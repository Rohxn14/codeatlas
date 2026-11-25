// CodeAtlas web app: the chat panel. Everything else works without JavaScript, and so does
// asking (the Ask button is a link to a page). No library, no build step.
//
// The server renders every message; this file only opens and closes the panel, sends a
// question, and asks for the conversation again while an answer is being made. Nothing the
// model writes is turned into HTML here.

(() => {
  "use strict";
  const root = document.documentElement;
  const OPEN = "codeatlas-chat-open";

  function remembered() {
    try { return localStorage.getItem(OPEN) === "1"; } catch { return false; }
  }
  function remember(open) {
    try { localStorage.setItem(OPEN, open ? "1" : "0"); } catch { /* private window */ }
  }

  // Before the page is drawn, so an open panel does not slide in on every page.
  if (remembered()) root.classList.add("chat-open");

  document.addEventListener("DOMContentLoaded", () => {
    const chat = document.getElementById("chat");
    if (!chat) { root.classList.remove("chat-open"); return; }
    const url = chat.dataset.url;
    const log = chat.querySelector(".chat-log");
    const form = chat.querySelector(".chat-form");
    const box = form.querySelector("textarea");
    let timer = 0;

    function setOpen(open) {
      root.classList.toggle("chat-open", open);
      remember(open);
      if (open) { load(true); box.focus(); } else { clearTimeout(timer); }
    }

    // Put in the messages that changed and leave the others alone, so opened details and
    // the reader's place survive an update.
    function show(html, jump) {
      const next = new DOMParser().parseFromString(html, "text/html").body.firstElementChild;
      if (!next) return;
      const low = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      const seen = new Set();
      for (const item of [...next.children]) {
        seen.add(item.id);
        const old = document.getElementById(item.id);
        if (!old || old.parentElement !== log) log.append(item);
        else if (old.outerHTML !== item.outerHTML && old.dataset.state !== "done") old.replaceWith(item);
      }
      for (const old of [...log.children]) if (!seen.has(old.id)) old.remove();
      if (jump || low) log.scrollTop = log.scrollHeight;
      clearTimeout(timer);
      if (next.dataset.active === "1" && root.classList.contains("chat-open")) {
        timer = setTimeout(() => load(false), 1500);
      }
    }

    async function load(jump) {
      try {
        const reply = await fetch(url, { headers: { "X-Requested-With": "chat" } });
        if (reply.ok) show(await reply.text(), jump);
      } catch {
        timer = setTimeout(() => load(false), 4000);  // the app is restarting
      }
    }

    async function post(to, fields) {
      const reply = await fetch(to, { method: "POST", body: new URLSearchParams(fields) });
      show(await reply.text(), true);
      return reply.ok;
    }

    function grow() {
      box.style.height = "auto";
      box.style.height = Math.min(box.scrollHeight, 160) + "px";
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const question = box.value.trim();
      if (!question) return;
      box.value = "";
      grow();
      if (!await post(url, { question })) { box.value = question; grow(); }
    });
    box.addEventListener("input", grow);
    box.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    log.addEventListener("submit", (event) => {  // Stop
      event.preventDefault();
      post(event.target.action, {});
    });
    for (const opener of document.querySelectorAll("[data-chat-open]")) {
      opener.addEventListener("click", (event) => {
        if (event.ctrlKey || event.metaKey || event.shiftKey) return;  // open the page instead
        event.preventDefault();
        setOpen(true);
      });
    }
    chat.querySelector("[data-chat-close]").addEventListener("click", () => setOpen(false));
    chat.addEventListener("keydown", (event) => { if (event.key === "Escape") setOpen(false); });
    if (root.classList.contains("chat-open")) load(true);
  });
})();
