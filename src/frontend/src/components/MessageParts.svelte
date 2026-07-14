<script lang="ts">
  import { marked } from 'marked';
  import ToolCall from './ToolCall.svelte';
  import type { Part } from '../lib/types.js';

  marked.setOptions({ breaks: true });

  let { parts }: { parts: Part[] } = $props();
</script>

{#each parts as part}
  {#if part.kind === 'text'}
    <div class="msg-content markdown">{@html marked(part.content)}</div>
  {:else if part.kind === 'tool_call'}
    <ToolCall {part} />
  {:else if part.kind === 'reasoning'}
    <div class="thinking reasoning-trace">{part.content}</div>
  {/if}
{/each}

<style>
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

  .reasoning-trace {
    white-space: pre-wrap;
  }
</style>
