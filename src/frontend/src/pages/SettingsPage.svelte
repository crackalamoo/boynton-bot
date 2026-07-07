<script lang="ts">
  import { onMount } from 'svelte';
  import { navigate } from '../lib/router.svelte.js';
  import { uiPrefs, setShowHidden } from '../lib/uiPrefs.svelte.js';

  const SECRET_PLACEHOLDER = '__SET__';

  type FormState = {
    BOYNTON_OPENAI_API_KEY: string;
    BOYNTON_LLM_BASE_URL: string;
    BOYNTON_LLM_MODEL: string;
    BOYNTON_MEMORY_DIR: string;
    BOYNTON_EMAIL_ADDRESS: string;
    BOYNTON_EMAIL_PASSWORD: string;
    BOYNTON_EMAIL_SMTP_HOST: string;
    BOYNTON_EMAIL_SMTP_PORT: string;
    BOYNTON_EMAIL_RECIPIENT: string;
  };

  const SECRET_KEYS: (keyof FormState)[] = ['BOYNTON_OPENAI_API_KEY', 'BOYNTON_EMAIL_PASSWORD'];

  function emptyForm(): FormState {
    return {
      BOYNTON_OPENAI_API_KEY: '', BOYNTON_LLM_BASE_URL: '', BOYNTON_LLM_MODEL: '', BOYNTON_MEMORY_DIR: '',
      BOYNTON_EMAIL_ADDRESS: '', BOYNTON_EMAIL_PASSWORD: '', BOYNTON_EMAIL_SMTP_HOST: '', BOYNTON_EMAIL_SMTP_PORT: '', BOYNTON_EMAIL_RECIPIENT: '',
    };
  }

  let form = $state<FormState>(emptyForm());
  let secretConfigured = $state<Record<string, boolean>>({});
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
        payload[key] = !secretEdited[key] ? (secretConfigured[key] ? SECRET_PLACEHOLDER : '') : form[key];
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
      if (!res.ok) { message = 'error: could not save settings'; saving = false; return false; }
      saving = false;
      return true;
    } catch (_) {
      message = 'error: could not reach server'; saving = false; return false;
    }
  }

  async function onSave() {
    const ok = await saveSettings();
    if (ok) { message = 'Settings saved. Restart to apply changes.'; await loadSettings(); }
  }

  async function onSaveAndRestart() {
    const ok = await saveSettings();
    if (!ok) return;
    restarting = true;
    message = 'Restarting... reload in a few seconds.';
    try { await fetch('/api/restart', { method: 'POST' }); } catch (_) {}
    setTimeout(() => { window.location.reload(); }, 5000);
  }

  // ── Tabs ──────────────────────────────────────────────────────────────────

  let activeTab = $state<'config' | 'cron'>('config');

  // ── Cron jobs ─────────────────────────────────────────────────────────────

  type CronJob = {
    id: number;
    name: string;
    channel: string;
    prompt: string;
    schedule_type: 'at' | 'cron';
    schedule_value: string;
    enabled: boolean;
    last_run_at: string | null;
    created_at: string;
  };

  type EditDraft = {
    name: string;
    channel: string;
    prompt: string;
    schedule_type: 'at' | 'cron';
    schedule_value: string;
    enabled: boolean;
  };

  let cronJobs = $state<CronJob[]>([]);
  let cronLoading = $state(false);
  let cronMessage = $state('');
  let editingId = $state<number | null>(null);
  let editDraft = $state<EditDraft | null>(null);
  let savingId = $state<number | null>(null);
  let deletingId = $state<number | null>(null);

  type NewJobForm = { name: string; channel: string; prompt: string; schedule_type: 'at' | 'cron'; schedule_value: string };
  function emptyNewJob(): NewJobForm {
    return { name: '', channel: 'web', prompt: '', schedule_type: 'cron', schedule_value: '' };
  }
  let newJob = $state<NewJobForm>(emptyNewJob());
  let addingJob = $state(false);
  let showAddForm = $state(false);

  async function loadCronJobs() {
    cronLoading = true;
    try {
      const res = await fetch('/api/cron-jobs');
      if (res.ok) { cronJobs = await res.json() as CronJob[]; }
      else { cronMessage = 'error: could not load cron jobs'; }
    } catch (_) { cronMessage = 'error: could not reach server'; }
    cronLoading = false;
  }

  function startEdit(job: CronJob) {
    editingId = job.id;
    editDraft = { name: job.name, channel: job.channel, prompt: job.prompt, schedule_type: job.schedule_type, schedule_value: job.schedule_value, enabled: job.enabled };
    cronMessage = '';
  }

  function cancelEdit() {
    editingId = null;
    editDraft = null;
  }

  async function saveEdit(id: number) {
    if (!editDraft) return;
    savingId = id;
    cronMessage = '';
    try {
      const res = await fetch(`/api/cron-jobs/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editDraft),
      });
      if (res.ok) {
        editingId = null;
        editDraft = null;
        await loadCronJobs();
      } else {
        const data = await res.json() as { detail?: string };
        cronMessage = `error: ${data.detail ?? 'could not update job'}`;
      }
    } catch (_) { cronMessage = 'error: could not reach server'; }
    savingId = null;
  }

  async function addCronJob(e: SubmitEvent) {
    e.preventDefault();
    addingJob = true;
    cronMessage = '';
    try {
      const res = await fetch('/api/cron-jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newJob),
      });
      if (res.ok) {
        newJob = emptyNewJob();
        showAddForm = false;
        await loadCronJobs();
      } else {
        const data = await res.json() as { detail?: string };
        cronMessage = `error: ${data.detail ?? 'could not create job'}`;
      }
    } catch (_) { cronMessage = 'error: could not reach server'; }
    addingJob = false;
  }

  async function deleteCronJob(id: number) {
    deletingId = id;
    cronMessage = '';
    try {
      const res = await fetch(`/api/cron-jobs/${id}`, { method: 'DELETE' });
      if (res.ok) { await loadCronJobs(); }
      else { cronMessage = 'error: could not delete job'; }
    } catch (_) { cronMessage = 'error: could not reach server'; }
    deletingId = null;
  }

  function formatDate(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
  }

  $effect(() => {
    if (activeTab === 'cron') loadCronJobs();
  });
</script>

<div class="main">
  <article>
    <div class="header-row">
      <h1>Settings</h1>
      <button class="link-btn" onclick={() => navigate('/chat')}>back to chat</button>
    </div>
    <hr />

    <div class="tab-bar">
      <button class="tab-pill" class:active={activeTab === 'config'} onclick={() => activeTab = 'config'}>Config</button>
      <button class="tab-pill" class:active={activeTab === 'cron'} onclick={() => activeTab = 'cron'}>Cron Jobs</button>
    </div>

    {#if activeTab === 'config'}
      {#if loading}
        <p class="muted">loading settings…</p>
      {:else}
        <form onsubmit={(e) => { e.preventDefault(); onSave(); }}>
          <section>
            <h2>LLM</h2>
            <label>
              <span>OpenAI-compatible API key</span>
              <input type="password" placeholder={secretConfigured.BOYNTON_OPENAI_API_KEY ? '(configured — leave blank to keep)' : ''} bind:value={form.BOYNTON_OPENAI_API_KEY} oninput={() => onSecretInput('BOYNTON_OPENAI_API_KEY')} autocomplete="off" />
            </label>
            <label>
              <span>LLM base URL</span>
              <input type="text" bind:value={form.BOYNTON_LLM_BASE_URL} autocomplete="off" />
            </label>
            <label>
              <span>LLM model</span>
              <input type="text" bind:value={form.BOYNTON_LLM_MODEL} autocomplete="off" />
            </label>
          </section>

          <section>
            <h2>Memory</h2>
            <label>
              <span>Memory directory</span>
              <input type="text" bind:value={form.BOYNTON_MEMORY_DIR} autocomplete="off" />
            </label>
          </section>

          <section>
            <h2>Display</h2>
            <label class="inline-check">
              <input type="checkbox" checked={uiPrefs.showHidden} onchange={(e) => setShowHidden(e.currentTarget.checked)} />
              <span>Show hidden messages in chat</span>
            </label>
          </section>

          <section>
            <h2>Email</h2>
            <label><span>From address</span><input type="text" bind:value={form.BOYNTON_EMAIL_ADDRESS} autocomplete="off" /></label>
            <label>
              <span>Password</span>
              <input type="password" placeholder={secretConfigured.BOYNTON_EMAIL_PASSWORD ? '(configured — leave blank to keep)' : ''} bind:value={form.BOYNTON_EMAIL_PASSWORD} oninput={() => onSecretInput('BOYNTON_EMAIL_PASSWORD')} autocomplete="off" />
            </label>
            <label><span>SMTP host</span><input type="text" bind:value={form.BOYNTON_EMAIL_SMTP_HOST} autocomplete="off" /></label>
            <label><span>SMTP port</span><input type="text" bind:value={form.BOYNTON_EMAIL_SMTP_PORT} autocomplete="off" /></label>
            <label><span>Recipient</span><input type="text" bind:value={form.BOYNTON_EMAIL_RECIPIENT} autocomplete="off" /></label>
          </section>

          {#if message}
            <p class="message">{message}</p>
          {/if}

          <div class="actions">
            <button type="submit" disabled={saving || restarting}>{saving ? 'saving...' : 'save'}</button>
            <button type="button" onclick={onSaveAndRestart} disabled={saving || restarting}>{restarting ? 'restarting...' : 'save & restart'}</button>
          </div>
        </form>
      {/if}

    {:else if activeTab === 'cron'}
      <div class="cron-tab">
        {#if cronLoading}
          <p class="muted">loading…</p>
        {:else if cronJobs.length === 0}
          <p class="muted">No cron jobs scheduled.</p>
        {:else}
          <div class="job-list">
            {#each cronJobs as job (job.id)}
              <div class="job-card" class:editing={editingId === job.id}>
                {#if editingId === job.id && editDraft}
                  <!-- ── Edit form ── -->
                  <div class="edit-form">
                    <label><span>Name</span><input type="text" bind:value={editDraft.name} autocomplete="off" /></label>
                    <label><span>Channel</span><input type="text" bind:value={editDraft.channel} autocomplete="off" /></label>
                    <label>
                      <span>Schedule type</span>
                      <select bind:value={editDraft.schedule_type}>
                        <option value="cron">cron (recurring)</option>
                        <option value="at">at (one-time)</option>
                      </select>
                    </label>
                    <label>
                      <span>{editDraft.schedule_type === 'cron' ? 'Cron expression' : 'ISO timestamp'}</span>
                      <input type="text" bind:value={editDraft.schedule_value} autocomplete="off" />
                    </label>
                    <label><span>Prompt</span><textarea bind:value={editDraft.prompt} rows="4"></textarea></label>
                    <label class="inline-check">
                      <input type="checkbox" bind:checked={editDraft.enabled} />
                      <span>Enabled</span>
                    </label>
                    <div class="edit-actions">
                      <button class="btn-primary" onclick={() => saveEdit(job.id)} disabled={savingId === job.id}>{savingId === job.id ? 'saving...' : 'save'}</button>
                      <button class="btn-ghost" onclick={cancelEdit}>cancel</button>
                      <button class="btn-danger" onclick={() => deleteCronJob(job.id)} disabled={deletingId === job.id}>{deletingId === job.id ? '…' : 'delete'}</button>
                    </div>
                  </div>
                {:else}
                  <!-- ── Display view ── -->
                  <div class="job-header">
                    <span class="job-name">{job.name}</span>
                    <span class="job-badge" class:disabled={!job.enabled}>{job.enabled ? 'enabled' : 'disabled'}</span>
                    <button class="btn-ghost small" onclick={() => startEdit(job)}>edit</button>
                  </div>
                  <div class="job-meta">
                    <span>{job.schedule_type === 'cron' ? 'cron' : 'at'} <code>{job.schedule_value}</code></span>
                    <span>channel: {job.channel}</span>
                    <span>last run: {formatDate(job.last_run_at)}</span>
                  </div>
                  <div class="job-prompt">{job.prompt}</div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}

        {#if cronMessage}
          <p class="message">{cronMessage}</p>
        {/if}

        {#if !showAddForm}
          <button class="add-btn" onclick={() => { showAddForm = true; cronMessage = ''; }}>+ new job</button>
        {:else}
          <form class="add-form" onsubmit={addCronJob}>
            <h2>New Job</h2>
            <label><span>Name</span><input type="text" bind:value={newJob.name} required autocomplete="off" /></label>
            <label><span>Channel</span><input type="text" bind:value={newJob.channel} required autocomplete="off" /></label>
            <label>
              <span>Schedule type</span>
              <select bind:value={newJob.schedule_type}>
                <option value="cron">cron (recurring)</option>
                <option value="at">at (one-time)</option>
              </select>
            </label>
            <label>
              <span>{newJob.schedule_type === 'cron' ? 'Cron expression (e.g. 0 9 * * *)' : 'ISO timestamp (e.g. 2026-07-01T09:00:00)'}</span>
              <input type="text" bind:value={newJob.schedule_value} required autocomplete="off" />
            </label>
            <label><span>Prompt</span><textarea bind:value={newJob.prompt} required rows="4"></textarea></label>
            <div class="edit-actions">
              <button class="btn-primary" type="submit" disabled={addingJob}>{addingJob ? 'creating...' : 'create'}</button>
              <button class="btn-ghost" type="button" onclick={() => { showAddForm = false; newJob = emptyNewJob(); cronMessage = ''; }}>cancel</button>
            </div>
          </form>
        {/if}
      </div>
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

  .link-btn:hover { color: var(--text-color); }

  /* ── Pill tab bar ─────────────────────────────────────────────────────── */

  .tab-bar {
    display: flex;
    background: var(--button-bg);
    border: 1.5px solid var(--button-border);
    border-radius: 10px;
    padding: 3px;
    gap: 2px;
    width: fit-content;
    margin-block-end: 1.75rem;
  }

  .tab-pill {
    font-family: inherit;
    font-size: 0.875rem;
    padding: 0.3rem 1rem;
    border: none;
    border-radius: 7px;
    background: none;
    color: var(--muted-color);
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .tab-pill:hover { color: var(--text-color); }

  .tab-pill.active {
    background: var(--bg-color);
    color: var(--text-color);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
  }

  /* ── Config tab ───────────────────────────────────────────────────────── */

  section { margin-block: 1.25rem; }

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

  label span { color: var(--muted-color); font-size: 0.8rem; }

  label.inline-check {
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    margin-block-end: 0.75rem;
  }

  label.inline-check span { font-size: 0.9rem; }

  input, select, textarea {
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

  input:focus, select:focus, textarea:focus { border-color: var(--link-color); }
  textarea { resize: vertical; min-height: 5rem; }
  input[type="checkbox"] { width: auto; }

  .muted { color: var(--muted-color); }
  .message { font-size: 0.85rem; color: var(--muted-color); }

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

  .actions button:hover:not(:disabled) { opacity: 0.85; }
  .actions button:disabled { opacity: 0.4; cursor: default; }

  .actions button[type="button"] {
    background: var(--button-bg);
    color: var(--text-color);
    border: 1.5px solid var(--button-border);
  }

  /* ── Shared button styles ─────────────────────────────────────────────── */

  .btn-primary {
    font-family: inherit;
    font-size: 0.88rem;
    padding: 0.4rem 0.9rem;
    border-radius: 7px;
    border: none;
    background: linear-gradient(135deg, #52A2F6, #3282e6);
    color: white;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .btn-primary:hover:not(:disabled) { opacity: 0.85; }
  .btn-primary:disabled { opacity: 0.4; cursor: default; }

  .btn-ghost {
    font-family: inherit;
    font-size: 0.88rem;
    padding: 0.4rem 0.9rem;
    border-radius: 7px;
    border: 1.5px solid var(--button-border);
    background: var(--button-bg);
    color: var(--muted-color);
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }

  .btn-ghost:hover { color: var(--text-color); border-color: var(--hr-color); }
  .btn-ghost.small { padding: 0.2rem 0.6rem; font-size: 0.78rem; }

  .btn-danger {
    font-family: inherit;
    font-size: 0.88rem;
    padding: 0.4rem 0.9rem;
    border-radius: 7px;
    border: 1.5px solid transparent;
    background: none;
    color: var(--muted-color);
    cursor: pointer;
    margin-inline-start: auto;
    transition: color 0.15s, border-color 0.15s;
  }

  .btn-danger:hover:not(:disabled) { color: #e05252; border-color: #e05252; }
  .btn-danger:disabled { opacity: 0.4; cursor: default; }

  /* ── Cron tab ─────────────────────────────────────────────────────────── */

  .cron-tab { padding-block-end: 1.5rem; }

  .job-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    margin-block-end: 1.25rem;
  }

  .job-card {
    border: 1.5px solid var(--hr-color);
    border-radius: 10px;
    padding: 0.75rem 1rem;
  }

  .job-card.editing { border-color: var(--link-color); }

  .job-header {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-block-end: 0.35rem;
  }

  .job-name { font-weight: 600; font-size: 0.95rem; flex: 1; }

  .job-badge {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.15em 0.5em;
    border-radius: 4px;
    background: #3282e622;
    color: var(--link-color);
  }

  .job-badge.disabled { background: var(--button-bg); color: var(--muted-color); }

  .job-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    font-size: 0.8rem;
    color: var(--muted-color);
    margin-block-end: 0.4rem;
  }

  .job-meta code {
    font-family: monospace;
    font-size: 0.85em;
    background: var(--button-bg);
    border: 1px solid var(--button-border);
    border-radius: 3px;
    padding: 0.05em 0.3em;
  }

  .job-prompt {
    font-size: 0.85rem;
    color: var(--muted-color);
    white-space: pre-wrap;
    border-left: 2px solid var(--hr-color);
    padding-inline-start: 0.6rem;
  }

  .edit-form {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .edit-actions {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin-block: 0.75rem 0.25rem;
  }

  .add-btn {
    font-family: inherit;
    font-size: 0.88rem;
    padding: 0.4rem 0.85rem;
    border-radius: 8px;
    border: 1.5px solid var(--hr-color);
    background: none;
    color: var(--muted-color);
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }

  .add-btn:hover { color: var(--text-color); border-color: var(--text-color); }

  .add-form {
    border: 1.5px solid var(--hr-color);
    border-radius: 10px;
    padding: 1rem 1.25rem 0.25rem;
    margin-block-start: 1rem;
  }

  .add-form h2 {
    font-size: 0.95rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-color);
    margin-block-end: 0.75rem;
  }
</style>
