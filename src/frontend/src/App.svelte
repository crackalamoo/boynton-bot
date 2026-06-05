<script>
  import { onMount, tick } from 'svelte';
  import MessageList from './components/MessageList.svelte';
  import ChatInput from './components/ChatInput.svelte';
  import { parseHistory } from './lib/messageHistory.js';

  const isMobile = typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches;

  let messages = $state([]);
  let sending = $state(false);

  async function scrollToBottom(behavior = 'instant') {
    await tick();
    window.scrollTo({ top: document.body.scrollHeight, behavior });
  }

  onMount(async () => {
    try {
      const res = await fetch('/api/history');
      if (res.ok) {
        messages = parseHistory(await res.json());
        scrollToBottom();
      }
    } catch (_) {}
  });

  async function sendMessage(message) {
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
          if (data.error) errMsg = `error: ${data.error}`;
        } catch (_) {}
        messages = messages.map((m, i) =>
          i === assistantIndex ? { ...m, parts: [{ kind: 'text', content: errMsg }] } : m
        );
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
          let event;
          try {
            event = JSON.parse(line.slice('data: '.length));
          } catch (_) {
            continue;
          }

          if (event.type === 'token') {
            messages = messages.map((m, i) => {
              if (i !== assistantIndex) return m;
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
            messages = messages.map((m, i) =>
              i === assistantIndex
                ? { ...m, parts: [...m.parts, { kind: 'tool_call', name: event.name, arguments: event.arguments ?? {}, result: null }] }
                : m
            );
            scrollToBottom();
          } else if (event.type === 'tool_result') {
            messages = messages.map((m, i) => {
              if (i !== assistantIndex) return m;
              const parts = [...m.parts];
              const pending = parts.findLastIndex((p) => p.kind === 'tool_call' && p.result === null);
              if (pending !== -1) parts[pending] = { ...parts[pending], result: event.content };
              return { ...m, parts };
            });
          } else if (event.type === 'done') {
            if (event.summarized) {
              const before = messages.slice(0, assistantIndex);
              const after = messages.slice(assistantIndex);
              messages = [...before, { type: 'divider' }, ...after];
            }
          } else if (event.type === 'error') {
            messages = messages.map((m, i) =>
              i === assistantIndex
                ? { ...m, parts: [...m.parts, { kind: 'text', content: `error: ${event.message}` }] }
                : m
            );
          }
        }
      }
    } catch (e) {
      messages = messages.map((m, i) =>
        i === assistantIndex
          ? { ...m, parts: [{ kind: 'text', content: `error: ${e?.message ?? 'could not reach server'}` }] }
          : m
      );
    }

    sending = false;
  }

  async function clearConversation() {
    await fetch('/api/clear', { method: 'POST' });
    messages = [];
  }
</script>

<div class="main">
  <article>
    <h1>Boynton Bot</h1>
    <hr />
    <MessageList {messages} />
    <ChatInput {sending} {isMobile} onsend={sendMessage} onclear={clearConversation} />
  </article>
</div>
