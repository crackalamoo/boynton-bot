<script lang="ts">
  import Message from './Message.svelte';
  import type { Message as MessageType } from '../lib/types.js';

  let { messages }: { messages: MessageType[] } = $props();
</script>

<div id="messages">
  {#each messages as msg}
    {#if msg.type === 'divider'}
      <div class="summary-notice">— conversation summarized —</div>
    {:else}
      <Message {msg} />
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
