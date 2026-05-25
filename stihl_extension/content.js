// Runs on ssc.stihl.com — reads token and detects current model from the page.

function getPageInfo() {
  const token = localStorage.getItem('access_token') || '';

  // Material number: look in URL first, then DOM data attributes
  let materialNumber = '';
  const urlNums = window.location.href.match(/\b(\d{8,15})\b/g) || [];
  if (urlNums.length) materialNumber = urlNums[0];

  // Also try common data attributes and Angular/React state
  if (!materialNumber) {
    const el = document.querySelector('[data-material-number],[data-product-id],[data-id]');
    if (el) materialNumber = el.dataset.materialNumber || el.dataset.productId || el.dataset.id || '';
  }

  // Model name: try heading elements, then page title
  let modelName = '';
  const heading = document.querySelector('h1,h2,[class*="product-title"],[class*="model-name"],[class*="designation"]');
  if (heading) modelName = heading.textContent.trim().split('\n')[0].trim();
  if (!modelName && document.title) {
    modelName = document.title.replace(/[-|].*$/, '').trim();
  }

  return { token, materialNumber, modelName, onPortal: true };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'GET_PAGE_INFO') {
    sendResponse(getPageInfo());
  }
  return true;
});
