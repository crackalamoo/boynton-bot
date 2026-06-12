<script lang="ts">
  import { onMount, tick } from 'svelte';
  import MessageList from '../components/MessageList.svelte';
  import ChatInput from '../components/ChatInput.svelte';
  import { parseHistory } from '../lib/messageHistory.js';
  import { navigate } from '../lib/router.svelte.js';
  import type { Message, SSEEvent } from '../lib/types.js';

  const isMobile = typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches;

  let messages = $state<Message[]>([]);
  let sending = $state(false);
  let compacting = $state(false);
  let showHidden = $state(false);

  async function scrollToBottom(behavior: ScrollBehavior = 'instant') {
    await tick();
    window.scrollTo({ top: document.body.scrollHeight, behavior });
  }

  async function loadHistory() {
    try {
      const res = await fetch('/api/history?include_hidden=true');
      if (res.ok) {
        messages = parseHistory(await res.json());
        scrollToBottom();
      }
    } catch (_) {}
  }

  onMount(loadHistory);

  async function sendMessage(message: string) {
    sending = true;
    messages = [...messages, { type: 'user', content: message }];
    const assistantIndex = messages.length;
    messages = [...messages, { type: 'assistant', parts: [] }];
    scrollToBottom();

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
        messages = messages.map((m, i) => {
          if (i !== assistantIndex || m.type !== 'assistant') return m;
          return { ...m, parts: [{ kind: 'text' as const, content: errMsg }] };
        });
        sending = false;
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

          if (event.type === 'token') {
            messages = messages.map((m, i) => {
              if (i !== assistantIndex || m.type !== 'assistant') return m;
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
          } else if (event.type === 'tool_call') {
            messages = messages.map((m, i) => {
              if (i !== assistantIndex || m.type !== 'assistant') return m;
              return { ...m, parts: [...m.parts, { kind: 'tool_call' as const, name: event.name, arguments: event.arguments ?? {}, result: null }] };
            });
            scrollToBottom();
          } else if (event.type === 'tool_result') {
            messages = messages.map((m, i) => {
              if (i !== assistantIndex || m.type !== 'assistant') return m;
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
            if (event.summarized) {
              const before = messages.slice(0, assistantIndex);
              const after = messages.slice(assistantIndex);
              messages = [...before, { type: 'divider' }, ...after];
            }
          } else if (event.type === 'error') {
            messages = messages.map((m, i) => {
              if (i !== assistantIndex || m.type !== 'assistant') return m;
              return { ...m, parts: [...m.parts, { kind: 'text' as const, content: `error: ${event.message}` }] };
            });
          }
        }
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : 'could not reach server';
      messages = messages.map((m, i) => {
        if (i !== assistantIndex || m.type !== 'assistant') return m;
        return { ...m, parts: [{ kind: 'text' as const, content: `error: ${errMsg}` }] };
      });
    }

    sending = false;
  }

  async function clearConversation() {
    await fetch('/api/clear', { method: 'POST' });
    messages = [];
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
    <h1>Boynton Bot</h1>
    <hr />
    <MessageList {messages} {showHidden} />
    <ChatInput {sending} {compacting} {showHidden} {isMobile} onsend={sendMessage} onclear={clearConversation} oncompact={compactConversation} onsettings={() => navigate('/settings')} ontogglehidden={() => showHidden = !showHidden} />
  </article>
</div>
