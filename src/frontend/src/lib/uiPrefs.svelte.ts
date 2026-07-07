const SHOW_HIDDEN_KEY = 'boynton-show-hidden';

function readShowHidden(): boolean {
  if (typeof localStorage === 'undefined') return false;
  return localStorage.getItem(SHOW_HIDDEN_KEY) === '1';
}

const uiPrefs = $state({
  showHidden: readShowHidden(),
});

export function setShowHidden(value: boolean) {
  uiPrefs.showHidden = value;
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(SHOW_HIDDEN_KEY, value ? '1' : '0');
  }
}

export { uiPrefs };
