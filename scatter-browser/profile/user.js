// Scatter Browser — Firefox preferences override.
//
// This file lives in the Scatter Firefox profile directory. Firefox reads
// it at startup and applies every setting here, overriding defaults. To
// undo a change here, comment the line or remove the file.
//
// Scope: strip telemetry, disable phone-home services, prefer privacy
// defaults, set DoH to Cloudflare (change the resolver if you prefer
// a different policy).
//
// This is NOT a replacement for a hardened profile like Arkenfox —
// it's a conservative subset that matches Scatter's threat model
// (accidental leakage + distracted developer drift). Adversaries
// at the nation-state level are explicitly out of scope.

// ---------- telemetry: off ----------
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("toolkit.telemetry.newProfilePing.enabled", false);
user_pref("toolkit.telemetry.shutdownPingSender.enabled", false);
user_pref("toolkit.telemetry.updatePing.enabled", false);
user_pref("toolkit.telemetry.bhrPing.enabled", false);
user_pref("toolkit.telemetry.firstShutdownPing.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);

// ---------- crash reports: off ----------
user_pref("breakpad.reportURL", "");
user_pref("browser.tabs.crashReporting.sendReport", false);
user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);

// ---------- safe-browsing: off (it's google phone-home) ----------
user_pref("browser.safebrowsing.malware.enabled", false);
user_pref("browser.safebrowsing.phishing.enabled", false);
user_pref("browser.safebrowsing.downloads.enabled", false);
user_pref("browser.safebrowsing.downloads.remote.enabled", false);
user_pref("browser.safebrowsing.passwords.enabled", false);

// ---------- experiments, studies, recommendations: off ----------
user_pref("app.normandy.enabled", false);
user_pref("app.normandy.api_url", "");
user_pref("app.shield.optoutstudies.enabled", false);
user_pref("extensions.shield-recipe-client.enabled", false);
user_pref("browser.discovery.enabled", false);
user_pref("browser.newtabpage.activity-stream.showSponsored", false);
user_pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);
user_pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);

// ---------- Pocket: off ----------
user_pref("extensions.pocket.enabled", false);

// ---------- Firefox Accounts / Sync: off (we don't sync across devices) ----------
user_pref("identity.fxaccounts.enabled", false);
user_pref("services.sync.engine.addresses", false);
user_pref("services.sync.engine.creditcards", false);

// ---------- autofill of cards / addresses: off ----------
user_pref("extensions.formautofill.creditCards.enabled", false);
user_pref("extensions.formautofill.addresses.enabled", false);

// ---------- geolocation: prompt (not wolfSSL default) ----------
user_pref("permissions.default.geo", 0);           // 0=prompt, 1=allow, 2=block
user_pref("geo.provider.network.url", "");         // no Google geolocation API

// ---------- DNS over HTTPS: on, Cloudflare ----------
user_pref("network.trr.mode", 3);                  // 3 = DoH only (no fallback)
user_pref("network.trr.uri", "https://mozilla.cloudflare-dns.com/dns-query");
user_pref("network.trr.custom_uri", "https://mozilla.cloudflare-dns.com/dns-query");

// ---------- HTTPS-Only mode: on ----------
user_pref("dom.security.https_only_mode", true);
user_pref("dom.security.https_only_mode_ever_enabled", true);

// ---------- WebRTC ip leak prevention ----------
user_pref("media.peerconnection.ice.default_address_only", true);

// ---------- referrer policy: trim to origin on cross-site ----------
user_pref("network.http.referer.XOriginTrimmingPolicy", 2);

// ---------- prefetching: off (no speculative requests) ----------
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.predictor.enabled", false);
user_pref("network.http.speculative-parallel-limit", 0);

// ---------- search suggestions: off (they ping the search engine per keystroke) ----------
user_pref("browser.search.suggest.enabled", false);
user_pref("browser.urlbar.suggest.searches", false);
user_pref("browser.urlbar.trimURLs", false);

// ---------- first-launch noise: off ----------
user_pref("browser.aboutwelcome.enabled", false);
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.rights.3.shown", true);
user_pref("toolkit.startup.max_resumed_crashes", -1);

// ---------- new tab page: blank ----------
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.startup.homepage", "about:blank");
user_pref("browser.startup.page", 0);              // 0 = blank

// ---------- disable passwords-in-URL-bar saving prompts (let a password manager handle it) ----------
user_pref("signon.rememberSignons", false);

// ---------- cache policy: disk cache on, but clean on quit ----------
user_pref("browser.cache.disk.enable", true);
user_pref("privacy.sanitize.sanitizeOnShutdown", true);
user_pref("privacy.clearOnShutdown.cache", true);
user_pref("privacy.clearOnShutdown.cookies", false);   // keep sessions across restarts
user_pref("privacy.clearOnShutdown.downloads", false);
user_pref("privacy.clearOnShutdown.formdata", true);
user_pref("privacy.clearOnShutdown.history", false);   // keep history (legibility)
user_pref("privacy.clearOnShutdown.sessions", false);

// ---------- theme: default to system dark where possible ----------
user_pref("ui.systemUsesDarkTheme", 1);
user_pref("browser.theme.content-theme", 0);
user_pref("browser.theme.toolbar-theme", 0);

// ---------- userChrome.css / userContent.css: enabled so Scatter chrome applies ----------
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);

// ---------- Scatter branding ----------
// The omnibox placeholder reads "Search with Scatter or enter address" once
// the search engine is renamed via policies.json (SearchEngines policy).
// Phase 2 swaps the underlying engine from DuckDuckGo to a Scatter-Core
// journal-first endpoint per CORE_SYNTHESIS §3.
user_pref("browser.urlbar.placeholderName", "Scatter");
user_pref("browser.urlbar.placeholderName.private", "Scatter");

// Tab bar density — match userChrome.css Chromium-like slim tabs.
user_pref("browser.uidensity", 1);   // 0 = normal, 1 = compact, 2 = touch

// Disable the alert-bar "Make Firefox/LibreWolf the default browser" nag.
user_pref("browser.shell.checkDefaultBrowser", false);
