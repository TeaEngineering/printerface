// Email compose form: when a contact is ticked or unticked the suggested text is re-rendered by the server,
// since the template can use the recipients (${email.name}). Text the user has already edited is never
// replaced silently: it is kept, and a notice offers to replace it.
(function () {
	function init(doc, fetchFn) {
		var area = doc.getElementById('inputBody');
		if (!area || !area.getAttribute('data-url')) {
			return;
		}
		var boxes = doc.querySelectorAll('input[name="em"]');
		var notice = doc.getElementById('bodyNotice');
		var reapply = doc.getElementById('bodyReapply');
		var lastRendered = area.value;   // what the server gave us; anything else in the box was typed
		var latest = 0;

		function selected() {
			var out = [];
			for (var i = 0; i < boxes.length; i++) {
				if (boxes[i].checked) {
					out.push(boxes[i].value);
				}
			}
			return out;
		}

		function url() {
			var u = area.getAttribute('data-url');
			selected().forEach(function (address) {
				u += '&em=' + encodeURIComponent(address);
			});
			return u;
		}

		function showNotice(visible) {
			if (notice) {
				notice.style.display = visible ? '' : 'none';
			}
		}

		function refresh(replaceEdits) {
			var mine = ++latest;
			return fetchFn(url()).then(function (r) {
				return r.json();
			}).then(function (d) {
				if (mine !== latest) {
					return;   // a later tick has asked again; its answer is the one that counts
				}
				if (area.value !== lastRendered && !replaceEdits) {
					showNotice(true);
					return;
				}
				area.value = d.body;
				lastRendered = area.value;
				showNotice(false);
			}).catch(function () {
				// leave the text as it is; the user can still edit it by hand
			});
		}

		for (var i = 0; i < boxes.length; i++) {
			boxes[i].addEventListener('change', function () {
				refresh(false);
			});
		}
		if (reapply) {
			reapply.addEventListener('click', function (event) {
				if (event && event.preventDefault) {
					event.preventDefault();
				}
				refresh(true);
			});
		}
		return {refresh: refresh};
	}

	if (typeof window !== 'undefined') {
		window.addEventListener('DOMContentLoaded', function () {
			init(document, window.fetch.bind(window));
		});
	}
	if (typeof module !== 'undefined') {
		module.exports = {init: init};
	}
})();
