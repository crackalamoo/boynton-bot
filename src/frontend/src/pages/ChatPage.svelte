<script lang="ts">
  import { onMount, tick } from 'svelte';
  import MessageList from '../components/MessageList.svelte';
  import ChatInput from '../components/ChatInput.svelte';
  import { parseHistory } from '../lib/messageHistory.js';
  import { navigate } from '../lib/router.svelte.js';
  import { uiPrefs } from '../lib/uiPrefs.svelte.js';
  import type { Message, SSEEvent } from '../lib/types.js';

  const isMobile = typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches;

  let messages = $state<Message[]>([]);
  let compacting = $state(false);
  let nextMsgId = 0;

  let oldestLoadedUserRowId = $state<number | null>(null);
  let hasMoreHistory = $state(false);
  let loadingOlderHistory = $state(false);
  let topSentinel = $state<HTMLDivElement | null>(null);

  async function scrollToBottom(behavior: ScrollBehavior = 'instant') {
    await tick();
    window.scrollTo({ top: document.body.scrollHeight, behavior });
  }

  function oldestUserRowId(history: { messages: { id?: number; role: string }[] }): number | null {
    const firstUser = history.messages.find((m) => m.role === 'user');
    return firstUser?.id ?? null;
  }

  async function loadHistory() {
    try {
      const res = await fetch('/api/history?include_hidden=true');
      if (res.ok) {
        const history = await res.json();
        messages = parseHistory(history);
        oldestLoadedUserRowId = oldestUserRowId(history);
        hasMoreHistory = history.has_more ?? false;
        scrollToBottom();
      }
    } catch (_) {}
  }

  async function loadOlderHistory() {
    if (loadingOlderHistory || !hasMoreHistory || oldestLoadedUserRowId === null) return;
    loadingOlderHistory = true;
    try {
      const res = await fetch(`/api/history?include_hidden=true&before_id=${oldestLoadedUserRowId}`);
      if (res.ok) {
        const history = await res.json();
        let olderMessages = parseHistory(history);
        // The divider can only ever belong once, at the seam between the last pre-cutoff
        // and first post-cutoff message. If the currently-loaded window already contains
        // it, an older page can only be entirely pre-cutoff (created_at/id are both
        // monotonic), so any divider parseHistory placed in it is a duplicate — drop it.
        if (messages.some((m) => m.type === 'divider')) {
          olderMessages = olderMessages.filter((m) => m.type !== 'divider');
        }
        const oldScrollHeight = document.body.scrollHeight;
        const oldScrollY = window.scrollY;
        messages = [...olderMessages, ...messages];
        oldestLoadedUserRowId = oldestUserRowId(history) ?? oldestLoadedUserRowId;
        hasMoreHistory = history.has_more ?? false;
        await tick();
        const newScrollHeight = document.body.scrollHeight;
        window.scrollTo(0, oldScrollY + (newScrollHeight - oldScrollHeight));
      }
    } catch (_) {
    } finally {
      loadingOlderHistory = false;
    }
  }

  onMount(loadHistory);

  onMount(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadOlderHistory();
      },
      { rootMargin: '200px 0px 0px 0px' }
    );
    if (topSentinel) observer.observe(topSentinel);
    return () => observer.disconnect();
  });

  async function sendMessage(message: string) {
    const id = nextMsgId++;
    messages = [...messages, { type: 'user', content: message, id, queued: true }];
    scrollToBottom();

    // lazily add the assistant bubble on first content event
    let assistantAdded = false;
    function ensureAssistant() {
      if (!assistantAdded) {
        messages = messages.map((m) => (m.type === 'user' && m.id === id ? { ...m, queued: false } : m));
        messages = [...messages, { type: 'assistant', parts: [], id }];
        assistantAdded = true;
      }
    }

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });

      if (!res.ok || !res.body) {
        let errMsg = 'error: could not reach server';
        try {
          const data = await res.json();
          if (data.detail) errMsg = `error: ${data.detail}`;
        } catch (_) {}
        ensureAssistant();
        messages = messages.map((m) => {
          if (m.type !== 'assistant' || m.id !== id) return m;
          return { ...m, parts: [{ kind: 'text' as const, content: errMsg }] };
        });
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith('data: ')) continue;
          let event: SSEEvent;
          try {
            event = JSON.parse(line.slice('data: '.length)) as SSEEvent;
          } catch (_) {
            continue;
          }

          if (event.type === 'queued') {
            // job is waiting in queue — user bubble stays muted, no assistant bubble yet
          } else if (event.type === 'token') {
            ensureAssistant();
            messages = messages.map((m) => {
              if (m.type !== 'assistant' || m.id !== id) return m;
              const parts = [...m.parts];
              const last = parts[parts.length - 1];
              if (last?.kind === 'text') {
                parts[parts.length - 1] = { ...last, content: last.content + event.content };
              } else {
                parts.push({ kind: 'text', content: event.content });
              }
              return { ...m, parts };
            });
            scrollToBottom();
          } else if (event.type === 'reasoning') {
            ensureAssistant();
            const text = event.summary ?? event.content ?? '';
            messages = messages.map((m) => {
              if (m.type !== 'assistant' || m.id !== id) return m;
              const parts = [...m.parts];
              const last = parts[parts.length - 1];
              if (last?.kind === 'reasoning') {
                parts[parts.length - 1] = { ...last, content: last.content + text };
              } else {
                parts.push({ kind: 'reasoning', content: text });
              }
              return { ...m, parts };
            });
            scrollToBottom();
          } else if (event.type === 'tool_call') {
            ensureAssistant();
            messages = messages.map((m) => {
              if (m.type !== 'assistant' || m.id !== id) return m;
              return { ...m, parts: [...m.parts, { kind: 'tool_call' as const, name: event.name, arguments: event.arguments ?? {}, result: null }] };
            });
            scrollToBottom();
          } else if (event.type === 'tool_result') {
            messages = messages.map((m) => {
              if (m.type !== 'assistant' || m.id !== id) return m;
              const parts = [...m.parts];
              const pending = parts.findLastIndex((p) => p.kind === 'tool_call' && p.result === null);
              if (pending !== -1) {
                const existing = parts[pending];
                if (existing.kind === 'tool_call') {
                  parts[pending] = { ...existing, result: event.content };
                }
              }
              return { ...m, parts };
            });
          } else if (event.type === 'done') {
            if (event.message_id !== undefined) {
              messages = messages.map((m) =>
                m.type === 'assistant' && m.id === id
                  ? { ...m, dbId: event.message_id, isPrimaryModel: event.is_primary_model ?? false }
                  : m
              );
            }
            if (event.summarized) {
              const idx = messages.findIndex((m) => m.type === 'assistant' && m.id === id);
              if (idx !== -1) {
                messages = [...messages.slice(0, idx), { type: 'divider' }, ...messages.slice(idx)];
              }
            }
          } else if (event.type === 'error') {
            ensureAssistant();
            messages = messages.map((m) => {
              if (m.type !== 'assistant' || m.id !== id) return m;
              return { ...m, parts: [...m.parts, { kind: 'text' as const, content: `error: ${event.message}` }] };
            });
          }
        }
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : 'could not reach server';
      ensureAssistant();
      messages = messages.map((m) => {
        if (m.type !== 'assistant' || m.id !== id) return m;
        return { ...m, parts: [{ kind: 'text' as const, content: `error: ${errMsg}` }] };
      });
    }
  }

  async function clearConversation() {
    await fetch('/api/clear', { method: 'POST' });
    messages = [];
    oldestLoadedUserRowId = null;
    hasMoreHistory = false;
  }

  async function compactConversation() {
    compacting = true;
    try {
      await fetch('/api/compact', { method: 'POST' });
      await loadHistory();
    } catch (_) {}
    compacting = false;
  }
</script>

<div class="main">
  <article>
    <div class="page-header">
      <div class="header-row">
        <h1>Boynton Bot</h1>
        <div class="header-actions">
          <button class="settings-icon-btn" onclick={() => navigate('/feedback')} aria-label="Feedback" title="Feedback">📝</button>
          <button class="settings-icon-btn" onclick={() => navigate('/settings')} aria-label="Settings" title="Settings">⚙</button>
        </div>
      </div>
      <hr />
    </div>
    <div bind:this={topSentinel}></div>
    <MessageList {messages} showHidden={uiPrefs.showHidden} />
    <ChatInput {compacting} {isMobile} onsend={sendMessage} onclear={clearConversation} oncompact={compactConversation} />
  </article>
</div>

<style>
  /* Sticky like #input-area, so the gear icon stays reachable without scrolling to
     the top of a long conversation instead of just scrolling away with the messages. */
  .page-header {
    position: sticky;
    top: 0;
    background: var(--bg-color);
    z-index: 1;
    padding-block-start: 0.5rem;
  }

  .header-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 0.15rem;
  }

  .settings-icon-btn {
    background: none;
    border: none;
    color: var(--muted-color);
    cursor: pointer;
    font-size: 1.3rem;
    line-height: 1;
    padding: 0.25rem;
  }

  .settings-icon-btn:hover {
    color: var(--text-color);
  }

  /* The browser's own scroll anchoring would otherwise fight the manual scrollHeight-delta
     correction in loadOlderHistory, since the scroll container here is the document, not a
     bounded div. Disabling it makes the delta the only thing adjusting scroll position. */
  :global(html) {
    overflow-anchor: none;
  }
</style>
