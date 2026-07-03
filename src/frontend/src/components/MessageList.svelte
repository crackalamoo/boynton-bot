<script lang="ts">
  import Message from './Message.svelte';
  import type { Message as MessageType } from '../lib/types.js';

  let { messages, showHidden }: { messages: MessageType[]; showHidden: boolean } = $props();

  let expandedDividers: Set<string> = $state(new Set());

  function dividerKey(msg: MessageType, index: number): string {
    return msg.type === 'divider' && msg.key !== undefined ? msg.key : `idx-${index}`;
  }

  function toggleDivider(key: string) {
    if (expandedDividers.has(key)) {
      expandedDividers.delete(key);
    } else {
      expandedDividers.add(key);
    }
    expandedDividers = new Set(expandedDividers);
  }

  function visibleMessages(msgs: MessageType[]): MessageType[] {
    if (showHidden) return msgs;
    return msgs.filter((msg) => {
      if (msg.type !== 'assistant') return true;
      const originalParts = msg.parts;
      if (originalParts.length === 0) return true;
      const filteredParts = originalParts.filter((part) => !part.hidden);
      return !(originalParts.length > 0 && filteredParts.length === 0);
    });
  }

  function visibleParts(msg: MessageType): MessageType {
    if (showHidden || msg.type !== 'assistant') return msg;
    return { ...msg, parts: msg.parts.filter((part) => !part.hidden) };
  }
</script>

<div id="messages">
  {#each visibleMessages(messages) as msg, i}
    {#if msg.type === 'divider'}
      {@const key = dividerKey(msg, i)}
      <div
        class="summary-notice"
        role="button"
        tabindex="0"
        onclick={() => toggleDivider(key)}
        onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && toggleDivider(key)}
      >
        — conversation summarized —
      </div>
      {#if expandedDividers.has(key) && msg.summary}
        <div class="summary-text">{msg.summary}</div>
      {/if}
    {:else}
      <Message msg={visibleParts(msg)} {showHidden} />
    {/if}
  {/each}
</div>

<style>
  #messages {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    margin-block-end: 1rem;
    padding-block-end: 0.5rem;
  }

  .summary-notice {
    font-size: 0.8rem;
    color: var(--muted-color);
    text-align: center;
    font-style: italic;
    margin-block: 0.25rem;
    cursor: pointer;
  }

  .summary-notice:hover {
    color: var(--text-color);
  }

  .summary-text {
    font-size: 0.8rem;
    color: var(--muted-color);
    white-space: pre-wrap;
    margin-block: 0.25rem;
    padding: 0.5rem 0.75rem;
    border-radius: 0.5rem;
    background: var(--button-bg);
  }
</style>
