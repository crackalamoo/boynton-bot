const routerState = $state({
  path: typeof window !== 'undefined' ? window.location.pathname : '/',
});

if (typeof window !== 'undefined') {
  window.addEventListener('popstate', () => {
    routerState.path = window.location.pathname;
  });
}

export function navigate(path: string) {
  if (typeof window === 'undefined') return;
  history.pushState(null, '', path);
  routerState.path = path;
}

export function currentPath(): string {
  return routerState.path;
}

export { routerState };
