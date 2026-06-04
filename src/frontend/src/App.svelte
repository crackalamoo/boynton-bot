<script>
  import { onMount } from 'svelte';

  let messages = $state([]);
  let inputValue = $state('');
  let sending = $state(false);
  let textareaEl = $state(null);

  onMount(async () => {
    try {
      const res = await fetch('/api/history');
      if (res.ok) {
        const history = await res.json();
        messages = history.map((m) => ({ type: m.role, content: m.content }));
      }
    } catch (_) {
      // If history fetch fails, start with empty messages
    }
  });

  function autoResize(node) {
    function resize() {
      node.style.height = 'auto';
      node.style.height = node.scrollHeight + 'px';
    }
    node.addEventListener('input', resize);
    return {
      destroy() {
        node.removeEventListener('input', resize);
      },
    };
  }

  async function sendMessage() {
    const message = inputValue.trim();
    if (!message || sending) return;

    inputValue = '';
    // reset textarea height after clearing
    if (textareaEl) {
      textareaEl.style.height = 'auto';
    }
    sending = true;

    messages = [...messages, { type: 'user', content: message }];

    // Add an empty assistant message that we'll stream into
    const assistantIndex = messages.length;
    messages = [...messages, { type: 'assistant', content: '' }];

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });

      if (!res.ok || !res.body) {
        // Fallback: try to parse error JSON
        let errMsg = 'error: could not reach server';
        try {
          const data = await res.json();
          if (data.error) errMsg = `error: ${data.error}`;
        } catch (_) {}
        messages = messages.map((m, i) =>
          i === assistantIndex ? { ...m, content: errMsg } : m
        );
        sending = false;
        textareaEl?.focus();
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split on SSE frame boundaries
        const frames = buffer.split('\n\n');
        // Keep the last (possibly incomplete) fragment in the buffer
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
            messages = messages.map((m, i) =>
              i === assistantIndex ? { ...m, content: m.content + event.content } : m
            );
          } else if (event.type === 'done') {
            if (event.summarized) {
              // Insert the divider before the assistant message
              const before = messages.slice(0, assistantIndex);
              const after = messages.slice(assistantIndex);
              messages = [...before, { type: 'divider' }, ...after];
            }
          } else if (event.type === 'error') {
            messages = messages.map((m, i) =>
              i === assistantIndex ? { ...m, content: `error: ${event.message}` } : m
            );
          }
        }
      }
    } catch (e) {
      messages = messages.map((m, i) =>
        i === assistantIndex ? { ...m, content: 'error: could not reach server' } : m
      );
    }

    sending = false;
    textareaEl?.focus();
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  async function clearConversation() {
    await fetch('/api/clear', { method: 'POST' });
    messages = [];
  }
</script>

<div class="main">
  <article>
    <h1>boynton bot</h1>
    <hr />

    <div id="messages">
      {#each messages as msg}
        {#if msg.type === 'divider'}
          <div class="summary-notice">— conversation summarized —</div>
        {:else}
          <div class="msg {msg.type}">
            <div class="msg-label">{msg.type === 'user' ? 'you' : 'boynton bot'}</div>
            <div class="msg-content">{msg.content}</div>
          </div>
        {/if}
      {/each}
    </div>

    <div id="input-row">
      <textarea
        bind:this={textareaEl}
        bind:value={inputValue}
        placeholder="ask something..."
        rows="1"
        use:autoResize
        onkeydown={handleKeydown}
      ></textarea>
      <button id="send-btn" onclick={sendMessage} disabled={sending}>send</button>
    </div>
    <button id="clear-btn" onclick={clearConversation}>clear conversation</button>
  </article>
</div>

<style>
  #messages {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    margin-block-end: 2rem;
  }
  .msg {
    max-width: 85%;
  }
  .msg.user {
    align-self: flex-end;
    text-align: right;
  }
  .msg.assistant {
    align-self: flex-start;
  }
  .msg-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted-color);
    margin-block-end: 0.2rem;
  }
  .msg-content {
    line-height: 1.5;
    white-space: pre-wrap;
  }
  .summary-notice {
    font-size: 0.8rem;
    color: var(--muted-color);
    text-align: center;
    font-style: italic;
    margin-block: 0.5rem;
  }
  #input-row {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
  }
  #input-row textarea {
    flex: 1;
    font-family: inherit;
    font-size: 1rem;
    padding: 0.5rem;
    border: 1.5px solid var(--hr-color);
    border-radius: 4px;
    background: var(--bg-color);
    color: var(--text-color);
    resize: none;
    line-height: 1.5;
    min-height: 2.5rem;
    max-height: 10rem;
    overflow-y: auto;
  }
  #input-row textarea:focus {
    outline: none;
    border-color: var(--link-color);
  }
  #send-btn {
    white-space: nowrap;
  }
  #send-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  #clear-btn {
    font-size: 0.85rem;
    color: var(--muted-color);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    margin-block-start: 0.5rem;
  }
  #clear-btn:hover {
    color: var(--text-color);
  }
</style>
