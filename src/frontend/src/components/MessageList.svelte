<script lang="ts">
  import Message from './Message.svelte';
  import type { Message as MessageType } from '../lib/types.js';

  let { messages }: { messages: MessageType[] } = $props();

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
</script>

<div id="messages">
  {#each messages as msg, i}
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
      <Message msg={msg} />
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
