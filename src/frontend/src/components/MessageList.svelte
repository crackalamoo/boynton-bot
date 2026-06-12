<script lang="ts">
  import Message from './Message.svelte';
  import type { Message as MessageType } from '../lib/types.js';

  let { messages, showHidden }: { messages: MessageType[]; showHidden: boolean } = $props();

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
  {#each visibleMessages(messages) as msg}
    {#if msg.type === 'divider'}
      <div class="summary-notice">— conversation summarized —</div>
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
  }
</style>
