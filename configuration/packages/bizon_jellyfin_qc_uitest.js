// Playwright check of the jf Google/QR login (run inside the lampac container, see deploy notes).
// desktop: QR shown, code authorized via admin API (stands in for the phone) -> page logs in by itself.
// phone: "Увійти через Google" -> /qc?c=..&r=1 -> Google. Test device is removed afterwards.
const { chromium } = require('/lampac/.playwright/package');
const H = 'https://jf.yuriip4.duckdns.org', JF = process.env.JF, K = process.env.K, UID = process.env.UID;
const A = { Authorization: `MediaBrowser Token="${K}"` };
(async () => {
  const b = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] });
  let ok = true;
  {
    const ctx = await b.newContext({ viewport: { width: 1600, height: 900 } });
    const p = await ctx.newPage();
    await p.goto(H + '/web/');
    await p.waitForSelector('#loginPage .jfqc .jfqc-qr svg', { timeout: 60000 });
    const code = (await p.textContent('.jfqc-code')).trim();
    console.log('desktop: QR ok, code', code, 'button', await p.$('.jfqc-btn') ? 'yes' : 'no');
    const r = await fetch(`${JF}/QuickConnect/Authorize?code=${code}&userId=${UID}`, { method: 'POST', headers: A });
    console.log('authorize', r.status);
    await p.waitForURL(u => !/login/i.test(u.toString()), { timeout: 30000 }).catch(() => {});
    await p.waitForTimeout(4000);
    const cred = await p.evaluate(() => { try { const s = JSON.parse(localStorage.getItem('jellyfin_credentials')).Servers[0]; return { u: s.UserId, t: !!s.AccessToken }; } catch (e) { return null; } });
    const dev = await p.evaluate(() => localStorage.getItem('_deviceId2'));
    console.log('after: url', p.url(), 'cred', JSON.stringify(cred));
    if (!cred || cred.u.replace(/-/g, '') != UID.replace(/-/g, '') || /login/i.test(p.url())) ok = false;
    const d = await fetch(`${JF}/Devices?id=${encodeURIComponent(dev)}`, { method: 'DELETE', headers: A });
    console.log('test device removed', d.status);
    await ctx.close();
  }
  {
    const ctx = await b.newContext({ viewport: { width: 390, height: 800 }, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' });
    const p = await ctx.newPage();
    await p.goto(H + '/web/');
    await p.waitForSelector('#loginPage .jfqc .jfqc-btn', { timeout: 60000 });
    console.log('phone: QR', await p.$('.jfqc-qr') ? 'yes' : 'no');
    await p.waitForTimeout(2500);
    await p.click('.jfqc-btn');
    await p.waitForURL(/accounts\.google\.com/, { timeout: 20000 }).catch(() => {});
    const g = /accounts\.google\.com/.test(p.url());
    console.log('phone: button ->', g ? 'Google' : p.url());
    if (!g) ok = false;
    await ctx.close();
  }
  await b.close();
  console.log(ok ? 'UITEST OK' : 'UITEST FAIL');
})().catch(e => { console.log('UITEST ERROR', e.message); process.exit(1); });
