<script lang="ts">
  import type { ToolCallPart } from '../lib/types.js';

  let { part, showHidden = false }: { part: ToolCallPart; showHidden?: boolean } = $props();
</script>

<details class="tool-call" class:hidden-part={showHidden && part.hidden}>
  <summary class="tool-call-header">
    <span class="tool-call-status">{part.result === null ? 'Using' : 'Used'}</span>
    {part.name.replaceAll('_', ' ')}
  </summary>
  {#if part.result !== null}
    {#if part.arguments && Object.keys(part.arguments).length > 0}
      <pre class="tool-call-args">{JSON.stringify(part.arguments, null, 2)}</pre>
    {/if}
    <pre class="tool-call-result">{part.result}</pre>
  {:else}
    <div class="tool-call-running">running…</div>
  {/if}
</details>

<style>
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
    color: var(--muted-color);
  }

  .tool-call-args {
    margin: 0;
    padding: 0.35rem 0.6rem;
    font-size: 0.8rem;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--muted-color);
    border-top: 1px solid var(--button-border);
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

  .hidden-part {
    color: var(--muted-color);
    opacity: 0.7;
  }
</style>
