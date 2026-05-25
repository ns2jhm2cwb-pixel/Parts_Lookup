// Grab the auth token from localStorage whenever this page is active.
// The popup asks for it on open.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'GET_TOKEN') {
    sendResponse({ token: localStorage.getItem('access_token') || '' });
  }
  return true;
});
