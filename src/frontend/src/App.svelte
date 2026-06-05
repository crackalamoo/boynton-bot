<script>
  import { onMount, tick } from 'svelte';
  import { marked } from 'marked';

  marked.setOptions({ breaks: true });

  let messages = $state([]);
  let inputValue = $state('');
  let sending = $state(false);
  let textareaEl = $state(null);
  let messagesEl = $state(null);
  const isMobile = typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches;

  async function scrollToBottom(behavior = 'instant') {
    await tick();
    window.scrollTo({ top: document.body.scrollHeight, behavior });
  }

  onMount(async () => {
    try {
      const res = await fetch('/api/history');
      if (res.ok) {
        const history = await res.json();
        const mapped = history.messages.map((m) => ({ type: m.role, content: m.content }));
        if (history.summary_created_at) {
          const cutoff = new Date(history.summary_created_at);
          // Find the last message whose created_at is <= summary_created_at
          let insertAfter = -1;
          for (let i = 0; i < history.messages.length; i++) {
            if (new Date(history.messages[i].created_at) <= cutoff) {
              insertAfter = i;
            }
          }
          if (insertAfter >= 0) {
            mapped.splice(insertAfter + 1, 0, { type: 'divider' });
          }
        }
        messages = mapped;
        scrollToBottom();
      }
    } catch (_) {}
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
    if (textareaEl) textareaEl.style.height = 'auto';
    sending = true;

    messages = [...messages, { type: 'user', content: message }];

    const assistantIndex = messages.length;
    messages = [...messages, { type: 'assistant', content: '', toolCalls: [] }];
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

          if (event.type === 'tool_call') {
            messages = messages.map((m, i) =>
              i === assistantIndex
                ? { ...m, toolCalls: [...m.toolCalls, { name: event.name, result: null }] }
                : m
            );
            scrollToBottom();
          } else if (event.type === 'tool_result') {
            messages = messages.map((m, i) => {
              if (i !== assistantIndex) return m;
              const toolCalls = [...m.toolCalls];
              const pending = toolCalls.findLastIndex((tc) => tc.result === null);
              if (pending !== -1) toolCalls[pending] = { ...toolCalls[pending], result: event.content };
              return { ...m, toolCalls };
            });
          } else if (event.type === 'token') {
            messages = messages.map((m, i) =>
              i === assistantIndex ? { ...m, content: m.content + event.content } : m
            );
            scrollToBottom();
          } else if (event.type === 'done') {
            if (event.summarized) {
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
        i === assistantIndex ? { ...m, content: `error: ${e?.message ?? 'could not reach server'}` } : m
      );
    }

    sending = false;
    if (isMobile) {
      textareaEl?.blur();
    } else {
      textareaEl?.focus();
    }
  }

  function handleKeydown(e) {
    if (!isMobile && e.key === 'Enter' && !e.shiftKey) {
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
    <h1>Boynton Bot</h1>
    <hr />

    <div id="messages" bind:this={messagesEl}>
      {#each messages as msg}
        {#if msg.type === 'divider'}
          <div class="summary-notice">— conversation summarized —</div>
        {:else}
          <div class="msg {msg.type}">
            <div class="msg-label">{msg.type === 'user' ? 'you' : 'boynton bot'}</div>
            {#if msg.type === 'assistant'}
              {#if msg.toolCalls && msg.toolCalls.length > 0}
                <div class="tool-calls">
                  {#each msg.toolCalls as tc}
                    <details class="tool-call">
                      <summary class="tool-call-header">
                        <span class="tool-call-status">{tc.result === null ? 'Using' : 'Used'}</span>
                        {tc.name.replaceAll('_', ' ')}
                      </summary>
                      {#if tc.result !== null}
                        <pre class="tool-call-result">{tc.result}</pre>
                      {:else}
                        <div class="tool-call-running">running…</div>
                      {/if}
                    </details>
                  {/each}
                </div>
              {/if}
              {#if !msg.content && (!msg.toolCalls || msg.toolCalls.length === 0 || msg.toolCalls.every((tc) => tc.result !== null))}
                <div class="thinking">thinking…</div>
              {/if}
              {#if msg.content}
                <div class="msg-content markdown">{@html marked(msg.content)}</div>
              {/if}
            {:else}
              <div class="msg-content">{msg.content}</div>
            {/if}
          </div>
        {/if}
      {/each}
    </div>

    <div id="input-area">
      <div id="input-box">
        <textarea
          bind:this={textareaEl}
          bind:value={inputValue}
          placeholder="ask something..."
          rows="1"
          use:autoResize
          onkeydown={handleKeydown}
        ></textarea>
        <div id="input-actions">
          <button id="send-btn" onclick={sendMessage} disabled={sending} aria-label="Send">↑</button>
        </div>
      </div>
      <button id="clear-btn" onclick={clearConversation}>clear conversation</button>
    </div>
  </article>
</div>

<style>
  #messages {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    margin-block-end: 1rem;
    padding-block-end: 0.5rem;
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
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-color);
    margin-block-end: 0.25rem;
  }
  .msg-content {
    line-height: 1.6;
    white-space: pre-wrap;
  }
  .msg-content.markdown {
    white-space: normal;
  }
  .msg-content.markdown :global(p) { margin-block: 0.4rem; }
  .msg-content.markdown :global(p:first-child) { margin-block-start: 0; }
  .msg-content.markdown :global(p:last-child) { margin-block-end: 0; }
  .msg-content.markdown :global(ul),
  .msg-content.markdown :global(ol) { padding-inline-start: 1.4rem; margin-block: 0.4rem; }
  .msg-content.markdown :global(li) { margin-block: 0.15rem; }
  .msg-content.markdown :global(code) {
    font-family: monospace;
    font-size: 0.9em;
    background: var(--button-bg);
    border: 1px solid var(--button-border);
    border-radius: 3px;
    padding: 0.1em 0.35em;
  }
  .msg-content.markdown :global(pre) {
    background: var(--button-bg);
    border: 1px solid var(--button-border);
    border-radius: 6px;
    padding: 0.75rem 1rem;
    overflow-x: auto;
    margin-block: 0.5rem;
  }
  .msg-content.markdown :global(pre code) {
    background: none;
    border: none;
    padding: 0;
    font-size: 0.85em;
  }
  .msg-content.markdown :global(h1),
  .msg-content.markdown :global(h2),
  .msg-content.markdown :global(h3) { margin-block: 0.6rem 0.3rem; }
  .msg-content.markdown :global(blockquote) {
    border-inline-start: 3px solid var(--hr-color);
    margin-inline-start: 0;
    padding-inline-start: 0.75rem;
    color: var(--muted-color);
  }

  .thinking {
    font-size: 0.9rem;
    color: var(--muted-color);
    font-style: italic;
  }

  .tool-calls {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-block-end: 0.5rem;
  }

  .tool-call {
    border: 1px solid var(--button-border);
    border-radius: 6px;
    font-size: 0.85rem;
    overflow: hidden;
  }

  .tool-call-header {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.6rem;
    cursor: pointer;
    user-select: none;
    background: var(--button-bg);
    list-style: none;
  }

  .tool-call-header::-webkit-details-marker { display: none; }

  .tool-call-status {
    font-size: 0.75rem;
    color: var(--muted-color);
  }

  .tool-call-result {
    margin: 0;
    padding: 0.5rem 0.6rem;
    font-size: 0.8rem;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 12rem;
    overflow-y: auto;
    border-top: 1px solid var(--button-border);
  }

  .tool-call-running {
    padding: 0.35rem 0.6rem;
    font-size: 0.8rem;
    color: var(--muted-color);
    font-style: italic;
    border-top: 1px solid var(--button-border);
  }

  .summary-notice {
    font-size: 0.8rem;
    color: var(--muted-color);
    text-align: center;
    font-style: italic;
    margin-block: 0.25rem;
  }

  #input-area {
    position: sticky;
    bottom: 0;
    background: var(--bg-color);
    padding-block: 1rem 1.5rem;
  }

  #input-box {
    display: flex;
    flex-direction: column;
    border: 1.5px solid var(--hr-color);
    border-radius: 8px;
    background: var(--bg-color);
    transition: border-color 0.15s;
    padding: 0.6rem 0.5rem 0.4rem 0.65rem;
    gap: 0.4rem;
  }

  #input-box:focus-within {
    border-color: var(--link-color);
  }

  #input-box textarea {
    width: 100%;
    font-family: inherit;
    font-size: 1rem;
    background: transparent;
    color: var(--text-color);
    border: none;
    outline: none;
    resize: none;
    line-height: 1.5;
    min-height: 1.5rem;
    max-height: 10rem;
    overflow-y: auto;
    padding: 0;
  }

  #input-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
  }

  #send-btn {
    width: 2rem;
    height: 2rem;
    min-width: 2rem;
    aspect-ratio: 1;
    border-radius: 50%;
    border: none;
    background: linear-gradient(135deg, #52A2F6, #3282e6);
    color: white;
    font-size: 1rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: opacity 0.15s;
    line-height: 1;
    padding: 0;
  }

  #send-btn:hover:not(:disabled) {
    opacity: 0.85;
  }

  #send-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }

  #clear-btn {
    font-size: 0.8rem;
    color: var(--muted-color);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    margin-block-start: 0.4rem;
    display: block;
  }

  #clear-btn:hover {
    color: var(--text-color);
  }
</style>
