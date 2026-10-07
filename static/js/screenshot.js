// Screenshot page: preview the chosen image, reject bad files early, and stop double submits.
// The server checks everything again; this only saves the user a round trip.
(function () {
  var input = document.getElementById('screenshot');
  var form = document.getElementById('shot-form');
  if (!form) return;

  var MAX_BYTES = 5 * 1024 * 1024;
  var TYPES = ['image/png', 'image/jpeg', 'image/webp'];
  var preview = document.getElementById('shot-preview');
  var error = document.getElementById('shot-error');
  var submit = document.getElementById('shot-submit');
  var currentUrl = null;

  function showError(message) {
    if (!error) return;
    error.textContent = message;
    error.hidden = !message;
  }

  function clearPreview() {
    if (currentUrl) { URL.revokeObjectURL(currentUrl); currentUrl = null; }
    if (preview) { preview.hidden = true; preview.removeAttribute('src'); }
  }

  if (input) {
    input.addEventListener('change', function () {
      clearPreview();
      showError('');
      var file = input.files && input.files[0];
      if (!file) return;
      if (TYPES.indexOf(file.type) === -1) {
        showError('Choose a PNG, JPG or WebP screenshot.');
        input.value = '';
        return;
      }
      if (file.size > MAX_BYTES) {
        showError('That file is larger than 5 MB. Choose a smaller screenshot.');
        input.value = '';
        return;
      }
      currentUrl = URL.createObjectURL(file);
      preview.src = currentUrl;
      preview.hidden = false;
    });
  }

  form.addEventListener('submit', function () {
    if (!submit) return;
    submit.disabled = true;
    submit.textContent = 'Checking...';
  });

  // Coming back with the browser's Back button must not leave the button stuck on "Checking..."
  window.addEventListener('pageshow', function () {
    if (!submit) return;
    submit.disabled = false;
    submit.textContent = 'Check error';
  });
})();
