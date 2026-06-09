<script lang="ts">
  let { sending, compacting, onsend, onclear, oncompact, isMobile }: {
    sending: boolean;
    compacting: boolean;
    onsend: (message: string) => Promise<void>;
    onclear: () => void;
    oncompact: () => Promise<void>;
    isMobile: boolean;
  } = $props();

  let inputValue = $state('');
  let textareaEl = $state<HTMLTextAreaElement | null>(null);

  function autoResize(node: HTMLTextAreaElement) {
    function resize() {
      node.style.height = 'auto';
      node.style.height = node.scrollHeight + 'px';
    }
    node.addEventListener('input', resize);
    return { destroy() { node.removeEventListener('input', resize); } };
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!isMobile && e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  async function submit() {
    const message = inputValue.trim();
    if (!message || sending) return;
    inputValue = '';
    if (textareaEl) textareaEl.style.height = 'auto';
    await onsend(message);
    if (isMobile) {
      textareaEl?.blur();
    } else {
      textareaEl?.focus();
    }
  }
</script>

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
      <button id="send-btn" onclick={submit} disabled={sending} aria-label="Send">↑</button>
    </div>
  </div>
  <button id="clear-btn" onclick={onclear}>clear conversation</button>
  <button id="compact-btn" onclick={oncompact} disabled={compacting}>{compacting ? 'compacting...' : 'compact conversation'}</button>
</div>

<style>
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

  #compact-btn {
    font-size: 0.8rem;
    color: var(--muted-color);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    margin-block-start: 0.2rem;
    display: block;
  }

  #compact-btn:hover:not(:disabled) {
    color: var(--text-color);
  }

  #compact-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
