<script lang="ts">
  import { onMount } from 'svelte';
  import { navigate } from '../lib/router.svelte.js';

  const SECRET_PLACEHOLDER = '__SET__';

  type FormState = {
    OPENAI_API_KEY: string;
    LLM_BASE_URL: string;
    LLM_MODEL: string;
    MEMORY_DIR: string;
    HEARTBEAT_CHANNEL: string;
    HEARTBEAT_INTERVAL_MINUTES: string;
    HEARTBEAT_TIMEOUT_SECONDS: string;
    HEARTBEAT_MAX_TOKENS: string;
    HEARTBEAT_ACK_MAX_CHARS: string;
    EMAIL_ADDRESS: string;
    EMAIL_PASSWORD: string;
    EMAIL_SMTP_HOST: string;
    EMAIL_SMTP_PORT: string;
    EMAIL_RECIPIENT: string;
  };

  const SECRET_KEYS: (keyof FormState)[] = ['OPENAI_API_KEY', 'EMAIL_PASSWORD'];

  function emptyForm(): FormState {
    return {
      OPENAI_API_KEY: '',
      LLM_BASE_URL: '',
      LLM_MODEL: '',
      MEMORY_DIR: '',
      HEARTBEAT_CHANNEL: '',
      HEARTBEAT_INTERVAL_MINUTES: '',
      HEARTBEAT_TIMEOUT_SECONDS: '',
      HEARTBEAT_MAX_TOKENS: '',
      HEARTBEAT_ACK_MAX_CHARS: '',
      EMAIL_ADDRESS: '',
      EMAIL_PASSWORD: '',
      EMAIL_SMTP_HOST: '',
      EMAIL_SMTP_PORT: '',
      EMAIL_RECIPIENT: '',
    };
  }

  let form = $state<FormState>(emptyForm());
  // Tracks whether each secret field currently shows the "(configured)" placeholder
  // state rather than a value the user has typed.
  let secretConfigured = $state<Record<string, boolean>>({});
  // Tracks whether the user has edited a secret field since load.
  let secretEdited = $state<Record<string, boolean>>({});

  let loading = $state(true);
  let saving = $state(false);
  let restarting = $state(false);
  let message = $state('');

  async function loadSettings() {
    loading = true;
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        const next = emptyForm();
        const configured: Record<string, boolean> = {};
        const edited: Record<string, boolean> = {};
        for (const key of Object.keys(next) as (keyof FormState)[]) {
          const value = data[key] ?? '';
          if (SECRET_KEYS.includes(key)) {
            configured[key] = value === SECRET_PLACEHOLDER;
            edited[key] = false;
            next[key] = '';
          } else {
            next[key] = value;
          }
        }
        form = next;
        secretConfigured = configured;
        secretEdited = edited;
      }
    } catch (_) {
      message = 'error: could not load settings';
    }
    loading = false;
  }

  onMount(loadSettings);

  function onSecretInput(key: keyof FormState) {
    secretEdited = { ...secretEdited, [key]: true };
  }

  function buildPayload(): Record<string, string> {
    const payload: Record<string, string> = {};
    for (const key of Object.keys(form) as (keyof FormState)[]) {
      if (SECRET_KEYS.includes(key)) {
        if (!secretEdited[key]) {
          // Untouched: preserve existing secret (if any) without sending it.
          payload[key] = secretConfigured[key] ? SECRET_PLACEHOLDER : '';
        } else {
          // User typed something (possibly cleared it on purpose).
          payload[key] = form[key];
        }
      } else {
        payload[key] = form[key];
      }
    }
    return payload;
  }

  async function saveSettings(): Promise<boolean> {
    saving = true;
    message = '';
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      });
      if (!res.ok) {
        message = 'error: could not save settings';
        saving = false;
        return false;
      }
      saving = false;
      return true;
    } catch (_) {
      message = 'error: could not reach server';
      saving = false;
      return false;
    }
  }

  async function onSave() {
    const ok = await saveSettings();
    if (ok) {
      message = 'Settings saved. Restart to apply changes.';
      await loadSettings();
    }
  }

  async function onSaveAndRestart() {
    const ok = await saveSettings();
    if (!ok) return;
    restarting = true;
    message = 'Restarting... reload in a few seconds.';
    try {
      await fetch('/api/restart', { method: 'POST' });
    } catch (_) {
      // Expected: the server may die mid-response.
    }
    setTimeout(() => {
      window.location.reload();
    }, 5000);
  }
</script>

<div class="main">
  <article>
    <div class="header-row">
      <h1>Settings</h1>
      <button class="link-btn" onclick={() => navigate('/chat')}>back to chat</button>
    </div>
    <hr />

    {#if loading}
      <p class="muted">loading settings…</p>
    {:else}
      <form onsubmit={(e) => { e.preventDefault(); onSave(); }}>
        <section>
          <h2>LLM</h2>
          <label>
            <span>OpenAI-compatible API key</span>
            <input
              type="password"
              placeholder={secretConfigured.OPENAI_API_KEY ? '(configured — leave blank to keep)' : ''}
              bind:value={form.OPENAI_API_KEY}
              oninput={() => onSecretInput('OPENAI_API_KEY')}
              autocomplete="off"
            />
          </label>
          <label>
            <span>LLM base URL</span>
            <input type="text" bind:value={form.LLM_BASE_URL} autocomplete="off" />
          </label>
          <label>
            <span>LLM model</span>
            <input type="text" bind:value={form.LLM_MODEL} autocomplete="off" />
          </label>
        </section>

        <section>
          <h2>Memory</h2>
          <label>
            <span>Memory directory</span>
            <input type="text" bind:value={form.MEMORY_DIR} autocomplete="off" />
          </label>
        </section>

        <section>
          <h2>Heartbeat</h2>
          <label>
            <span>Channel</span>
            <input type="text" bind:value={form.HEARTBEAT_CHANNEL} autocomplete="off" />
          </label>
          <label>
            <span>Interval (minutes)</span>
            <input type="text" bind:value={form.HEARTBEAT_INTERVAL_MINUTES} autocomplete="off" />
          </label>
          <label>
            <span>Timeout (seconds)</span>
            <input type="text" bind:value={form.HEARTBEAT_TIMEOUT_SECONDS} autocomplete="off" />
          </label>
          <label>
            <span>Max tokens</span>
            <input type="text" bind:value={form.HEARTBEAT_MAX_TOKENS} autocomplete="off" />
          </label>
          <label>
            <span>Ack max chars</span>
            <input type="text" bind:value={form.HEARTBEAT_ACK_MAX_CHARS} autocomplete="off" />
          </label>
        </section>

        <section>
          <h2>Email</h2>
          <label>
            <span>From address</span>
            <input type="text" bind:value={form.EMAIL_ADDRESS} autocomplete="off" />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              placeholder={secretConfigured.EMAIL_PASSWORD ? '(configured — leave blank to keep)' : ''}
              bind:value={form.EMAIL_PASSWORD}
              oninput={() => onSecretInput('EMAIL_PASSWORD')}
              autocomplete="off"
            />
          </label>
          <label>
            <span>SMTP host</span>
            <input type="text" bind:value={form.EMAIL_SMTP_HOST} autocomplete="off" />
          </label>
          <label>
            <span>SMTP port</span>
            <input type="text" bind:value={form.EMAIL_SMTP_PORT} autocomplete="off" />
          </label>
          <label>
            <span>Recipient</span>
            <input type="text" bind:value={form.EMAIL_RECIPIENT} autocomplete="off" />
          </label>
        </section>

        {#if message}
          <p class="message">{message}</p>
        {/if}

        <div class="actions">
          <button type="submit" disabled={saving || restarting}>
            {saving ? 'saving...' : 'save'}
          </button>
          <button type="button" onclick={onSaveAndRestart} disabled={saving || restarting}>
            {restarting ? 'restarting...' : 'save & restart'}
          </button>
        </div>
      </form>
    {/if}
  </article>
</div>

<style>
  .header-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }

  .link-btn {
    font-size: 0.8rem;
    color: var(--muted-color);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
  }

  .link-btn:hover {
    color: var(--text-color);
  }

  section {
    margin-block: 1.25rem;
  }

  section h2 {
    font-size: 0.95rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-color);
    margin-block-end: 0.6rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin-block-end: 0.75rem;
    font-size: 0.9rem;
  }

  label span {
    color: var(--muted-color);
    font-size: 0.8rem;
  }

  input {
    font-family: inherit;
    font-size: 1rem;
    color: var(--text-color);
    background: var(--bg-color);
    border: 1.5px solid var(--hr-color);
    border-radius: 8px;
    padding: 0.5rem 0.65rem;
    outline: none;
    transition: border-color 0.15s;
  }

  input:focus {
    border-color: var(--link-color);
  }

  .muted {
    color: var(--muted-color);
  }

  .message {
    font-size: 0.85rem;
    color: var(--muted-color);
  }

  .actions {
    display: flex;
    gap: 0.75rem;
    margin-block-start: 1.5rem;
    padding-block-end: 1.5rem;
  }

  .actions button {
    font-family: inherit;
    font-size: 0.9rem;
    padding: 0.5rem 1rem;
    border-radius: 8px;
    border: none;
    background: linear-gradient(135deg, #52A2F6, #3282e6);
    color: white;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .actions button:hover:not(:disabled) {
    opacity: 0.85;
  }

  .actions button:disabled {
    opacity: 0.4;
    cursor: default;
  }
</style>
