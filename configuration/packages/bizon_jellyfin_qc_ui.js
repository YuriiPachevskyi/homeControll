// Jellyfin web login page add-on (served by rpi4 nginx as /__jfqc/ui.js, injected into /web/index.html).
// OPTIONAL Google / QR login on top of Jellyfin's own Quick Connect; password login is untouched.
//  - this page starts Quick Connect itself (POST /QuickConnect/Initiate) and shows a QR with
//    https://<host>/qc?c=CODE; a phone scans it, signs in with Google and confirms; nginx authorizes
//    the code for the mapped Jellyfin user; this page polls, gets its OWN token and logs in.
//  - "Увійти через Google" (phone/PC browser): same, but the confirmation happens in this tab.
// The QR encoder (__jfqr) is prepended by bizon_jellyfin_qc_deploy.py.
(function () {
  if (window.__jfqc) return;
  window.__jfqc = 1;

  var KEY = 'jfqc';
  var ua = navigator.userAgent;
  var tvUa = /Tizen|Web0S|webOS|SMART-TV|SmartTV|CrKey|AFT|BRAVIA|Android TV|; wv\)/.test(ua);
  var st = { secret: null, code: null, timer: null, busy: false, info: null };

  function isTv() {
    return tvUa || document.documentElement.classList.contains('layout-tv');
  }
  function canGoogle() {
    return /(Safari|Firefox)\//.test(ua) && !isTv();
  }
  function store(v) {
    try { if (v) sessionStorage.setItem(KEY, JSON.stringify(v)); else sessionStorage.removeItem(KEY); } catch (e) {}
  }
  function pending() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (e) { return null; }
  }
  function deviceId() {
    var id = null;
    try { id = localStorage.getItem('_deviceId2'); } catch (e) {}
    if (!id) {
      id = btoa(ua + '|' + Date.now()).replace(/=/g, '1');
      try { localStorage.setItem('_deviceId2', id); } catch (e) {}
    }
    return id;
  }
  function deviceName() {
    var m = /(Edg|OPR|Firefox|Chrome|Safari)\//.exec(ua);
    var n = m ? { Edg: 'Edge', OPR: 'Opera' }[m[1]] || m[1] : 'Browser';
    return n.replace(/"/g, '');
  }
  function authHeader() {
    var v = (st.info && st.info.Version) || '10.11.0';
    return 'MediaBrowser Client="Jellyfin Web", Device="' + deviceName() + '", DeviceId="' + deviceId() + '", Version="' + v + '"';
  }
  function api(method, path, body, ok, fail) {
    try {
      var x = new XMLHttpRequest();
      x.open(method, path, true);
      x.timeout = 20000;
      x.setRequestHeader('Authorization', authHeader());
      if (body) x.setRequestHeader('Content-Type', 'application/json');
      x.onload = function () {
        var j = null;
        try { j = JSON.parse(x.responseText); } catch (e) {}
        if (x.status == 200 && j) ok(j); else if (fail) fail(x.status);
      };
      x.onerror = x.ontimeout = function () { if (fail) fail(0); };
      x.send(body ? JSON.stringify(body) : null);
    } catch (e) { if (fail) fail(0); }
  }

  function loginPage() {
    var p = document.getElementById('loginPage');
    return p && !p.classList.contains('hide') ? p : null;
  }

  function finish() {
    api('POST', '/Users/AuthenticateWithQuickConnect', { Secret: st.secret }, function (r) {
      store(null);
      stop();
      var sid = st.info.Id;
      try {
        var k = 'jellyfin_credentials', c = JSON.parse(localStorage.getItem(k) || '{}');
        c.Servers = (c.Servers || []).filter(function (s) { return s.Id !== sid; });
        c.Servers.unshift({ Id: sid, Name: st.info.ServerName, AccessToken: r.AccessToken, UserId: r.User.Id,
          ManualAddress: location.origin, manualAddressOnly: true, LastConnectionMode: 2, DateLastAccessed: Date.now() });
        localStorage.setItem(k, JSON.stringify(c));
      } catch (e) {}
      location.replace(location.origin + '/web/');
    }, function () { st.busy = false; });
  }

  function poll() {
    if (st.busy || !st.secret) return;
    if (!loginPage() && !pending()) { stop(); return; }
    st.busy = true;
    api('GET', '/QuickConnect/Connect?Secret=' + encodeURIComponent(st.secret), null, function (j) {
      if (j.Authenticated) { finish(); return; }
      st.busy = false;
    }, function (code) {
      st.busy = false;
      if (code == 404 || code == 401 || code == 400) { store(null); st.secret = null; start(); } // expired
    });
  }
  function stop() {
    if (st.timer) clearInterval(st.timer);
    st.timer = null;
  }

  function render() {
    var box = document.querySelector('#loginPage .jfqc');
    if (!box || !st.code) return;
    var url = location.origin + '/qc?c=' + st.code;
    var qr = box.querySelector('.jfqc-qr');
    if (qr && qr.getAttribute('data-c') !== st.code) {
      qr.setAttribute('data-c', st.code);
      try {
        var q = __jfqr(0, 'M');
        q.addData(url);
        q.make();
        qr.innerHTML = q.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
        var svg = qr.querySelector('svg');
        if (svg) { svg.style.width = '100%'; svg.style.height = '100%'; }
      } catch (e) { qr.textContent = url; }
    }
    var c = box.querySelector('.jfqc-code');
    if (c) c.textContent = st.code;
  }

  function start() {
    if (st.secret) { render(); return; }
    var p = pending();
    if (p && p.secret) {
      st.secret = p.secret; st.code = p.code;
    } else {
      api('POST', '/QuickConnect/Initiate', null, function (j) {
        if (!j.Secret || !j.Code) return;
        st.secret = j.Secret; st.code = j.Code;
        render();
      });
    }
    render();
    if (!st.timer) st.timer = setInterval(poll, 3000);
  }

  function block() {
    var d = document.createElement('div');
    d.className = 'jfqc';
    d.style.cssText = 'margin:0 auto 1.5em;text-align:center';
    var showQr = !canGoogle() || window.innerWidth > 900;
    var html = '';
    if (showQr) {
      html += '<div style="display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:1.2em;margin-bottom:1em">'
        + '<div class="jfqc-qr" style="width:11em;height:11em;background:#fff;border-radius:.5em;padding:.3em;color:#000;word-break:break-all;font-size:.7em"></div>'
        + '<div style="max-width:19em;text-align:left;line-height:1.45">Увійти через Google: відскануйте QR-код телефоном і підтвердіть вхід.'
        + '<div style="margin-top:.8em">Або відкрийте на телефоні <b>' + location.host + '/qc</b> і введіть код:</div>'
        + '<div class="jfqc-code" style="font-size:2.6em;font-weight:700;letter-spacing:.18em;margin-top:.2em;color:#00a4dc;font-variant-numeric:tabular-nums"></div></div>'
        + '</div>';
    }
    if (canGoogle()) {
      html += '<button type="button" is="emby-button" class="raised button-submit block emby-button jfqc-btn"><span>Увійти через Google</span></button>';
    }
    d.innerHTML = html;
    var b = d.querySelector('.jfqc-btn');
    if (b) b.addEventListener('click', function () {
      if (!st.secret || !st.code) return;
      store({ secret: st.secret, code: st.code });
      location.href = '/qc?c=' + encodeURIComponent(st.code) + '&r=1';
    });
    return d;
  }

  function tick() {
    var p = loginPage();
    if (!p) {
      // back from /qc confirmation in this tab: finish the pending login even before the login page shows
      if (pending() && st.info) start();
      return;
    }
    var ro = p.querySelector('.readOnlyContent');
    if (ro && !ro.querySelector('.jfqc')) {
      ro.insertBefore(block(), ro.firstChild);
    }
    if (st.info) start();
  }

  var x = new XMLHttpRequest();
  x.open('GET', '/System/Info/Public', true);
  x.onload = function () { try { st.info = JSON.parse(x.responseText); } catch (e) {} };
  x.send();
  setInterval(tick, 700);
})();
